param(
    [Parameter(Mandatory = $true)][string]$ServerHost,
    [int]$Port = 22,
    [string]$User = "root",
    [string]$Password = "",
    [string]$AppDir = "/opt/flask_downloader",
    [string]$ServiceName = "flask-downloader",
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
        --exclude=tools/dlna/runtime `
        --exclude=data/config.json `
        --exclude=data/jobs.json `
        --exclude=data/users.json `
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
  tar --exclude='.venv' --exclude='data' --exclude='.env' --exclude='backups' --exclude='tools/dlna/runtime' -czf '$AppDir/backups/code-$timestamp.tgz' -C '$AppDir' .
fi
if [ '$BackupRetentionCount' -gt 0 ] 2>/dev/null; then
  ls -1t '$AppDir'/backups/code-*.tgz 2>/dev/null | tail -n +$(($BackupRetentionCount + 1)) | xargs -r rm -f
fi
tar -xzf '$remoteArchive' -C '$AppDir'
rm -f '$remoteArchive'
if [ -x '$AppDir/.venv/bin/pip' ]; then
  '$AppDir/.venv/bin/pip' install -r '$AppDir/requirements.txt' >/dev/null
fi
systemctl restart '$ServiceName.service'
systemctl is-active '$ServiceName.service'
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
