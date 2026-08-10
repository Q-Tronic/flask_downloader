#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${FLASK_DOWNLOADER_UPDATE_APP_DIR:-/opt/flask_downloader}"
BRANCH="${FLASK_DOWNLOADER_UPDATE_BRANCH:-main}"
REPO_OWNER="${FLASK_DOWNLOADER_REPO_OWNER:-Q-Tronic}"
REPO_NAME="${FLASK_DOWNLOADER_REPO_NAME:-flask_downloader}"
SERVICE_NAME="${FLASK_DOWNLOADER_UPDATE_SERVICE_NAME:-}"
IPTV_SERVICE_NAME="${FLASK_DOWNLOADER_UPDATE_IPTV_SERVICE_NAME:-}"
APP_USER=""
APP_GROUP=""
SKIP_RESTART="${FLASK_DOWNLOADER_UPDATE_SKIP_RESTART:-0}"
TMP_DIR=""

log() {
    printf '%s\n' "$1"
}

fail() {
    log "BŁĄD: $1"
    exit 1
}

cleanup() {
    if [[ -n "${TMP_DIR:-}" && -d "${TMP_DIR:-}" ]]; then
        rm -rf "${TMP_DIR}"
    fi
}
trap cleanup EXIT

require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        fail "Uruchom aktualizację jako root albo przez sudo."
    fi
}

read_env_value() {
    local env_file="$1"
    local env_name="$2"
    if [[ ! -f "$env_file" ]]; then
        return 1
    fi
    python3 - "$env_file" "$env_name" <<'PY'
import sys

env_path = sys.argv[1]
key = sys.argv[2]
try:
    with open(env_path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() != key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            print(value)
            raise SystemExit(0)
except FileNotFoundError:
    pass
raise SystemExit(1)
PY
}

download_file() {
    local url="$1"
    local out_file="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$out_file"
        return 0
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -qO "$out_file" "$url"
        return 0
    fi
    fail "Brakuje curl albo wget potrzebnego do pobrania aktualizacji."
}

main() {
    require_root

    [[ -d "$APP_DIR" ]] || fail "Nie znaleziono katalogu aplikacji: $APP_DIR. Najpierw uruchom instalator."
    [[ -f "$APP_DIR/requirements.txt" ]] || fail "W katalogu $APP_DIR nie ma requirements.txt. To nie wygląda na poprawną instalację."

    local env_file="$APP_DIR/.env"
    if [[ -z "$SERVICE_NAME" ]]; then
        SERVICE_NAME="$(read_env_value "$env_file" "FLASK_DOWNLOADER_SERVICE_NAME" || true)"
    fi
    SERVICE_NAME="${SERVICE_NAME:-flask-downloader}"
    if [[ -z "$IPTV_SERVICE_NAME" ]]; then
        IPTV_SERVICE_NAME="$(read_env_value "$env_file" "FLASK_DOWNLOADER_IPTV_SERVICE_NAME" || true)"
    fi
    IPTV_SERVICE_NAME="${IPTV_SERVICE_NAME:-${SERVICE_NAME}-iptv}"
    APP_USER="$(read_env_value "$env_file" "FLASK_DOWNLOADER_SERVICE_USER" || true)"
    APP_GROUP="$(read_env_value "$env_file" "FLASK_DOWNLOADER_SERVICE_GROUP" || true)"
    local service_load_state
    service_load_state="$(systemctl show "${SERVICE_NAME}.service" --property=LoadState --value 2>/dev/null || true)"
    if [[ -z "$APP_USER" ]]; then
        APP_USER="$(systemctl show "${SERVICE_NAME}.service" --property=User --value 2>/dev/null || true)"
        if [[ -z "$APP_USER" && -n "$service_load_state" && "$service_load_state" != "not-found" ]]; then
            APP_USER="root"
        fi
    fi
    if [[ -z "$APP_GROUP" ]]; then
        APP_GROUP="$(systemctl show "${SERVICE_NAME}.service" --property=Group --value 2>/dev/null || true)"
        if [[ -z "$APP_GROUP" && -n "$service_load_state" && "$service_load_state" != "not-found" ]]; then
            APP_GROUP="root"
        fi
    fi
    if [[ -z "$APP_USER" && -e "$env_file" ]]; then
        APP_USER="$(stat -c '%U' "$env_file" 2>/dev/null || true)"
    fi
    if [[ -z "$APP_GROUP" && -e "$env_file" ]]; then
        APP_GROUP="$(stat -c '%G' "$env_file" 2>/dev/null || true)"
    fi
    APP_USER="${APP_USER:-flaskdl}"
    APP_GROUP="${APP_GROUP:-$APP_USER}"

    TMP_DIR="$(mktemp -d)"
    local archive_url="https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/refs/heads/${BRANCH}"
    local archive_file="${TMP_DIR}/repo.tar.gz"
    local extract_dir="${TMP_DIR}/extract"
    local source_dir=""
    local payload_archive="${TMP_DIR}/payload.tgz"
    local timestamp
    timestamp="$(date +%Y%m%d-%H%M%S)"

    mkdir -p "$extract_dir" "$APP_DIR/backups"

    log "Aktualizuję VLC Stream Extractor z gałęzi ${BRANCH}..."
    log "Pobieram paczkę z GitHuba..."
    download_file "$archive_url" "$archive_file"

    tar -xzf "$archive_file" -C "$extract_dir"
    source_dir="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d | head -n1)"
    [[ -n "$source_dir" && -d "$source_dir" ]] || fail "Nie udało się rozpakować archiwum z GitHuba."

    log "Tworzę backup bieżącego kodu..."
    tar \
        --exclude='.venv' \
        --exclude='data' \
        --exclude='.env' \
        --exclude='tools/dlna/runtime' \
        --exclude='tools/ffmpeg' \
        --exclude='backups' \
        -czf "$APP_DIR/backups/code-update-${timestamp}.tgz" \
        -C "$APP_DIR" .

    log "Przygotowuję paczkę aktualizacyjną..."
    tar \
        --exclude='.git' \
        --exclude='.venv' \
        --exclude='.github' \
        --exclude='data/config.json' \
        --exclude='data/jobs.json' \
        --exclude='data/users.json' \
        --exclude='data/radios.json' \
        --exclude='data/iptv.json' \
        --exclude='data/iptv.json.bak' \
        --exclude='data/calendar_cache.json' \
        --exclude='data/name_days_pl.json' \
        --exclude='data/unusual_holidays_pl.json' \
        --exclude='data/runtime' \
        --exclude='.env' \
        --exclude='backups' \
        --exclude='tools/dlna/runtime' \
        --exclude='tools/ffmpeg' \
        --exclude='dlna' \
        -czf "$payload_archive" \
        -C "$source_dir" .

    log "Podmieniam pliki aplikacji..."
    tar -xzf "$payload_archive" -C "$APP_DIR"

    if [[ -x "$APP_DIR/.venv/bin/pip" ]]; then
        log "Aktualizuję zależności Pythona..."
        "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" >/dev/null
    else
        log "UWAGA: nie znaleziono $APP_DIR/.venv/bin/pip, pomijam aktualizację zależności."
    fi

    local iptv_template="$APP_DIR/deploy/flask-downloader-iptv.service.template"
    local iptv_unit="/etc/systemd/system/${IPTV_SERVICE_NAME}.service"
    [[ -f "$iptv_template" ]] || fail "Brakuje szablonu usługi IPTV: $iptv_template"
    sed \
        -e "s|__APP_USER__|$APP_USER|g" \
        -e "s|__APP_GROUP__|$APP_GROUP|g" \
        -e "s|__APP_DIR__|$APP_DIR|g" \
        -e "s|__ENV_FILE__|$env_file|g" \
        -e "s|__PYTHON_BIN__|$APP_DIR/.venv/bin/python|g" \
        "$iptv_template" > "$iptv_unit"
    if ! grep -q '^FLASK_DOWNLOADER_IPTV_SERVICE_NAME=' "$env_file"; then
        printf '\nFLASK_DOWNLOADER_IPTV_SERVICE_NAME=%s\n' "$IPTV_SERVICE_NAME" >> "$env_file"
    fi
    chown "$APP_USER:$APP_GROUP" "$env_file" 2>/dev/null || true
    mkdir -p "$APP_DIR/data/runtime/iptv"
    chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/data/runtime/iptv" 2>/dev/null || true
    systemctl daemon-reload
    systemctl enable "${IPTV_SERVICE_NAME}.service" >/dev/null

    if [[ "$SKIP_RESTART" != "1" ]]; then
        log "Restartuję usługę ${IPTV_SERVICE_NAME}.service..."
        if ! systemctl restart "${IPTV_SERVICE_NAME}.service"; then
            log "UWAGA: nie udało się uruchomić bramki IPTV. Główna aplikacja zostanie zaktualizowana, a diagnostyka będzie dostępna w panelu IPTV."
        fi
        log "Restartuję usługę ${SERVICE_NAME}.service..."
        systemctl restart "${SERVICE_NAME}.service"
        systemctl is-active "${SERVICE_NAME}.service" >/dev/null
    else
        log "Pomijam restart usługi zgodnie z FLASK_DOWNLOADER_UPDATE_SKIP_RESTART=1."
    fi

    log "Aktualizacja zakończona powodzeniem."
    log "Katalog aplikacji: $APP_DIR"
    log "Backup kodu: $APP_DIR/backups/code-update-${timestamp}.tgz"
    if [[ "$SKIP_RESTART" != "1" ]]; then
        log "Usługa: ${SERVICE_NAME}.service jest aktywna."
        log "Bramka IPTV: $(systemctl is-active "${IPTV_SERVICE_NAME}.service" 2>/dev/null || true)."
    fi
}

main "$@"
