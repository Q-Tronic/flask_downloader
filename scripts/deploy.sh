#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-}"
PORT="${2:-22}"
USER_NAME="${3:-root}"
APP_DIR="${4:-/opt/flask_downloader}"
SERVICE_NAME="${5:-flask-downloader}"

if [[ -z "$HOST" ]]; then
    echo "Użycie: bash scripts/deploy.sh <host> [port] [user] [app_dir] [service_name]" >&2
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

ssh -p "$PORT" "${USER_NAME}@${HOST}" "APP_DIR='$APP_DIR' SERVICE_NAME='$SERVICE_NAME' REMOTE_ARCHIVE='$REMOTE_ARCHIVE' TIMESTAMP='$TIMESTAMP' bash -s" <<'EOF'
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

systemctl restart "${SERVICE_NAME}.service"
systemctl is-active "${SERVICE_NAME}.service"
EOF

echo "Deploy zakończony powodzeniem: ${HOST}:${APP_DIR}"
