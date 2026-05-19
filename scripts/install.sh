#!/usr/bin/env bash
set -euo pipefail

TOTAL_STEPS=15
CURRENT_STEP=0
INSTALL_LOG="${FLASK_DOWNLOADER_INSTALL_LOG:-/tmp/flask_downloader_install.log}"

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
MAX_PARALLEL_DOWNLOADS_PER_USER_DEFAULT="3"
SERVICE_NAME_DEFAULT="${FLASK_DOWNLOADER_SERVICE_NAME:-flask-downloader}"
DLNA_SERVICE_NAME_DEFAULT="${FLASK_DOWNLOADER_DLNA_SERVICE_NAME:-}"
RADIO_SERVICE_NAME_DEFAULT="${FLASK_DOWNLOADER_RADIO_SERVICE_NAME:-}"
RADIO_STATION_TEMPLATE_DEFAULT="${FLASK_DOWNLOADER_RADIO_STATION_SERVICE_TEMPLATE:-}"
DLNA_PORT_DEFAULT="49152"
DLNA_CHANNEL_DEFAULT="latest"
NON_INTERACTIVE=0
ADMIN_PASSWORD="${FLASK_DOWNLOADER_ADMIN_PASSWORD:-}"
APP_DIR_FROM_ARG=0
STORAGE_ROOT_FROM_ARG=0
APP_USER_FROM_ARG=0
APP_GROUP_FROM_ARG=0
APP_PORT_FROM_ARG=0
SERVICE_NAME_FROM_ARG=0
DLNA_SERVICE_NAME_FROM_ARG=0
RADIO_SERVICE_NAME_FROM_ARG=0
RADIO_STATION_TEMPLATE_FROM_ARG=0

REPO_URL="$REPO_URL_DEFAULT"
BRANCH="$BRANCH_DEFAULT"
APP_DIR="$APP_DIR_DEFAULT"
STORAGE_ROOT="$STORAGE_ROOT_DEFAULT"
APP_USER="$APP_USER_DEFAULT"
APP_GROUP="$APP_GROUP_DEFAULT"
APP_PORT="$APP_PORT_DEFAULT"
SERVICE_NAME="$SERVICE_NAME_DEFAULT"
DLNA_SERVICE_NAME="$DLNA_SERVICE_NAME_DEFAULT"
RADIO_SERVICE_NAME="$RADIO_SERVICE_NAME_DEFAULT"
RADIO_STATION_TEMPLATE="$RADIO_STATION_TEMPLATE_DEFAULT"

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

run_logged() {
    local description="$1"
    shift

    log_info "$description"
    if "$@" >>"$INSTALL_LOG" 2>&1; then
        return 0
    fi

    log_fail "${description}. Szczegóły: ${INSTALL_LOG}"
    tail -n 40 "$INSTALL_LOG" >&2 || true
    exit 1
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

port_is_available() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        if ss -ltnH "( sport = :${port} )" 2>/dev/null | grep -q .; then
            return 1
        fi
        return 0
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        return 0
    fi

    python3 - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("0.0.0.0", port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
raise SystemExit(0)
PY
}

validate_port_value() {
    local port="$1"
    [[ "$port" =~ ^[0-9]+$ ]] || return 1
    (( port >= 1 && port <= 65535 )) || return 1
    return 0
}

resolve_install_value() {
    local current_value="$1"
    local was_set="$2"
    local prompt="$3"
    local default_value="$4"
    local timeout_seconds="${5:-}"

    if [[ "$was_set" -eq 1 || "$NON_INTERACTIVE" -eq 1 ]]; then
        printf "%s" "$current_value"
        return
    fi

    if [[ -n "$timeout_seconds" ]]; then
        prompt_timeout_default "$prompt" "$default_value" "$timeout_seconds"
        return
    fi

    prompt_default "$prompt" "$default_value"
}

current_install_uses_port() {
    local port="$1"
    local env_file="$APP_DIR/.env"
    local configured_port=""

    if [[ ! -f "$env_file" ]]; then
        return 1
    fi

    configured_port="$(awk -F= '/^FLASK_DOWNLOADER_PORT=/{print $2}' "$env_file" | tail -n 1 | tr -d '\r' | xargs)"
    [[ -n "$configured_port" && "$configured_port" == "$port" ]]
}

ensure_group_and_user() {
    if ! getent group "$APP_GROUP" >/dev/null 2>&1; then
        groupadd --system "$APP_GROUP"
    fi
    if ! id -u "$APP_USER" >/dev/null 2>&1; then
        useradd --system --create-home --home-dir "/home/$APP_USER" --gid "$APP_GROUP" --shell /usr/sbin/nologin "$APP_USER"
    fi
}

ensure_git_safe_directory() {
    git config --global --add safe.directory "$APP_DIR" >/dev/null 2>&1 || true
}

generate_secret_key() {
    python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

run_app_bootstrap_task() {
    local task_key="$1"
    APP_DIR="$APP_DIR" "$APP_DIR/.venv/bin/python" - "$task_key" <<'PY'
import os
import sys

app_dir = os.environ["APP_DIR"]
task_key = str(sys.argv[1] or "").strip().lower()
if not task_key:
    print("Brak identyfikatora zadania bootstrap.")
    raise SystemExit(1)

os.chdir(app_dir)

from flask_downloader.legacy_app import (  # noqa: E402
    install_or_update_dlna_server,
    install_or_update_ffmpeg,
    install_or_update_radio_backend,
    update_yt_dlp_package,
)


TASKS = {
    "yt_dlp": update_yt_dlp_package,
    "ffmpeg": install_or_update_ffmpeg,
    "dlna": install_or_update_dlna_server,
    "radio": install_or_update_radio_backend,
}


def progress_callback(**event):
    percent = event.get("progress_percent")
    status_label = str(event.get("status_label") or "").strip()
    detail = str(event.get("detail") or "").strip()
    prefix = "[%s]" % task_key
    if percent not in (None, ""):
        try:
            prefix += " %05.1f%%" % float(percent)
        except Exception:
            pass
    line = prefix
    if status_label:
        line += " " + status_label
    if detail:
        line += " | " + detail
    print(line)


task = TASKS.get(task_key)
if task is None:
    print("Nieznane zadanie bootstrap: %s" % task_key)
    raise SystemExit(1)

ok, message = task(progress_callback=progress_callback)
print("[%s] result=%s message=%s" % (task_key, ok, message))
raise SystemExit(0 if ok else 1)
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
FLASK_DOWNLOADER_MAX_PARALLEL_DOWNLOADS_PER_USER=${MAX_PARALLEL_DOWNLOADS_PER_USER_DEFAULT}
FLASK_SECRET_KEY=${secret_key}

FLASK_DOWNLOADER_SERVICE_USER=${APP_USER}
FLASK_DOWNLOADER_SERVICE_GROUP=${APP_GROUP}
FLASK_DOWNLOADER_SERVICE_NAME=${SERVICE_NAME}
FLASK_DOWNLOADER_DLNA_SERVICE_NAME=${DLNA_SERVICE_NAME}
FLASK_DOWNLOADER_RADIO_SERVICE_NAME=${RADIO_SERVICE_NAME}
FLASK_DOWNLOADER_RADIO_STATION_SERVICE_TEMPLATE=${RADIO_STATION_TEMPLATE}

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
import secrets
import sys
import time
from werkzeug.security import generate_password_hash

app_dir = os.environ["APP_DIR"]
admin_password = os.environ["ADMIN_PASSWORD"]
storage_root = os.environ["STORAGE_ROOT"]
sys.path.insert(0, app_dir)

from flask_downloader.stores.radios_store import default_radio_store

data_dir = os.path.join(app_dir, "data")
os.makedirs(data_dir, exist_ok=True)

config_path = os.path.join(data_dir, "config.json")
jobs_path = os.path.join(data_dir, "jobs.json")
users_path = os.path.join(data_dir, "users.json")
radios_path = os.path.join(data_dir, "radios.json")
config_example_path = os.path.join(data_dir, "config.example.json")
users_example_path = os.path.join(data_dir, "users.example.json")
jobs_example_path = os.path.join(data_dir, "jobs.example.json")

user_root = os.path.join(storage_root, "flask_downloader_users")


def load_example_json(path, fallback):
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if isinstance(payload, type(fallback)):
                return payload
        except Exception:
            pass
    return fallback


def generate_runtime_secret(min_length=24):
    raw = secrets.token_urlsafe(max(18, int(min_length or 24)))
    text = str(raw or "").strip()
    if len(text) < min_length:
        text = (text + secrets.token_urlsafe(min_length))[:min_length]
    return text[: max(min_length, 24)]


config_payload = load_example_json(config_example_path, {
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
        "last_sync_error": "",
    },
})
config_payload["user_storage_root"] = user_root
config_payload["download_root"] = os.path.join(user_root, "admin", "video")
config_payload["audio_download_root"] = os.path.join(user_root, "admin", "audio")

if not os.path.isfile(config_path):
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(config_payload, fh, ensure_ascii=False, indent=2)

if not os.path.isfile(jobs_path):
    jobs_payload = load_example_json(jobs_example_path, [])
    with open(jobs_path, "w", encoding="utf-8") as fh:
        json.dump(jobs_payload, fh, ensure_ascii=False, indent=2)

if not os.path.isfile(users_path):
    users_payload = load_example_json(users_example_path, {"schema_version": 1, "users": []})
    if not isinstance(users_payload, dict):
        users_payload = {"schema_version": 1, "users": []}
    users_payload["schema_version"] = int(users_payload.get("schema_version") or 1)
    users_payload["users"] = [
        {
            "username": "admin",
            "role": "admin",
            "password_hash": generate_password_hash(admin_password),
            "enabled": True,
            "created_at": time.time(),
        }
    ]
    with open(users_path, "w", encoding="utf-8") as fh:
        json.dump(users_payload, fh, ensure_ascii=False, indent=2)

if not os.path.isfile(radios_path):
    radios_payload = default_radio_store()
    global_payload = radios_payload.get("global") if isinstance(radios_payload, dict) else None
    if isinstance(global_payload, dict):
        global_payload["source_password"] = generate_runtime_secret(32)
        global_payload["admin_password"] = generate_runtime_secret(32)
    with open(radios_path, "w", encoding="utf-8") as fh:
        json.dump(radios_payload, fh, ensure_ascii=False, indent=2)
PY
}

install_systemd_service() {
    local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
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
    systemctl enable "${SERVICE_NAME}.service" >/dev/null
    systemctl restart "${SERVICE_NAME}.service"
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
    printf "${C_MUTED}Log instalacji:${C_RESET} %s\n" "$INSTALL_LOG"
    printf "${C_MUTED}Status usługi:${C_RESET} "
    systemctl is-active "${SERVICE_NAME}.service" || true
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
            APP_DIR_FROM_ARG=1
            shift 2
            ;;
        --storage-root)
            STORAGE_ROOT="$2"
            STORAGE_ROOT_FROM_ARG=1
            shift 2
            ;;
        --user)
            APP_USER="$2"
            APP_USER_FROM_ARG=1
            shift 2
            ;;
        --group)
            APP_GROUP="$2"
            APP_GROUP_FROM_ARG=1
            shift 2
            ;;
        --port)
            APP_PORT="$2"
            APP_PORT_FROM_ARG=1
            shift 2
            ;;
        --service-name)
            SERVICE_NAME="$2"
            SERVICE_NAME_FROM_ARG=1
            shift 2
            ;;
        --dlna-service-name)
            DLNA_SERVICE_NAME="$2"
            DLNA_SERVICE_NAME_FROM_ARG=1
            shift 2
            ;;
        --radio-service-name)
            RADIO_SERVICE_NAME="$2"
            RADIO_SERVICE_NAME_FROM_ARG=1
            shift 2
            ;;
        --radio-station-template)
            RADIO_STATION_TEMPLATE="$2"
            RADIO_STATION_TEMPLATE_FROM_ARG=1
            shift 2
            ;;
        --admin-password)
            ADMIN_PASSWORD="$2"
            shift 2
            ;;
        --non-interactive|--yes)
            NON_INTERACTIVE=1
            shift
            ;;
        *)
            log_fail "Nieznany parametr: $1"
            exit 1
            ;;
    esac
done

print_banner
: > "$INSTALL_LOG"

begin_step "Wykrywanie systemu"
require_root
detect_debian
log_ok "Wykryto Debian ${DEBIAN_MAJOR}."

begin_step "Pobranie ustawień instalacji"
APP_DIR="$(resolve_install_value "$APP_DIR" "$APP_DIR_FROM_ARG" 'Katalog aplikacji' "$APP_DIR_DEFAULT")"
STORAGE_ROOT="$(resolve_install_value "$STORAGE_ROOT" "$STORAGE_ROOT_FROM_ARG" 'Katalog bazowy danych użytkowników' "$STORAGE_ROOT_DEFAULT")"
APP_USER="$(resolve_install_value "$APP_USER" "$APP_USER_FROM_ARG" 'Użytkownik Linux dla usługi' "$APP_USER_DEFAULT")"
APP_GROUP="$(resolve_install_value "$APP_GROUP" "$APP_GROUP_FROM_ARG" 'Grupa Linux dla usługi' "$APP_GROUP_DEFAULT")"
APP_PORT="$(resolve_install_value "$APP_PORT" "$APP_PORT_FROM_ARG" 'Port aplikacji' "$APP_PORT_DEFAULT" 30)"
SERVICE_NAME="$(resolve_install_value "$SERVICE_NAME" "$SERVICE_NAME_FROM_ARG" 'Nazwa usługi Flask w systemd' "$SERVICE_NAME_DEFAULT")"
if [[ -z "$DLNA_SERVICE_NAME_DEFAULT" ]]; then
    DLNA_SERVICE_NAME_DEFAULT="${SERVICE_NAME}-dlna"
fi
if [[ -z "$RADIO_SERVICE_NAME_DEFAULT" ]]; then
    RADIO_SERVICE_NAME_DEFAULT="${SERVICE_NAME}-radio"
fi
if [[ -z "$RADIO_STATION_TEMPLATE_DEFAULT" ]]; then
    RADIO_STATION_TEMPLATE_DEFAULT="${SERVICE_NAME}-radio-station@"
fi
DLNA_SERVICE_NAME="$(resolve_install_value "${DLNA_SERVICE_NAME:-$DLNA_SERVICE_NAME_DEFAULT}" "$DLNA_SERVICE_NAME_FROM_ARG" 'Nazwa usługi DLNA w systemd' "$DLNA_SERVICE_NAME_DEFAULT")"
RADIO_SERVICE_NAME="$(resolve_install_value "${RADIO_SERVICE_NAME:-$RADIO_SERVICE_NAME_DEFAULT}" "$RADIO_SERVICE_NAME_FROM_ARG" 'Nazwa backendu radia w systemd' "$RADIO_SERVICE_NAME_DEFAULT")"
RADIO_STATION_TEMPLATE="$(resolve_install_value "${RADIO_STATION_TEMPLATE:-$RADIO_STATION_TEMPLATE_DEFAULT}" "$RADIO_STATION_TEMPLATE_FROM_ARG" 'Prefiks szablonu usług stacji radia' "$RADIO_STATION_TEMPLATE_DEFAULT")"
while ! validate_port_value "$APP_PORT"; do
    if [[ "$NON_INTERACTIVE" -eq 1 || "$APP_PORT_FROM_ARG" -eq 1 ]]; then
        log_fail "Port musi być liczbą z zakresu 1-65535."
        exit 1
    fi
    log_warn "Port musi być liczbą z zakresu 1-65535."
    APP_PORT="$(prompt_default 'Port aplikacji' "$APP_PORT_DEFAULT")"
done
while ! port_is_available "$APP_PORT"; do
    if current_install_uses_port "$APP_PORT"; then
        break
    fi
    if [[ "$NON_INTERACTIVE" -eq 1 || "$APP_PORT_FROM_ARG" -eq 1 ]]; then
        log_fail "Port ${APP_PORT} jest już zajęty."
        exit 1
    fi
    log_warn "Port ${APP_PORT} jest już zajęty."
    APP_PORT="$(prompt_default 'Port aplikacji' "$APP_PORT_DEFAULT")"
done
if [[ -n "$ADMIN_PASSWORD" ]]; then
    if [[ "${#ADMIN_PASSWORD}" -lt 4 ]]; then
        log_fail "Hasło admina musi mieć co najmniej 4 znaki."
        exit 1
    fi
elif [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    log_fail "W trybie nieinteraktywnym podaj hasło przez FLASK_DOWNLOADER_ADMIN_PASSWORD albo --admin-password."
    exit 1
else
    prompt_admin_password
fi
log_ok "Zebrano ustawienia instalacyjne."

begin_step "Instalacja pakietów systemowych"
export DEBIAN_FRONTEND=noninteractive
run_logged "Odświeżam listę pakietów apt" apt-get update -y
run_logged "Instaluję pakiety systemowe" apt-get install -y git ca-certificates curl python3 python3-venv python3-pip cifs-utils iproute2 ffmpegthumbnailer
log_ok "Pakiety systemowe są gotowe."

begin_step "Tworzenie użytkownika i uprawnień"
ensure_group_and_user
mkdir -p "$APP_DIR" "$APP_DIR/backups" "$STORAGE_ROOT"
mkdir -p "$STORAGE_ROOT/flask_downloader" "$STORAGE_ROOT/flask_downloader_audio" "$STORAGE_ROOT/flask_downloader_users/admin/video" "$STORAGE_ROOT/flask_downloader_users/admin/audio"
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR" "$STORAGE_ROOT"
log_ok "Użytkownik i katalogi systemowe są gotowe."

begin_step "Pobranie kodu aplikacji"
if [[ -d "$APP_DIR/.git" ]]; then
    ensure_git_safe_directory
    run_logged "Odświeżam lokalne repozytorium aplikacji" git -C "$APP_DIR" fetch --all --prune
    run_logged "Przełączam repozytorium na gałąź ${BRANCH}" git -C "$APP_DIR" checkout "$BRANCH"
    run_logged "Pobieram najnowszy kod z origin/${BRANCH}" git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
    if [[ -n "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name backups 2>/dev/null)" ]]; then
        log_fail "Katalog aplikacji nie jest pusty i nie wygląda na repo Git: $APP_DIR"
        exit 1
    fi
    rm -rf "$APP_DIR"
    run_logged "Klonuję kod aplikacji" git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    ensure_git_safe_directory
fi
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
log_ok "Kod aplikacji jest gotowy."

begin_step "Tworzenie środowiska Python"
run_logged "Tworzę środowisko virtualenv" python3 -m venv "$APP_DIR/.venv"
run_logged "Aktualizuję pip" "$APP_DIR/.venv/bin/pip" install --upgrade pip
run_logged "Instaluję zależności Pythona" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
log_ok "Środowisko Python zostało przygotowane."

begin_step "Tworzenie .env"
write_env_file "$(generate_secret_key)"
chown "$APP_USER:$APP_GROUP" "$APP_DIR/.env" 2>/dev/null || true
log_ok "Plik .env jest gotowy."

begin_step "Inicjalizacja danych aplikacji"
run_logged "Tworzę początkowe pliki danych aplikacji" initialize_data_files
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/data"
log_ok "Pliki data/config.json, data/jobs.json, data/users.json i data/radios.json są gotowe."

begin_step "Aktualizacja yt-dlp"
run_logged "Aktualizuję yt-dlp w środowisku aplikacji" run_app_bootstrap_task yt_dlp
log_ok "yt-dlp jest gotowy."

begin_step "Instalacja ffmpeg"
run_logged "Instaluję zarządzany ffmpeg dla aplikacji" run_app_bootstrap_task ffmpeg
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/tools" 2>/dev/null || true
log_ok "ffmpeg jest gotowy."

begin_step "Instalacja DLNA"
run_logged "Instaluję backend Gerbera i przygotowuję runtime DLNA" run_app_bootstrap_task dlna
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/tools" 2>/dev/null || true
log_ok "Backend DLNA jest gotowy."

begin_step "Instalacja backendu radia"
run_logged "Instaluję backend Icecast + Liquidsoap" run_app_bootstrap_task radio
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/data" "$APP_DIR/tools" 2>/dev/null || true
log_ok "Backend radia jest gotowy."

begin_step "Instalacja usługi systemd"
run_logged "Instaluję i restartuję usługę systemd" install_systemd_service
log_ok "Usługa systemd została zainstalowana."

begin_step "Weryfikacja działania"
sleep 2
run_logged "Sprawdzam status usługi ${SERVICE_NAME}.service" systemctl --no-pager --full status "${SERVICE_NAME}.service"
log_ok "Usługa Flask Downloader działa poprawnie."

begin_step "Podsumowanie"
show_summary
