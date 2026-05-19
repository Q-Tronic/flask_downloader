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
INTERACTIVE_INPUT_FD=""
STATUS_LINE_VISIBLE=0
APP_DIR_EXISTED_BEFORE=0
STORAGE_ROOT_EXISTED_BEFORE=0
STORAGE_DOWNLOAD_DIR_EXISTED_BEFORE=0
STORAGE_AUDIO_DIR_EXISTED_BEFORE=0
STORAGE_USERS_DIR_EXISTED_BEFORE=0
APP_USER_EXISTED_BEFORE=0
APP_GROUP_EXISTED_BEFORE=0
FLASK_SERVICE_FILE_EXISTED_BEFORE=0
DLNA_SERVICE_FILE_EXISTED_BEFORE=0
RADIO_SERVICE_FILE_EXISTED_BEFORE=0
RADIO_STATION_TEMPLATE_FILE_EXISTED_BEFORE=0
DLNA_EXPORT_ROOT_EXISTED_BEFORE=0
GERBERA_REPO_KEY_EXISTED_BEFORE=0
GERBERA_REPO_LIST_EXISTED_BEFORE=0
CLEANUP_STATE_RECORDED=0
SUDOERS_RULE_FILE=""
SUDOERS_RULE_FILE_EXISTED_BEFORE=0

trim_text() {
    local text="$1"
    text="${text#"${text%%[![:space:]]*}"}"
    text="${text%"${text##*[![:space:]]}"}"
    printf "%s" "$text"
}

ensure_interactive_input_fd() {
    if [[ -n "$INTERACTIVE_INPUT_FD" ]]; then
        return 0
    fi

    if [[ -t 0 ]]; then
        INTERACTIVE_INPUT_FD="0"
        return 0
    fi

    if exec 3<> /dev/tty 2>/dev/null; then
        INTERACTIVE_INPUT_FD="3"
        return 0
    fi

    return 1
}

render_bar_text_with_slots() {
    local percent="$1"
    local total_slots="${2:-28}"
    local filled=$(( percent * total_slots / 100 ))
    local empty=$(( total_slots - filled ))
    local bar
    bar="$(printf '%*s' "$filled" '' | tr ' ' '#')"
    bar="${bar}$(printf '%*s' "$empty" '' | tr ' ' '-')"
    printf "[%s] %3s%%" "$bar" "$percent"
}

render_bar_text() {
    render_bar_text_with_slots "$1" 28
}

render_bar() {
    render_bar_text "$1"
}

clear_screen_if_interactive() {
    if [[ -t 1 && -n "${TERM:-}" && "${TERM}" != "dumb" ]] && command -v clear >/dev/null 2>&1; then
        clear >/dev/null 2>&1 || true
    fi
}

format_elapsed() {
    local seconds="${1:-0}"
    if ! [[ "$seconds" =~ ^[0-9]+$ ]]; then
        seconds=0
    fi
    printf "%02d:%02d" $(( seconds / 60 )) $(( seconds % 60 ))
}

current_step_percent() {
    printf "%d" $(( CURRENT_STEP * 100 / TOTAL_STEPS ))
}

terminal_columns() {
    local cols=""
    if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
        cols="$(tput cols 2>/dev/null || true)"
    fi
    if ! [[ "$cols" =~ ^[0-9]+$ ]] || (( cols < 40 )); then
        cols=80
    fi
    printf "%s" "$cols"
}

truncate_plain_text() {
    local text="$1"
    local limit="${2:-80}"
    local ellipsis="..."

    if ! [[ "$limit" =~ ^[0-9]+$ ]] || (( limit <= 0 )); then
        printf ""
        return 0
    fi

    if (( ${#text} <= limit )); then
        printf "%s" "$text"
        return 0
    fi

    if (( limit <= ${#ellipsis} )); then
        printf "%.*s" "$limit" "$ellipsis"
        return 0
    fi

    printf "%s%s" "${text:0:$((limit - ${#ellipsis}))}" "$ellipsis"
}

show_live_status() {
    if [[ ! -t 1 ]]; then
        return 0
    fi

    local local_percent="${1:-0}"
    local activity_label="$2"
    local activity_detail="${3:-}"
    local elapsed_seconds="${4:-0}"
    local overall_percent
    local term_cols
    local bar_slots=18
    local bar_text=""
    local detail_suffix=""
    local short_elapsed=""
    local line

    overall_percent="$(current_step_percent)"
    term_cols="$(terminal_columns)"
    if (( term_cols < 70 )); then
        bar_slots=12
    fi
    if (( term_cols < 56 )); then
        bar_slots=8
    fi
    bar_text="$(render_bar_text_with_slots "$overall_percent" "$bar_slots")"
    short_elapsed="trwa $(format_elapsed "$elapsed_seconds")"

    if [[ -n "$activity_detail" ]]; then
        detail_suffix="$activity_detail"
    fi
    if [[ -n "$local_percent" && "$local_percent" != "0" ]]; then
        if [[ -n "$detail_suffix" ]]; then
            detail_suffix="${local_percent}% ${detail_suffix}"
        else
            detail_suffix="${local_percent}%"
        fi
    fi

    line="${bar_text} ${activity_label}"
    if [[ -n "$detail_suffix" ]]; then
        line="${line} | ${detail_suffix}"
    fi
    line="${line} | ${short_elapsed}"
    line="$(truncate_plain_text "$line" "$((term_cols - 1))")"
    printf "\r\033[2K%s" "$line"
    STATUS_LINE_VISIBLE=1
}

clear_live_status() {
    if [[ "${STATUS_LINE_VISIBLE:-0}" -eq 1 ]]; then
        printf "\r\033[2K"
        STATUS_LINE_VISIBLE=0
    fi
}

parse_bootstrap_progress_line() {
    local line="$1"
    BOOTSTRAP_PROGRESS_PERCENT=""
    BOOTSTRAP_PROGRESS_STATUS=""
    BOOTSTRAP_PROGRESS_DETAIL=""

    if [[ "$line" =~ ^\[[^]]+\][[:space:]]+([0-9]+)(\.[0-9]+)?%[[:space:]]+([^|]+?)([[:space:]]+\|[[:space:]]+(.*))?$ ]]; then
        BOOTSTRAP_PROGRESS_PERCENT="${BASH_REMATCH[1]}"
        BOOTSTRAP_PROGRESS_STATUS="$(trim_text "${BASH_REMATCH[3]}")"
        BOOTSTRAP_PROGRESS_DETAIL="$(trim_text "${BASH_REMATCH[5]:-}")"
        return 0
    fi

    return 1
}

stream_bootstrap_log_updates() {
    local task_log="$1"
    local processed_lines="$2"
    local description="$3"
    local start_ts="$4"
    local total_lines=0
    local line=""
    local elapsed=0

    if [[ -f "$task_log" ]]; then
        total_lines="$(wc -l < "$task_log" 2>/dev/null || printf '0')"
    fi

    if ! [[ "$total_lines" =~ ^[0-9]+$ ]]; then
        total_lines=0
    fi

    if (( total_lines <= processed_lines )); then
        printf "%s" "$processed_lines"
        return 0
    fi

    while IFS= read -r line; do
        printf "%s\n" "$line" >>"$INSTALL_LOG"
        elapsed=$(( $(date +%s) - start_ts ))
        if parse_bootstrap_progress_line "$line"; then
            show_live_status "${BOOTSTRAP_PROGRESS_PERCENT:-0}" "${BOOTSTRAP_PROGRESS_STATUS:-$description}" "${BOOTSTRAP_PROGRESS_DETAIL:-$description}" "$elapsed"
        elif [[ -n "$line" ]]; then
            show_live_status 0 "$description" "$line" "$elapsed"
        fi
    done < <(sed -n "$((processed_lines + 1)),${total_lines}p" "$task_log")

    printf "%s" "$total_lines"
}

print_banner() {
    clear_screen_if_interactive
    printf "\n${C_BLUE}${C_BOLD}VLC Stream Extractor${C_RESET} ${C_MUTED}instalator Debiana${C_RESET}\n"
    printf "${C_MUTED}Automatyczna instalacja aplikacji, .env, usług i pierwszego administratora.${C_RESET}\n\n"
}

log_info() {
    clear_live_status
    printf "${C_CYAN}INFO${C_RESET} %s\n" "$1"
}

log_ok() {
    clear_live_status
    printf "${C_GREEN}OK${C_RESET}   %s\n" "$1"
}

log_warn() {
    clear_live_status
    printf "${C_YELLOW}WARN${C_RESET} %s\n" "$1"
}

log_fail() {
    clear_live_status
    printf "${C_RED}ERR${C_RESET}  %s\n" "$1" >&2
}

run_logged() {
    local description="$1"
    shift
    local cmd_pid=0
    local command_ok=0
    local spinner_frames='|/-\'
    local spinner_index=0
    local start_ts
    local elapsed=0
    local spinner_frame=""

    log_info "$description"
    start_ts="$(date +%s)"
    set +e
    "$@" >>"$INSTALL_LOG" 2>&1 &
    cmd_pid=$!
    while kill -0 "$cmd_pid" 2>/dev/null; do
        elapsed=$(( $(date +%s) - start_ts ))
        spinner_frame="${spinner_frames:spinner_index:1}"
        show_live_status 0 "$description" "pracuję ${spinner_frame}" "$elapsed"
        spinner_index=$(( (spinner_index + 1) % 4 ))
        sleep 1
    done
    wait "$cmd_pid"
    command_ok=$?
    set -e
    clear_live_status

    if [[ "$command_ok" -eq 0 ]]; then
        return 0
    fi

    log_fail "${description}. Szczegóły: ${INSTALL_LOG}"
    tail -n 40 "$INSTALL_LOG" >&2 || true
    abort_install
}

run_logged_streamed() {
    local description="$1"
    shift
    local task_log=""
    local processed_lines=0
    local cmd_pid=0
    local command_ok=0
    local start_ts

    log_info "$description"
    task_log="$(mktemp)"
    start_ts="$(date +%s)"
    set +e
    "$@" >"$task_log" 2>&1 &
    cmd_pid=$!
    while kill -0 "$cmd_pid" 2>/dev/null; do
        processed_lines="$(stream_bootstrap_log_updates "$task_log" "$processed_lines" "$description" "$start_ts")"
        if [[ "$processed_lines" == "0" ]]; then
            show_live_status 0 "$description" "uruchamiam zadanie" $(( $(date +%s) - start_ts ))
        fi
        sleep 1
    done
    wait "$cmd_pid"
    command_ok=$?
    processed_lines="$(stream_bootstrap_log_updates "$task_log" "$processed_lines" "$description" "$start_ts")"
    set -e
    clear_live_status
    rm -f "$task_log"

    if [[ "$command_ok" -eq 0 ]]; then
        return 0
    fi

    log_fail "${description}. Szczegóły: ${INSTALL_LOG}"
    tail -n 40 "$INSTALL_LOG" >&2 || true
    abort_install
}

record_preinstall_state() {
    SUDOERS_RULE_FILE="$(build_sudoers_rule_file_path)"
    [[ -e "$APP_DIR" ]] && APP_DIR_EXISTED_BEFORE=1
    [[ -e "$STORAGE_ROOT" ]] && STORAGE_ROOT_EXISTED_BEFORE=1
    [[ -d "$STORAGE_ROOT/flask_downloader" ]] && STORAGE_DOWNLOAD_DIR_EXISTED_BEFORE=1
    [[ -d "$STORAGE_ROOT/flask_downloader_audio" ]] && STORAGE_AUDIO_DIR_EXISTED_BEFORE=1
    [[ -d "$STORAGE_ROOT/flask_downloader_users" ]] && STORAGE_USERS_DIR_EXISTED_BEFORE=1
    getent group "$APP_GROUP" >/dev/null 2>&1 && APP_GROUP_EXISTED_BEFORE=1
    id -u "$APP_USER" >/dev/null 2>&1 && APP_USER_EXISTED_BEFORE=1
    [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]] && FLASK_SERVICE_FILE_EXISTED_BEFORE=1
    [[ -f "/etc/systemd/system/${DLNA_SERVICE_NAME}.service" ]] && DLNA_SERVICE_FILE_EXISTED_BEFORE=1
    [[ -f "/etc/systemd/system/${RADIO_SERVICE_NAME}.service" ]] && RADIO_SERVICE_FILE_EXISTED_BEFORE=1
    [[ -f "/etc/systemd/system/${RADIO_STATION_TEMPLATE}.service" ]] && RADIO_STATION_TEMPLATE_FILE_EXISTED_BEFORE=1
    [[ -e "/dlna" ]] && DLNA_EXPORT_ROOT_EXISTED_BEFORE=1
    [[ -f "/usr/share/keyrings/gerbera-keyring.gpg" ]] && GERBERA_REPO_KEY_EXISTED_BEFORE=1
    [[ -f "/etc/apt/sources.list.d/gerbera.list" ]] && GERBERA_REPO_LIST_EXISTED_BEFORE=1
    [[ -n "$SUDOERS_RULE_FILE" && -f "$SUDOERS_RULE_FILE" ]] && SUDOERS_RULE_FILE_EXISTED_BEFORE=1
    CLEANUP_STATE_RECORDED=1
}

cleanup_candidates_exist() {
    if (( CLEANUP_STATE_RECORDED == 0 )); then
        return 1
    fi
    if (( APP_DIR_EXISTED_BEFORE == 0 )) && [[ -e "$APP_DIR" ]]; then
        return 0
    fi
    if (( STORAGE_DOWNLOAD_DIR_EXISTED_BEFORE == 0 )) && [[ -e "$STORAGE_ROOT/flask_downloader" ]]; then
        return 0
    fi
    if (( STORAGE_AUDIO_DIR_EXISTED_BEFORE == 0 )) && [[ -e "$STORAGE_ROOT/flask_downloader_audio" ]]; then
        return 0
    fi
    if (( STORAGE_USERS_DIR_EXISTED_BEFORE == 0 )) && [[ -e "$STORAGE_ROOT/flask_downloader_users" ]]; then
        return 0
    fi
    if (( STORAGE_ROOT_EXISTED_BEFORE == 0 )) && [[ -e "$STORAGE_ROOT" ]]; then
        return 0
    fi
    if (( FLASK_SERVICE_FILE_EXISTED_BEFORE == 0 )) && [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
        return 0
    fi
    if (( DLNA_SERVICE_FILE_EXISTED_BEFORE == 0 )) && [[ -f "/etc/systemd/system/${DLNA_SERVICE_NAME}.service" ]]; then
        return 0
    fi
    if (( RADIO_SERVICE_FILE_EXISTED_BEFORE == 0 )) && [[ -f "/etc/systemd/system/${RADIO_SERVICE_NAME}.service" ]]; then
        return 0
    fi
    if (( RADIO_STATION_TEMPLATE_FILE_EXISTED_BEFORE == 0 )) && [[ -f "/etc/systemd/system/${RADIO_STATION_TEMPLATE}.service" ]]; then
        return 0
    fi
    if (( DLNA_EXPORT_ROOT_EXISTED_BEFORE == 0 )) && [[ -e "/dlna" ]]; then
        return 0
    fi
    if (( SUDOERS_RULE_FILE_EXISTED_BEFORE == 0 )) && [[ -n "$SUDOERS_RULE_FILE" && -f "$SUDOERS_RULE_FILE" ]]; then
        return 0
    fi
    if (( GERBERA_REPO_KEY_EXISTED_BEFORE == 0 )) && [[ -f "/usr/share/keyrings/gerbera-keyring.gpg" ]]; then
        return 0
    fi
    if (( GERBERA_REPO_LIST_EXISTED_BEFORE == 0 )) && [[ -f "/etc/apt/sources.list.d/gerbera.list" ]]; then
        return 0
    fi
    if (( APP_USER_EXISTED_BEFORE == 0 )) && id -u "$APP_USER" >/dev/null 2>&1; then
        return 0
    fi
    if (( APP_GROUP_EXISTED_BEFORE == 0 )) && getent group "$APP_GROUP" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

perform_install_cleanup() {
    log_info "Usuwam pliki i usługi utworzone przez nieudaną instalację."

    systemctl disable --now "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
    systemctl disable --now "${DLNA_SERVICE_NAME}.service" >/dev/null 2>&1 || true
    systemctl disable --now "${RADIO_SERVICE_NAME}.service" >/dev/null 2>&1 || true

    if (( FLASK_SERVICE_FILE_EXISTED_BEFORE == 0 )); then
        rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    fi
    if (( DLNA_SERVICE_FILE_EXISTED_BEFORE == 0 )); then
        rm -f "/etc/systemd/system/${DLNA_SERVICE_NAME}.service"
    fi
    if (( RADIO_SERVICE_FILE_EXISTED_BEFORE == 0 )); then
        rm -f "/etc/systemd/system/${RADIO_SERVICE_NAME}.service"
    fi
    if (( RADIO_STATION_TEMPLATE_FILE_EXISTED_BEFORE == 0 )); then
        rm -f "/etc/systemd/system/${RADIO_STATION_TEMPLATE}.service"
    fi
    if (( SUDOERS_RULE_FILE_EXISTED_BEFORE == 0 )) && [[ -n "$SUDOERS_RULE_FILE" ]]; then
        rm -f "$SUDOERS_RULE_FILE"
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true

    if (( GERBERA_REPO_KEY_EXISTED_BEFORE == 0 )); then
        rm -f "/usr/share/keyrings/gerbera-keyring.gpg"
    fi
    if (( GERBERA_REPO_LIST_EXISTED_BEFORE == 0 )); then
        rm -f "/etc/apt/sources.list.d/gerbera.list"
    fi

    if (( DLNA_EXPORT_ROOT_EXISTED_BEFORE == 0 )); then
        rm -rf /dlna
    fi
    if (( APP_DIR_EXISTED_BEFORE == 0 )); then
        rm -rf "$APP_DIR"
    fi
    if (( STORAGE_DOWNLOAD_DIR_EXISTED_BEFORE == 0 )); then
        rm -rf "$STORAGE_ROOT/flask_downloader"
    fi
    if (( STORAGE_AUDIO_DIR_EXISTED_BEFORE == 0 )); then
        rm -rf "$STORAGE_ROOT/flask_downloader_audio"
    fi
    if (( STORAGE_USERS_DIR_EXISTED_BEFORE == 0 )); then
        rm -rf "$STORAGE_ROOT/flask_downloader_users"
    fi
    if (( STORAGE_ROOT_EXISTED_BEFORE == 0 )); then
        rm -rf "$STORAGE_ROOT"
    fi
    if (( APP_USER_EXISTED_BEFORE == 0 )); then
        userdel -r "$APP_USER" >/dev/null 2>&1 || true
    fi
    if (( APP_GROUP_EXISTED_BEFORE == 0 )); then
        groupdel "$APP_GROUP" >/dev/null 2>&1 || true
    fi

    log_ok "Usunięto pliki i usługi utworzone przez instalator."
}

offer_cleanup_after_failure() {
    if ! cleanup_candidates_exist; then
        return 0
    fi

    if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
        log_warn "Instalacja nie powiodła się. Pozostawiam utworzone pliki do diagnostyki, bo tryb jest nieinteraktywny."
        return 0
    fi

    if ! ensure_interactive_input_fd; then
        log_warn "Instalacja nie powiodła się i nie mam dostępu do terminala, więc zostawiam pliki do ręcznej diagnostyki."
        return 0
    fi

    local answer=""
    printf "%s" "Czy usunąć pliki i usługi utworzone przez nieudaną instalację? [t/N]: " > /dev/tty
    IFS= read -r -u "$INTERACTIVE_INPUT_FD" answer || true
    answer="$(trim_text "$answer")"
    case "${answer,,}" in
        t|tak|y|yes)
            perform_install_cleanup
            ;;
        *)
            log_warn "Pozostawiono utworzone pliki do ręcznej diagnostyki."
            ;;
    esac
}

abort_install() {
    offer_cleanup_after_failure
    exit 1
}

build_sudoers_rule_file_path() {
    local base_name
    base_name="$(printf '%s' "${SERVICE_NAME:-flask-downloader}" | tr -cs 'a-zA-Z0-9._-' '-')"
    base_name="${base_name#-}"
    base_name="${base_name%-}"
    if [[ -z "$base_name" ]]; then
        base_name="flask-downloader"
    fi
    printf "/etc/sudoers.d/%s-panel" "$base_name"
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
        abort_install
    fi
}

detect_debian() {
    if [[ ! -f /etc/os-release ]]; then
        log_fail "Nie znaleziono /etc/os-release."
        abort_install
    fi

    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != "debian" ]]; then
        log_fail "Instalator obsługuje wyłącznie Debiana."
        abort_install
    fi

    DEBIAN_MAJOR="${VERSION_ID%%.*}"
    if [[ -z "${DEBIAN_MAJOR}" || "${DEBIAN_MAJOR}" -lt 10 ]]; then
        log_fail "Wymagany jest Debian 10 lub nowszy."
        abort_install
    fi
}

prompt_default() {
    local prompt="$1"
    local default_value="$2"
    local answer
    if ! ensure_interactive_input_fd; then
        log_fail "Brak dostępu do terminala dla interaktywnych pytań. Użyj --non-interactive albo uruchom instalator przez: bash -c \"\$(curl -fsSL .../install.sh)\""
        abort_install
    fi
    printf "%s [%s]: " "$prompt" "$default_value" > /dev/tty
    IFS= read -r -u "$INTERACTIVE_INPUT_FD" answer || true
    printf "%s" "${answer:-$default_value}"
}

prompt_timeout_default() {
    local prompt="$1"
    local default_value="$2"
    local timeout_seconds="$3"
    local answer=""
    if ! ensure_interactive_input_fd; then
        log_fail "Brak dostępu do terminala dla interaktywnych pytań. Użyj --non-interactive albo uruchom instalator przez: bash -c \"\$(curl -fsSL .../install.sh)\""
        abort_install
    fi
    printf "%s [%s] (timeout %ss): " "$prompt" "$default_value" "$timeout_seconds" > /dev/tty
    IFS= read -r -t "$timeout_seconds" -u "$INTERACTIVE_INPUT_FD" answer || true
    printf "%s" "${answer:-$default_value}"
}

prompt_admin_password() {
    local first=""
    local second=""
    if ! ensure_interactive_input_fd; then
        log_fail "Brak dostępu do terminala dla hasła administratora. Użyj FLASK_DOWNLOADER_ADMIN_PASSWORD albo --admin-password."
        abort_install
    fi
    while true; do
        printf "%s" "Hasło dla pierwszego użytkownika admin: " > /dev/tty
        stty -echo < /dev/tty
        IFS= read -r -u "$INTERACTIVE_INPUT_FD" first || true
        stty echo < /dev/tty
        printf "\n" > /dev/tty
        printf "%s" "Powtórz hasło admina: " > /dev/tty
        stty -echo < /dev/tty
        IFS= read -r -u "$INTERACTIVE_INPUT_FD" second || true
        stty echo < /dev/tty
        printf "\n" > /dev/tty
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

install_privileged_sudoers_rules() {
    local sudoers_file
    sudoers_file="$(build_sudoers_rule_file_path)"
    SUDOERS_RULE_FILE="$sudoers_file"

    cat > "$sudoers_file" <<EOF
Defaults:${APP_USER} !requiretty
${APP_USER} ALL=(root) NOPASSWD: /bin/systemctl, /usr/bin/systemctl, /bin/mount, /usr/bin/mount
EOF
    chmod 440 "$sudoers_file"
    if command -v visudo >/dev/null 2>&1; then
        visudo -cf "$sudoers_file" >>"$INSTALL_LOG" 2>&1 || {
            log_fail "Wygenerowana reguła sudoers dla ${APP_USER} jest nieprawidłowa."
            abort_install
        }
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

ensure_random_radio_runtime_secrets() {
    APP_DIR="$APP_DIR" "$APP_DIR/.venv/bin/python" - <<'PY'
import json
import os
import secrets
import sys

app_dir = os.environ["APP_DIR"]
sys.path.insert(0, app_dir)
radios_path = os.path.join(app_dir, "data", "radios.json")

if not os.path.isfile(radios_path):
    raise SystemExit(0)


def generate_runtime_secret(min_length=24):
    raw = secrets.token_urlsafe(max(18, int(min_length or 24)))
    text = str(raw or "").strip()
    if len(text) < min_length:
        text = (text + secrets.token_urlsafe(min_length))[:min_length]
    return text[: max(min_length, 24)]


with open(radios_path, "r", encoding="utf-8") as fh:
    store = json.load(fh)

if not isinstance(store, dict):
    raise SystemExit(0)

global_payload = store.get("global")
if not isinstance(global_payload, dict):
    raise SystemExit(0)

changed = False
for key, placeholder in (
    ("source_password", "radio-source"),
    ("admin_password", "radio-admin"),
):
    current_value = str(global_payload.get(key) or "").strip()
    if not current_value or current_value == placeholder:
        global_payload[key] = generate_runtime_secret(32)
        changed = True

if changed:
    with open(radios_path, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)
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
            abort_install
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
log_info "Wciśnij Enter, aby zostawić wartość domyślną pokazaną w nawiasie kwadratowym."
log_info "Jeśli nic nie wpiszesz przy porcie, po 30 sekundach zostanie użyte ustawienie domyślne."
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
        abort_install
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
        abort_install
    fi
    log_warn "Port ${APP_PORT} jest już zajęty."
    APP_PORT="$(prompt_default 'Port aplikacji' "$APP_PORT_DEFAULT")"
done
if [[ -n "$ADMIN_PASSWORD" ]]; then
    if [[ "${#ADMIN_PASSWORD}" -lt 4 ]]; then
        log_fail "Hasło admina musi mieć co najmniej 4 znaki."
        abort_install
    fi
elif [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    log_fail "W trybie nieinteraktywnym podaj hasło przez FLASK_DOWNLOADER_ADMIN_PASSWORD albo --admin-password."
    abort_install
else
    prompt_admin_password
fi
log_ok "Zebrano ustawienia instalacyjne."
record_preinstall_state

begin_step "Instalacja pakietów systemowych"
export DEBIAN_FRONTEND=noninteractive
run_logged "Odświeżam listę pakietów apt" apt-get update -y
run_logged "Instaluję pakiety systemowe" apt-get install -y git sudo ca-certificates curl gnupg python3 python3-venv python3-pip cifs-utils iproute2 ffmpegthumbnailer
log_ok "Pakiety systemowe są gotowe."

begin_step "Tworzenie użytkownika i uprawnień"
ensure_group_and_user
run_logged "Konfiguruję uprawnienia sudoers dla usera usługi" install_privileged_sudoers_rules
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
        abort_install
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
run_logged "Pilnuję losowych sekretów backendu radia w data/radios.json" ensure_random_radio_runtime_secrets
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/data"
log_ok "Pliki data/config.json, data/jobs.json, data/users.json i data/radios.json są gotowe."

begin_step "Aktualizacja yt-dlp"
run_logged_streamed "Aktualizuję yt-dlp w środowisku aplikacji" run_app_bootstrap_task yt_dlp
log_ok "yt-dlp jest gotowy."

begin_step "Instalacja ffmpeg"
run_logged_streamed "Instaluję zarządzany ffmpeg dla aplikacji" run_app_bootstrap_task ffmpeg
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/tools" 2>/dev/null || true
log_ok "ffmpeg jest gotowy."

begin_step "Instalacja DLNA"
run_logged_streamed "Instaluję backend Gerbera i przygotowuję runtime DLNA" run_app_bootstrap_task dlna
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/tools" 2>/dev/null || true
log_ok "Backend DLNA jest gotowy."

begin_step "Instalacja backendu radia"
run_logged_streamed "Instaluję backend Icecast + Liquidsoap" run_app_bootstrap_task radio
run_logged "Weryfikuję końcowe sekrety backendu radia po bootstrapie pakietów" ensure_random_radio_runtime_secrets
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
