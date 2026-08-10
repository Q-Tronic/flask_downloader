#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-}"
PORT="${2:-22}"
USER_NAME="${3:-root}"
APP_DIR="${4:-/opt/flask_downloader}"
SERVICE_NAME="${5:-flask-downloader}"
IPTV_SERVICE_NAME="${6:-${SERVICE_NAME}-iptv}"

if [[ -z "$HOST" ]]; then
    echo "Użycie: bash scripts/deploy.sh <host> [port] [user] [app_dir] [service_name] [iptv_service_name]" >&2
    exit 1
fi

TMP_DIR="$(mktemp -d)"
ARCHIVE_FILE="$TMP_DIR/flask_downloader_deploy.tgz"
REMOTE_ARCHIVE="/tmp/flask_downloader_deploy_$$.tgz"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

tar \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='data/*.json' \
    --exclude='data/runtime' \
    --exclude='.env' \
    --exclude='backups' \
    --exclude='tools/dlna/runtime' \
    --exclude='tools/ffmpeg' \
    -czf "$ARCHIVE_FILE" .

scp -P "$PORT" "$ARCHIVE_FILE" "${USER_NAME}@${HOST}:${REMOTE_ARCHIVE}"

ssh -p "$PORT" "${USER_NAME}@${HOST}" "APP_DIR='$APP_DIR' SERVICE_NAME='$SERVICE_NAME' IPTV_SERVICE_NAME='$IPTV_SERVICE_NAME' REMOTE_ARCHIVE='$REMOTE_ARCHIVE' TIMESTAMP='$TIMESTAMP' bash -s" <<'EOF'
set -euo pipefail

mkdir -p "$APP_DIR/backups"
if [[ -d "$APP_DIR" ]]; then
    tar \
        --exclude='.venv' \
        --exclude='data' \
        --exclude='.env' \
        --exclude='tools/dlna/runtime' \
        --exclude='tools/ffmpeg' \
        -czf "$APP_DIR/backups/code-$TIMESTAMP.tgz" \
        -C "$APP_DIR" .
fi

tar -xzf "$REMOTE_ARCHIVE" -C "$APP_DIR"
rm -f "$REMOTE_ARCHIVE"

if [[ -x "$APP_DIR/.venv/bin/pip" ]]; then
    "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" >/dev/null
fi

ENV_FILE="$APP_DIR/.env"
APP_USER=""
APP_GROUP=""
if [[ -f "$ENV_FILE" ]]; then
    APP_USER="$(awk -F= '/^FLASK_DOWNLOADER_SERVICE_USER=/{print $2}' "$ENV_FILE" | tail -n1 | xargs)"
    APP_GROUP="$(awk -F= '/^FLASK_DOWNLOADER_SERVICE_GROUP=/{print $2}' "$ENV_FILE" | tail -n1 | xargs)"
fi
SERVICE_LOAD_STATE="$(systemctl show "${SERVICE_NAME}.service" --property=LoadState --value 2>/dev/null || true)"
if [[ -z "$APP_USER" ]]; then
    APP_USER="$(systemctl show "${SERVICE_NAME}.service" --property=User --value 2>/dev/null || true)"
    if [[ -z "$APP_USER" && -n "$SERVICE_LOAD_STATE" && "$SERVICE_LOAD_STATE" != "not-found" ]]; then
        APP_USER="root"
    fi
fi
if [[ -z "$APP_GROUP" ]]; then
    APP_GROUP="$(systemctl show "${SERVICE_NAME}.service" --property=Group --value 2>/dev/null || true)"
    if [[ -z "$APP_GROUP" && -n "$SERVICE_LOAD_STATE" && "$SERVICE_LOAD_STATE" != "not-found" ]]; then
        APP_GROUP="root"
    fi
fi
if [[ -z "$APP_USER" && -e "$ENV_FILE" ]]; then
    APP_USER="$(stat -c '%U' "$ENV_FILE" 2>/dev/null || true)"
fi
if [[ -z "$APP_GROUP" && -e "$ENV_FILE" ]]; then
    APP_GROUP="$(stat -c '%G' "$ENV_FILE" 2>/dev/null || true)"
fi
APP_USER="${APP_USER:-flaskdl}"
APP_GROUP="${APP_GROUP:-$APP_USER}"
if [[ -f "$ENV_FILE" ]] && grep -q '^FLASK_DOWNLOADER_IPTV_SERVICE_NAME=' "$ENV_FILE"; then
    IPTV_SERVICE_NAME="$(awk -F= '/^FLASK_DOWNLOADER_IPTV_SERVICE_NAME=/{print $2}' "$ENV_FILE" | tail -n1 | xargs)"
else
    printf '\nFLASK_DOWNLOADER_IPTV_SERVICE_NAME=%s\n' "$IPTV_SERVICE_NAME" >> "$ENV_FILE"
fi
sed \
    -e "s|__APP_USER__|$APP_USER|g" \
    -e "s|__APP_GROUP__|$APP_GROUP|g" \
    -e "s|__APP_DIR__|$APP_DIR|g" \
    -e "s|__ENV_FILE__|$ENV_FILE|g" \
    -e "s|__PYTHON_BIN__|$APP_DIR/.venv/bin/python|g" \
    "$APP_DIR/deploy/flask-downloader-iptv.service.template" > "/etc/systemd/system/${IPTV_SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable --now "${IPTV_SERVICE_NAME}.service"

systemctl restart "${SERVICE_NAME}.service"
systemctl is-active "${SERVICE_NAME}.service"
systemctl is-active "${IPTV_SERVICE_NAME}.service"
EOF

echo "Deploy zakończony powodzeniem: ${HOST}:${APP_DIR}"
