#!/usr/bin/env bash
set -euo pipefail

TOTAL_STEPS=10
CURRENT_STEP=0

C_RESET="\033[0m"
C_BOLD="\033[1m"
C_BLUE="\033[38;5;75m"
C_GREEN="\033[38;5;82m"
C_YELLOW="\033[38;5;220m"
C_RED="\033[38;5;203m"
C_CYAN="\033[38;5;117m"
C_MUTED="\033[38;5;245m"

APP_DIR_DEFAULT="/opt/flask_downloader"
STORAGE_ROOT_DEFAULT="/srv/flask_downloader/share"
REPO_URL_DEFAULT="${FLASK_DOWNLOADER_REPO_URL:-https://github.com/Q-Tronic/flask_downloader.git}"
BRANCH_DEFAULT="${FLASK_DOWNLOADER_BRANCH:-main}"
APP_USER_DEFAULT="flaskdl"
APP_GROUP_DEFAULT="flaskdl"
APP_PORT_DEFAULT="9999"
APP_HOST_DEFAULT="0.0.0.0"
SERVICE_NAME_DEFAULT="flask-downloader"
DLNA_SERVICE_NAME_DEFAULT="flask-downloader-dlna"
DLNA_PORT_DEFAULT="49152"
DLNA_CHANNEL_DEFAULT="latest"

REPO_URL="$REPO_URL_DEFAULT"
BRANCH="$BRANCH_DEFAULT"
APP_DIR="$APP_DIR_DEFAULT"
STORAGE_ROOT="$STORAGE_ROOT_DEFAULT"
APP_USER="$APP_USER_DEFAULT"
APP_GROUP="$APP_GROUP_DEFAULT"
APP_PORT="$APP_PORT_DEFAULT"

render_bar() {
    local percent="$1"
    local total_slots=28
    local filled=$(( percent * total_slots / 100 ))
    local empty=$(( total_slots - filled ))
    local bar
    bar="$(printf '%*s' "$filled" '' | tr ' ' '#')"
    bar="${bar}$(printf '%*s' "$empty" '' | tr ' ' '-')"
    printf "[%s] %3s%%" "$bar" "$percent"
}

print_banner() {
    printf "\n${C_BLUE}${C_BOLD}VLC Stream Extractor${C_RESET} ${C_MUTED}instalator Debiana${C_RESET}\n"
    printf "${C_MUTED}Automatyczna instalacja aplikacji, .env, usług i pierwszego administratora.${C_RESET}\n\n"
}

log_info() {
    printf "${C_CYAN}INFO${C_RESET} %s\n" "$1"
}

log_ok() {
    printf "${C_GREEN}OK${C_RESET}   %s\n" "$1"
}

log_warn() {
    printf "${C_YELLOW}WARN${C_RESET} %s\n" "$1"
}

log_fail() {
    printf "${C_RED}ERR${C_RESET}  %s\n" "$1" >&2
}

begin_step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    local percent=$(( CURRENT_STEP * 100 / TOTAL_STEPS ))
    printf "\n${C_BOLD}Krok %d/%d${C_RESET} %s ${C_MUTED}" "$CURRENT_STEP" "$TOTAL_STEPS" "$1"
    render_bar "$percent"
    printf "${C_RESET}\n"
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        log_fail "Uruchom instalator jako root lub przez sudo."
        exit 1
    fi
}

detect_debian() {
    if [[ ! -f /etc/os-release ]]; then
        log_fail "Nie znaleziono /etc/os-release."
        exit 1
    fi

    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != "debian" ]]; then
        log_fail "Instalator obsługuje wyłącznie Debiana."
        exit 1
    fi

    DEBIAN_MAJOR="${VERSION_ID%%.*}"
    if [[ -z "${DEBIAN_MAJOR}" || "${DEBIAN_MAJOR}" -lt 10 ]]; then
        log_fail "Wymagany jest Debian 10 lub nowszy."
        exit 1
    fi
}

prompt_default() {
    local prompt="$1"
    local default_value="$2"
    local answer
    read -r -p "${prompt} [${default_value}]: " answer || true
    printf "%s" "${answer:-$default_value}"
}

prompt_timeout_default() {
    local prompt="$1"
    local default_value="$2"
    local timeout_seconds="$3"
    local answer=""
    read -r -t "$timeout_seconds" -p "${prompt} [${default_value}] (timeout ${timeout_seconds}s): " answer || true
    printf "%s" "${answer:-$default_value}"
}

prompt_admin_password() {
    local first=""
    local second=""
    while true; do
        read -r -s -p "Hasło dla pierwszego użytkownika admin: " first
        printf "\n"
        read -r -s -p "Powtórz hasło admina: " second
        printf "\n"
        if [[ -z "$first" || "${#first}" -lt 4 ]]; then
            log_warn "Hasło musi mieć co najmniej 4 znaki."
            continue
        fi
        if [[ "$first" != "$second" ]]; then
            log_warn "Hasła nie są identyczne."
            continue
        fi
        ADMIN_PASSWORD="$first"
        return
    done
}

ensure_group_and_user() {
    if ! getent group "$APP_GROUP" >/dev/null 2>&1; then
        groupadd --system "$APP_GROUP"
    fi
    if ! id -u "$APP_USER" >/dev/null 2>&1; then
        useradd --system --create-home --home-dir "/home/$APP_USER" --gid "$APP_GROUP" --shell /usr/sbin/nologin "$APP_USER"
    fi
}

generate_secret_key() {
    python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

write_env_file() {
    local env_file="$APP_DIR/.env"
    local secret_key="$1"

    if [[ -f "$env_file" ]]; then
        log_warn ".env już istnieje. Zostawiam bez nadpisywania."
        return
    fi

    cat > "$env_file" <<EOF
FLASK_DOWNLOADER_HOST=${APP_HOST_DEFAULT}
FLASK_DOWNLOADER_PORT=${APP_PORT}
FLASK_SECRET_KEY=${secret_key}

FLASK_DOWNLOADER_SERVICE_USER=${APP_USER}
FLASK_DOWNLOADER_SERVICE_GROUP=${APP_GROUP}
FLASK_DOWNLOADER_SERVICE_NAME=${SERVICE_NAME_DEFAULT}
FLASK_DOWNLOADER_DLNA_SERVICE_NAME=${DLNA_SERVICE_NAME_DEFAULT}

FLASK_DOWNLOADER_MOUNT_POINT=${STORAGE_ROOT}
FLASK_DOWNLOADER_DOWNLOAD_DIR=${STORAGE_ROOT}/flask_downloader
FLASK_DOWNLOADER_AUDIO_DOWNLOAD_DIR=${STORAGE_ROOT}/flask_downloader_audio
FLASK_DOWNLOADER_USER_STORAGE_ROOT=${STORAGE_ROOT}/flask_downloader_users

FLASK_DOWNLOADER_SMB_SHARE=
FLASK_DOWNLOADER_SMB_CREDENTIALS_FILE=

FLASK_DOWNLOADER_DLNA_PORT=${DLNA_PORT_DEFAULT}
FLASK_DOWNLOADER_DLNA_CHANNEL=${DLNA_CHANNEL_DEFAULT}
EOF
}

initialize_data_files() {
    APP_DIR="$APP_DIR" ADMIN_PASSWORD="$ADMIN_PASSWORD" STORAGE_ROOT="$STORAGE_ROOT" "$APP_DIR/.venv/bin/python" - <<'PY'
import json
import os
import time
from werkzeug.security import generate_password_hash

app_dir = os.environ["APP_DIR"]
admin_password = os.environ["ADMIN_PASSWORD"]
storage_root = os.environ["STORAGE_ROOT"]
data_dir = os.path.join(app_dir, "data")
os.makedirs(data_dir, exist_ok=True)

config_path = os.path.join(data_dir, "config.json")
jobs_path = os.path.join(data_dir, "jobs.json")
users_path = os.path.join(data_dir, "users.json")

user_root = os.path.join(storage_root, "flask_downloader_users")
config_payload = {
    "user_storage_root": user_root,
    "user_storage_layout_version": 2,
    "download_root": os.path.join(user_root, "admin", "video"),
    "audio_download_root": os.path.join(user_root, "admin", "audio"),
    "job_retention_days": 3,
    "yt_dlp_update_state": {"latest_version": "", "checked_at": 0.0, "check_error": ""},
    "ffmpeg_update_state": {"latest_version": "", "latest_build_id": "", "checked_at": 0.0, "check_error": ""},
    "dlna_update_state": {"latest_version": "", "checked_at": 0.0, "check_error": ""},
    "dlna": {
        "enabled": False,
        "server_name": "Flask Downloader DLNA",
        "bind_ip": "",
        "port": 49152,
        "collections": [],
        "clients": [],
        "media_rules": [],
        "layout_version": 0,
        "last_sync_at": 0.0,
        "last_sync_error": ""
    }
}

if not os.path.isfile(config_path):
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(config_payload, fh, ensure_ascii=False, indent=2)

if not os.path.isfile(jobs_path):
    with open(jobs_path, "w", encoding="utf-8") as fh:
        json.dump([], fh, ensure_ascii=False, indent=2)

if not os.path.isfile(users_path):
    users_payload = {
        "schema_version": 1,
        "users": [
            {
                "username": "admin",
                "role": "admin",
                "password_hash": generate_password_hash(admin_password),
                "enabled": True,
                "created_at": time.time(),
            }
        ],
    }
    with open(users_path, "w", encoding="utf-8") as fh:
        json.dump(users_payload, fh, ensure_ascii=False, indent=2)
PY
}

install_systemd_service() {
    local service_file="/etc/systemd/system/${SERVICE_NAME_DEFAULT}.service"
    local template_file="$APP_DIR/deploy/flask-downloader.service.template"
    local python_bin="$APP_DIR/.venv/bin/python"
    local env_file="$APP_DIR/.env"

    sed \
        -e "s|__APP_USER__|$APP_USER|g" \
        -e "s|__APP_GROUP__|$APP_GROUP|g" \
        -e "s|__APP_DIR__|$APP_DIR|g" \
        -e "s|__ENV_FILE__|$env_file|g" \
        -e "s|__PYTHON_BIN__|$python_bin|g" \
        "$template_file" > "$service_file"

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME_DEFAULT}.service" >/dev/null
    systemctl restart "${SERVICE_NAME_DEFAULT}.service"
}

show_summary() {
    local primary_ip
    primary_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    primary_ip="${primary_ip:-127.0.0.1}"

    printf "\n${C_GREEN}${C_BOLD}Instalacja zakończona.${C_RESET}\n"
    printf "${C_MUTED}Adres aplikacji:${C_RESET} http://%s:%s/\n" "$primary_ip" "$APP_PORT"
    printf "${C_MUTED}Katalog aplikacji:${C_RESET} %s\n" "$APP_DIR"
    printf "${C_MUTED}Użytkownik usługi:${C_RESET} %s:%s\n" "$APP_USER" "$APP_GROUP"
    printf "${C_MUTED}Plik środowiskowy:${C_RESET} %s/.env\n" "$APP_DIR"
    printf "${C_MUTED}Dane aplikacji:${C_RESET} %s/data\n" "$APP_DIR"
    printf "${C_MUTED}Storage użytkowników:${C_RESET} %s/flask_downloader_users\n" "$STORAGE_ROOT"
    printf "${C_MUTED}Status usługi:${C_RESET} "
    systemctl is-active "${SERVICE_NAME_DEFAULT}.service" || true
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-url)
            REPO_URL="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --app-dir)
            APP_DIR="$2"
            shift 2
            ;;
        --storage-root)
            STORAGE_ROOT="$2"
            shift 2
            ;;
        --user)
            APP_USER="$2"
            shift 2
            ;;
        --group)
            APP_GROUP="$2"
            shift 2
            ;;
        --port)
            APP_PORT="$2"
            shift 2
            ;;
        *)
            log_fail "Nieznany parametr: $1"
            exit 1
            ;;
    esac
done

print_banner

begin_step "Wykrywanie systemu"
require_root
detect_debian
log_ok "Wykryto Debian ${DEBIAN_MAJOR}."

begin_step "Pobranie ustawień instalacji"
APP_DIR="$(prompt_default 'Katalog aplikacji' "$APP_DIR")"
STORAGE_ROOT="$(prompt_default 'Katalog bazowy danych użytkowników' "$STORAGE_ROOT")"
APP_USER="$(prompt_default 'Użytkownik Linux dla usługi' "$APP_USER")"
APP_GROUP="$(prompt_default 'Grupa Linux dla usługi' "$APP_GROUP")"
APP_PORT="$(prompt_timeout_default 'Port aplikacji' "$APP_PORT" 30)"
while ! [[ "$APP_PORT" =~ ^[0-9]+$ ]] || (( APP_PORT < 1 || APP_PORT > 65535 )); do
    log_warn "Port musi być liczbą z zakresu 1-65535."
    APP_PORT="$(prompt_default 'Port aplikacji' "$APP_PORT_DEFAULT")"
done
prompt_admin_password
log_ok "Zebrano ustawienia instalacyjne."

begin_step "Instalacja pakietów systemowych"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git ca-certificates curl python3 python3-venv python3-pip
log_ok "Pakiety systemowe są gotowe."

begin_step "Tworzenie użytkownika i uprawnień"
ensure_group_and_user
mkdir -p "$APP_DIR" "$APP_DIR/backups" "$STORAGE_ROOT"
mkdir -p "$STORAGE_ROOT/flask_downloader" "$STORAGE_ROOT/flask_downloader_audio" "$STORAGE_ROOT/flask_downloader_users/admin/video" "$STORAGE_ROOT/flask_downloader_users/admin/audio"
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR" "$STORAGE_ROOT"
log_ok "Użytkownik i katalogi systemowe są gotowe."

begin_step "Pobranie kodu aplikacji"
if [[ -d "$APP_DIR/.git" ]]; then
    git -C "$APP_DIR" fetch --all --prune
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
    if [[ -n "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name backups 2>/dev/null)" ]]; then
        log_fail "Katalog aplikacji nie jest pusty i nie wygląda na repo Git: $APP_DIR"
        exit 1
    fi
    rm -rf "$APP_DIR"
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
log_ok "Kod aplikacji jest gotowy."

begin_step "Tworzenie środowiska Python"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
log_ok "Środowisko Python zostało przygotowane."

begin_step "Tworzenie .env"
write_env_file "$(generate_secret_key)"
chown "$APP_USER:$APP_GROUP" "$APP_DIR/.env" 2>/dev/null || true
log_ok "Plik .env jest gotowy."

begin_step "Inicjalizacja danych aplikacji"
initialize_data_files
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/data"
log_ok "Pliki data/config.json, data/jobs.json i data/users.json są gotowe."

begin_step "Instalacja usługi systemd"
install_systemd_service
log_ok "Usługa systemd została zainstalowana."

begin_step "Weryfikacja działania"
sleep 2
systemctl --no-pager --full status "${SERVICE_NAME_DEFAULT}.service" >/dev/null
log_ok "Usługa Flask Downloader działa poprawnie."

begin_step "Podsumowanie"
show_summary
