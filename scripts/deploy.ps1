param(
    [Parameter(Mandatory = $true)][string]$ServerHost,
    [int]$Port = 22,
    [string]$User = "root",
    [string]$Password = "",
    [string]$AppDir = "/opt/flask_downloader",
    [string]$ServiceName = "flask-downloader",
    [string]$IptvServiceName = "",
    [int]$BackupRetentionCount = 5
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$tempRoot = Join-Path $env:TEMP ("flask_downloader_deploy_" + [guid]::NewGuid().ToString("N"))
$archiveFile = Join-Path $tempRoot "flask_downloader_deploy.tgz"
$remoteScriptFile = Join-Path $tempRoot "remote_deploy.sh"
$remoteArchive = "/tmp/flask_downloader_deploy_$PID.tgz"
$remoteScriptPath = "/tmp/flask_downloader_remote_deploy_$PID.sh"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$effectiveIptvServiceName = if ($IptvServiceName) { $IptvServiceName } else { "$ServiceName-iptv" }
$plink = "C:\Program Files\PuTTY\plink.exe"
$pscp = "C:\Program Files\PuTTY\pscp.exe"

New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
    tar.exe `
        --exclude=.git `
        --exclude=.venv `
        --exclude=__pycache__ `
        --exclude=.env `
        --exclude=backups `
        --exclude=data/runtime `
        --exclude=tools/dlna/runtime `
        --exclude=tools/ffmpeg `
        --exclude=data/config.json `
        --exclude=data/jobs.json `
        --exclude=data/users.json `
        --exclude=data/radios.json `
        --exclude=data/iptv.json `
        --exclude=data/iptv.json.bak `
        -czf $archiveFile `
        -C $projectRoot .

    $scpArgs = @("-P", "$Port")
    if ($Password) {
        $scpArgs += @("-pw", $Password)
    }
    $scpArgs += @($archiveFile, "$User@${ServerHost}:$remoteArchive")
    & $pscp @scpArgs

    $remoteScript = @"
set -euo pipefail
mkdir -p '$AppDir/backups'
if [ -d '$AppDir' ]; then
  tar --exclude='.venv' --exclude='data' --exclude='.env' --exclude='backups' --exclude='tools/dlna/runtime' --exclude='tools/ffmpeg' -czf '$AppDir/backups/code-$timestamp.tgz' -C '$AppDir' .
fi
if [ '$BackupRetentionCount' -gt 0 ] 2>/dev/null; then
  ls -1t '$AppDir'/backups/code-*.tgz 2>/dev/null | tail -n +$(($BackupRetentionCount + 1)) | xargs -r rm -f
fi
tar -xzf '$remoteArchive' -C '$AppDir'
rm -f '$remoteArchive'
if [ -x '$AppDir/.venv/bin/pip' ]; then
  '$AppDir/.venv/bin/pip' install -r '$AppDir/requirements.txt' >/dev/null
fi
ENV_FILE='$AppDir/.env'
APP_USER=''
APP_GROUP=''
if [ -f "`$ENV_FILE" ]; then
  APP_USER=`$(awk -F= '/^FLASK_DOWNLOADER_SERVICE_USER=/{print `$2}' "`$ENV_FILE" | tail -n1 | xargs)
  APP_GROUP=`$(awk -F= '/^FLASK_DOWNLOADER_SERVICE_GROUP=/{print `$2}' "`$ENV_FILE" | tail -n1 | xargs)
fi
SERVICE_LOAD_STATE=`$(systemctl show '$ServiceName.service' --property=LoadState --value 2>/dev/null || true)
if [ -z "`$APP_USER" ]; then
  APP_USER=`$(systemctl show '$ServiceName.service' --property=User --value 2>/dev/null || true)
  if [ -z "`$APP_USER" ] && [ -n "`$SERVICE_LOAD_STATE" ] && [ "`$SERVICE_LOAD_STATE" != 'not-found' ]; then
    APP_USER=root
  fi
fi
if [ -z "`$APP_GROUP" ]; then
  APP_GROUP=`$(systemctl show '$ServiceName.service' --property=Group --value 2>/dev/null || true)
  if [ -z "`$APP_GROUP" ] && [ -n "`$SERVICE_LOAD_STATE" ] && [ "`$SERVICE_LOAD_STATE" != 'not-found' ]; then
    APP_GROUP=root
  fi
fi
if [ -z "`$APP_USER" ] && [ -e "`$ENV_FILE" ]; then
  APP_USER=`$(stat -c '%U' "`$ENV_FILE" 2>/dev/null || true)
fi
if [ -z "`$APP_GROUP" ] && [ -e "`$ENV_FILE" ]; then
  APP_GROUP=`$(stat -c '%G' "`$ENV_FILE" 2>/dev/null || true)
fi
APP_USER="`${APP_USER:-flaskdl}"
APP_GROUP="`${APP_GROUP:-`$APP_USER}"
IPTV_SERVICE_NAME='$effectiveIptvServiceName'
if [ -f "`$ENV_FILE" ] && grep -q '^FLASK_DOWNLOADER_IPTV_SERVICE_NAME=' "`$ENV_FILE"; then
  IPTV_SERVICE_NAME=`$(awk -F= '/^FLASK_DOWNLOADER_IPTV_SERVICE_NAME=/{print `$2}' "`$ENV_FILE" | tail -n1 | xargs)
else
  printf '\nFLASK_DOWNLOADER_IPTV_SERVICE_NAME=%s\n' "`$IPTV_SERVICE_NAME" >> "`$ENV_FILE"
fi
sed -e "s|__APP_USER__|`$APP_USER|g" -e "s|__APP_GROUP__|`$APP_GROUP|g" -e "s|__APP_DIR__|$AppDir|g" -e "s|__ENV_FILE__|`$ENV_FILE|g" -e "s|__PYTHON_BIN__|$AppDir/.venv/bin/python|g" '$AppDir/deploy/flask-downloader-iptv.service.template' > "/etc/systemd/system/`$IPTV_SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable --now "`$IPTV_SERVICE_NAME.service"
systemctl restart '$ServiceName.service'
systemctl is-active '$ServiceName.service'
systemctl is-active "`$IPTV_SERVICE_NAME.service"
"@
    $remoteScript = $remoteScript -replace "`r`n", "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($remoteScriptFile, $remoteScript, $utf8NoBom)

    $scpScriptArgs = @("-P", "$Port")
    if ($Password) {
        $scpScriptArgs += @("-pw", $Password)
    }
    $scpScriptArgs += @($remoteScriptFile, "$User@${ServerHost}:$remoteScriptPath")
    & $pscp @scpScriptArgs

    $plinkArgs = @("-P", "$Port")
    if ($Password) {
        $plinkArgs += @("-pw", $Password)
    }
    $plinkArgs += @("$User@$ServerHost", "bash '$remoteScriptPath' && rm -f '$remoteScriptPath'")
    & $plink @plinkArgs

    Write-Host "Deploy zakonczony powodzeniem: $ServerHost -> $AppDir" -ForegroundColor Green
}
finally {
    if (Test-Path $tempRoot) {
        Remove-Item -Recurse -Force $tempRoot
    }
}
