#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import io
import os
import platform
import re
import shlex
import shutil
import signal
import sys
import tarfile
import tempfile
import time
import uuid
import threading
import subprocess
import zipfile
import copy
import ipaddress
import socket
import hashlib
from functools import partial
from datetime import datetime, timedelta
from importlib import metadata as importlib_metadata
from urllib.parse import quote, urlparse
from xml.etree import ElementTree as ET

try:
    import pwd
except Exception:  # pragma: no cover - unavailable on Windows
    pwd = None

try:
    import grp
except Exception:  # pragma: no cover - unavailable on Windows
    grp = None

try:
    from packaging.version import InvalidVersion, Version
except Exception:  # pragma: no cover - fallback if packaging is unavailable
    InvalidVersion = Exception
    Version = None

import requests
import yt_dlp
from flask import (
    Response,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_downloader.config import (
    APP_HOST as CONFIG_APP_HOST,
    MAX_PARALLEL_DOWNLOADS_PER_USER as CONFIG_MAX_PARALLEL_DOWNLOADS_PER_USER,
    APP_PORT as CONFIG_APP_PORT,
    APP_SECRET_KEY as CONFIG_APP_SECRET_KEY,
    APP_SERVICE_GROUP as CONFIG_APP_SERVICE_GROUP,
    APP_SERVICE_NAME as CONFIG_SYSTEMD_SERVICE_NAME,
    APP_SERVICE_USER as CONFIG_APP_SERVICE_USER,
    AUDIO_DOWNLOAD_DIR as CONFIG_AUDIO_DOWNLOAD_DIR,
    DLNA_DEFAULT_PORT as CONFIG_DLNA_DEFAULT_PORT,
    DLNA_PREFERRED_REPO_CHANNEL as CONFIG_DLNA_PREFERRED_REPO_CHANNEL,
    RADIO_SERVICE_NAME as CONFIG_RADIO_SERVICE_NAME,
    RADIO_STATION_SERVICE_TEMPLATE as CONFIG_RADIO_STATION_SERVICE_TEMPLATE,
    DLNA_SERVICE_NAME as CONFIG_DLNA_SERVICE_NAME,
    DOWNLOAD_DIR as CONFIG_DOWNLOAD_DIR,
    MOUNT_POINT as CONFIG_MOUNT_POINT,
    SMB_CREDENTIALS_FILE as CONFIG_SMB_CREDENTIALS_FILE,
    SMB_SHARE as CONFIG_SMB_SHARE,
    USER_STORAGE_ROOT as CONFIG_USER_STORAGE_ROOT,
    LOCAL_STORAGE_ROOT as CONFIG_LOCAL_STORAGE_ROOT,
    NETWORK_STORAGE_CREDENTIALS_FILE as CONFIG_NETWORK_STORAGE_CREDENTIALS_FILE,
    NETWORK_STORAGE_HELPER as CONFIG_NETWORK_STORAGE_HELPER,
    NETWORK_STORAGE_MOUNT_DIR as CONFIG_NETWORK_STORAGE_MOUNT_DIR,
    REPO_BRANCH as CONFIG_REPO_BRANCH,
    REPO_NAME as CONFIG_REPO_NAME,
    REPO_OWNER as CONFIG_REPO_OWNER,
)
from flask_downloader.paths import (
    CONFIG_FILE,
    DATA_DIR,
    JOBS_FILE,
    LEGACY_CONFIG_FILE,
    PROJECT_ROOT,
    RADIOS_FILE,
    USERS_FILE,
    VERSION_FILE,
    ensure_data_layout,
)
from flask_downloader.bootstrap import register_application_routes, start_background_schedulers
from flask_downloader.services.jobs_service import DownloadJobsService, JobViewService
from flask_downloader.services.maintenance_service import MaintenanceTaskService
from flask_downloader.services.storage_service import MANAGED_STORAGE_PREFIX, ManagedStorageService
from flask_downloader.services.storage_backend_service import StorageBackendService
from flask_downloader.services.system_service import SystemServiceHelper
from flask_downloader.services.download_service import DownloadPathService
from flask_downloader.services.source_service import SourceMediaService
from flask_downloader.services.ffmpeg_service import FfmpegMaintenanceService
from flask_downloader.services.ytdlp_service import YtDlpMaintenanceService
from flask_downloader.services.calendar_service import CalendarService
from flask_downloader.services.app_update_service import AppUpdateService
from flask_downloader.services.dlna_service import DlnaLibraryService
from flask_downloader.services.dlna_runtime_service import DlnaRuntimeService
from flask_downloader.services.dlna_update_service import DlnaUpdateService
from flask_downloader.services.page_state_service import PageStateService
from flask_downloader.services.radio_runtime_service import RadioRuntimeService
from flask_downloader.services.radio_service import RadioService
from flask_downloader.services.storage_stats_service import StorageStatsService
from flask_downloader.stores.config_store import (
    load_app_config as config_store_load_app_config,
    write_app_config as config_store_write_app_config,
)
from flask_downloader.stores.jobs_store import (
    read_jobs_payload as jobs_store_read_jobs_payload,
    write_jobs_payload as jobs_store_write_jobs_payload,
)
from flask_downloader.stores.users_store import (
    create_user_account as users_store_create_user_account,
    default_user_record as users_store_default_user_record,
    default_user_store as users_store_default_user_store,
    get_user_by_username as users_store_get_user_by_username,
    get_users_snapshot as users_store_get_users_snapshot,
    hash_user_password as users_store_hash_user_password,
    load_user_store as users_store_load_user_store,
    normalize_user_entry as users_store_normalize_user_entry,
    normalize_user_role as users_store_normalize_user_role,
    normalize_username as users_store_normalize_username,
    update_user_password as users_store_update_user_password,
    verify_user_credentials as users_store_verify_user_credentials,
    write_user_store as users_store_write_user_store,
)
from flask_downloader.stores.radios_store import (
    load_radio_store as radios_store_load_radio_store,
    write_radio_store as radios_store_write_radio_store,
)
from flask_downloader.utils import auth as auth_utils
from flask_downloader.utils.formatting import build_natural_sort_key, format_duration, format_ts
from flask_downloader.utils.live import create_sse_json_response
from flask_downloader.utils.responses import build_stateful_json_response

APP_STARTED_AT_TS = time.time()

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

CACHE_TTL = 300
CACHE = {}

MOUNT_POINT = CONFIG_MOUNT_POINT
DOWNLOAD_DIR = CONFIG_DOWNLOAD_DIR
AUDIO_DOWNLOAD_DIR = CONFIG_AUDIO_DOWNLOAD_DIR
APP_ROOT = PROJECT_ROOT
ensure_data_layout()

SMB_SHARE = CONFIG_SMB_SHARE
SMB_CREDENTIALS_FILE = CONFIG_SMB_CREDENTIALS_FILE
LOCAL_STORAGE_ROOT = CONFIG_LOCAL_STORAGE_ROOT
NETWORK_STORAGE_MOUNT_DIR = CONFIG_NETWORK_STORAGE_MOUNT_DIR
NETWORK_STORAGE_CREDENTIALS_FILE = CONFIG_NETWORK_STORAGE_CREDENTIALS_FILE
NETWORK_STORAGE_HELPER = CONFIG_NETWORK_STORAGE_HELPER
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"
USER_STORAGE_ROOT = CONFIG_USER_STORAGE_ROOT
DEFAULT_ADMIN_VIDEO_ROOT = os.path.join(USER_STORAGE_ROOT, DEFAULT_ADMIN_USERNAME, "video")
DEFAULT_ADMIN_AUDIO_ROOT = os.path.join(USER_STORAGE_ROOT, DEFAULT_ADMIN_USERNAME, "audio")
USER_STORAGE_LAYOUT_VERSION = 3
MAX_PARALLEL_DOWNLOADS_PER_USER = CONFIG_MAX_PARALLEL_DOWNLOADS_PER_USER
APP_SERVICE_USER = CONFIG_APP_SERVICE_USER
APP_SERVICE_GROUP = CONFIG_APP_SERVICE_GROUP
APP_REPO_OWNER = CONFIG_REPO_OWNER
APP_REPO_NAME = CONFIG_REPO_NAME
APP_REPO_BRANCH = CONFIG_REPO_BRANCH

MOUNT_RETRY_COOLDOWN = 15
DEFAULT_COMPLETED_JOB_RETENTION_DAYS = 3
MIN_VALID_FILE_SIZE_BYTES = 1024 * 1024
YTDLP_CHECK_HOUR = 4
YTDLP_PIP_PACKAGE_SPEC = "yt-dlp[default]"
AUDIO_DOWNLOAD_TARGET_CODEC = "mp3"
AUDIO_DOWNLOAD_TARGET_QUALITY = "0"
FFMPEG_CHECK_HOUR = 4
FFMPEG_RELEASE_API_URL = "https://api.github.com/repos/yt-dlp/FFmpeg-Builds/releases/latest"
FFMPEG_TOOLS_ROOT = os.path.join(APP_ROOT, "tools", "ffmpeg")
FFMPEG_MANAGED_DIR = os.path.join(FFMPEG_TOOLS_ROOT, "managed")
FFMPEG_MANIFEST_FILE = os.path.join(FFMPEG_MANAGED_DIR, "ffmpeg_manifest.json")
PYTHON_VENV_PIP = os.path.join(APP_ROOT, ".venv", "bin", "pip")
SYSTEMD_SERVICE_NAME = CONFIG_SYSTEMD_SERVICE_NAME
DLNA_PACKAGE_NAME = "gerbera"
DLNA_SYSTEM_SERVICE_NAME = "gerbera"
DLNA_CHECK_HOUR = 4
DLNA_AUTOHEAL_INTERVAL_SECONDS = 30
DLNA_SERVICE_NAME = CONFIG_DLNA_SERVICE_NAME
RADIO_SERVICE_NAME = CONFIG_RADIO_SERVICE_NAME
RADIO_STATION_SERVICE_TEMPLATE = CONFIG_RADIO_STATION_SERVICE_TEMPLATE
DLNA_OFFICIAL_REPO_KEY_URL = "https://pkg.gerbera.io/public.asc"
DLNA_OFFICIAL_REPO_KEYRING_FILE = os.path.join("/usr", "share", "keyrings", "gerbera-keyring.gpg")
DLNA_OFFICIAL_REPO_LIST_FILE = os.path.join("/etc", "apt", "sources.list.d", "gerbera.list")
DLNA_OFFICIAL_REPO_CHANNELS = {
    "stable": {
        "apt_path": "debian",
        "label": "Oficjalne repo Gerbera / stable",
    },
    "latest": {
        "apt_path": "debian-git",
        "label": "Oficjalne repo Gerbera / latest git",
    },
}
DLNA_PREFERRED_REPO_CHANNEL = CONFIG_DLNA_PREFERRED_REPO_CHANNEL
DLNA_TOOLS_ROOT = os.path.join(APP_ROOT, "tools", "dlna")
DLNA_RUNTIME_ROOT = os.path.join(DLNA_TOOLS_ROOT, "runtime")
DLNA_HOME_DIR = os.path.join(DLNA_RUNTIME_ROOT, "home")
DLNA_LEGACY_EXPORT_ROOT = os.path.join(DLNA_RUNTIME_ROOT, "export")
DLNA_EXPORT_ROOT = "/dlna" if os.name != "nt" else DLNA_LEGACY_EXPORT_ROOT
DLNA_WEBROOT_DIR = os.path.join(DLNA_RUNTIME_ROOT, "web")
DLNA_SYSTEM_WEBROOT_DIR = os.path.join("/usr", "share", "gerbera", "web")
DLNA_ICONS_DIR = os.path.join(DLNA_WEBROOT_DIR, "icons")
DLNA_CUSTOM_ASSETS_DIR = os.path.join(DLNA_RUNTIME_ROOT, "custom")
DLNA_CONFIG_DIR = os.path.join(DLNA_RUNTIME_ROOT, "config")
DLNA_SCRIPT_DIR = os.path.join(DLNA_CONFIG_DIR, "js")
DLNA_COMMON_SCRIPT_DIR = os.path.join(DLNA_SCRIPT_DIR, "common")
DLNA_CUSTOM_SCRIPT_DIR = os.path.join(DLNA_SCRIPT_DIR, "custom")
DLNA_LEGACY_SCRIPT_DIR = os.path.join(DLNA_SCRIPT_DIR, "legacy")
DLNA_RUNTIME_BIN_DIR = os.path.join(DLNA_RUNTIME_ROOT, "bin")
DLNA_LOG_DIR = os.path.join(DLNA_RUNTIME_ROOT, "logs")
DLNA_LOG_FILE = os.path.join(DLNA_LOG_DIR, "gerbera.log")
DLNA_LOG_MAX_BYTES = 5 * 1024 * 1024
DLNA_LOG_BROWSER_MAX_BYTES = 1024 * 1024
DLNA_LOG_TAIL_READ_BYTES = 256 * 1024
DLNA_CONFIG_XML_FILE = os.path.join(DLNA_CONFIG_DIR, "config.xml")
DLNA_VIRTUAL_LAYOUT_SCRIPT_FILE = os.path.join(DLNA_CUSTOM_SCRIPT_DIR, "zz_flask_dlna_layout.js")
DLNA_LEGACY_IMPORT_SCRIPT_FILE = os.path.join(DLNA_LEGACY_SCRIPT_DIR, "flask_dlna_import.js")
DLNA_RESTART_GUARD_SCRIPT_FILE = os.path.join(DLNA_RUNTIME_BIN_DIR, "dlna_restart_guard.sh")
DLNA_RESTART_STATE_FILE = os.path.join(DLNA_HOME_DIR, "restart_backoff.env")
DLNA_CUSTOM_ICON_SOURCE_BASENAME = "dlna-custom-icon-source"
DLNA_ALLOWED_ICON_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
DLNA_CUSTOM_ICON_MAX_BYTES = 10 * 1024 * 1024
DLNA_ICON_VARIANTS = (
    (120, "png", "image/png"),
    (120, "bmp", "image/x-ms-bmp"),
    (120, "jpg", "image/jpeg"),
    (48, "png", "image/png"),
    (48, "bmp", "image/x-ms-bmp"),
    (48, "jpg", "image/jpeg"),
    (32, "png", "image/png"),
    (32, "bmp", "image/x-ms-bmp"),
    (32, "jpg", "image/jpeg"),
)
GERBERA_SYSTEM_SCRIPT_DIR = os.path.join("/usr", "share", "gerbera", "js")
DLNA_SERVICE_UNIT_FILE = os.path.join("/etc", "systemd", "system", "%s.service" % DLNA_SERVICE_NAME)
DLNA_DEFAULT_PORT = CONFIG_DLNA_DEFAULT_PORT
DLNA_ALLOWED_NETWORK = ipaddress.ip_network("192.168.0.0/16")
DLNA_ALL_COLLECTION_ID = "__all_active__"
DLNA_ALL_COLLECTION_NAME = "Wszystkie aktywne media"
DLNA_VIRTUAL_LAYOUT_VERSION = 4
GERBERA_CONFIG_NS = "http://gerbera.io/config/2"
GERBERA_LEGACY_CONFIG_NS = "http://mediatomb.cc/config/2"
RADIO_RUNTIME_ROOT = os.path.join(DATA_DIR, "runtime", "radio")
RADIO_LOG_DIR = os.path.join(RADIO_RUNTIME_ROOT, "logs")
RADIO_BACKEND_LOG_FILE = os.path.join(RADIO_LOG_DIR, "radio-backend.log")
RADIO_LOG_BROWSER_MAX_BYTES = 1024 * 1024
RADIO_LOG_TAIL_READ_BYTES = 256 * 1024

ET.register_namespace("", GERBERA_CONFIG_NS)

def create_maintenance_task_state(title):
    return {
        "title": title,
        "status": "idle",
        "status_label": "Brak aktywnego zadania",
        "progress_percent": 0.0,
        "detail": "",
        "started_at": 0.0,
        "finished_at": 0.0,
        "visible": False,
        "message": "",
    }


DOWNLOAD_JOBS = {}
DOWNLOAD_LOCK = threading.Lock()
JOB_CANCEL_EVENTS = {}
JOB_STOP_REQUESTS = {}
FFMPEG_INSTALL_LOCK = threading.Lock()
FFMPEG_SCHEDULER_LOCK = threading.Lock()
FFMPEG_SCHEDULER_STARTED = False
DLNA_INSTALL_LOCK = threading.Lock()
RADIO_INSTALL_LOCK = threading.Lock()
DLNA_SCHEDULER_LOCK = threading.Lock()
DLNA_SCHEDULER_STARTED = False
DLNA_AUTOHEAL_LOCK = threading.Lock()
DLNA_AUTOHEAL_STARTED = False
DLNA_SYNC_LOCK = threading.Lock()
MAINTENANCE_TASKS_LOCK = threading.Lock()
MAINTENANCE_TASKS = {
    "yt_dlp_update": create_maintenance_task_state("Aktualizacja yt-dlp"),
    "ffmpeg_install": create_maintenance_task_state("Instalacja ffmpeg"),
    "app_update": create_maintenance_task_state("Aktualizacja aplikacji"),
    "dlna_install": create_maintenance_task_state("Instalacja serwera DLNA"),
    "radio_backend_install": create_maintenance_task_state("Instalacja backendu radia"),
}
MAINTENANCE_SERVICE = MaintenanceTaskService(
    MAINTENANCE_TASKS,
    MAINTENANCE_TASKS_LOCK,
    create_maintenance_task_state,
    format_ts,
)
YTDLP_SCHEDULER_LOCK = threading.Lock()
YTDLP_SCHEDULER_STARTED = False
YTDLP_SERVICES_LOCK = threading.Lock()
YTDLP_SERVICES_CACHE = {
    "version": "",
    "services": [],
    "generated_at": 0.0,
    "error": "",
}

LAST_MOUNT_ATTEMPT_TS = 0.0
LAST_MOUNT_STATUS = {
    "online": False,
    "message": "Stan udziału nie został jeszcze sprawdzony.",
    "checked_at": 0.0,
}

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64" fill="none">
<defs>
<linearGradient id="vlcBadge" x1="12" y1="10" x2="54" y2="58" gradientUnits="userSpaceOnUse">
<stop stop-color="#61adff"/>
<stop offset="1" stop-color="#315fa4"/>
</linearGradient>
</defs>
<rect x="8" y="8" width="48" height="48" rx="15" fill="url(#vlcBadge)"/>
<text x="32" y="38" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#ffffff">VLC</text>
</svg>"""

BASE_PAGE_TEMPLATE = 'base.html'

INDEX_CONTENT_TEMPLATE = 'pages/index.html'

DOWNLOADS_CONTENT_TEMPLATE = 'pages/downloads.html'

JOBS_CONTENT_TEMPLATE = 'pages/jobs.html'

SETTINGS_CONTENT_TEMPLATE = 'pages/settings.html'


SERVICES_CONTENT_TEMPLATE = 'pages/services.html'


DLNA_CONTENT_TEMPLATE = 'pages/dlna.html'


RADIO_CONTENT_TEMPLATE = 'pages/radio.html'


APP_CONFIG_LOCK = threading.Lock()
USER_STORE_LOCK = threading.Lock()
RADIO_STORE_LOCK = threading.Lock()


def normalize_username(value):
    return users_store_normalize_username(value)


def normalize_user_role(value):
    return users_store_normalize_user_role(value)


def hash_user_password(password):
    return users_store_hash_user_password(password)


def default_user_record(username=DEFAULT_ADMIN_USERNAME, role="admin", password_hash=""):
    return users_store_default_user_record(
        username,
        DEFAULT_ADMIN_USERNAME,
        DEFAULT_ADMIN_PASSWORD,
        role=role,
        password_hash=password_hash,
    )


def default_user_store():
    return users_store_default_user_store(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)


def normalize_user_entry(raw):
    return users_store_normalize_user_entry(raw)


def load_user_store():
    return users_store_load_user_store(USERS_FILE, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)


USER_STORE = load_user_store()


def write_user_store_locked():
    users_store_write_user_store(USERS_FILE, USER_STORE)


def get_user_store_snapshot():
    with USER_STORE_LOCK:
        return copy.deepcopy(USER_STORE)


def get_users_snapshot():
    return users_store_get_users_snapshot(get_user_store_snapshot())


def get_user_by_username(username):
    with USER_STORE_LOCK:
        return users_store_get_user_by_username(USER_STORE, username)


def verify_user_credentials(username, password):
    with USER_STORE_LOCK:
        return users_store_verify_user_credentials(USER_STORE, username, password)


def set_session_user(user):
    auth_utils.set_session_user(user)


def clear_session_user():
    auth_utils.clear_session_user()


def create_user_account(username, password, role):
    with USER_STORE_LOCK:
        user = users_store_create_user_account(USER_STORE, username, password, role)
        write_user_store_locked()
    return user


def update_user_password(username, new_password):
    with USER_STORE_LOCK:
        user = users_store_update_user_password(USER_STORE, username, new_password)
        write_user_store_locked()
        return user


def ensure_user_has_no_active_jobs(username, action_label="tą operacją"):
    normalized_username = normalize_username(username)
    with DOWNLOAD_LOCK:
        active_jobs = [
            job.get("job_id")
            for job in DOWNLOAD_JOBS.values()
            if normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME) == normalized_username
            and job.get("status") in ("queued", "downloading", "paused")
        ]
    if active_jobs:
        raise ValueError("Najpierw przerwij aktywne zadania użytkownika przed %s." % action_label)


def rebase_managed_relative_path_owner(relative_path, previous_username, next_username):
    parsed = parse_managed_relative_path(relative_path)
    if not parsed:
        return safe_relative_download_path(relative_path)

    previous_owner = normalize_username(previous_username)
    next_owner = normalize_username(next_username)
    if parsed["owner_username"] != previous_owner:
        return parsed["relative_path"]

    return build_managed_relative_path(
        next_owner,
        parsed["storage_kind"],
        parsed["user_relative_path"],
        storage_id=parsed.get("storage_id") or "local",
    )


def compute_rebased_user_filepath(path, previous_username, next_username, storage_kind="video"):
    text = str(path or "").strip()
    if not text:
        return text

    previous_owner = normalize_username(previous_username)
    next_owner = normalize_username(next_username)
    normalized_storage_kind = normalize_storage_kind(storage_kind or "video")
    candidate = os.path.abspath(text)
    path_info = get_managed_path_info(candidate) or {}
    storage_id = normalize_storage_id(path_info.get("storage_id") or "local", default="local")
    previous_root = os.path.abspath(get_user_storage_root(previous_owner, normalized_storage_kind, storage_id=storage_id))
    next_root = os.path.abspath(get_user_storage_root(next_owner, normalized_storage_kind, storage_id=storage_id))
    try:
        if os.path.commonpath([previous_root, candidate]) != previous_root:
            return candidate
        suffix = os.path.relpath(candidate, previous_root).replace("\\", "/")
    except Exception:
        return candidate
    return os.path.abspath(os.path.join(next_root, suffix.replace("/", os.sep)))


def iter_storage_ids():
    return ("local", "network")


def ensure_user_storage_dirs(username, storage_id=None):
    owner = normalize_username(username)
    if storage_id:
        ensure_directory(get_user_storage_root(owner, "video", storage_id=storage_id))
        ensure_directory(get_user_storage_root(owner, "audio", storage_id=storage_id))
        return

    for candidate_storage_id in iter_storage_ids():
        base_root = os.path.abspath(get_user_storage_base_root(candidate_storage_id))
        if candidate_storage_id != "local" and not os.path.isdir(base_root):
            continue
        ensure_directory(get_user_storage_root(owner, "video", storage_id=candidate_storage_id))
        ensure_directory(get_user_storage_root(owner, "audio", storage_id=candidate_storage_id))


def move_user_storage_root(previous_username, next_username):
    previous_owner = normalize_username(previous_username)
    next_owner = normalize_username(next_username)
    moved_roots = []

    for storage_id in iter_storage_ids():
        previous_root = os.path.abspath(get_user_root(previous_owner, storage_id=storage_id))
        next_root = os.path.abspath(get_user_root(next_owner, storage_id=storage_id))
        base_root = os.path.abspath(get_user_storage_base_root(storage_id))

        if previous_root == next_root:
            continue

        try:
            if os.path.commonpath([base_root, previous_root]) != base_root or os.path.commonpath([base_root, next_root]) != base_root:
                raise ValueError("Ścieżka użytkownika wykracza poza katalog bazowy.")
        except Exception as exc:
            raise ValueError("Nie można bezpiecznie przenieść katalogu użytkownika.") from exc

        if os.path.lexists(next_root):
            raise ValueError("Docelowy katalog użytkownika już istnieje na dysku. Wybierz inny login.")

        if os.path.isdir(previous_root):
            shutil.move(previous_root, next_root)
            moved_roots.append(next_root)

    ensure_user_storage_dirs(next_owner)
    return moved_roots


def update_user_account(username, new_username, role):
    previous_owner = normalize_username(username)
    next_owner = normalize_username(new_username or username)
    next_role = normalize_user_role(role or "user")
    original_user = None
    original_jobs = []
    original_dlna_config = None
    storage_moved = False
    updated_user = None

    if previous_owner == DEFAULT_ADMIN_USERNAME:
        raise ValueError("Domyślnego konta administratora nie można zmieniać w tym panelu.")

    if previous_owner != next_owner:
        ensure_user_has_no_active_jobs(previous_owner, action_label="zmianą loginu")

    with USER_STORE_LOCK:
        target_user = None
        for item in USER_STORE.get("users") or []:
            if item.get("username") == previous_owner:
                target_user = item
                break

        if target_user is None:
            raise ValueError("Nie znaleziono użytkownika do edycji.")

        for item in USER_STORE.get("users") or []:
            if item.get("username") == next_owner and item.get("username") != previous_owner:
                raise ValueError("Użytkownik o takim loginie już istnieje.")

        original_user = copy.deepcopy(target_user)

    if previous_owner != next_owner:
        with DOWNLOAD_LOCK:
            for job in DOWNLOAD_JOBS.values():
                if normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME) == previous_owner:
                    original_jobs.append(copy.deepcopy(job))

        with APP_CONFIG_LOCK:
            original_dlna_config = copy.deepcopy(normalize_dlna_config(APP_CONFIG.get("dlna")))

    try:
        if previous_owner != next_owner:
            move_user_storage_root(previous_owner, next_owner)
            storage_moved = True

            with DOWNLOAD_LOCK:
                jobs_changed = False
                for job in DOWNLOAD_JOBS.values():
                    if normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME) != previous_owner:
                        continue
                    job["owner_username"] = next_owner
                    storage_kind = normalize_storage_kind(job.get("storage_kind") or "video")
                    job["relative_path"] = rebase_managed_relative_path_owner(job.get("relative_path") or "", previous_owner, next_owner)
                    job["filepath"] = compute_rebased_user_filepath(job.get("filepath") or "", previous_owner, next_owner, storage_kind=storage_kind)
                    jobs_changed = True
                if jobs_changed:
                    write_download_jobs_locked()

            with APP_CONFIG_LOCK:
                dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))
                config_changed = False
                for rule in dlna_config.get("media_rules") or []:
                    next_relative_path = rebase_managed_relative_path_owner(rule.get("relative_path") or "", previous_owner, next_owner)
                    if next_relative_path != rule.get("relative_path"):
                        rule["relative_path"] = next_relative_path
                        config_changed = True
                for client in dlna_config.get("clients") or []:
                    usernames = list(client.get("usernames") or [])
                    next_usernames = [next_owner if item == previous_owner else item for item in usernames]
                    if next_usernames != usernames:
                        client["usernames"] = next_usernames
                        config_changed = True
                if config_changed:
                    APP_CONFIG["dlna"] = normalize_dlna_config(dlna_config)
                    write_app_config_locked()

            sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)

        with USER_STORE_LOCK:
            target_user = None
            for item in USER_STORE.get("users") or []:
                if item.get("username") == previous_owner:
                    target_user = item
                    break

            if target_user is None:
                raise ValueError("Nie znaleziono użytkownika do edycji.")

            for item in USER_STORE.get("users") or []:
                if item.get("username") == next_owner and item.get("username") != previous_owner:
                    raise ValueError("Użytkownik o takim loginie już istnieje.")

            target_user["username"] = next_owner
            target_user["role"] = next_role
            USER_STORE["users"].sort(key=lambda item: (0 if item.get("role") == "admin" else 1, item.get("username") or ""))
            write_user_store_locked()
            updated_user = copy.deepcopy(target_user)

        if previous_owner != next_owner:
            rename_radio_station_owner(previous_owner, next_owner)

        if has_request_context() and get_current_username() == previous_owner:
            refreshed_user = get_user_by_username(next_owner)
            if refreshed_user:
                set_session_user(refreshed_user)
        return updated_user
    except Exception:
        if previous_owner != next_owner:
            if original_dlna_config is not None:
                with APP_CONFIG_LOCK:
                    APP_CONFIG["dlna"] = normalize_dlna_config(copy.deepcopy(original_dlna_config))
                    write_app_config_locked()

            with DOWNLOAD_LOCK:
                original_jobs_by_id = {str(item.get("job_id") or ""): copy.deepcopy(item) for item in original_jobs}
                for job_id, original_job in original_jobs_by_id.items():
                    if job_id:
                        DOWNLOAD_JOBS[job_id] = copy.deepcopy(original_job)
                if original_jobs_by_id:
                    write_download_jobs_locked()

            if storage_moved:
                for storage_id in iter_storage_ids():
                    current_root = os.path.abspath(get_user_root(next_owner, storage_id=storage_id))
                    previous_root = os.path.abspath(get_user_root(previous_owner, storage_id=storage_id))
                    if os.path.isdir(current_root) and not os.path.lexists(previous_root):
                        shutil.move(current_root, previous_root)

            try:
                rename_radio_station_owner(next_owner, previous_owner)
            except Exception:
                pass

        with USER_STORE_LOCK:
            restored = False
            for item in USER_STORE.get("users") or []:
                if item.get("username") in (previous_owner, next_owner) and original_user:
                    item.update(copy.deepcopy(original_user))
                    restored = True
                    break
            if original_user and not restored:
                USER_STORE.setdefault("users", []).append(copy.deepcopy(original_user))
            USER_STORE["users"].sort(key=lambda item: (0 if item.get("role") == "admin" else 1, item.get("username") or ""))
            write_user_store_locked()
        raise


def count_user_media_files(username):
    owner = normalize_username(username)
    total = 0
    for storage_id in iter_storage_ids():
        for storage_kind in ("video", "audio"):
            root = get_user_storage_root(owner, storage_kind, storage_id=storage_id)
            if not os.path.isdir(root):
                continue
            for _, _, filenames in os.walk(root):
                for name in filenames:
                    if not is_temporary_download_artifact_name(name):
                        total += 1
    return total


def count_user_jobs(username):
    ensure_download_jobs_loaded()
    owner = normalize_username(username)
    with DOWNLOAD_LOCK:
        return sum(1 for job in DOWNLOAD_JOBS.values() if normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME) == owner)


def build_user_management_rows():
    rows = []
    current_username = get_current_username() if has_request_context() else ""
    for user in get_users_snapshot():
        username = normalize_username(user.get("username") or "")
        is_default_admin = username == DEFAULT_ADMIN_USERNAME
        is_current_user = bool(current_username and username == current_username)
        rows.append({
            "username": username,
            "role": normalize_user_role(user.get("role") or "user"),
            "enabled": bool(user.get("enabled", True)),
            "created_at": float(user.get("created_at") or 0.0),
            "created_at_text": format_ts(user.get("created_at")),
            "file_count": count_user_media_files(username),
            "job_count": count_user_jobs(username),
            "can_delete": (not is_default_admin) and (not is_current_user),
            "can_edit": (not is_default_admin) and (not is_current_user),
            "can_admin_reset_password": not is_current_user,
            "is_current_user": is_current_user,
            "is_default_admin": is_default_admin,
        })
    rows.sort(key=lambda item: (0 if item["role"] == "admin" else 1, item["username"]))
    return rows


def delete_user_account(username):
    normalized_username = normalize_username(username)
    if normalized_username == DEFAULT_ADMIN_USERNAME:
        raise ValueError("Nie można usunąć domyślnego konta administratora.")

    ensure_user_has_no_active_jobs(normalized_username, action_label="usunięciem konta")

    deleted_user = None
    with USER_STORE_LOCK:
        remaining_users = []
        for item in USER_STORE.get("users") or []:
            if item.get("username") == normalized_username:
                deleted_user = copy.deepcopy(item)
                continue
            remaining_users.append(item)

        if deleted_user is None:
            raise ValueError("Nie znaleziono użytkownika do usunięcia.")

        USER_STORE["users"] = remaining_users
        write_user_store_locked()

    with DOWNLOAD_LOCK:
        for job_id, job in list(DOWNLOAD_JOBS.items()):
            if normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME) != normalized_username:
                continue
            DOWNLOAD_JOBS.pop(job_id, None)
            JOB_CANCEL_EVENTS.pop(job_id, None)
        write_download_jobs_locked()

    with APP_CONFIG_LOCK:
        dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))
        filtered_rules = []
        changed = False
        for rule in dlna_config.get("media_rules") or []:
            parsed = parse_managed_relative_path(rule.get("relative_path") or "")
            if parsed and parsed.get("owner_username") == normalized_username:
                changed = True
                continue
            filtered_rules.append(rule)
        if changed:
            dlna_config["media_rules"] = filtered_rules
        for client in dlna_config.get("clients") or []:
            usernames = list(client.get("usernames") or [])
            next_usernames = [item for item in usernames if item != normalized_username]
            if next_usernames != usernames:
                client["usernames"] = next_usernames
                changed = True
        if changed:
            APP_CONFIG["dlna"] = normalize_dlna_config(dlna_config)
            write_app_config_locked()

    for storage_id in iter_storage_ids():
        user_root = os.path.abspath(get_user_root(normalized_username, storage_id=storage_id))
        base_root = os.path.abspath(get_user_storage_base_root(storage_id))
        try:
            if os.path.commonpath([base_root, user_root]) != base_root:
                raise ValueError("Ścieżka użytkownika wykracza poza katalog bazowy.")
        except Exception as exc:
            raise ValueError("Nie można bezpiecznie usunąć katalogu użytkownika.") from exc

        if os.path.isdir(user_root):
            shutil.rmtree(user_root)

    delete_radio_station_for_user(normalized_username)
    sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
    return deleted_user


def default_ffmpeg_update_state():
    return {
        "latest_version": "",
        "latest_build_id": "",
        "checked_at": 0.0,
        "check_error": "",
    }


def default_dlna_update_state():
    return {
        "latest_version": "",
        "checked_at": 0.0,
        "check_error": "",
    }


def default_dlna_config():
    return {
        "enabled": False,
        "server_name": "Flask Downloader DLNA",
        "bind_ip": "",
        "port": DLNA_DEFAULT_PORT,
        "icon_mode": "default",
        "icon_source_name": "",
        "icon_updated_at": 0.0,
        "collections": [],
        "clients": [],
        "entries": [],
        "media_rules": [],
        "layout_version": 0,
        "last_sync_at": 0.0,
        "last_sync_error": "",
        "runtime_phase": "idle",
        "runtime_phase_detail": "",
        "runtime_phase_started_at": 0.0,
        "pending_manual_sync_paths": [],
        "pending_manual_sync_since": 0.0,
        "pending_manual_sync_last_item": "",
    }


def normalize_storage_backend_kind(value):
    return "network" if str(value or "").strip().lower() == "network" else "local"


def normalize_storage_id(value, default="local"):
    return "network" if str(value or "").strip().lower() == "network" else str(default or "local")


def normalize_network_storage_mode(value):
    return "external_path" if str(value or "").strip().lower() == "external_path" else "managed_smb"


def normalize_absolute_storage_path(value, field_label="Katalog danych", fallback=""):
    text = str(value or fallback or "").strip()
    if not text:
        raise ValueError("%s nie może być pusty." % field_label)
    path = os.path.abspath(text)
    if not path or path in ("", ".", os.path.abspath(".")):
        raise ValueError("%s ma nieprawidłową wartość." % field_label)
    return path.rstrip("/\\") or path


def normalize_network_share_value(value, allow_empty=True):
    text = str(value or "").strip()
    if not text:
        return "" if allow_empty else text
    if not text.startswith("//"):
        raise ValueError("Adres udziału sieciowego musi mieć format //host/udział.")
    parts = [item for item in text.split("/") if item]
    if len(parts) < 2:
        raise ValueError("Adres udziału sieciowego musi mieć format //host/udział.")
    return "//%s/%s" % (parts[0], parts[1])


def normalize_network_subpath_value(value):
    text = str(value or "").strip().replace("\\", "/").strip("/")
    if not text:
        return ""
    normalized = os.path.normpath(text).replace("\\", "/").strip("/")
    if normalized in ("", ".", "..") or normalized.startswith("../"):
        raise ValueError("Podfolder udziału sieciowego ma nieprawidłową wartość.")
    return normalized


def normalize_simple_storage_text(value, *, max_len=255):
    text = str(value or "").strip()
    if len(text) > max_len:
        raise ValueError("Wartość pola jest za długa.")
    return text


def normalize_storage_test_state(raw):
    if not isinstance(raw, dict):
        raw = {}
    try:
        checked_at = float(raw.get("last_test_at") or 0.0)
    except Exception:
        checked_at = 0.0
    return {
        "last_test_ok": bool(raw.get("last_test_ok", False)),
        "last_test_message": str(raw.get("last_test_message") or "").strip(),
        "last_test_at": checked_at,
        "last_test_signature": str(raw.get("last_test_signature") or "").strip(),
        "manual_unmounted": bool(raw.get("manual_unmounted", False)),
    }


def build_storage_network_signature(storage_config):
    storage = normalize_storage_config(storage_config or {})
    network = dict(storage.get("network") or {})
    signature_payload = {
        "mode": normalize_network_storage_mode(network.get("mode") or "managed_smb"),
        "share": str(network.get("share") or "").strip(),
        "subpath": str(network.get("subpath") or "").strip(),
        "mount_dir": os.path.abspath(str(network.get("mount_dir") or "").strip() or "."),
        "username": str(network.get("username") or "").strip(),
        "domain": str(network.get("domain") or "").strip(),
        "credentials_file": os.path.abspath(str(network.get("credentials_file") or "").strip() or "."),
        "cifs_version": str(network.get("cifs_version") or "").strip(),
        "iocharset": str(network.get("iocharset") or "").strip(),
    }
    return hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8", errors="ignore")
    ).hexdigest()


def get_default_local_storage_root():
    candidate = str(LOCAL_STORAGE_ROOT or "").strip()
    if candidate:
        return os.path.abspath(candidate)
    current_user_root = os.path.abspath(str(USER_STORAGE_ROOT or "").strip() or os.path.join(MOUNT_POINT, "flask_downloader_users"))
    return os.path.abspath(os.path.dirname(current_user_root))


def get_default_network_mount_dir():
    candidate = str(NETWORK_STORAGE_MOUNT_DIR or "").strip()
    if candidate:
        return os.path.abspath(candidate)
    if str(MOUNT_POINT or "").strip():
        return os.path.abspath(MOUNT_POINT)
    return os.path.abspath("/srv/flask_downloader/network-share")


def get_default_network_credentials_file():
    candidate = str(NETWORK_STORAGE_CREDENTIALS_FILE or SMB_CREDENTIALS_FILE or "").strip()
    if candidate:
        return os.path.abspath(candidate)
    return os.path.abspath("/etc/flask-downloader/network-share.credentials")


def default_storage_config():
    credentials_file = get_default_network_credentials_file()
    return {
        "active_backend": "network" if str(SMB_SHARE or "").strip() else "local",
        "default_write_storage_id": "network" if str(SMB_SHARE or "").strip() else "local",
        "local": {
            "id": "local",
            "label": "Lokalny storage",
            "root": get_default_local_storage_root(),
        },
        "network": {
            "id": "network",
            "label": "Udział sieciowy",
            "mode": "managed_smb",
            "share": str(SMB_SHARE or "").strip(),
            "subpath": "",
            "mount_dir": get_default_network_mount_dir(),
            "username": "",
            "domain": "",
            "credentials_file": credentials_file,
            "cifs_version": "3.0",
            "iocharset": "utf8",
            "password_saved": bool(credentials_file and os.path.isfile(credentials_file)),
            "last_test_ok": False,
            "last_test_message": "",
            "last_test_at": 0.0,
            "last_test_signature": "",
            "manual_unmounted": False,
        },
    }


def normalize_storage_config(value):
    base = default_storage_config()
    raw = dict(value or {}) if isinstance(value, dict) else {}
    raw_local = dict(raw.get("local") or {}) if isinstance(raw.get("local"), dict) else {}
    raw_network = dict(raw.get("network") or {}) if isinstance(raw.get("network"), dict) else {}
    network_test_state = normalize_storage_test_state(raw_network)

    credentials_file = normalize_absolute_storage_path(
        raw_network.get("credentials_file") or base["network"]["credentials_file"],
        "Plik poświadczeń SMB",
    )
    password_saved = bool(raw_network.get("password_saved", False))
    if not password_saved and credentials_file and os.path.isfile(credentials_file):
        password_saved = True

    default_write_storage_id = normalize_storage_id(
        raw.get("default_write_storage_id") or raw.get("active_backend") or base["default_write_storage_id"],
        default=base["default_write_storage_id"],
    )

    normalized = {
        "active_backend": default_write_storage_id,
        "default_write_storage_id": default_write_storage_id,
        "local": {
            "id": "local",
            "label": normalize_simple_storage_text(raw_local.get("label") or base["local"].get("label") or "Lokalny storage", max_len=120) or "Lokalny storage",
            "root": normalize_absolute_storage_path(
                raw_local.get("root") or base["local"]["root"],
                "Lokalny katalog danych",
            ),
        },
        "network": {
            "id": "network",
            "label": normalize_simple_storage_text(raw_network.get("label") or base["network"].get("label") or "Udział sieciowy", max_len=120) or "Udział sieciowy",
            "mode": normalize_network_storage_mode(raw_network.get("mode") or raw_network.get("management_mode") or base["network"].get("mode") or "managed_smb"),
            "share": normalize_network_share_value(raw_network.get("share") or base["network"]["share"], allow_empty=True),
            "subpath": normalize_network_subpath_value(raw_network.get("subpath") or base["network"]["subpath"]),
            "mount_dir": normalize_absolute_storage_path(
                raw_network.get("mount_dir") or base["network"]["mount_dir"],
                "Katalog montowania udziału sieciowego",
            ),
            "username": normalize_simple_storage_text(raw_network.get("username") or base["network"]["username"], max_len=120),
            "domain": normalize_simple_storage_text(raw_network.get("domain") or base["network"]["domain"], max_len=120),
            "credentials_file": credentials_file,
            "cifs_version": normalize_simple_storage_text(raw_network.get("cifs_version") or base["network"]["cifs_version"], max_len=32) or "3.0",
            "iocharset": normalize_simple_storage_text(raw_network.get("iocharset") or base["network"]["iocharset"], max_len=32) or "utf8",
            "password_saved": password_saved,
            **network_test_state,
        },
    }
    return normalized


def get_storage_active_root(storage_config=None):
    config = normalize_storage_config(storage_config or default_storage_config())
    if normalize_storage_id(config.get("default_write_storage_id") or config.get("active_backend")) == "network":
        return os.path.abspath(config["network"]["mount_dir"])
    return os.path.abspath(config["local"]["root"])


def get_storage_root_by_id(storage_config=None, storage_id=None):
    config = normalize_storage_config(storage_config or default_storage_config())
    normalized_storage_id = normalize_storage_id(
        storage_id or config.get("default_write_storage_id") or config.get("active_backend"),
        default="local",
    )
    if normalized_storage_id == "network":
        return os.path.abspath(config["network"]["mount_dir"])
    return os.path.abspath(config["local"]["root"])


def hydrate_storage_paths(config_data):
    payload = copy.deepcopy(config_data or {})
    storage_config = normalize_storage_config(payload.get("storage"))
    active_root = get_storage_active_root(storage_config)
    local_user_storage_root = os.path.join(os.path.abspath(storage_config["local"]["root"]), "flask_downloader_users")
    network_user_storage_root = os.path.join(os.path.abspath(storage_config["network"]["mount_dir"]), "flask_downloader_users")
    user_storage_root = os.path.join(active_root, "flask_downloader_users")
    payload["storage"] = storage_config
    payload["storage_roots"] = {
        "local": local_user_storage_root,
        "network": network_user_storage_root,
    }
    payload["user_storage_root"] = user_storage_root
    payload["download_root"] = os.path.join(user_storage_root, DEFAULT_ADMIN_USERNAME, "video")
    payload["audio_download_root"] = os.path.join(user_storage_root, DEFAULT_ADMIN_USERNAME, "audio")
    return payload


def get_storage_user_root_by_id(storage_config=None, storage_id=None):
    return os.path.join(
        get_storage_root_by_id(storage_config, storage_id),
        "flask_downloader_users",
    )


def default_app_config():
    return hydrate_storage_paths({
        "storage": default_storage_config(),
        "user_storage_layout_version": USER_STORAGE_LAYOUT_VERSION,
        "job_retention_days": DEFAULT_COMPLETED_JOB_RETENTION_DAYS,
        "yt_dlp_update_state": {
            "latest_version": "",
            "checked_at": 0.0,
            "check_error": "",
        },
        "ffmpeg_update_state": default_ffmpeg_update_state(),
        "app_update_state": AppUpdateService.default_update_state(),
        "dlna_update_state": default_dlna_update_state(),
        "dlna": default_dlna_config(),
    })


DLNA_UPDATE_SERVICE = DlnaUpdateService(
    default_update_state_factory=default_dlna_update_state,
    default_config_factory=default_dlna_config,
    normalize_username=normalize_username,
    get_users_snapshot=get_users_snapshot,
    allowed_network=DLNA_ALLOWED_NETWORK,
    all_collection_id=DLNA_ALL_COLLECTION_ID,
    preferred_repo_channel=DLNA_PREFERRED_REPO_CHANNEL,
    official_repo_channels=DLNA_OFFICIAL_REPO_CHANNELS,
    repo_key_url=DLNA_OFFICIAL_REPO_KEY_URL,
    repo_keyring_file=DLNA_OFFICIAL_REPO_KEYRING_FILE,
    repo_list_file=DLNA_OFFICIAL_REPO_LIST_FILE,
    user_agent=USER_AGENT,
    requests_module=requests,
    package_name=DLNA_PACKAGE_NAME,
    check_hour=DLNA_CHECK_HOUR,
    is_linux_runtime=lambda: is_linux_runtime(),
    format_ts=format_ts,
    read_config_values=lambda: (
        copy.deepcopy((APP_CONFIG or {}).get("dlna_update_state")),
        copy.deepcopy((APP_CONFIG or {}).get("dlna")),
    ),
    save_update_state=lambda latest_version, checked_at, check_error: save_dlna_update_state(
        latest_version,
        checked_at,
        check_error,
    ),
)


def normalize_storage_root(value):
    return normalize_absolute_storage_path(value, "Katalog danych")


def normalize_user_storage_root(value):
    return normalize_storage_root(value)


def normalize_download_root(value):
    return normalize_storage_root(value)


def normalize_audio_download_root(value):
    return normalize_storage_root(value)


def normalize_retention_days(value):
    try:
        days = int(str(value or "").strip())
    except Exception as exc:
        raise ValueError("Liczba dni retencji musi być liczbą całkowitą.") from exc

    if days < 1 or days > 365:
        raise ValueError("Liczba dni retencji musi mieścić się w zakresie 1-365.")

    return days


def normalize_yt_dlp_update_state(value):
    state = {
        "latest_version": "",
        "checked_at": 0.0,
        "check_error": "",
    }

    if not isinstance(value, dict):
        return state

    latest_version = str(value.get("latest_version") or "").strip()
    check_error = str(value.get("check_error") or "").strip()

    try:
        checked_at = float(value.get("checked_at") or 0.0)
    except Exception:
        checked_at = 0.0

    state.update({
        "latest_version": latest_version,
        "checked_at": checked_at,
        "check_error": check_error,
    })
    return state


def normalize_ffmpeg_update_state(value):
    state = default_ffmpeg_update_state()

    if not isinstance(value, dict):
        return state

    latest_version = str(value.get("latest_version") or "").strip()
    latest_build_id = str(value.get("latest_build_id") or "").strip()
    check_error = str(value.get("check_error") or "").strip()

    try:
        checked_at = float(value.get("checked_at") or 0.0)
    except Exception:
        checked_at = 0.0

    state.update({
        "latest_version": latest_version,
        "latest_build_id": latest_build_id,
        "checked_at": checked_at,
        "check_error": check_error,
    })
    return state


def normalize_app_update_state(value):
    return AppUpdateService.normalize_update_state(value)


def normalize_dlna_update_state(value):
    return DLNA_UPDATE_SERVICE.normalize_update_state(value)


def normalize_dlna_server_name(value):
    return DLNA_UPDATE_SERVICE.normalize_server_name(value)


def normalize_dlna_bind_ip(value):
    return DLNA_UPDATE_SERVICE.normalize_bind_ip(value)


def normalize_dlna_port(value):
    return DLNA_UPDATE_SERVICE.normalize_port(value)


def normalize_dlna_collection_name(value):
    return DLNA_UPDATE_SERVICE.normalize_collection_name(value)


def normalize_dlna_description(value, max_len=240):
    return DLNA_UPDATE_SERVICE.normalize_description(value, max_len=max_len)


def normalize_dlna_collection_id(value, fallback=None):
    return DLNA_UPDATE_SERVICE.normalize_collection_id(value, fallback=fallback)


def normalize_dlna_collection_entry(raw, existing_ids=None):
    return DLNA_UPDATE_SERVICE.normalize_collection_entry(raw, existing_ids=existing_ids)


def normalize_dlna_client_ip(value):
    return DLNA_UPDATE_SERVICE.normalize_client_ip(value)


def normalize_dlna_client_entry(raw, valid_collection_ids, valid_usernames):
    return DLNA_UPDATE_SERVICE.normalize_client_entry(raw, valid_collection_ids, valid_usernames)


def normalize_dlna_config_storage_kind(value):
    return DLNA_UPDATE_SERVICE.normalize_config_storage_kind(value)


def normalize_dlna_config_relative_path(value):
    return DLNA_UPDATE_SERVICE.normalize_config_relative_path(value)


def normalize_dlna_media_rule_entry(raw, valid_collection_ids):
    return DLNA_UPDATE_SERVICE.normalize_media_rule_entry(raw, valid_collection_ids)


def normalize_dlna_config(value):
    return DLNA_UPDATE_SERVICE.normalize_config(value)


def iter_legacy_config_candidates():
    seen = set()
    candidates = []

    def add_candidate(path):
        normalized_path = os.path.abspath(str(path or ""))
        if not normalized_path or normalized_path in seen:
            return
        if not os.path.isfile(normalized_path):
            return
        seen.add(normalized_path)
        candidates.append(normalized_path)

    add_candidate(LEGACY_CONFIG_FILE)

    backups_root = os.path.join(PROJECT_ROOT, "backups")
    if os.path.isdir(backups_root):
        for entry in sorted(os.listdir(backups_root), reverse=True):
            add_candidate(os.path.join(backups_root, entry, "flask_downloader_config.json"))

    return candidates


def load_app_config():
    loaded = config_store_load_app_config(
        CONFIG_FILE,
        default_app_config,
        normalize_user_storage_root,
        normalize_download_root,
        normalize_audio_download_root,
        normalize_storage_config,
        normalize_retention_days,
        normalize_yt_dlp_update_state,
        normalize_ffmpeg_update_state,
        normalize_app_update_state,
        normalize_dlna_update_state,
        normalize_dlna_config,
    )
    return hydrate_storage_paths(loaded)


def recover_legacy_dlna_config_if_needed(config_data):
    current_data = copy.deepcopy(config_data or {})
    current_dlna = normalize_dlna_config(current_data.get("dlna"))
    current_data["dlna"] = current_dlna

    legacy_dlna = None
    for candidate_path in iter_legacy_config_candidates():
        try:
            with open(candidate_path, "r", encoding="utf-8") as fh:
                legacy_raw = json.load(fh) or {}
        except Exception:
            continue
        next_legacy_dlna = normalize_dlna_config((legacy_raw or {}).get("dlna"))
        if next_legacy_dlna.get("collections") or next_legacy_dlna.get("clients") or next_legacy_dlna.get("media_rules"):
            legacy_dlna = next_legacy_dlna
            break

    if legacy_dlna is None:
        return current_data, False

    changed = False

    current_collections = list(current_dlna.get("collections") or [])
    current_collection_ids = {str(item.get("id") or "") for item in current_collections}
    for item in legacy_dlna.get("collections") or []:
        collection_id = str(item.get("id") or "")
        if not collection_id or collection_id in current_collection_ids:
            continue
        current_collections.append(copy.deepcopy(item))
        current_collection_ids.add(collection_id)
        changed = True
    if current_collections != list(current_dlna.get("collections") or []):
        current_dlna["collections"] = current_collections

    if not (current_dlna.get("clients") or []):
        current_dlna["clients"] = copy.deepcopy(legacy_dlna.get("clients") or [])
        changed = changed or bool(current_dlna["clients"])

    if not (current_dlna.get("media_rules") or []) and (legacy_dlna.get("media_rules") or []):
        current_dlna["media_rules"] = copy.deepcopy(legacy_dlna.get("media_rules") or [])
        changed = True

    if changed:
        current_dlna["layout_version"] = max(
            int(current_dlna.get("layout_version") or 0),
            int(legacy_dlna.get("layout_version") or 0),
        )
        current_data["dlna"] = normalize_dlna_config(current_dlna)

    return current_data, changed


APP_CONFIG, LEGACY_DLNA_CONFIG_RECOVERED = recover_legacy_dlna_config_if_needed(load_app_config())
APP_CONFIG = hydrate_storage_paths(APP_CONFIG)
if LEGACY_DLNA_CONFIG_RECOVERED:
    config_store_write_app_config(CONFIG_FILE, APP_CONFIG)


def write_app_config_locked():
    config_store_write_app_config(CONFIG_FILE, APP_CONFIG)


def save_app_config(
    *,
    download_root=None,
    audio_download_root=None,
    job_retention_days,
    active_backend=None,
    local_storage_root=None,
    network_storage=None,
):
    previous_config = get_config_snapshot()
    previous_storage = normalize_storage_config(previous_config.get("storage"))
    previous_storage_id = normalize_storage_id(
        previous_storage.get("default_write_storage_id") or previous_storage.get("active_backend"),
        default="local",
    )
    previous_user_root = os.path.abspath(
        get_storage_user_root_by_id(previous_storage, previous_storage_id)
    )
    normalized_days = normalize_retention_days(job_retention_days)
    next_storage_raw = copy.deepcopy(previous_storage)

    if local_storage_root is None and download_root:
        local_storage_root = download_root
    if active_backend is not None:
        next_storage_raw["active_backend"] = active_backend
    if local_storage_root:
        next_storage_raw.setdefault("local", {})
        next_storage_raw["local"]["root"] = local_storage_root
    if isinstance(network_storage, dict):
        next_storage_raw.setdefault("network", {})
        next_storage_raw["network"].update(network_storage)

    next_storage = normalize_storage_config(next_storage_raw)
    next_storage_id = normalize_storage_id(
        next_storage.get("default_write_storage_id") or next_storage.get("active_backend"),
        default="local",
    )
    next_payload = hydrate_storage_paths({
        "storage": next_storage,
        "user_storage_layout_version": USER_STORAGE_LAYOUT_VERSION,
        "job_retention_days": normalized_days,
    })
    normalized_user_root = normalize_user_storage_root(next_payload["user_storage_root"])
    next_user_root = os.path.abspath(normalized_user_root)

    next_network_mode = normalize_network_storage_mode(next_storage.get("network", {}).get("mode") or "managed_smb")
    if (
        next_storage["active_backend"] == "network"
        and next_network_mode == "managed_smb"
        and not os.path.ismount(get_storage_active_root(next_storage))
    ):
        raise ValueError("Aktywny backend jest ustawiony na udział sieciowy, ale udział nie jest teraz zamontowany.")

    payload = {
        "storage": next_storage,
        "user_storage_root": normalized_user_root,
        "user_storage_layout_version": USER_STORAGE_LAYOUT_VERSION,
        "download_root": os.path.join(normalized_user_root, DEFAULT_ADMIN_USERNAME, "video"),
        "audio_download_root": os.path.join(normalized_user_root, DEFAULT_ADMIN_USERNAME, "audio"),
        "job_retention_days": normalized_days,
    }

    path_map = {}
    should_move_storage_tree = (
        previous_storage_id == next_storage_id == "local"
        and previous_user_root != next_user_root
        and os.path.isdir(previous_user_root)
    )
    if should_move_storage_tree:
        path_map = move_legacy_storage_tree_contents(previous_user_root, next_user_root)

        with DOWNLOAD_LOCK:
            changed = False
            for job in DOWNLOAD_JOBS.values():
                filepath = str(job.get("filepath") or "").strip()
                if not filepath:
                    continue
                absolute_path = os.path.abspath(filepath)
                try:
                    if os.path.commonpath([previous_user_root, absolute_path]) != previous_user_root:
                        continue
                except Exception:
                    continue

                relative_path = os.path.relpath(absolute_path, previous_user_root).replace("\\", "/")
                new_path = path_map.get(absolute_path) or os.path.abspath(os.path.join(next_user_root, relative_path))
                job["filepath"] = new_path
                job["relative_path"] = safe_relative_download_path(relative_path)
                changed = True

                replace_paths = []
                for raw_path in job.get("replace_paths") or []:
                    current_path = os.path.abspath(str(raw_path or ""))
                    migrated_path = path_map.get(current_path)
                    if not migrated_path:
                        try:
                            if os.path.commonpath([previous_user_root, current_path]) == previous_user_root:
                                rel = os.path.relpath(current_path, previous_user_root).replace("\\", "/")
                                migrated_path = os.path.abspath(os.path.join(next_user_root, rel))
                        except Exception:
                            migrated_path = current_path
                    replace_paths.append(migrated_path or current_path)
                if replace_paths != list(job.get("replace_paths") or []):
                    job["replace_paths"] = replace_paths

            if changed:
                write_download_jobs_locked()

    with APP_CONFIG_LOCK:
        APP_CONFIG.update(payload)
        APP_CONFIG.update(hydrate_storage_paths(APP_CONFIG))
        write_app_config_locked()

    return dict(payload)


def update_storage_network_test_state(ok, message, **extra):
    with APP_CONFIG_LOCK:
        storage = normalize_storage_config(APP_CONFIG.get("storage"))
        network = dict(storage.get("network") or {})
        network["last_test_ok"] = bool(ok)
        network["last_test_message"] = str(message or "").strip()
        network["last_test_at"] = time.time()
        if "password_saved" in extra:
            network["password_saved"] = bool(extra.get("password_saved"))
        if "last_test_signature" in extra:
            network["last_test_signature"] = str(extra.get("last_test_signature") or "").strip()
        if "manual_unmounted" in extra:
            network["manual_unmounted"] = bool(extra.get("manual_unmounted"))
        storage["network"] = normalize_storage_config({"active_backend": storage.get("active_backend"), "local": storage.get("local"), "network": network})["network"]
        APP_CONFIG["storage"] = storage
        APP_CONFIG.update(hydrate_storage_paths(APP_CONFIG))
        write_app_config_locked()
        return copy.deepcopy(storage)


def build_updated_storage_config(*, active_backend=None, local_root=None, network_updates=None):
    storage = get_storage_config_snapshot()
    next_storage = copy.deepcopy(storage)
    if active_backend is not None:
        next_storage["active_backend"] = normalize_storage_backend_kind(active_backend)
        next_storage["default_write_storage_id"] = normalize_storage_backend_kind(active_backend)
    if local_root is not None:
        next_storage.setdefault("local", {})
        next_storage["local"]["root"] = local_root
    if isinstance(network_updates, dict):
        next_storage.setdefault("network", {})
        next_storage["network"].update(network_updates)
    return normalize_storage_config(next_storage)


def test_network_storage_config(storage_config, *, password="", keep_existing_password=True):
    response = STORAGE_BACKEND_SERVICE.test_network_config(
        storage_config,
        password=password,
        keep_existing_password=keep_existing_password,
    )
    update_storage_network_test_state(
        True,
        response.get("message") or "Połączenie z udziałem sieciowym działa poprawnie.",
        password_saved=bool(password) or bool(storage_config.get("network", {}).get("password_saved")),
        last_test_signature=build_storage_network_signature(storage_config),
        manual_unmounted=bool((storage_config.get("network") or {}).get("manual_unmounted")),
    )
    return response


def configure_network_storage_config(storage_config, *, password="", keep_existing_password=True, mount_now=False):
    response = STORAGE_BACKEND_SERVICE.configure_network_storage(
        storage_config,
        password=password,
        keep_existing_password=keep_existing_password,
        mount_now=mount_now,
    )
    update_storage_network_test_state(
        True,
        response.get("message") or "Konfiguracja udziału sieciowego została zapisana.",
        password_saved=bool(password) or True,
        last_test_signature=build_storage_network_signature(storage_config),
        manual_unmounted=not bool(mount_now),
    )
    return response


def mount_network_storage_config(storage_config=None):
    effective_config = normalize_storage_config((storage_config or get_storage_config_snapshot()))
    response = STORAGE_BACKEND_SERVICE.mount_network_storage(effective_config)
    update_storage_network_test_state(
        True,
        response.get("message") or "Udział sieciowy został zamontowany.",
        password_saved=bool(effective_config.get("network", {}).get("password_saved")),
        last_test_signature=build_storage_network_signature(effective_config),
        manual_unmounted=False,
    )
    return response


def unmount_network_storage_config(storage_config=None):
    effective_config = normalize_storage_config((storage_config or get_storage_config_snapshot()))
    response = STORAGE_BACKEND_SERVICE.unmount_network_storage(effective_config)
    update_storage_network_test_state(
        bool(response.get("is_mount") is False),
        response.get("message") or "Udział sieciowy został odmontowany.",
        password_saved=bool(effective_config.get("network", {}).get("password_saved")),
        last_test_signature=build_storage_network_signature(effective_config),
        manual_unmounted=True,
    )
    return response


def remove_network_storage_config(storage_config=None, *, remove_credentials=False):
    effective_config = normalize_storage_config((storage_config or get_storage_config_snapshot()))
    response = STORAGE_BACKEND_SERVICE.remove_network_storage(
        effective_config,
        remove_credentials=remove_credentials,
    )
    next_storage = normalize_storage_config({
        "active_backend": "local",
        "default_write_storage_id": "local",
        "local": effective_config.get("local") or {},
        "network": default_storage_config().get("network") or {},
    })
    payload = hydrate_storage_paths({
        "storage": next_storage,
        "user_storage_layout_version": USER_STORAGE_LAYOUT_VERSION,
        "job_retention_days": get_config_snapshot().get("job_retention_days"),
    })
    with APP_CONFIG_LOCK:
        APP_CONFIG["storage"] = next_storage
        APP_CONFIG.update(payload)
        write_app_config_locked()
    update_storage_network_test_state(
        False,
        "Konfiguracja udziału sieciowego została usunięta.",
        password_saved=False,
        last_test_signature="",
        manual_unmounted=False,
    )
    return response


def get_config_snapshot():
    with APP_CONFIG_LOCK:
        return copy.deepcopy(APP_CONFIG)


def get_dlna_config_snapshot():
    with APP_CONFIG_LOCK:
        return normalize_dlna_config(copy.deepcopy(APP_CONFIG.get("dlna")))


def save_dlna_update_state(latest_version, checked_at, check_error):
    with APP_CONFIG_LOCK:
        APP_CONFIG["dlna_update_state"] = normalize_dlna_update_state({
            "latest_version": latest_version,
            "checked_at": checked_at,
            "check_error": check_error,
        })
        write_app_config_locked()


def save_dlna_runtime_status(last_sync_at=None, last_sync_error=None):
    with APP_CONFIG_LOCK:
        dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))
        if last_sync_at is not None:
            dlna_config["last_sync_at"] = float(last_sync_at or 0.0)
        if last_sync_error is not None:
            dlna_config["last_sync_error"] = str(last_sync_error or "").strip()
        APP_CONFIG["dlna"] = dlna_config
        write_app_config_locked()
    return copy.deepcopy(dlna_config)


def set_dlna_runtime_phase(phase, detail="", started_at=None):
    normalized_phase = str(phase or "").strip().lower()
    if normalized_phase not in ("idle", "starting", "rebuilding", "running", "error"):
        normalized_phase = "idle"
    started_ts = float(started_at if started_at is not None else time.time())
    with APP_CONFIG_LOCK:
        dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))
        dlna_config["runtime_phase"] = normalized_phase
        dlna_config["runtime_phase_detail"] = str(detail or "").strip()[:240]
        dlna_config["runtime_phase_started_at"] = started_ts if normalized_phase in ("starting", "rebuilding") else 0.0
        APP_CONFIG["dlna"] = dlna_config
        write_app_config_locked()
    return copy.deepcopy(dlna_config)


def normalize_dlna_pending_manual_sync_paths(paths):
    normalized_paths = []
    seen = set()
    for raw_path in paths or []:
        path_text = str(raw_path or "").strip()
        if not path_text:
            continue
        canonical_path = canonicalize_managed_relative_path(path_text) or safe_relative_download_path(path_text)
        if not canonical_path or canonical_path in seen:
            continue
        seen.add(canonical_path)
        normalized_paths.append(canonical_path)
    return normalized_paths


def get_dlna_manual_sync_notice_state(dlna_config=None):
    config = normalize_dlna_config(dlna_config if dlna_config is not None else get_dlna_config_snapshot())
    pending_paths = normalize_dlna_pending_manual_sync_paths(config.get("pending_manual_sync_paths") or [])
    try:
        pending_since = float(config.get("pending_manual_sync_since") or 0.0)
    except Exception:
        pending_since = 0.0
    last_item = str(config.get("pending_manual_sync_last_item") or "").strip()
    pending_count = len(pending_paths)
    return {
        "pending": bool(pending_count),
        "count": pending_count,
        "since": pending_since,
        "since_text": format_ts(pending_since) if pending_since else "",
        "last_item": last_item,
        "message": (
            "Pobrano nowe pliki i biblioteka DLNA czeka na ręczną aktualizację."
            if pending_count
            else ""
        ),
    }


def mark_dlna_manual_sync_needed(relative_path="", item_label=""):
    canonical_path = canonicalize_managed_relative_path(relative_path) or safe_relative_download_path(relative_path)
    item_label_text = str(item_label or "").strip()
    with APP_CONFIG_LOCK:
        dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))
        pending_paths = normalize_dlna_pending_manual_sync_paths(dlna_config.get("pending_manual_sync_paths") or [])
        changed = False
        if canonical_path and canonical_path not in pending_paths:
            pending_paths.append(canonical_path)
            changed = True
        if pending_paths and not float(dlna_config.get("pending_manual_sync_since") or 0.0):
            dlna_config["pending_manual_sync_since"] = time.time()
            changed = True
        if item_label_text and item_label_text != str(dlna_config.get("pending_manual_sync_last_item") or ""):
            dlna_config["pending_manual_sync_last_item"] = item_label_text[:200]
            changed = True
        dlna_config["pending_manual_sync_paths"] = pending_paths
        if changed:
            APP_CONFIG["dlna"] = normalize_dlna_config(dlna_config)
            write_app_config_locked()
        return get_dlna_manual_sync_notice_state(dlna_config)


def discard_dlna_manual_sync_path(relative_path):
    canonical_path = canonicalize_managed_relative_path(relative_path) or safe_relative_download_path(relative_path)
    if not canonical_path:
        return get_dlna_manual_sync_notice_state()
    with APP_CONFIG_LOCK:
        dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))
        pending_paths = normalize_dlna_pending_manual_sync_paths(dlna_config.get("pending_manual_sync_paths") or [])
        next_paths = [item for item in pending_paths if item != canonical_path]
        if next_paths == pending_paths:
            return get_dlna_manual_sync_notice_state(dlna_config)
        dlna_config["pending_manual_sync_paths"] = next_paths
        if not next_paths:
            dlna_config["pending_manual_sync_since"] = 0.0
            dlna_config["pending_manual_sync_last_item"] = ""
        APP_CONFIG["dlna"] = normalize_dlna_config(dlna_config)
        write_app_config_locked()
        return get_dlna_manual_sync_notice_state(dlna_config)


def clear_dlna_manual_sync_needed():
    with APP_CONFIG_LOCK:
        dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))
        dlna_config["pending_manual_sync_paths"] = []
        dlna_config["pending_manual_sync_since"] = 0.0
        dlna_config["pending_manual_sync_last_item"] = ""
        APP_CONFIG["dlna"] = normalize_dlna_config(dlna_config)
        write_app_config_locked()
        return get_dlna_manual_sync_notice_state(dlna_config)


def set_dlna_config(dlna_config):
    normalized = normalize_dlna_config(dlna_config)
    with APP_CONFIG_LOCK:
        APP_CONFIG["dlna"] = normalized
        write_app_config_locked()
    return copy.deepcopy(normalized)


def get_download_root():
    return get_config_snapshot()["download_root"]


def get_audio_download_root():
    return get_config_snapshot()["audio_download_root"]


def normalize_storage_kind(value):
    return "audio" if str(value or "").strip().lower() == "audio" else "video"


STORAGE_BACKEND_SERVICE = StorageBackendService(
    helper_path=NETWORK_STORAGE_HELPER,
    app_service_user=APP_SERVICE_USER,
    app_service_group=APP_SERVICE_GROUP,
)

STORAGE_STATS_SERVICE = StorageStatsService(
    get_storage_config_snapshot=lambda: get_storage_config_snapshot(),
    read_storage_runtime_access_state=lambda root_path, require_mount=False: read_storage_runtime_access_state(
        root_path,
        require_mount=require_mount,
    ),
    format_bytes_text=lambda value: format_bytes_text(value),
)


STORAGE_SERVICE = ManagedStorageService(
    get_config_snapshot=get_config_snapshot,
    normalize_username=normalize_username,
    normalize_storage_kind=normalize_storage_kind,
    get_current_username=lambda: get_current_username(),
    default_admin_username=DEFAULT_ADMIN_USERNAME,
    has_request_context=has_request_context,
    is_admin_authenticated=lambda: is_admin_authenticated(),
    ensure_share_ready=lambda auto_remount=True: ensure_share_ready(auto_remount=auto_remount),
    format_ts=format_ts,
)


def get_user_storage_base_root(storage_id=None):
    return STORAGE_SERVICE.get_user_storage_base_root(storage_id)


def get_user_root(username, storage_id=None):
    return STORAGE_SERVICE.get_user_root(username, storage_id)


def get_user_storage_root(username, storage_kind="video", storage_id=None):
    return STORAGE_SERVICE.get_user_storage_root(username, storage_kind, storage_id)


def build_managed_relative_path(owner_username, storage_kind="video", user_relative_path="", storage_id=None):
    return STORAGE_SERVICE.build_managed_relative_path(owner_username, storage_kind, user_relative_path, storage_id=storage_id)


def parse_managed_relative_path(value):
    return STORAGE_SERVICE.parse_managed_relative_path(value)


def get_managed_path_info(path):
    return STORAGE_SERVICE.get_managed_path_info(path)


def get_storage_root(storage_kind="video", owner_username=None, storage_id=None):
    return STORAGE_SERVICE.get_storage_root(storage_kind, owner_username, storage_id=storage_id)


def get_managed_storage_roots():
    return STORAGE_SERVICE.get_managed_storage_roots()


def get_storage_kind_for_path(path):
    return STORAGE_SERVICE.get_storage_kind_for_path(path)


def get_storage_disk_state():
    return STORAGE_STATS_SERVICE.get_state()


def get_path_owner_username(path):
    return STORAGE_SERVICE.get_path_owner_username(path)


def format_relative_path_for_user(relative_path, viewer_username="", is_admin=False):
    return STORAGE_SERVICE.format_relative_path_for_user(relative_path, viewer_username=viewer_username, is_admin=is_admin)


def build_managed_file_url(owner_username, storage_kind, relative_path):
    return STORAGE_SERVICE.build_managed_file_url(owner_username, storage_kind, relative_path)


def get_completed_job_retention_seconds():
    return get_config_snapshot()["job_retention_days"] * 24 * 60 * 60


def get_daily_folder_name(ts=None):
    return STORAGE_SERVICE.get_daily_folder_name(ts)


def get_daily_download_dir(ts=None, media_kind="video", owner_username=None):
    return STORAGE_SERVICE.get_daily_download_dir(ts, media_kind=media_kind, owner_username=owner_username)


def get_relative_download_path(path, media_kind=None, owner_username=None, storage_id=None):
    return STORAGE_SERVICE.get_relative_download_path(path, media_kind=media_kind, owner_username=owner_username, storage_id=storage_id)


def safe_relative_download_path(value):
    return STORAGE_SERVICE.safe_relative_download_path(value)


def resolve_download_path(relative_path, media_kind="video", owner_username=None, storage_id=None):
    return STORAGE_SERVICE.resolve_download_path(relative_path, media_kind=media_kind, owner_username=owner_username, storage_id=storage_id)


def canonicalize_managed_relative_path(relative_path, *, owner_username=None, storage_kind="video"):
    safe_path = safe_relative_download_path(relative_path)
    if not safe_path:
        return ""

    parsed = parse_managed_relative_path(safe_path)
    normalized_owner = normalize_username(
        (parsed or {}).get("owner_username") or owner_username or DEFAULT_ADMIN_USERNAME
    )
    normalized_kind = normalize_storage_kind(
        (parsed or {}).get("storage_kind") or storage_kind or "video"
    )
    user_relative_path = safe_relative_download_path(
        (parsed or {}).get("user_relative_path") or safe_path
    )
    if not user_relative_path:
        return ""

    if parsed and not parsed.get("is_legacy"):
        return build_managed_relative_path(
            normalized_owner,
            normalized_kind,
            user_relative_path,
            storage_id=parsed.get("storage_id") or "local",
        )

    matched_storage_id = ""
    for candidate_storage_id in ("local", "network"):
        candidate_path = STORAGE_SERVICE.resolve_download_path(
            build_managed_relative_path(
                normalized_owner,
                normalized_kind,
                user_relative_path,
                storage_id=candidate_storage_id,
            ),
            normalized_kind,
            owner_username=normalized_owner,
        )
        if candidate_path and os.path.isfile(candidate_path):
            matched_storage_id = candidate_storage_id
            break

    return build_managed_relative_path(
        normalized_owner,
        normalized_kind,
        user_relative_path,
        storage_id=matched_storage_id or STORAGE_SERVICE.get_default_write_storage_id(),
    )


def cleanup_empty_download_dirs(path):
    return STORAGE_SERVICE.cleanup_empty_download_dirs(path)


def is_temporary_download_artifact_name(name):
    return STORAGE_SERVICE.is_temporary_download_artifact_name(name)


def get_download_artifact_roots(path):
    return DOWNLOAD_PATH_SERVICE.get_download_artifact_roots(path)


def cleanup_download_artifacts(paths):
    return DOWNLOAD_PATH_SERVICE.cleanup_download_artifacts(paths)


def normalize_saved_job_record(raw):
    now_ts = time.time()
    default_job_id = uuid.uuid4().hex
    allowed_statuses = {"queued", "downloading", "paused", "completed", "failed", "canceled"}
    raw_owner_username = raw.get("owner_username") or DEFAULT_ADMIN_USERNAME

    try:
        owner_username = normalize_username(raw_owner_username)
    except Exception:
        owner_username = DEFAULT_ADMIN_USERNAME

    normalized_relative_path = canonicalize_managed_relative_path(
        raw.get("relative_path") or "",
        owner_username=owner_username,
        storage_kind=normalize_storage_kind(raw.get("storage_kind") or "video"),
    )

    job = {
        "job_id": str(raw.get("job_id") or default_job_id),
        "owner_username": owner_username,
        "page_url": str(raw.get("page_url") or ""),
        "format_id": str(raw.get("format_id") or ""),
        "selection_signature": dict(raw.get("selection_signature") or {}),
        "storage_kind": normalize_storage_kind(raw.get("storage_kind") or "video"),
        "status": str(raw.get("status") or "failed"),
        "status_label": str(raw.get("status_label") or "Nieznany"),
        "title": str(raw.get("title") or ""),
        "label": str(raw.get("label") or ""),
        "filename": str(raw.get("filename") or ""),
        "planned_filename": str(raw.get("planned_filename") or raw.get("filename") or ""),
        "filepath": str(raw.get("filepath") or ""),
        "relative_path": normalized_relative_path,
        "downloaded_bytes": 0,
        "total_bytes": None,
        "progress_percent": None,
        "error": str(raw.get("error") or ""),
        "created_at": now_ts,
        "started_at": None,
        "finished_at": None,
        "overwrite_existing": bool(raw.get("overwrite_existing")),
        "replace_paths": [str(path) for path in (raw.get("replace_paths") or []) if path],
        "auto_dlna_collection_id": str(raw.get("auto_dlna_collection_id") or "").strip(),
        "dlna_current_relative_path": safe_relative_download_path(raw.get("dlna_current_relative_path") or ""),
        "dlna_collection_id": str(raw.get("dlna_collection_id") or "").strip(),
        "dlna_collection_name": str(raw.get("dlna_collection_name") or "").strip(),
        "is_live_capture": bool(raw.get("is_live_capture")),
        "live_status": str(raw.get("live_status") or ""),
        "processing_stage": str(raw.get("processing_stage") or "").strip(),
    }

    if job["status"] not in allowed_statuses:
        job["status"] = "failed"
        job["status_label"] = "Niepowodzenie"
        job["error"] = "Przywrócono nieznany status zadania po restarcie usługi."

    for key in ("downloaded_bytes", "total_bytes"):
        try:
            value = raw.get(key)
            job[key] = int(value) if value not in (None, "", False) else None
        except Exception:
            job[key] = None

    if job["downloaded_bytes"] is None:
        job["downloaded_bytes"] = 0

    for key in ("progress_percent", "created_at", "started_at", "finished_at"):
        try:
            value = raw.get(key)
            job[key] = float(value) if value not in (None, "", False) else None
        except Exception:
            job[key] = None

    if job["created_at"] is None:
        job["created_at"] = now_ts

    return job


def serialize_job_for_storage(job):
    return {
        "job_id": str(job.get("job_id") or ""),
        "owner_username": normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME),
        "page_url": str(job.get("page_url") or ""),
        "format_id": str(job.get("format_id") or ""),
        "selection_signature": dict(job.get("selection_signature") or {}),
        "storage_kind": normalize_storage_kind(job.get("storage_kind") or "video"),
        "status": str(job.get("status") or ""),
        "status_label": str(job.get("status_label") or ""),
        "title": str(job.get("title") or ""),
        "label": str(job.get("label") or ""),
        "filename": str(job.get("filename") or ""),
        "planned_filename": str(job.get("planned_filename") or ""),
        "filepath": str(job.get("filepath") or ""),
        "relative_path": canonicalize_managed_relative_path(
            job.get("relative_path") or "",
            owner_username=job.get("owner_username") or DEFAULT_ADMIN_USERNAME,
            storage_kind=job.get("storage_kind") or "video",
        ),
        "downloaded_bytes": int(job.get("downloaded_bytes") or 0),
        "total_bytes": int(job.get("total_bytes")) if job.get("total_bytes") not in (None, "", False) else None,
        "progress_percent": float(job.get("progress_percent")) if job.get("progress_percent") not in (None, "", False) else None,
        "error": str(job.get("error") or ""),
        "created_at": float(job.get("created_at") or 0.0),
        "started_at": float(job.get("started_at")) if job.get("started_at") not in (None, "", False) else None,
        "finished_at": float(job.get("finished_at")) if job.get("finished_at") not in (None, "", False) else None,
        "overwrite_existing": bool(job.get("overwrite_existing")),
        "replace_paths": [str(path) for path in (job.get("replace_paths") or []) if path],
        "auto_dlna_collection_id": str(job.get("auto_dlna_collection_id") or "").strip(),
        "dlna_current_relative_path": safe_relative_download_path(job.get("dlna_current_relative_path") or ""),
        "dlna_collection_id": str(job.get("dlna_collection_id") or "").strip(),
        "dlna_collection_name": str(job.get("dlna_collection_name") or "").strip(),
        "is_live_capture": bool(job.get("is_live_capture")),
        "live_status": str(job.get("live_status") or ""),
        "processing_stage": str(job.get("processing_stage") or "").strip(),
    }


def write_download_jobs_locked():
    payload = [serialize_job_for_storage(job) for job in DOWNLOAD_JOBS.values()]
    jobs_store_write_jobs_payload(JOBS_FILE, payload)


def save_download_jobs():
    with DOWNLOAD_LOCK:
        write_download_jobs_locked()


def make_unique_path(candidate_path):
    candidate = os.path.abspath(str(candidate_path or ""))
    if not candidate or not os.path.exists(candidate):
        return candidate

    base, ext = os.path.splitext(candidate)
    counter = 1
    while True:
        next_candidate = "%s_migrated_%d%s" % (base, counter, ext)
        if not os.path.exists(next_candidate):
            return next_candidate
        counter += 1


def move_legacy_storage_tree_contents(source_root, target_root):
    source = os.path.abspath(str(source_root or ""))
    target = os.path.abspath(str(target_root or ""))
    path_map = {}

    if not source or not target or source == target or not os.path.isdir(source):
        return path_map

    os.makedirs(target, exist_ok=True)

    for current_root, _, filenames in os.walk(source):
        for name in filenames:
            source_path = os.path.abspath(os.path.join(current_root, name))
            try:
                relative_path = os.path.relpath(source_path, source).replace("\\", "/")
            except Exception:
                continue

            destination_path = os.path.abspath(os.path.join(target, relative_path))
            try:
                if os.path.commonpath([target, destination_path]) != target:
                    continue
            except Exception:
                continue

            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            final_destination = make_unique_path(destination_path)
            shutil.move(source_path, final_destination)
            path_map[source_path] = os.path.abspath(final_destination)

    for current_root, dirnames, _ in os.walk(source, topdown=False):
        for name in dirnames:
            candidate = os.path.join(current_root, name)
            try:
                os.rmdir(candidate)
            except OSError:
                pass

    return path_map


def migrate_legacy_job_payloads(raw_jobs, path_map, legacy_roots):
    changed = False
    migrated_jobs = []

    for raw in raw_jobs:
        if not isinstance(raw, dict):
            continue

        job = dict(raw)
        storage_kind = normalize_storage_kind(job.get("storage_kind") or "video")
        owner_username = normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME)
        legacy_root = os.path.abspath(legacy_roots.get(storage_kind) or "")
        target_root = os.path.abspath(get_user_storage_root(owner_username, storage_kind))

        if job.get("owner_username") != owner_username:
            job["owner_username"] = owner_username
            changed = True

        filepath = str(job.get("filepath") or "").strip()
        if filepath:
            absolute_path = os.path.abspath(filepath)
            new_path = path_map.get(absolute_path)
            if not new_path and legacy_root:
                try:
                    if os.path.commonpath([legacy_root, absolute_path]) == legacy_root:
                        relative_under_legacy = os.path.relpath(absolute_path, legacy_root).replace("\\", "/")
                        new_path = os.path.abspath(os.path.join(target_root, relative_under_legacy))
                except Exception:
                    new_path = None

            if new_path and str(job.get("filepath") or "") != new_path:
                job["filepath"] = new_path
                changed = True

        relative_path = safe_relative_download_path(job.get("relative_path") or "")
        canonical_relative_path = canonicalize_managed_relative_path(
            relative_path,
            owner_username=owner_username,
            storage_kind=storage_kind,
        )
        if canonical_relative_path and canonical_relative_path != relative_path:
            job["relative_path"] = canonical_relative_path
            changed = True
        elif job.get("filepath"):
            computed_relative_path = get_relative_download_path(job.get("filepath"), storage_kind, owner_username)
            if computed_relative_path and computed_relative_path != relative_path:
                job["relative_path"] = computed_relative_path
                changed = True

        replace_paths = []
        for raw_path in job.get("replace_paths") or []:
            current_path = os.path.abspath(str(raw_path or ""))
            next_path = path_map.get(current_path, current_path)
            if legacy_root:
                try:
                    if os.path.commonpath([legacy_root, current_path]) == legacy_root and current_path not in path_map:
                        relative_under_legacy = os.path.relpath(current_path, legacy_root).replace("\\", "/")
                        next_path = os.path.abspath(os.path.join(target_root, relative_under_legacy))
                except Exception:
                    pass
            replace_paths.append(next_path)
        if replace_paths != list(job.get("replace_paths") or []):
            job["replace_paths"] = replace_paths
            changed = True

        migrated_jobs.append(job)

    return migrated_jobs, changed


def migrate_legacy_dlna_rules(config, default_storage_id="local"):
    if not isinstance(config, dict):
        return config, False

    def parse_managed_relative_path_legacy(value):
        safe_value = safe_relative_download_path(value or "")
        if not safe_value or not safe_value.startswith("@"):
            return None

        parts = [str(part or "").strip() for part in safe_value.split("/")]
        if len(parts) < 4:
            return None

        storage_id = normalize_storage_id(str(parts[0])[1:], default=normalized_default_storage_id)
        owner_username = normalize_username(parts[1] or DEFAULT_ADMIN_USERNAME)
        storage_kind = normalize_storage_kind(parts[2] or "video")
        user_relative_path = safe_relative_download_path("/".join(parts[3:]))
        if not user_relative_path:
            return None

        return {
            "storage_id": storage_id,
            "owner_username": owner_username,
            "storage_kind": storage_kind,
            "user_relative_path": user_relative_path,
            "is_legacy": False,
        }

    changed = False
    normalized_default_storage_id = normalize_storage_id(default_storage_id or "local", default="local")
    media_rules = []
    for raw_rule in config.get("media_rules") or []:
        if not isinstance(raw_rule, dict):
            continue

        rule = dict(raw_rule)
        storage_kind = normalize_storage_kind(rule.get("storage_kind") or "video")
        relative_path = safe_relative_download_path(rule.get("relative_path") or "")
        parsed_relative_path = None
        if relative_path.startswith("@"):
            parsed_relative_path = parse_managed_relative_path_legacy(relative_path)
        if parsed_relative_path and not parsed_relative_path.get("is_legacy"):
            canonical_relative_path = build_managed_relative_path(
                parsed_relative_path.get("owner_username") or DEFAULT_ADMIN_USERNAME,
                parsed_relative_path.get("storage_kind") or storage_kind,
                parsed_relative_path.get("user_relative_path") or "",
                storage_id=parsed_relative_path.get("storage_id") or normalized_default_storage_id,
            )
        else:
            canonical_relative_path = build_managed_relative_path(
                DEFAULT_ADMIN_USERNAME,
                storage_kind,
                relative_path,
                storage_id=normalized_default_storage_id,
            )
        if canonical_relative_path and canonical_relative_path != relative_path:
            rule["relative_path"] = canonical_relative_path
            changed = True
        media_rules.append(rule)

    if media_rules != list(config.get("media_rules") or []):
        config["media_rules"] = media_rules

    return config, changed


def migrate_legacy_storage_layout():
    config_snapshot = get_config_snapshot()
    try:
        current_layout_version = int(config_snapshot.get("user_storage_layout_version") or 1)
    except Exception:
        current_layout_version = 1

    user_storage_root = normalize_user_storage_root(config_snapshot.get("user_storage_root") or USER_STORAGE_ROOT)
    admin_video_root = os.path.abspath(os.path.join(user_storage_root, DEFAULT_ADMIN_USERNAME, "video"))
    admin_audio_root = os.path.abspath(os.path.join(user_storage_root, DEFAULT_ADMIN_USERNAME, "audio"))
    os.makedirs(admin_video_root, exist_ok=True)
    os.makedirs(admin_audio_root, exist_ok=True)

    legacy_roots = {
        "video": os.path.abspath(normalize_download_root(config_snapshot.get("download_root") or DOWNLOAD_DIR)),
        "audio": os.path.abspath(normalize_audio_download_root(config_snapshot.get("audio_download_root") or AUDIO_DOWNLOAD_DIR)),
    }

    path_map = {}
    migrated_anything = False
    if current_layout_version < USER_STORAGE_LAYOUT_VERSION:
        for storage_kind, legacy_root in legacy_roots.items():
            target_root = admin_audio_root if storage_kind == "audio" else admin_video_root
            moved_paths = move_legacy_storage_tree_contents(legacy_root, target_root)
            if moved_paths:
                migrated_anything = True
                path_map.update(moved_paths)

    jobs_changed = False
    if os.path.isfile(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as fh:
                raw_jobs = json.load(fh) or []
            if isinstance(raw_jobs, list):
                migrated_jobs, jobs_changed = migrate_legacy_job_payloads(raw_jobs, path_map, legacy_roots)
                if jobs_changed:
                    with open(JOBS_FILE, "w", encoding="utf-8") as fh:
                        json.dump(migrated_jobs, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    config_changed = False
    with APP_CONFIG_LOCK:
        APP_CONFIG["user_storage_root"] = user_storage_root
        if int(APP_CONFIG.get("user_storage_layout_version") or 1) != USER_STORAGE_LAYOUT_VERSION:
            APP_CONFIG["user_storage_layout_version"] = USER_STORAGE_LAYOUT_VERSION
            config_changed = True
        if APP_CONFIG.get("download_root") != admin_video_root:
            APP_CONFIG["download_root"] = admin_video_root
            config_changed = True
        if APP_CONFIG.get("audio_download_root") != admin_audio_root:
            APP_CONFIG["audio_download_root"] = admin_audio_root
            config_changed = True
        migrated_dlna_config, dlna_changed = migrate_legacy_dlna_rules(
            normalize_dlna_config(APP_CONFIG.get("dlna")),
            default_storage_id=normalize_storage_id(
                ((APP_CONFIG.get("storage") or {}).get("default_write_storage_id"))
                or ((APP_CONFIG.get("storage") or {}).get("active_backend"))
                or "local",
                default="local",
            ),
        )
        if dlna_changed:
            APP_CONFIG["dlna"] = normalize_dlna_config(migrated_dlna_config)
            config_changed = True
        if config_changed:
            write_app_config_locked()

    return {
        "migrated_files": migrated_anything,
        "migrated_jobs": jobs_changed,
        "config_changed": config_changed,
    }


def load_saved_download_jobs():
    jobs = {}
    now_ts = time.time()
    cutoff_ts = now_ts - get_completed_job_retention_seconds()

    try:
        if not os.path.isfile(JOBS_FILE):
            return jobs

        raw_jobs = jobs_store_read_jobs_payload(JOBS_FILE)

        if not isinstance(raw_jobs, list):
            return jobs

        changed = False

        for raw in raw_jobs:
            if not isinstance(raw, dict):
                continue

            job = normalize_saved_job_record(raw)
            job_id = job["job_id"]
            owner_username = normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME)

            if job["status"] in ("completed", "failed", "canceled"):
                finished_at = job.get("finished_at")
                if finished_at and finished_at <= cutoff_ts:
                    changed = True
                    continue

            if job["status"] in ("queued", "downloading"):
                cleanup_download_artifacts({
                    job.get("filepath"),
                    resolve_download_path(job.get("relative_path"), job.get("storage_kind"), owner_username=owner_username),
                })
                job.update({
                    "status": "failed",
                    "status_label": "Niepowodzenie",
                    "error": "Usługa została zrestartowana przed zakończeniem pobierania.",
                    "finished_at": now_ts,
                    "filepath": "",
                    "relative_path": "",
                })
                changed = True
            elif job["status"] == "paused":
                if not job.get("status_label"):
                    job["status_label"] = "Wstrzymane"
                    changed = True

            jobs[job_id] = job

        if changed:
            jobs_store_write_jobs_payload(
                JOBS_FILE,
                [serialize_job_for_storage(job) for job in jobs.values()],
            )
    except Exception:
        return {}

    return jobs


def ensure_download_jobs_loaded(force=False):
    with DOWNLOAD_LOCK:
        if DOWNLOAD_JOBS and not force:
            return False

    reloaded_jobs = load_saved_download_jobs()
    if not reloaded_jobs:
        return False

    with DOWNLOAD_LOCK:
        if DOWNLOAD_JOBS and not force:
            return False
        DOWNLOAD_JOBS.clear()
        DOWNLOAD_JOBS.update(copy.deepcopy(reloaded_jobs))
    return True


LEGACY_STORAGE_MIGRATION_STATE = migrate_legacy_storage_layout()
DOWNLOAD_JOBS = load_saved_download_jobs()


def parse_iso8601_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return 0.0

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def get_ffmpeg_executable_name():
    return "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def get_ffprobe_executable_name():
    return "ffprobe.exe" if os.name == "nt" else "ffprobe"


def get_ffmpeg_install_source_label(source_key):
    if source_key == "managed":
        return "lokalny pakiet aplikacji"
    if source_key == "system":
        return "ffmpeg z systemowego PATH"
    return "brak"


def load_ffmpeg_manifest():
    if not os.path.isfile(FFMPEG_MANIFEST_FILE):
        return {}

    try:
        with open(FFMPEG_MANIFEST_FILE, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except Exception:
        return {}

    if not isinstance(raw, dict):
        return {}

    try:
        installed_at = float(raw.get("installed_at") or 0.0)
    except Exception:
        installed_at = 0.0

    return {
        "build_id": str(raw.get("build_id") or "").strip(),
        "version_label": str(raw.get("version_label") or "").strip(),
        "asset_name": str(raw.get("asset_name") or "").strip(),
        "asset_url": str(raw.get("asset_url") or "").strip(),
        "published_at": str(raw.get("published_at") or "").strip(),
        "version": str(raw.get("version") or "").strip(),
        "installed_at": installed_at,
    }


def find_binary_in_tree(root_dir, executable_name):
    if not root_dir or not os.path.isdir(root_dir):
        return ""

    for current_root, _, files in os.walk(root_dir):
        if executable_name in files:
            return os.path.abspath(os.path.join(current_root, executable_name))

    return ""


def get_managed_ffmpeg_binary_path():
    return find_binary_in_tree(FFMPEG_MANAGED_DIR, get_ffmpeg_executable_name())


def resolve_ffmpeg_binary():
    managed_path = get_managed_ffmpeg_binary_path()
    if managed_path and os.path.isfile(managed_path):
        return managed_path, "managed"

    system_path = shutil.which("ffmpeg")
    if system_path:
        return os.path.abspath(system_path), "system"

    return "", "missing"


def get_ffmpeg_location_for_yt_dlp():
    binary_path, _ = resolve_ffmpeg_binary()
    if not binary_path:
        return ""
    return os.path.dirname(binary_path)


def apply_ffmpeg_location(options):
    return FFMPEG_SERVICE.apply_ffmpeg_location(options)


def ensure_ffmpeg_available_for_audio_conversion():
    return FFMPEG_SERVICE.ensure_ffmpeg_available_for_audio_conversion()


def get_installed_ffmpeg_version(binary_path=None):
    command_path = str(binary_path or "").strip()
    if not command_path:
        command_path, _ = resolve_ffmpeg_binary()

    if not command_path:
        return "niezainstalowany"

    try:
        result = subprocess.run(
            [command_path, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        return "nieznana"

    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return "nieznana"

    first_line = ""
    for line in output.splitlines():
        line = str(line or "").strip()
        if line:
            first_line = line
            break

    if not first_line:
        return "nieznana"

    match = re.search(r"ffmpeg\s+version\s+([^\s]+)", first_line, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return first_line[-160:]


def detect_ffmpeg_release_asset_name():
    system_name = platform.system().strip().lower()
    machine = platform.machine().strip().lower()

    if machine in ("x86_64", "amd64", "x64"):
        arch = "x86_64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine in ("x86", "i386", "i686"):
        arch = "x86"
    else:
        arch = machine

    if system_name == "windows":
        if arch == "x86_64":
            return "ffmpeg-master-latest-win64-gpl.zip"
        if arch == "arm64":
            return "ffmpeg-master-latest-winarm64-gpl.zip"
        if arch == "x86":
            return "ffmpeg-master-latest-win32-gpl.zip"
    elif system_name == "linux":
        if arch == "x86_64":
            return "ffmpeg-master-latest-linux64-gpl.tar.xz"
        if arch == "arm64":
            return "ffmpeg-master-latest-linuxarm64-gpl.tar.xz"

    raise RuntimeError(
        "Automatyczna instalacja ffmpeg nie obsługuje jeszcze platformy %s/%s." % (
            platform.system() or "unknown",
            platform.machine() or "unknown",
        )
    )


def fetch_latest_ffmpeg_release_info():
    response = requests.get(
        FFMPEG_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
        timeout=(5, 20),
    )
    response.raise_for_status()

    payload = response.json() or {}
    asset_name = detect_ffmpeg_release_asset_name()
    assets = payload.get("assets") or []
    asset = None

    for entry in assets:
        if str((entry or {}).get("name") or "").strip() == asset_name:
            asset = entry or {}
            break

    if not asset:
        raise RuntimeError("Nie znaleziono paczki ffmpeg %s w najnowszym wydaniu." % asset_name)

    published_at = str(payload.get("published_at") or asset.get("updated_at") or "").strip()
    published_ts = parse_iso8601_timestamp(published_at)
    release_name = str(payload.get("name") or "").strip()
    version_label = release_name or ("build z %s" % format_ts(published_ts) if published_ts else asset_name)

    return {
        "asset_name": asset_name,
        "asset_url": str(asset.get("browser_download_url") or "").strip(),
        "asset_size": int(asset.get("size") or 0),
        "build_id": published_at or str(asset.get("id") or "").strip(),
        "version_label": version_label,
        "published_at": published_at,
        "published_at_text": format_ts(published_ts) if published_ts else "nieznana data",
    }


def ensure_child_path(root_dir, candidate_path):
    root_abs = os.path.abspath(root_dir)
    candidate_abs = os.path.abspath(candidate_path)
    if os.path.commonpath([root_abs, candidate_abs]) != root_abs:
        raise RuntimeError("Archiwum ffmpeg zawiera nieprawidłową ścieżkę: %s" % candidate_path)


def extract_ffmpeg_archive(archive_path, extract_dir):
    os.makedirs(extract_dir, exist_ok=True)

    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.infolist():
                ensure_child_path(extract_dir, os.path.join(extract_dir, member.filename))
            archive.extractall(extract_dir)
        return

    if archive_path.endswith(".tar.xz"):
        with tarfile.open(archive_path, "r:xz") as archive:
            for member in archive.getmembers():
                ensure_child_path(extract_dir, os.path.join(extract_dir, member.name))
            archive.extractall(extract_dir)
        return

    raise RuntimeError("Nieobsługiwany format archiwum ffmpeg: %s" % archive_path)


def find_ffmpeg_bin_dir(root_dir):
    ffmpeg_name = get_ffmpeg_executable_name()
    ffprobe_name = get_ffprobe_executable_name()
    candidates = []

    for current_root, _, files in os.walk(root_dir):
        if ffmpeg_name not in files:
            continue
        score = 1 if ffprobe_name in files else 0
        candidates.append((score, -len(os.path.abspath(current_root)), os.path.abspath(current_root)))

    if not candidates:
        raise RuntimeError("Po rozpakowaniu nie znaleziono binarki ffmpeg.")

    candidates.sort(reverse=True)
    return candidates[0][2]


def download_file(url, destination_path, progress_callback=None):
    with requests.get(
        url,
        headers={
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
        },
        stream=True,
        timeout=(10, 120),
    ) as response:
        response.raise_for_status()
        total_bytes = int(response.headers.get("Content-Length") or 0)
        downloaded_bytes = 0

        if progress_callback:
            progress_callback(downloaded_bytes, total_bytes)

        with open(destination_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
                    downloaded_bytes += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded_bytes, total_bytes)


def activate_ffmpeg_candidate_dir(candidate_dir):
    os.makedirs(FFMPEG_TOOLS_ROOT, exist_ok=True)
    final_dir = FFMPEG_MANAGED_DIR
    backup_dir = ""

    if os.path.isdir(final_dir):
        backup_dir = os.path.join(FFMPEG_TOOLS_ROOT, "managed-backup-%s" % uuid.uuid4().hex)
        os.replace(final_dir, backup_dir)

    try:
        os.replace(candidate_dir, final_dir)
    except Exception:
        if backup_dir and os.path.isdir(backup_dir) and not os.path.exists(final_dir):
            os.replace(backup_dir, final_dir)
        raise

    if backup_dir and os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)


def build_ffmpeg_candidate_dir(temp_root, release_info, progress_callback=None):
    archive_path = os.path.join(temp_root, release_info["asset_name"])
    extract_dir = os.path.join(temp_root, "extract")
    candidate_dir = os.path.join(temp_root, "candidate")

    download_file(release_info["asset_url"], archive_path, progress_callback=progress_callback)

    if progress_callback:
        progress_callback(
            status="running",
            status_label="Rozpakowywanie",
            progress_percent=80.0,
            detail="Rozpakowuję archiwum i przygotowuję katalog binarek.",
        )

    extract_ffmpeg_archive(archive_path, extract_dir)

    bin_dir = find_ffmpeg_bin_dir(extract_dir)
    package_root = os.path.dirname(bin_dir)
    ffmpeg_binary_path = os.path.join(bin_dir, get_ffmpeg_executable_name())
    detected_version = get_installed_ffmpeg_version(ffmpeg_binary_path)

    if progress_callback:
        progress_callback(
            status="running",
            status_label="Weryfikacja",
            progress_percent=90.0,
            detail="Sprawdzam wykryte binarki ffmpeg i ffprobe (%s)." % detected_version,
        )

    shutil.move(package_root, candidate_dir)

    manifest = {
        "build_id": release_info["build_id"],
        "version_label": release_info["version_label"],
        "asset_name": release_info["asset_name"],
        "asset_url": release_info["asset_url"],
        "published_at": release_info["published_at"],
        "version": detected_version,
        "installed_at": time.time(),
    }

    with open(os.path.join(candidate_dir, "ffmpeg_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    return candidate_dir, detected_version


def save_ffmpeg_update_state(latest_version, latest_build_id, checked_at, check_error):
    with APP_CONFIG_LOCK:
        APP_CONFIG["ffmpeg_update_state"] = normalize_ffmpeg_update_state({
            "latest_version": latest_version,
            "latest_build_id": latest_build_id,
            "checked_at": checked_at,
            "check_error": check_error,
        })
        write_app_config_locked()


def read_ffmpeg_update_state():
    with APP_CONFIG_LOCK:
        return normalize_ffmpeg_update_state(APP_CONFIG.get("ffmpeg_update_state"))


def save_app_update_state(latest_version, checked_at, check_error):
    with APP_CONFIG_LOCK:
        APP_CONFIG["app_update_state"] = normalize_app_update_state({
            "latest_version": latest_version,
            "checked_at": checked_at,
            "check_error": check_error,
        })
        write_app_config_locked()


def read_app_update_state():
    with APP_CONFIG_LOCK:
        return normalize_app_update_state(APP_CONFIG.get("app_update_state"))


def is_ffmpeg_scheduler_started():
    return bool(FFMPEG_SCHEDULER_STARTED)


def set_ffmpeg_scheduler_started(value):
    global FFMPEG_SCHEDULER_STARTED
    FFMPEG_SCHEDULER_STARTED = bool(value)


def get_last_due_ffmpeg_check_dt(now=None):
    current = now or datetime.now()
    scheduled = current.replace(hour=FFMPEG_CHECK_HOUR, minute=0, second=0, microsecond=0)
    if current < scheduled:
        scheduled -= timedelta(days=1)
    return scheduled


def get_next_ffmpeg_check_dt(now=None):
    current = now or datetime.now()
    scheduled = current.replace(hour=FFMPEG_CHECK_HOUR, minute=0, second=0, microsecond=0)
    if current >= scheduled:
        scheduled += timedelta(days=1)
    return scheduled


def needs_scheduled_ffmpeg_check(last_checked_at, now=None):
    due_dt = get_last_due_ffmpeg_check_dt(now=now)
    try:
        return float(last_checked_at or 0.0) < due_dt.timestamp()
    except Exception:
        return True


def get_ffmpeg_update_state_snapshot():
    return FFMPEG_SERVICE.get_update_state_snapshot()


def refresh_ffmpeg_update_state(force=False):
    return FFMPEG_SERVICE.refresh_update_state(force=force)


def ffmpeg_check_scheduler():
    while True:
        try:
            refresh_ffmpeg_update_state(force=False)
            next_check_dt = get_next_ffmpeg_check_dt()
            sleep_for = max(60.0, min((next_check_dt - datetime.now()).total_seconds(), 3600.0))
        except Exception:
            sleep_for = 300.0

        time.sleep(sleep_for)


def start_ffmpeg_scheduler_once():
    return FFMPEG_SERVICE.start_scheduler_once()


def install_or_update_ffmpeg(progress_callback=None):
    return FFMPEG_SERVICE.install_or_update(progress_callback=progress_callback)


def get_installed_yt_dlp_version():
    return YTDLP_SERVICE.get_installed_version()


def fetch_latest_yt_dlp_version():
    return YTDLP_SERVICE.fetch_latest_version()


def is_version_newer(candidate_version, installed_version):
    candidate_version = str(candidate_version or "").strip()
    installed_version = str(installed_version or "").strip()

    if not candidate_version or not installed_version:
        return False

    if candidate_version == installed_version:
        return False

    if Version is None:
        return candidate_version != installed_version

    try:
        return Version(candidate_version) > Version(installed_version)
    except (InvalidVersion, TypeError, ValueError):
        return candidate_version != installed_version


def get_last_due_yt_dlp_check_dt(now=None):
    current = now or datetime.now()
    scheduled = current.replace(hour=YTDLP_CHECK_HOUR, minute=0, second=0, microsecond=0)
    if current < scheduled:
        scheduled -= timedelta(days=1)
    return scheduled


def get_next_yt_dlp_check_dt(now=None):
    current = now or datetime.now()
    scheduled = current.replace(hour=YTDLP_CHECK_HOUR, minute=0, second=0, microsecond=0)
    if current >= scheduled:
        scheduled += timedelta(days=1)
    return scheduled


def needs_scheduled_yt_dlp_check(last_checked_at, now=None):
    due_dt = get_last_due_yt_dlp_check_dt(now=now)
    try:
        return float(last_checked_at or 0.0) < due_dt.timestamp()
    except Exception:
        return True


def save_yt_dlp_update_state(latest_version, checked_at, check_error):
    with APP_CONFIG_LOCK:
        APP_CONFIG["yt_dlp_update_state"] = normalize_yt_dlp_update_state({
            "latest_version": latest_version,
            "checked_at": checked_at,
            "check_error": check_error,
        })
        write_app_config_locked()


def read_yt_dlp_update_state():
    with APP_CONFIG_LOCK:
        return normalize_yt_dlp_update_state(APP_CONFIG.get("yt_dlp_update_state"))


def is_yt_dlp_scheduler_started():
    return bool(YTDLP_SCHEDULER_STARTED)


def set_yt_dlp_scheduler_started(value):
    global YTDLP_SCHEDULER_STARTED
    YTDLP_SCHEDULER_STARTED = bool(value)


def fetch_yt_dlp_supported_services():
    return YTDLP_SERVICE.fetch_supported_services()


def get_yt_dlp_services_state(force=False):
    return YTDLP_SERVICE.get_services_state(force=force)


def get_yt_dlp_update_state_snapshot():
    return YTDLP_SERVICE.get_update_state_snapshot()


def refresh_yt_dlp_update_state(force=False):
    return YTDLP_SERVICE.refresh_update_state(force=force)


def yt_dlp_check_scheduler():
    while True:
        try:
            refresh_yt_dlp_update_state(force=False)
            next_check_dt = get_next_yt_dlp_check_dt()
            sleep_for = max(60.0, min((next_check_dt - datetime.now()).total_seconds(), 3600.0))
        except Exception:
            sleep_for = 300.0

        time.sleep(sleep_for)


def start_yt_dlp_scheduler_once():
    return YTDLP_SERVICE.start_scheduler_once()


def classify_yt_dlp_pip_progress(output_line):
    return YTDLP_SERVICE.classify_pip_progress(output_line)


def update_yt_dlp_package(progress_callback=None):
    return YTDLP_SERVICE.update_package(progress_callback=progress_callback)


def get_current_session_username():
    return auth_utils.get_current_session_username()


def get_current_session_role():
    return auth_utils.get_current_session_role()


def get_authenticated_user():
    return auth_utils.get_authenticated_user(get_user_by_username)


def is_authenticated():
    return bool(get_authenticated_user())


def is_admin_authenticated():
    user = get_authenticated_user()
    return bool(user and user.get("role") == "admin")


def get_current_username():
    user = get_authenticated_user()
    return str((user or {}).get("username") or "").strip()


def get_current_user_role():
    user = get_authenticated_user()
    return str((user or {}).get("role") or "").strip().lower()


safe_next_url = auth_utils.safe_next_url
set_ui_flash = auth_utils.set_ui_flash
pop_ui_flash = auth_utils.pop_ui_flash
wants_json_response = auth_utils.wants_json_response


def require_admin_json():
    return auth_utils.require_admin_json(is_admin_authenticated)


def require_authenticated_json():
    return auth_utils.require_authenticated_json(is_authenticated)


def require_authenticated_page(message="Zaloguj się, aby korzystać z aplikacji."):
    return auth_utils.require_authenticated_page(
        is_authenticated,
        wants_json_response,
        require_authenticated_json,
        set_ui_flash,
        message=message,
    )


def can_access_owner(owner_username):
    try:
        owner = normalize_username(owner_username)
    except Exception:
        return False
    return is_admin_authenticated() or owner == get_current_username()


def resolve_view_scope_username(raw_value, session_key):
    current_username = get_current_username()
    if not current_username:
        return ""

    if not is_admin_authenticated():
        session.pop(session_key, None)
        return current_username

    candidate = str(raw_value or session.get(session_key) or "all").strip().lower()
    if candidate in ("", "all", "*"):
        session[session_key] = "all"
        return ""

    try:
        selected_username = normalize_username(candidate)
    except Exception:
        session[session_key] = "all"
        return ""

    if not get_user_by_username(selected_username):
        session[session_key] = "all"
        return ""

    session[session_key] = selected_username
    return selected_username


def clamp_progress_percent(value):
    return MAINTENANCE_SERVICE.clamp_progress_percent(value)


def get_maintenance_task_status_kind(status):
    return MAINTENANCE_SERVICE.get_status_kind(status)


def serialize_maintenance_task_state(task_key, task):
    return MAINTENANCE_SERVICE.serialize_task_state(task_key, task)


def get_maintenance_task_snapshot(task_key):
    return MAINTENANCE_SERVICE.get_task_snapshot(task_key)


def get_all_maintenance_task_snapshots():
    return MAINTENANCE_SERVICE.get_all_task_snapshots()


def update_maintenance_task_state(task_key, **updates):
    return MAINTENANCE_SERVICE.update_task_state(task_key, **updates)


def finish_maintenance_task(task_key, ok, message):
    return MAINTENANCE_SERVICE.finish_task(task_key, ok, message)


def start_maintenance_task(task_key, title, worker):
    return MAINTENANCE_SERVICE.start_task(task_key, title, worker)


def get_settings_maintenance_state():
    return {
        "yt_dlp_state": get_yt_dlp_update_state_snapshot(),
        "ffmpeg_state": get_ffmpeg_update_state_snapshot(),
        "app_update_state": get_app_update_state_snapshot(),
        "dlna_package_state": get_dlna_package_state_snapshot(),
        "dlna_service_state": get_dlna_service_state(),
        "radio_backend_package_state": get_radio_backend_package_state(),
        "radio_backend_service_state": get_radio_backend_service_state(),
        "tasks": get_all_maintenance_task_snapshots(),
    }


def get_settings_page_state(include_user_rows=False):
    return PAGE_STATE_SERVICE.get_settings_page_state(include_user_rows=include_user_rows)


def get_dlna_page_state():
    return PAGE_STATE_SERVICE.get_dlna_page_state()


def render_page(page_title, active_page, content_template, **context):
    return PAGE_STATE_SERVICE.render_page(page_title, active_page, content_template, **context)


class DownloadCancelledError(Exception):
    pass


class DownloadInterruptedError(Exception):
    def __init__(self, action, message):
        super().__init__(message)
        self.action = str(action or "cancel").strip().lower() or "cancel"


def ydl_opts():
    return apply_ffmpeg_location({
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "http_headers": {
            "User-Agent": USER_AGENT,
        },
    })


def is_valid_http_url(url):
    return SOURCE_MEDIA_SERVICE.is_valid_http_url(url)


def safe_filename(value, default="file"):
    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    fallback = str(default or "file").strip() or "file"
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x1f]+", "", text)
    text = re.sub(r'[\\\\/:*?"<>|]+', "_", text)
    text = re.sub(r"\\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._ ")
    if not text:
        text = fallback

    base, ext = os.path.splitext(text)
    if ext == ".":
        base, ext = text.rstrip("."), ""
    base = (base or text or fallback).strip("._ ")
    ext = str(ext or "").strip()

    if not base:
        base = fallback
    if base.upper() in reserved_names:
        base = "_%s" % base

    max_length = 120
    allowed_base_length = max(8, max_length - len(ext))
    base = base[:allowed_base_length].rstrip("._ ")
    if not base:
        base = (fallback[:allowed_base_length] or "file").strip("._ ") or "file"
    if base.upper() in reserved_names:
        base = "_%s" % base

    result = ("%s%s" % (base, ext)).rstrip(" .")
    if not result:
        result = fallback
    if os.path.splitext(result)[0].upper() in reserved_names:
        result = "_%s" % result
    return result[:max_length] or fallback


def safe_basename(value):
    return os.path.basename(str(value or "").strip())


def guess_content_type(ext):
    ext = (ext or "").lower()
    if ext == "mp4":
        return "video/mp4"
    if ext == "mp3":
        return "audio/mpeg"
    if ext == "m3u8":
        return "application/vnd.apple.mpegurl"
    if ext == "webm":
        return "video/webm"
    if ext == "mkv":
        return "video/x-matroska"
    return "application/octet-stream"


def get_download_output_ext(item):
    return SOURCE_MEDIA_SERVICE.get_download_output_ext(item)


def get_download_intermediate_ext(item):
    return SOURCE_MEDIA_SERVICE.get_download_intermediate_ext(item)


def replace_filename_extension(filename, ext):
    return SOURCE_MEDIA_SERVICE.replace_filename_extension(filename, ext)


def build_download_basename(title, item):
    return SOURCE_MEDIA_SERVICE.build_download_basename(title, item)


def build_download_filename(title, item):
    return SOURCE_MEDIA_SERVICE.build_download_filename(title, item)


def build_intermediate_download_filename(title, item):
    return SOURCE_MEDIA_SERVICE.build_intermediate_download_filename(title, item)


def normalize_requested_download_filename(requested_filename, title, item):
    return SOURCE_MEDIA_SERVICE.normalize_requested_download_filename(requested_filename, title, item)


def make_label(fmt):
    return SOURCE_MEDIA_SERVICE.make_label(fmt)


def normalize_info(info):
    return SOURCE_MEDIA_SERVICE.normalize_info(info)


def filter_formats(info):
    return SOURCE_MEDIA_SERVICE.filter_formats(info)


def extract_video_data(page_url, force_refresh=False):
    return SOURCE_MEDIA_SERVICE.extract_video_data(page_url, force_refresh=force_refresh)


def extract_http_urls(raw_text):
    return SOURCE_MEDIA_SERVICE.extract_http_urls(raw_text)


def build_proxy_url(page_url, format_id):
    return SOURCE_MEDIA_SERVICE.build_proxy_url(page_url, format_id)


def build_download_url(page_url, format_id):
    return SOURCE_MEDIA_SERVICE.build_download_url(page_url, format_id)


def build_result_with_proxy_urls(result, request_root):
    return SOURCE_MEDIA_SERVICE.build_result_with_proxy_urls(result, request_root)


def find_format(result, format_id):
    return SOURCE_MEDIA_SERVICE.find_format(result, format_id)


def choose_best_source(items, preferred_media_kind="video", extractor_name=""):
    return SOURCE_MEDIA_SERVICE.choose_best_source(
        items,
        preferred_media_kind=preferred_media_kind,
        extractor_name=extractor_name,
    )


def format_bytes_text(num_bytes):
    return SOURCE_MEDIA_SERVICE.format_bytes_text(num_bytes)


def get_source_download_match_state(result, format_id, owner_username=None, target_filename_override=""):
    return SOURCE_MEDIA_SERVICE.get_source_download_match_state(
        result,
        format_id,
        owner_username=owner_username,
        target_filename_override=target_filename_override,
    )


def public_source_download_match_state(state):
    return SOURCE_MEDIA_SERVICE.public_source_download_match_state(state)


def finalize_overwritten_download(target_path, final_filename, replace_paths, owner_username=None, storage_kind="video"):
    return DOWNLOAD_PATH_SERVICE.finalize_overwritten_download(
        target_path,
        final_filename,
        replace_paths,
        owner_username=owner_username,
        storage_kind=storage_kind,
    )


def build_m3u(title, page_url, base_url, sources, only_format_id=None):
    return SOURCE_MEDIA_SERVICE.build_m3u(title, page_url, base_url, sources, only_format_id=only_format_id)


SOURCE_MEDIA_SERVICE = SourceMediaService(
    cache=CACHE,
    cache_ttl=CACHE_TTL,
    ytdlp_module=yt_dlp,
    ydl_opts_factory=ydl_opts,
    normalize_storage_kind=normalize_storage_kind,
    audio_download_target_codec=AUDIO_DOWNLOAD_TARGET_CODEC,
    safe_filename=safe_filename,
    get_current_username=get_current_username,
    is_admin_authenticated=is_admin_authenticated,
    default_admin_username=DEFAULT_ADMIN_USERNAME,
    normalize_username=normalize_username,
    get_user_storage_root=get_user_storage_root,
    is_temporary_download_artifact_name=is_temporary_download_artifact_name,
    get_relative_download_path=get_relative_download_path,
    format_relative_path_for_user=format_relative_path_for_user,
)


def set_mount_status(online, message):
    LAST_MOUNT_STATUS["online"] = bool(online)
    LAST_MOUNT_STATUS["message"] = str(message)
    LAST_MOUNT_STATUS["checked_at"] = time.time()


def get_storage_config_snapshot():
    return normalize_storage_config(get_config_snapshot().get("storage"))


def get_storage_backend_label(kind):
    return "Udział sieciowy" if normalize_storage_backend_kind(kind) == "network" else "Lokalny serwer"


def read_storage_runtime_access_state(root_path, *, require_mount=False):
    candidate = os.path.abspath(str(root_path or "").strip() or ".")
    result = {
        "path": candidate,
        "exists": os.path.isdir(candidate),
        "is_mount": os.path.ismount(candidate),
        "read_ok": False,
        "write_ok": False,
        "execute_ok": False,
        "message": "",
    }

    if require_mount and not result["is_mount"]:
        result["message"] = "Punkt montowania nie jest aktywny: %s" % candidate
        return result

    if not result["exists"]:
        result["message"] = "Katalog danych nie istnieje: %s" % candidate
        return result

    result["execute_ok"] = os.access(candidate, os.X_OK)
    result["write_ok"] = os.access(candidate, os.W_OK)
    try:
        os.listdir(candidate)
        result["read_ok"] = True
    except Exception as exc:
        result["message"] = "Katalog danych jest niedostępny: %s" % exc
        return result

    if not result["execute_ok"]:
        result["message"] = "Brak prawa wejścia do katalogu danych."
    elif not result["write_ok"]:
        result["message"] = "Katalog danych jest tylko do odczytu."
    else:
        result["message"] = "Dostęp do katalogu danych jest poprawny."
    return result


def check_download_dir_ready(storage_kind="video", owner_username=None):
    return DOWNLOAD_PATH_SERVICE.check_download_dir_ready(storage_kind=storage_kind, owner_username=owner_username)


def ensure_share_ready(auto_remount=True):
    global LAST_MOUNT_ATTEMPT_TS
    storage_config = get_storage_config_snapshot()
    active_backend = storage_config["active_backend"]
    active_root = get_storage_active_root(storage_config)

    if active_backend == "local":
        try:
            os.makedirs(active_root, exist_ok=True)
        except Exception as exc:
            message = "Nie udało się przygotować lokalnego katalogu danych: %s" % exc
            set_mount_status(False, message)
            return False, message

        ok, message = check_download_dir_ready("video")
        if ok:
            ready_message = "Lokalny katalog danych gotowy: %s" % active_root
            set_mount_status(True, ready_message)
            return True, ready_message
        set_mount_status(False, message)
        return False, message

    network_config = dict(storage_config.get("network") or {})
    network_mode = normalize_network_storage_mode(network_config.get("mode") or "managed_smb")
    if network_mode == "external_path":
        if not os.path.isdir(active_root):
            message = "Zewnętrzna ścieżka storage jest niedostępna: %s" % active_root
            set_mount_status(False, message)
            return False, message
        ok, message = check_download_dir_ready("video")
        if ok:
            ready_message = "Zewnętrzna ścieżka storage gotowa: %s" % active_root
            set_mount_status(True, ready_message)
            return True, ready_message
        set_mount_status(False, message)
        return False, message

    share_path = str(network_config.get("share") or "").strip()
    if not share_path:
        message = "Aktywny backend to udział sieciowy, ale nie skonfigurowano adresu udziału."
        set_mount_status(False, message)
        return False, message

    if os.path.ismount(active_root):
        ok, message = check_download_dir_ready("video")
        if ok:
            ready_message = "Udział sieciowy gotowy: %s" % active_root
            set_mount_status(True, ready_message)
            return True, ready_message
        set_mount_status(False, message)
        return False, message

    now = time.time()
    manual_unmounted = bool(network_config.get("manual_unmounted"))
    if auto_remount and not manual_unmounted and (now - LAST_MOUNT_ATTEMPT_TS >= MOUNT_RETRY_COOLDOWN):
        LAST_MOUNT_ATTEMPT_TS = now
        try:
            response = STORAGE_BACKEND_SERVICE.mount_network_storage(storage_config)
            update_storage_network_test_state(
                True,
                str(response.get("message") or "Udział sieciowy został zamontowany.").strip(),
                password_saved=storage_config.get("network", {}).get("password_saved"),
                last_test_signature=build_storage_network_signature(storage_config),
                manual_unmounted=False,
            )
        except Exception as exc:
            detail = str(exc or "").strip() or "Nie udało się zamontować udziału sieciowego."
            update_storage_network_test_state(
                False,
                detail,
                password_saved=storage_config.get("network", {}).get("password_saved"),
                last_test_signature=build_storage_network_signature(storage_config),
                manual_unmounted=False,
            )
            message = "Udział sieciowy offline. Automatyczne ponowne montowanie nie powiodło się.\n%s" % detail
            set_mount_status(False, message)
            return False, message

        ok, message = check_download_dir_ready("video")
        if ok:
            ready_message = "Udział sieciowy gotowy: %s" % active_root
            set_mount_status(True, ready_message)
            return True, ready_message
        set_mount_status(False, message)
        return False, message

    if manual_unmounted:
        message = "Udział sieciowy jest ręcznie odmontowany. Zamontuj go ponownie z panelu, gdy będzie potrzebny."
    else:
        message = "Udział sieciowy offline. Punkt montowania nie jest aktywny: %s" % active_root
    set_mount_status(False, message)
    return False, message


def get_mount_info(auto_remount=True, viewer_username=None, is_admin=None):
    storage_config = get_storage_config_snapshot()
    active_backend = storage_config["active_backend"]
    active_root = get_storage_active_root(storage_config)
    admin_view = is_admin_authenticated() if is_admin is None else bool(is_admin)
    username = str(viewer_username or get_current_username() or "").strip()
    video_dir = get_daily_download_dir(owner_username=username or DEFAULT_ADMIN_USERNAME)
    audio_dir = get_daily_download_dir(media_kind="audio", owner_username=username or DEFAULT_ADMIN_USERNAME)
    active_network_mode = normalize_network_storage_mode(storage_config.get("network", {}).get("mode") or "managed_smb")

    if auto_remount:
        online, message = ensure_share_ready(auto_remount=True)
        runtime_access = read_storage_runtime_access_state(
            active_root,
            require_mount=(active_backend == "network" and active_network_mode == "managed_smb"),
        )
    else:
        cached_checked_at = float(LAST_MOUNT_STATUS.get("checked_at") or 0.0)
        cached_online = bool(LAST_MOUNT_STATUS.get("online"))
        cached_message = str(LAST_MOUNT_STATUS.get("message") or "").strip()

        if cached_checked_at > 0:
            online = cached_online
            message = cached_message or "Używam ostatniego znanego stanu storage."
        elif active_backend == "local":
            online = True
            message = "Stan lokalnego storage zostanie zweryfikowany przy operacji na plikach lub w konfiguracji."
        elif active_network_mode == "external_path":
            online = False
            message = "Stan zewnętrznej ścieżki storage nie został jeszcze zweryfikowany."
        else:
            online = False
            message = "Stan udziału sieciowego nie został jeszcze zweryfikowany."

        runtime_access = {
            "path": os.path.abspath(str(active_root or "").strip() or "."),
            "exists": False,
            "is_mount": False,
            "read_ok": False,
            "write_ok": False,
            "execute_ok": False,
            "message": "Szczegóły dostępu do storage zostaną sprawdzone przy operacji na plikach lub w konfiguracji.",
        }

    public_message = message if admin_view else (
        "Przestrzeń użytkowników jest gotowa."
        if online else
        "Przestrzeń użytkowników jest teraz niedostępna."
    )
    payload = {
        "online": online,
        "message": public_message,
        "mount_point": active_root if admin_view else "",
        "download_root": get_download_root() if admin_view else "",
        "audio_download_root": get_audio_download_root() if admin_view else "",
        "download_dir": video_dir if admin_view else "video/%s" % get_daily_folder_name(),
        "audio_download_dir": audio_dir if admin_view else "audio/%s" % get_daily_folder_name(),
        "user_storage_root": get_user_storage_base_root() if admin_view else "",
        "owner_username": username,
        "checked_at": LAST_MOUNT_STATUS["checked_at"],
        "active_backend": active_backend,
        "active_backend_label": get_storage_backend_label(active_backend),
        "read_ok": bool(runtime_access.get("read_ok")),
        "write_ok": bool(runtime_access.get("write_ok")),
        "execute_ok": bool(runtime_access.get("execute_ok")),
        "is_mount": bool(runtime_access.get("is_mount")),
    }
    if admin_view:
        network_config = dict(storage_config.get("network") or {})
        network_mode = normalize_network_storage_mode(network_config.get("mode") or "managed_smb")
        network_configured = bool(network_config.get("mount_dir")) if network_mode == "external_path" else bool(
            network_config.get("share")
            and network_config.get("username")
            and network_config.get("credentials_file")
        )
        payload.update({
            "active_root": active_root,
            "local_root": storage_config["local"]["root"],
            "network_share": storage_config["network"]["share"],
            "network_subpath": storage_config["network"]["subpath"],
            "network_mount_dir": storage_config["network"]["mount_dir"],
            "network_mode": network_mode,
            "network_username": storage_config["network"]["username"],
            "network_domain": storage_config["network"]["domain"],
            "network_credentials_file": storage_config["network"]["credentials_file"],
            "network_password_saved": bool(storage_config["network"]["password_saved"]),
            "network_cifs_version": storage_config["network"]["cifs_version"],
            "network_iocharset": storage_config["network"]["iocharset"],
            "network_last_test_ok": bool(storage_config["network"]["last_test_ok"]),
            "network_last_test_message": storage_config["network"]["last_test_message"],
            "network_last_test_at": storage_config["network"]["last_test_at"],
            "network_last_test_at_text": format_ts(storage_config["network"]["last_test_at"]),
            "network_last_test_signature": storage_config["network"].get("last_test_signature") or "",
            "network_manual_unmounted": bool(storage_config["network"].get("manual_unmounted")),
            "network_configured": network_configured,
            "runtime_access_message": runtime_access.get("message") or "",
        })
    return payload


def ensure_download_dir_ready(storage_kind="video", owner_username=None):
    return DOWNLOAD_PATH_SERVICE.ensure_download_dir_ready(storage_kind=storage_kind, owner_username=owner_username)


def allocate_target_path(filename, media_kind="video", owner_username=None):
    return DOWNLOAD_PATH_SERVICE.allocate_target_path(filename, media_kind=media_kind, owner_username=owner_username)


DOWNLOAD_PATH_SERVICE = DownloadPathService(
    mount_point=MOUNT_POINT,
    get_user_storage_base_root=get_user_storage_base_root,
    get_user_storage_root=get_user_storage_root,
    normalize_username=normalize_username,
    normalize_storage_kind=normalize_storage_kind,
    get_current_username=get_current_username,
    default_admin_username=DEFAULT_ADMIN_USERNAME,
    ensure_share_ready=ensure_share_ready,
    safe_filename=safe_filename,
    get_daily_download_dir=get_daily_download_dir,
    is_temporary_download_artifact_name=is_temporary_download_artifact_name,
    cleanup_empty_download_dirs=cleanup_empty_download_dirs,
)


def update_job(job_id, **kwargs):
    return DOWNLOAD_JOBS_SERVICE.update_job(job_id, **kwargs)


def create_job(page_url, format_id, **kwargs):
    return DOWNLOAD_JOBS_SERVICE.create_job(page_url, format_id, **kwargs)


def build_upstream_headers(page_url, fmt):
    upstream_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Referer": page_url,
    }

    fmt_headers = fmt.get("http_headers") or {}
    if isinstance(fmt_headers, dict):
        for key, value in fmt_headers.items():
            if value:
                upstream_headers[str(key)] = str(value)

    return upstream_headers


def is_job_cancelled(job_id):
    with DOWNLOAD_LOCK:
        event = JOB_CANCEL_EVENTS.get(job_id)
    return bool(event and event.is_set())


def get_job_stop_action(job_id):
    with DOWNLOAD_LOCK:
        return str(JOB_STOP_REQUESTS.get(job_id) or "").strip().lower()


def get_user_download_slot_snapshot(owner_username, *, include_job_id=None):
    owner = normalize_username(owner_username or DEFAULT_ADMIN_USERNAME)

    with DOWNLOAD_LOCK:
        include_is_live_capture = False
        if include_job_id:
            current_job = DOWNLOAD_JOBS.get(str(include_job_id))
            include_is_live_capture = bool(current_job and current_job.get("is_live_capture"))
        same_owner_jobs = [
            dict(job)
            for job in DOWNLOAD_JOBS.values()
            if normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME) == owner
            and job.get("status") in ("queued", "downloading")
            and not bool(job.get("is_live_capture"))
        ]

    same_owner_jobs.sort(
        key=lambda item: (
            float(item.get("created_at") or 0.0),
            str(item.get("job_id") or ""),
        )
    )

    active_job_ids = [
        str(job.get("job_id") or "")
        for job in same_owner_jobs
        if job.get("status") == "downloading"
    ]
    eligible_job_ids = [
        str(job.get("job_id") or "")
        for job in same_owner_jobs[:MAX_PARALLEL_DOWNLOADS_PER_USER]
    ]

    return {
        "owner_username": owner,
        "active_count": len(active_job_ids),
        "active_job_ids": active_job_ids,
        "eligible_job_ids": eligible_job_ids,
        "can_start": bool(include_is_live_capture or (include_job_id and str(include_job_id) in eligible_job_ids)),
    }


def wait_for_user_download_slot(job_id, owner_username, *, poll_interval=0.5):
    owner = normalize_username(owner_username or DEFAULT_ADMIN_USERNAME)

    while True:
        if is_job_cancelled(job_id):
            stop_action = get_job_stop_action(job_id) or "cancel"
            if stop_action == "pause":
                raise DownloadInterruptedError("pause", "Pobieranie zostało wstrzymane podczas oczekiwania w kolejce.")
            raise DownloadInterruptedError("cancel", "Pobieranie anulowane podczas oczekiwania w kolejce.")

        with DOWNLOAD_LOCK:
            current_job = DOWNLOAD_JOBS.get(job_id)
            if not current_job:
                raise DownloadCancelledError("Zadanie zniknęło z kolejki przed rozpoczęciem pobierania.")
            current_status = str(current_job.get("status") or "")
            current_is_live_capture = bool(current_job.get("is_live_capture"))

        if current_is_live_capture:
            return

        if current_status != "queued":
            return

        slot_state = get_user_download_slot_snapshot(owner, include_job_id=job_id)
        if slot_state["can_start"]:
            return

        time.sleep(poll_interval)


def resolve_progress_component(path):
    cleaned_path = os.path.abspath(str(path or "")).strip()
    if not cleaned_path:
        return "__main__", True

    name = os.path.basename(cleaned_path)
    normalized_name = re.sub(r"(?i)\.part(?:-[^\\/]+)?(?:\.part)?$", "", name)
    normalized_name = re.sub(r"(?i)\.ytdl$", "", normalized_name)
    match = re.search(r"(?i)\.(temp|f[0-9a-z][0-9a-z-]*)\.[^.\\/]+$", normalized_name)
    if not match:
        return "__main__", True

    tag = str(match.group(1) or "").lower()
    if tag == "temp":
        return "__merge__", False
    return tag, True


def mark_job_cancel_requested(job_id):
    return DOWNLOAD_JOBS_SERVICE.mark_job_cancel_requested(job_id)


def mark_job_pause_requested(job_id):
    return DOWNLOAD_JOBS_SERVICE.mark_job_pause_requested(job_id)


def resume_job_download(job_id):
    return DOWNLOAD_JOBS_SERVICE.resume_job(job_id)


def retry_job_download(job_id):
    return DOWNLOAD_JOBS_SERVICE.retry_job(job_id)


def cleanup_job_cancel_handle(job_id):
    return DOWNLOAD_JOBS_SERVICE.cleanup_job_cancel_handle(job_id)


def purge_expired_jobs(now_ts=None):
    return DOWNLOAD_JOBS_SERVICE.purge_expired_jobs(now_ts=now_ts)


def download_worker(job_id):
    downloaded = 0
    total_bytes = None
    target_path = ""
    filename = ""
    temp_filename = ""
    relative_path = ""
    seen_paths = set()
    replace_paths = []
    overwrite_existing = False
    is_live_capture_requested = False
    progress_components = {}
    resume_target_path = ""

    try:
        def normalize_download_pathlike(value):
            if isinstance(value, os.PathLike):
                try:
                    return os.path.abspath(os.fspath(value))
                except Exception:
                    return ""
            if isinstance(value, bytes):
                try:
                    return os.path.abspath(os.fsdecode(value))
                except Exception:
                    return ""
            if isinstance(value, str):
                cleaned = value.strip()
                if not cleaned or cleaned == "-":
                    return ""
                try:
                    return os.path.abspath(cleaned)
                except Exception:
                    return ""
            return ""

        with DOWNLOAD_LOCK:
            job = DOWNLOAD_JOBS.get(job_id)
            if not job:
                return
            owner_username = normalize_username(job.get("owner_username") or DEFAULT_ADMIN_USERNAME)
            page_url = job["page_url"]
            format_id = job["format_id"]
            storage_kind = normalize_storage_kind(job.get("storage_kind") or "video")
            filename = str(job.get("planned_filename") or "")
            replace_paths = [str(path) for path in (job.get("replace_paths") or []) if path]
            overwrite_existing = bool(job.get("overwrite_existing"))
            is_live_capture_requested = bool(job.get("is_live_capture"))
            resume_target_path = str(job.get("filepath") or "").strip()
            if not resume_target_path:
                resume_target_path = str(
                    resolve_download_path(
                        job.get("relative_path"),
                        storage_kind,
                        owner_username=owner_username,
                    ) or ""
                ).strip()

        if is_job_cancelled(job_id):
            stop_action = get_job_stop_action(job_id) or "cancel"
            if stop_action == "pause":
                raise DownloadInterruptedError("pause", "Pobieranie zostało wstrzymane przed rozpoczęciem.")
            raise DownloadInterruptedError("cancel", "Pobieranie anulowane przed rozpoczęciem.")

        wait_for_user_download_slot(job_id, owner_username)

        if is_job_cancelled(job_id):
            stop_action = get_job_stop_action(job_id) or "cancel"
            if stop_action == "pause":
                raise DownloadInterruptedError("pause", "Pobieranie zostało wstrzymane przed przydzieleniem slotu.")
            raise DownloadInterruptedError("cancel", "Pobieranie anulowane przed przydzieleniem slotu.")

        ensure_download_dir_ready(storage_kind, owner_username)

        result = extract_video_data(page_url, force_refresh=True)
        fmt = find_format(result, format_id)
        if not fmt:
            fmt = SOURCE_MEDIA_SERVICE.find_format_by_signature(
                result,
                job.get("selection_signature") or {},
            )
        if not fmt:
            raise RuntimeError("Nie znaleziono wskazanego formatu.")

        is_live_capture = bool(
            is_live_capture_requested
            and result.get("is_live_stream")
            and result.get("supports_live_from_start")
        )

        if not filename:
            filename = build_download_filename(result.get("download_title") or result["title"], fmt)

        temp_filename = replace_filename_extension(filename, get_download_intermediate_ext(fmt))
        if storage_kind == "audio":
            ensure_ffmpeg_available_for_audio_conversion()

        candidate_resume_path = normalize_download_pathlike(resume_target_path)
        if candidate_resume_path:
            resume_artifact_exists = any(
                os.path.exists(root)
                or os.path.exists(root + ".part")
                or os.path.exists(root + ".ytdl")
                for root in get_download_artifact_roots(candidate_resume_path)
            )
            target_path = candidate_resume_path if resume_artifact_exists else ""
        else:
            target_path = ""

        if not target_path:
            target_path = allocate_target_path(temp_filename, media_kind=storage_kind, owner_username=owner_username)
        seen_paths.add(target_path)

        update_job(
            job_id,
            status="downloading",
            status_label=(
                "Nagrywanie live i konwersja"
                if is_live_capture and storage_kind == "audio"
                else "Nagrywanie live od początku"
                if is_live_capture
                else "Pobieranie i konwersja"
                if storage_kind == "audio"
                else "Pobieranie"
            ),
            started_at=time.time(),
            title=result["title"],
            label=fmt.get("label") or fmt.get("format_id") or "",
            filename=filename,
            filepath=target_path,
            relative_path=get_relative_download_path(target_path, storage_kind, owner_username),
            downloaded_bytes=0,
            total_bytes=None,
            progress_percent=0.0,
            error="",
            live_status=str(result.get("live_status") or ""),
            persist=True,
        )

        if is_job_cancelled(job_id):
            stop_action = get_job_stop_action(job_id) or "cancel"
            if stop_action == "pause":
                raise DownloadInterruptedError("pause", "Pobieranie zostało wstrzymane przed otwarciem strumienia.")
            raise DownloadInterruptedError("cancel", "Pobieranie anulowane przed otwarciem strumienia.")

        def progress_hook(status):
            nonlocal downloaded, total_bytes, target_path, relative_path, progress_components

            hook_filename = status.get("filename")
            hook_tmpfilename = status.get("tmpfilename")
            info_dict = status.get("info_dict") or {}

            for path in (hook_filename, hook_tmpfilename, info_dict.get("filepath")):
                normalized_seen_path = normalize_download_pathlike(path)
                if normalized_seen_path:
                    seen_paths.add(normalized_seen_path)

            if is_job_cancelled(job_id):
                stop_action = get_job_stop_action(job_id) or "cancel"
                if stop_action == "pause":
                    raise DownloadInterruptedError("pause", "Pobieranie zostało wstrzymane przez użytkownika.")
                raise DownloadInterruptedError("cancel", "Pobieranie zostało przerwane przez użytkownika.")

            status_name = status.get("status") or ""
            current_downloaded = int(status.get("downloaded_bytes") or 0)
            total_candidate = status.get("total_bytes") or status.get("total_bytes_estimate")
            current_total = int(total_candidate) if isinstance(total_candidate, (int, float)) else None

            current_filename = normalize_download_pathlike(hook_filename) or normalize_download_pathlike(info_dict.get("filepath")) or target_path
            if current_filename:
                target_path = current_filename
                relative_path = get_relative_download_path(target_path, storage_kind, owner_username)

            component_key, include_in_total = resolve_progress_component(
                hook_tmpfilename or hook_filename or info_dict.get("filepath") or target_path
            )
            component_state = progress_components.setdefault(component_key, {
                "downloaded": 0,
                "total": None,
                "include_in_total": include_in_total,
            })
            component_state["include_in_total"] = include_in_total
            component_state["downloaded"] = max(int(component_state.get("downloaded") or 0), current_downloaded)
            if current_total and current_total > 0:
                previous_total = component_state.get("total")
                component_state["total"] = max(int(previous_total or 0), current_total)
            elif status_name == "finished" and component_state.get("downloaded"):
                component_state["total"] = max(
                    int(component_state.get("total") or 0),
                    int(component_state.get("downloaded") or 0),
                )

            aggregate_downloaded = 0
            aggregate_total = 0
            has_known_total = False
            for component in progress_components.values():
                if not component.get("include_in_total", True):
                    continue
                part_downloaded = max(0, int(component.get("downloaded") or 0))
                part_total = component.get("total")
                if isinstance(part_total, int) and part_total > 0:
                    has_known_total = True
                    aggregate_total += part_total
                    aggregate_downloaded += min(part_downloaded, part_total)
                else:
                    aggregate_downloaded += part_downloaded

            downloaded = aggregate_downloaded or current_downloaded or downloaded
            total_bytes = aggregate_total if has_known_total and aggregate_total > 0 else None

            progress_percent = None
            if total_bytes and downloaded is not None:
                try:
                    progress_percent = max(0.0, min(100.0, (float(downloaded) * 100.0) / float(total_bytes)))
                except Exception:
                    progress_percent = None

            if status_name == "finished":
                update_job(
                    job_id,
                    downloaded_bytes=downloaded,
                    total_bytes=total_bytes,
                    progress_percent=100.0 if progress_percent is None else progress_percent,
                    processing_stage="",
                    relative_path=relative_path or get_relative_download_path(target_path, storage_kind, owner_username),
                )
                return

            if status_name == "downloading":
                update_job(
                    job_id,
                    downloaded_bytes=downloaded,
                    total_bytes=total_bytes,
                    progress_percent=progress_percent if progress_percent is not None else 0.0,
                    processing_stage="",
                    relative_path=relative_path or get_relative_download_path(target_path, storage_kind, owner_username),
                )

        def resolve_postprocessor_stage(postprocessor_name):
            normalized_name = str(postprocessor_name or "").strip().lower()
            if "extractaudio" in normalized_name:
                return "audio-conversion", "Konwersja audio"
            if "merger" in normalized_name:
                return (
                    "live-finalization",
                    "Finalizacja nagrania live" if is_live_capture else "Scalanie pliku",
                )
            if "movefilesafterdownload" in normalized_name or normalized_name.startswith("movefiles"):
                return "move-output", "Przenoszenie gotowego pliku"
            if (
                "fixup" in normalized_name
                or "metadata" in normalized_name
                or "embed" in normalized_name
                or "subtitles" in normalized_name
            ):
                return (
                    "finalizing",
                    "Finalizacja nagrania live" if is_live_capture else "Finalizacja pliku",
                )
            return (
                "processing",
                "Finalizacja nagrania live" if is_live_capture else "Przetwarzanie pliku",
            )

        def estimate_postprocess_input_bytes(info_dict):
            fallback_size = max(int(downloaded or 0), int(total_bytes or 0))
            candidate_paths = set()

            for path in (info_dict.get("filepath"), info_dict.get("__real_download")):
                normalized_candidate = normalize_download_pathlike(path)
                if normalized_candidate:
                    candidate_paths.add(normalized_candidate)

            for item in info_dict.get("requested_downloads") or []:
                if not isinstance(item, dict):
                    continue
                for path in (item.get("filepath"), item.get("tmpfilename")):
                    normalized_candidate = normalize_download_pathlike(path)
                    if normalized_candidate:
                        candidate_paths.add(normalized_candidate)

            total_on_disk = 0
            found_any = False
            for path in candidate_paths:
                try:
                    if os.path.isfile(path):
                        total_on_disk += int(os.path.getsize(path))
                        found_any = True
                except Exception:
                    continue

            if found_any:
                merged_size = max(total_on_disk, fallback_size)
                return merged_size, merged_size
            return fallback_size, fallback_size or None

        def postprocessor_hook(status):
            hook_status = str(status.get("status") or "").strip().lower()
            if hook_status not in {"started", "processing", "finished"}:
                return

            info_dict = status.get("info_dict") or {}
            stage_key, stage_label = resolve_postprocessor_stage(status.get("postprocessor"))
            processed_downloaded, processed_total = estimate_postprocess_input_bytes(info_dict)

            update_job(
                job_id,
                status="downloading",
                status_label=stage_label,
                downloaded_bytes=processed_downloaded,
                total_bytes=processed_total,
                progress_percent=None,
                processing_stage=stage_key,
                relative_path=relative_path or get_relative_download_path(target_path, storage_kind, owner_username),
            )

        selected_download_format = str(
            fmt.get("live_download_format") if is_live_capture else fmt.get("download_format") or format_id
        )

        ydl_download_opts = apply_ffmpeg_location({
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "http_headers": {
                "User-Agent": USER_AGENT,
            },
            "format": selected_download_format,
            "outtmpl": target_path,
            "noplaylist": True,
            "overwrites": False,
            "continuedl": True,
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
        })

        if is_live_capture:
            ydl_download_opts["live_from_start"] = True

        if storage_kind == "video" and not fmt.get("has_audio"):
            merge_ext = str(fmt.get("merge_ext") or fmt.get("ext") or "mp4").lower()
            if merge_ext in ("mp4", "mkv", "webm"):
                ydl_download_opts["merge_output_format"] = merge_ext
        elif storage_kind == "audio":
            ydl_download_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": AUDIO_DOWNLOAD_TARGET_CODEC,
                "preferredquality": AUDIO_DOWNLOAD_TARGET_QUALITY,
            }]

        with yt_dlp.YoutubeDL(ydl_download_opts) as ydl:
            download_info = ydl.extract_info(page_url, download=True)

        download_info = normalize_info(download_info)

        requested_downloads = download_info.get("requested_downloads") or []
        for item in requested_downloads:
            filepath = normalize_download_pathlike(item.get("filepath"))
            if filepath:
                seen_paths.add(filepath)

        final_path = normalize_download_pathlike(download_info.get("filepath"))
        if not final_path and requested_downloads:
            final_path = normalize_download_pathlike(requested_downloads[-1].get("filepath"))

        if final_path:
            target_path = final_path
            seen_paths.add(target_path)

        preferred_completed_path = os.path.abspath(
            os.path.join(
                get_daily_download_dir(media_kind=storage_kind, owner_username=owner_username),
                safe_filename(filename, default=os.path.basename(target_path) or "video.bin"),
            )
        )
        if (
            target_path
            and is_temporary_download_artifact_name(os.path.basename(target_path))
            and os.path.isfile(preferred_completed_path)
        ):
            target_path = preferred_completed_path
            seen_paths.add(target_path)

        relative_path = get_relative_download_path(target_path, storage_kind, owner_username)

        actual_size = 0
        try:
            actual_size = os.path.getsize(target_path)
        except Exception:
            actual_size = downloaded

        display_total_bytes = max(
            int(actual_size or 0),
            int(total_bytes or 0),
            int(downloaded or 0),
        )

        if actual_size < MIN_VALID_FILE_SIZE_BYTES:
            cleanup_download_artifacts(seen_paths)

            raise RuntimeError(
                "Pobrany plik został odrzucony: ma tylko %d bajtów, a minimum to %d bajtów." % (
                    actual_size,
                    MIN_VALID_FILE_SIZE_BYTES,
                )
            )

        if overwrite_existing:
            target_path = finalize_overwritten_download(target_path, filename, replace_paths, owner_username=owner_username, storage_kind=storage_kind)
            seen_paths.add(target_path)
            relative_path = get_relative_download_path(target_path, storage_kind, owner_username)

        update_job(
            job_id,
            status="completed",
            status_label="Nagranie live zakończone" if is_live_capture else "Ukończone",
            downloaded_bytes=display_total_bytes,
            total_bytes=display_total_bytes,
            progress_percent=100.0,
            finished_at=time.time(),
            filepath=target_path,
            filename=os.path.basename(target_path),
            relative_path=relative_path,
            processing_stage="",
            persist=True,
        )
        auto_dlna_collection_id = str(job.get("auto_dlna_collection_id") or "").strip()
        if auto_dlna_collection_id and relative_path:
            try:
                assignment_result = assign_file_to_dlna_collection(
                    storage_kind,
                    relative_path,
                    auto_dlna_collection_id,
                    sync_runtime=False,
                    return_details=True,
                )
                assigned_entry = dict((assignment_result or {}).get("entry") or {})
                assigned_collection = dict((assignment_result or {}).get("collection") or {})
                assigned_target_path = str((assignment_result or {}).get("target_path") or "").strip()
                assigned_relative_path = safe_relative_download_path(assigned_entry.get("current_relative_path") or "")
                assigned_filename = str(assigned_entry.get("file_name") or "").strip()
                if assigned_target_path or assigned_relative_path or assigned_filename:
                    if assigned_target_path:
                        target_path = assigned_target_path
                    if assigned_filename:
                        filename = assigned_filename
                    update_job(
                        job_id,
                        filepath=target_path,
                        filename=assigned_filename or os.path.basename(target_path) or filename,
                        dlna_current_relative_path=assigned_relative_path,
                        dlna_collection_id=str(assigned_entry.get("collection_id") or auto_dlna_collection_id or "").strip(),
                        dlna_collection_name=str(assigned_collection.get("name") or "").strip(),
                        persist=True,
                    )
                if assigned_relative_path:
                    mark_dlna_manual_sync_needed(
                        relative_path=assigned_relative_path,
                        item_label=os.path.basename(target_path) or filename or result["title"],
                    )
            except Exception as exc:
                update_job(
                    job_id,
                    error="Pobrano plik, ale nie udało się dodać go automatycznie do DLNA: %s" % exc,
                    persist=True,
                )

    except DownloadInterruptedError as exc:
        if exc.action == "pause":
            update_job(
                job_id,
                status="paused",
                status_label="Wstrzymane",
                error=str(exc),
                finished_at=time.time(),
                filepath=target_path,
                filename=filename,
                relative_path=relative_path or get_relative_download_path(target_path, storage_kind, owner_username),
                processing_stage="",
                persist=True,
            )
        else:
            cleanup_download_artifacts(seen_paths)

            update_job(
                job_id,
                status="canceled",
                status_label="Anulowano nagrywanie live" if is_live_capture_requested else "Anulowane",
                error=str(exc),
                finished_at=time.time(),
                progress_percent=0.0,
                downloaded_bytes=downloaded,
                filepath="",
                filename=filename,
                relative_path="",
                processing_stage="",
                persist=True,
            )

    except Exception as exc:
        cleanup_download_artifacts(seen_paths)

        update_job(
            job_id,
            status="failed",
            status_label="Niepowodzenie live" if is_live_capture_requested else "Niepowodzenie",
            error=str(exc),
            finished_at=time.time(),
            filepath="",
            relative_path="",
            processing_stage="",
            persist=True,
        )

    finally:
        cleanup_job_cancel_handle(job_id)


def get_jobs_snapshot():
    ensure_download_jobs_loaded()
    return DOWNLOAD_JOBS_SERVICE.get_jobs_snapshot()


FFMPEG_SERVICE = FfmpegMaintenanceService(
    resolve_ffmpeg_binary=resolve_ffmpeg_binary,
    get_ffmpeg_install_source_label=get_ffmpeg_install_source_label,
    get_installed_ffmpeg_version=get_installed_ffmpeg_version,
    load_ffmpeg_manifest=load_ffmpeg_manifest,
    read_update_state=read_ffmpeg_update_state,
    save_update_state=save_ffmpeg_update_state,
    needs_scheduled_check=needs_scheduled_ffmpeg_check,
    get_next_check_dt=get_next_ffmpeg_check_dt,
    fetch_latest_release_info=fetch_latest_ffmpeg_release_info,
    ffmpeg_tools_root=FFMPEG_TOOLS_ROOT,
    build_ffmpeg_candidate_dir=build_ffmpeg_candidate_dir,
    activate_ffmpeg_candidate_dir=activate_ffmpeg_candidate_dir,
    format_bytes_text=format_bytes_text,
    format_ts=format_ts,
    install_lock=FFMPEG_INSTALL_LOCK,
    scheduler_lock=FFMPEG_SCHEDULER_LOCK,
    is_scheduler_started=is_ffmpeg_scheduler_started,
    set_scheduler_started=set_ffmpeg_scheduler_started,
)

YTDLP_SERVICE = YtDlpMaintenanceService(
    importlib_metadata_module=importlib_metadata,
    ytdlp_module=yt_dlp,
    version_class=Version,
    invalid_version_exceptions=(InvalidVersion, TypeError, ValueError),
    user_agent=USER_AGENT,
    pip_package_spec=YTDLP_PIP_PACKAGE_SPEC,
    read_update_state=read_yt_dlp_update_state,
    save_update_state=save_yt_dlp_update_state,
    is_version_newer=is_version_newer,
    needs_scheduled_check=needs_scheduled_yt_dlp_check,
    get_next_check_dt=get_next_yt_dlp_check_dt,
    format_ts=format_ts,
    services_cache=YTDLP_SERVICES_CACHE,
    services_lock=YTDLP_SERVICES_LOCK,
    scheduler_lock=YTDLP_SCHEDULER_LOCK,
    is_scheduler_started=is_yt_dlp_scheduler_started,
    set_scheduler_started=set_yt_dlp_scheduler_started,
)


SYSTEM_SERVICE = SystemServiceHelper(
    dlna_log_file=DLNA_LOG_FILE,
    dlna_log_max_bytes=DLNA_LOG_MAX_BYTES,
    dlna_log_tail_read_bytes=DLNA_LOG_TAIL_READ_BYTES,
    dlna_log_browser_max_bytes=DLNA_LOG_BROWSER_MAX_BYTES,
    dlna_service_name=DLNA_SERVICE_NAME,
    format_ts=format_ts,
    format_duration=format_duration,
)

DOWNLOAD_JOBS_SERVICE = DownloadJobsService(
    jobs_store=DOWNLOAD_JOBS,
    cancel_events_store=JOB_CANCEL_EVENTS,
    stop_requests_store=JOB_STOP_REQUESTS,
    jobs_lock=DOWNLOAD_LOCK,
    default_admin_username=DEFAULT_ADMIN_USERNAME,
    normalize_username=normalize_username,
    normalize_storage_kind=normalize_storage_kind,
    get_current_username=get_current_username,
    is_admin_authenticated=is_admin_authenticated,
    get_completed_job_retention_seconds=get_completed_job_retention_seconds,
    write_download_jobs_locked=write_download_jobs_locked,
    download_worker=download_worker,
    can_access_owner=can_access_owner,
    safe_relative_download_path=safe_relative_download_path,
    parse_managed_relative_path=parse_managed_relative_path,
    resolve_download_path=resolve_download_path,
    cleanup_empty_download_dirs=cleanup_empty_download_dirs,
    cleanup_download_artifacts=cleanup_download_artifacts,
    ensure_share_ready=ensure_share_ready,
    sync_dlna_runtime_safe=lambda restart_service_if_active=True, force_full_rescan=False, include_pending_downloads=True: sync_dlna_runtime_safe(
        restart_service_if_active=restart_service_if_active,
        force_full_rescan=force_full_rescan,
        include_pending_downloads=include_pending_downloads,
    ),
    discard_dlna_manual_sync_path=discard_dlna_manual_sync_path,
    get_relative_download_path=get_relative_download_path,
    build_managed_file_url=build_managed_file_url,
    format_relative_path_for_user=format_relative_path_for_user,
)


def get_system_uptime_seconds():
    return SYSTEM_SERVICE.get_system_uptime_seconds()


def read_systemctl_service_info(service_name):
    return SYSTEM_SERVICE.read_systemctl_service_info(service_name)


def read_recent_service_journal_lines(service_name, lines=12):
    return SYSTEM_SERVICE.read_recent_service_journal_lines(service_name, lines=lines)


def read_recent_log_file_lines(path, lines=12):
    return SYSTEM_SERVICE.read_recent_log_file_lines(path, lines=lines)


def trim_text_log_file(path, max_bytes=DLNA_LOG_MAX_BYTES):
    return SYSTEM_SERVICE.trim_text_log_file(path, max_bytes=max_bytes)


def read_text_log_file_for_browser(path, max_bytes=DLNA_LOG_BROWSER_MAX_BYTES):
    return SYSTEM_SERVICE.read_text_log_file_for_browser(path, max_bytes=max_bytes)


def reset_dlna_log_file():
    ensure_dlna_runtime_dirs()
    try:
        remove_path_if_exists(DLNA_LOG_FILE)
    except Exception:
        pass


def select_service_log_excerpt(journal_lines):
    return SYSTEM_SERVICE.select_service_log_excerpt(journal_lines)


def get_generic_service_state(service_name):
    return SYSTEM_SERVICE.get_generic_service_state(service_name)


def get_flask_service_state():
    return SYSTEM_SERVICE.get_flask_service_state(SYSTEMD_SERVICE_NAME, APP_STARTED_AT_TS)


def schedule_systemd_service_restart(service_name):
    return SYSTEM_SERVICE.schedule_systemd_service_restart(service_name)


def schedule_flask_service_restart():
    return schedule_systemd_service_restart(SYSTEMD_SERVICE_NAME)


APP_UPDATE_SERVICE = AppUpdateService(
    project_root=APP_ROOT,
    version_file=VERSION_FILE,
    requirements_file=os.path.join(APP_ROOT, "requirements.txt"),
    venv_pip_path=PYTHON_VENV_PIP,
    requests_module=requests,
    format_ts=format_ts,
    is_linux_runtime=lambda: is_linux_runtime(),
    repo_owner=APP_REPO_OWNER,
    repo_name=APP_REPO_NAME,
    repo_branch=APP_REPO_BRANCH,
    read_update_state=read_app_update_state,
    save_update_state=save_app_update_state,
    schedule_service_restart=schedule_flask_service_restart,
)


def get_app_update_state_snapshot():
    return APP_UPDATE_SERVICE.get_update_state_snapshot()


def refresh_app_update_state(force=False):
    return APP_UPDATE_SERVICE.refresh_update_state(force=force)


def update_app_from_github(progress_callback=None):
    return APP_UPDATE_SERVICE.update_from_github(progress_callback=progress_callback)


JOB_VIEW_SERVICE = JobViewService(
    get_current_username=get_current_username,
    is_admin_authenticated=is_admin_authenticated,
    normalize_username=normalize_username,
    default_admin_username=DEFAULT_ADMIN_USERNAME,
)


def filter_jobs_for_viewer(jobs, scope_username=""):
    return JOB_VIEW_SERVICE.filter_jobs_for_viewer(jobs, scope_username=scope_username)


def delete_job_record(job_id):
    return DOWNLOAD_JOBS_SERVICE.delete_job(job_id)


def delete_managed_download_file(relative_path, storage_kind="video", owner_username=None):
    parsed = parse_managed_relative_path(relative_path)
    effective_storage_kind = normalize_storage_kind((parsed or {}).get("storage_kind") or storage_kind or "video")
    ok, message, status_code = DOWNLOAD_JOBS_SERVICE.delete_managed_file(
        relative_path,
        storage_kind=storage_kind,
        owner_username=owner_username,
    )
    if ok and effective_storage_kind == "audio":
        remove_radio_file_references(relative_path)
    return ok, message, status_code


def get_server_files(scope_username="", allow_auto_remount=False):
    return STORAGE_SERVICE.get_server_files(
        scope_username=scope_username,
        allow_auto_remount=allow_auto_remount,
    )


RADIO_STORE = radios_store_load_radio_store(
    RADIOS_FILE,
    normalize_username=normalize_username,
    parse_managed_relative_path=parse_managed_relative_path,
    canonicalize_relative_path=canonicalize_managed_relative_path,
)

CALENDAR_SERVICE = CalendarService(
    data_dir=DATA_DIR,
    requests_module=requests,
)


def write_radio_store_locked():
    radios_store_write_radio_store(RADIOS_FILE, RADIO_STORE)


def get_radio_store_snapshot():
    with RADIO_STORE_LOCK:
        return copy.deepcopy(RADIO_STORE)


RADIO_SERVICE = RadioService(
    radios_store=RADIO_STORE,
    radios_lock=RADIO_STORE_LOCK,
    write_radio_store_locked=write_radio_store_locked,
    get_radio_store_snapshot=get_radio_store_snapshot,
    normalize_username=normalize_username,
    parse_managed_relative_path=parse_managed_relative_path,
    build_managed_relative_path=build_managed_relative_path,
    safe_relative_download_path=safe_relative_download_path,
    resolve_download_path=resolve_download_path,
    get_relative_download_path=get_relative_download_path,
    build_managed_file_url=build_managed_file_url,
    format_relative_path_for_user=format_relative_path_for_user,
    get_current_username=get_current_username,
    is_admin_authenticated=is_admin_authenticated,
    get_users_snapshot=get_users_snapshot,
    get_server_files=get_server_files,
    get_mount_info=get_mount_info,
    safe_filename=safe_filename,
    get_daily_download_dir=get_daily_download_dir,
    ensure_share_ready=ensure_share_ready,
    format_ts=format_ts,
    build_calendar_placeholder_values=CALENDAR_SERVICE.build_erds_placeholder_values,
)

RADIO_RUNTIME_SERVICE = None


def get_radio_runtime_service():
    global RADIO_RUNTIME_SERVICE
    if RADIO_RUNTIME_SERVICE is None:
        RADIO_RUNTIME_SERVICE = RadioRuntimeService(
            radios_store=RADIO_STORE,
            radios_lock=RADIO_STORE_LOCK,
            write_radio_store_locked=write_radio_store_locked,
            get_radio_store_snapshot=get_radio_store_snapshot,
            normalize_username=normalize_username,
            resolve_download_path=resolve_download_path,
            format_ts=format_ts,
            app_service_user=APP_SERVICE_USER,
            app_service_group=APP_SERVICE_GROUP,
            app_root=APP_ROOT,
            runtime_root=RADIO_RUNTIME_ROOT,
            backend_service_name=RADIO_SERVICE_NAME,
            station_service_template_name=RADIO_STATION_SERVICE_TEMPLATE,
            requests_module=requests,
            is_linux_runtime=is_linux_runtime,
            get_generic_service_state=get_generic_service_state,
        run_systemctl_command=run_systemctl_command,
        run_systemctl_command_result=run_systemctl_command_result,
        systemd_quote_arg=systemd_quote_arg,
        build_erds_preview_lines=RADIO_SERVICE.build_erds_preview_lines,
        build_library_table_rows=RADIO_SERVICE.build_library_table_rows,
    )
    return RADIO_RUNTIME_SERVICE


def get_radio_backend_package_state():
    return get_radio_runtime_service().get_backend_package_state_snapshot()


def refresh_radio_backend_package_state(force=False):
    return get_radio_runtime_service().refresh_backend_package_state(force=force)


def install_or_update_radio_backend(progress_callback=None):
    with RADIO_INSTALL_LOCK:
        return get_radio_runtime_service().install_or_update_backend(progress_callback=progress_callback)


def get_radio_backend_service_state():
    return get_radio_runtime_service().get_backend_service_state()


def set_radio_backend_enabled(enabled):
    return get_radio_runtime_service().set_backend_enabled(enabled)


def restart_radio_backend_now():
    return get_radio_runtime_service().restart_backend_service_now()


def control_radio_station(owner_username, action):
    return get_radio_runtime_service().control_station(owner_username, action)


def sync_radio_runtime(restart_backend_if_active=False, restart_active_stations=False):
    return get_radio_runtime_service().sync_runtime(
        restart_backend_if_active=restart_backend_if_active,
        restart_active_stations=restart_active_stations,
    )


def sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False):
    return get_radio_runtime_service().sync_runtime_safe(
        restart_backend_if_active=restart_backend_if_active,
        restart_active_stations=restart_active_stations,
    )


def read_radio_log_file_for_browser(path, max_bytes=RADIO_LOG_BROWSER_MAX_BYTES):
    return get_radio_runtime_service().read_text_log_file_for_browser(path, max_bytes=max_bytes)


def get_radio_backend_log_file():
    return get_radio_runtime_service().get_backend_log_file()


def get_radio_station_log_file(owner_username):
    return get_radio_runtime_service().get_station_log_file(owner_username)


def build_config_export_bundle():
    return build_named_config_export_bundle()


def build_named_config_export_bundle(filename_prefix="flask-downloader-config", note=""):
    export_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_prefix = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(filename_prefix or "flask-downloader-config")).strip("-")
    export_name = "%s-%s.zip" % ((safe_prefix or "flask-downloader-config"), export_timestamp)
    archive_paths = [
        ("data/config.json", CONFIG_FILE),
        ("data/jobs.json", JOBS_FILE),
        ("data/users.json", USERS_FILE),
        ("data/radios.json", RADIOS_FILE),
    ]
    missing_files = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for archive_name, source_path in archive_paths:
            if os.path.isfile(source_path):
                bundle.write(source_path, arcname=archive_name)
            else:
                missing_files.append(archive_name)
        manifest = {
            "created_at": datetime.now().isoformat(),
            "project": "VLC Stream Extractor",
            "included_files": [archive_name for archive_name, source_path in archive_paths if os.path.isfile(source_path)],
            "missing_files": missing_files,
            "note": str(note or "Eksport zawiera tylko bieżące store'y aplikacji. Sekrety z .env nie są dołączane automatycznie."),
        }
        bundle.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    content = buffer.getvalue()
    backups_dir = os.path.join(PROJECT_ROOT, "backups")
    os.makedirs(backups_dir, exist_ok=True)
    saved_path = os.path.join(backups_dir, export_name)
    with open(saved_path, "wb") as fh:
        fh.write(content)
    return {
        "filename": export_name,
        "content": content,
        "saved_path": saved_path,
        "missing_files": missing_files,
    }


def normalize_imported_app_config(raw):
    if not isinstance(raw, dict):
        raise ValueError("Plik data/config.json w archiwum musi zawierać obiekt JSON.")

    payload = default_app_config()
    payload["user_storage_root"] = normalize_user_storage_root(raw.get("user_storage_root", payload["user_storage_root"]))
    try:
        payload["user_storage_layout_version"] = max(1, int(raw.get("user_storage_layout_version") or 1))
    except Exception:
        payload["user_storage_layout_version"] = 1
    payload["storage"] = normalize_storage_config(raw.get("storage", payload.get("storage")))
    payload["download_root"] = normalize_download_root(raw.get("download_root", payload["download_root"]))
    payload["audio_download_root"] = normalize_audio_download_root(raw.get("audio_download_root", payload["audio_download_root"]))
    payload["job_retention_days"] = normalize_retention_days(raw.get("job_retention_days", payload["job_retention_days"]))
    payload["yt_dlp_update_state"] = normalize_yt_dlp_update_state(raw.get("yt_dlp_update_state", payload["yt_dlp_update_state"]))
    payload["ffmpeg_update_state"] = normalize_ffmpeg_update_state(raw.get("ffmpeg_update_state", payload["ffmpeg_update_state"]))
    payload["dlna_update_state"] = normalize_dlna_update_state(raw.get("dlna_update_state", payload["dlna_update_state"]))
    payload["dlna"] = normalize_dlna_config(raw.get("dlna", payload["dlna"]))
    return hydrate_storage_paths(payload)


def normalize_imported_jobs_payload(raw):
    if not isinstance(raw, list):
        raise ValueError("Plik data/jobs.json w archiwum musi zawierać listę zadań.")

    normalized_jobs = []
    jobs_by_id = {}
    seen_job_ids = set()

    for item in raw:
        if not isinstance(item, dict):
            continue
        job = normalize_saved_job_record(item)
        job_id = str(job.get("job_id") or "").strip()
        if not job_id or job_id in seen_job_ids:
            continue
        seen_job_ids.add(job_id)
        if job.get("status") in ("queued", "downloading", "paused"):
            job["status"] = "failed"
            job["status_label"] = "Niepowodzenie"
            if not str(job.get("error") or "").strip():
                job["error"] = "Zadanie zostało przywrócone z importu konfiguracji i oznaczone jako nieukończone."
            job["finished_at"] = float(job.get("finished_at") or time.time())
            job["filepath"] = ""
            job["relative_path"] = ""
        normalized_jobs.append(job)
        jobs_by_id[job_id] = copy.deepcopy(job)

    return {
        "payload": [serialize_job_for_storage(job) for job in normalized_jobs],
        "jobs_map": jobs_by_id,
    }


def _normalize_zip_member_name(value):
    return str(value or "").replace("\\", "/").lstrip("./").strip().lower()


def _load_json_from_bundle(bundle, required_name):
    normalized_required_name = _normalize_zip_member_name(required_name)
    candidates = {}
    for member_name in bundle.namelist():
        normalized_name = _normalize_zip_member_name(member_name)
        if normalized_name:
            candidates[normalized_name] = member_name

    selected_member_name = None
    if normalized_required_name in candidates:
        selected_member_name = candidates[normalized_required_name]
    else:
        basename = normalized_required_name.split("/")[-1]
        for normalized_name, member_name in candidates.items():
            if normalized_name.endswith("/" + basename) or normalized_name == basename:
                selected_member_name = member_name
                break

    if not selected_member_name:
        raise ValueError("W archiwum brakuje pliku %s." % required_name)

    try:
        raw_content = bundle.read(selected_member_name)
    except KeyError as exc:
        raise ValueError("Nie udało się odczytać pliku %s z archiwum." % required_name) from exc

    try:
        return json.loads(raw_content.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Plik %s nie zawiera poprawnego JSON-a UTF-8." % required_name) from exc


def _load_normalized_store_from_temp(raw_payload, loader, *, temp_suffix=".json"):
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=temp_suffix, delete=False) as temp_file:
            json.dump(raw_payload, temp_file, ensure_ascii=False, indent=2)
            temp_path = temp_file.name
        return loader(temp_path)
    finally:
        if temp_path and os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def restore_config_bundle(bundle_bytes):
    raw_content = bundle_bytes if isinstance(bundle_bytes, (bytes, bytearray)) else b""
    if not raw_content:
        raise ValueError("Nie przesłano archiwum ZIP z konfiguracją.")

    with DOWNLOAD_LOCK:
        active_jobs = [
            job for job in DOWNLOAD_JOBS.values()
            if str((job or {}).get("status") or "").strip().lower() in ("queued", "downloading", "paused")
        ]
    if active_jobs:
        raise ValueError("Najpierw zakończ lub anuluj aktywne zadania pobierania, a dopiero potem przywróć konfigurację.")

    try:
        bundle = zipfile.ZipFile(io.BytesIO(raw_content), "r")
    except Exception as exc:
        raise ValueError("Przesłany plik nie jest poprawnym archiwum ZIP.") from exc

    with bundle:
        raw_config = _load_json_from_bundle(bundle, "data/config.json")
        raw_jobs = _load_json_from_bundle(bundle, "data/jobs.json")
        raw_users = _load_json_from_bundle(bundle, "data/users.json")
        raw_radios = _load_json_from_bundle(bundle, "data/radios.json")

    normalized_config = normalize_imported_app_config(raw_config)
    normalized_jobs = normalize_imported_jobs_payload(raw_jobs)
    normalized_user_store = _load_normalized_store_from_temp(
        raw_users,
        lambda temp_path: users_store_load_user_store(temp_path, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD),
    )
    normalized_radio_store = _load_normalized_store_from_temp(
        raw_radios,
        lambda temp_path: radios_store_load_radio_store(
            temp_path,
            normalize_username=normalize_username,
            parse_managed_relative_path=parse_managed_relative_path,
            canonicalize_relative_path=canonicalize_managed_relative_path,
        ),
    )

    previous_config = get_config_snapshot()
    previous_user_store = get_user_store_snapshot()
    previous_radio_store = get_radio_store_snapshot()
    with DOWNLOAD_LOCK:
        previous_jobs_payload = [serialize_job_for_storage(job) for job in DOWNLOAD_JOBS.values()]
        previous_jobs_map = copy.deepcopy(DOWNLOAD_JOBS)

    backup_bundle = build_named_config_export_bundle(
        filename_prefix="flask-downloader-before-restore",
        note="Automatyczny backup store'ów utworzony tuż przed przywróceniem konfiguracji z ZIP-a.",
    )

    try:
        config_store_write_app_config(CONFIG_FILE, normalized_config)
        jobs_store_write_jobs_payload(JOBS_FILE, normalized_jobs["payload"])
        users_store_write_user_store(USERS_FILE, normalized_user_store)
        radios_store_write_radio_store(RADIOS_FILE, normalized_radio_store)
    except Exception:
        try:
            config_store_write_app_config(CONFIG_FILE, previous_config)
            jobs_store_write_jobs_payload(JOBS_FILE, previous_jobs_payload)
            users_store_write_user_store(USERS_FILE, previous_user_store)
            radios_store_write_radio_store(RADIOS_FILE, previous_radio_store)
        except Exception:
            pass
        raise

    with APP_CONFIG_LOCK:
        APP_CONFIG.clear()
        APP_CONFIG.update(copy.deepcopy(normalized_config))
    with USER_STORE_LOCK:
        USER_STORE.clear()
        USER_STORE.update(copy.deepcopy(normalized_user_store))
    with DOWNLOAD_LOCK:
        DOWNLOAD_JOBS.clear()
        DOWNLOAD_JOBS.update(copy.deepcopy(normalized_jobs["jobs_map"]))
    with RADIO_STORE_LOCK:
        RADIO_STORE.clear()
        RADIO_STORE.update(copy.deepcopy(normalized_radio_store))

    warnings = []
    try:
        storage_ok, storage_message = ensure_share_ready(auto_remount=True)
        if not storage_ok and storage_message:
            warnings.append(str(storage_message).strip())
    except Exception as exc:
        warnings.append("Nie udało się sprawdzić backendu danych po imporcie: %s" % exc)

    try:
        sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
    except Exception as exc:
        warnings.append("Konfiguracja została przywrócona, ale synchronizacja DLNA zgłosiła błąd: %s" % exc)

    try:
        sync_radio_runtime_safe(restart_backend_if_active=True, restart_active_stations=True)
    except Exception as exc:
        warnings.append("Konfiguracja została przywrócona, ale synchronizacja radia zgłosiła błąd: %s" % exc)

    return {
        "backup_bundle": backup_bundle,
        "imported_files": [
            "data/config.json",
            "data/jobs.json",
            "data/users.json",
            "data/radios.json",
        ],
        "job_count": len(normalized_jobs["jobs_map"]),
        "user_count": len(list((normalized_user_store or {}).get("users") or [])),
        "station_count": len(dict((normalized_radio_store or {}).get("stations") or {})),
        "warnings": warnings,
    }


def start_radio_package_scheduler_once():
    return get_radio_runtime_service().start_package_scheduler_once()


def start_radio_metadata_scheduler_once():
    return get_radio_runtime_service().start_metadata_scheduler_once()


def get_radio_page_state(owner_username=""):
    page_state = RADIO_SERVICE.get_page_state(owner_username=owner_username)
    scope_username = str(page_state.get("scope_username") or "").strip()
    station_runtime_state = get_radio_runtime_service().get_station_runtime_state(scope_username) if scope_username else {}
    page_state["backend_package_state"] = get_radio_backend_package_state()
    page_state["backend_service_state"] = get_radio_backend_service_state()
    page_state["station_runtime_state"] = station_runtime_state
    page_state["backend_install_task"] = get_maintenance_task_snapshot("radio_backend_install")
    if page_state.get("station_exists") and page_state.get("station"):
        listener_count = int(station_runtime_state.get("listeners") or 0)
        station_payload = page_state.get("station") or {}
        station_stats = dict(station_payload.get("stats") or {})
        station_stats["listener_record"] = int(
            station_runtime_state.get("listener_record")
            or station_stats.get("listener_record")
            or 0
        )
        station_payload["stats"] = station_stats
        page_state["station"] = station_payload
        page_state["erds_preview_lines"] = RADIO_SERVICE.build_erds_preview_lines(
            station_payload,
            listener_count=listener_count,
            runtime_context=station_runtime_state,
            global_config=page_state.get("global_config") or {},
        )
        summary = dict(page_state.get("summary") or {})
        summary["listeners"] = listener_count
        summary["station_service_active"] = bool(station_runtime_state.get("service_active"))
        summary["mount_connected"] = bool(station_runtime_state.get("mount_connected"))
        summary["current_erds_text"] = str(station_runtime_state.get("current_erds_text") or "")
        summary["current_song"] = str(station_runtime_state.get("current_song") or "")
        summary["current_program_name"] = str(station_runtime_state.get("current_program_name") or "")
        summary["current_dj_name"] = str(station_runtime_state.get("current_dj_name") or "")
        summary["listener_record"] = int(station_runtime_state.get("listener_record") or 0)
        summary["max_listeners"] = int(station_runtime_state.get("max_listeners") or 0)
        summary["playable_music_count"] = int(station_runtime_state.get("playable_music_count") or 0)
        summary["playable_insert_count"] = int(station_runtime_state.get("playable_insert_count") or 0)
        page_state["summary"] = summary
    return page_state


def create_radio_station(owner_username):
    result = RADIO_SERVICE.create_station(owner_username)
    sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return result


def update_radio_station(owner_username, payload):
    previous_runtime_state = get_radio_runtime_service().get_station_runtime_state(owner_username)
    result = RADIO_SERVICE.update_station(owner_username, payload)
    restart_station = bool(payload.get("restart_runtime")) or any(
        key in (payload or {})
        for key in ("enabled", "autostart", "name", "description", "genre", "slug", "mount_name", "stream", "source", "live", "autopilot")
    )
    sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    if not bool(result.get("enabled", False)):
        get_radio_runtime_service().stop_and_disable_station(owner_username)
    elif restart_station and previous_runtime_state.get("service_active"):
        try:
            get_radio_runtime_service().control_station(owner_username, "restart")
        except Exception:
            pass
    else:
        try:
            get_radio_runtime_service().metadata_tick()
        except Exception:
            pass
    return result


def delete_radio_station(owner_username):
    get_radio_runtime_service().stop_and_disable_station(owner_username)
    result = RADIO_SERVICE.delete_station(owner_username)
    sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return result


def update_radio_global_settings(payload):
    result = RADIO_SERVICE.update_global_settings(payload)
    sync_radio_runtime_safe(restart_backend_if_active=True, restart_active_stations=True)
    return result


def add_radio_library_paths(owner_username, relative_paths, source_type="download"):
    result = RADIO_SERVICE.add_library_paths(owner_username, relative_paths, source_type=source_type)
    sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return result


def bulk_save_radio_library(owner_username, mode="manual", rows=None):
    result = RADIO_SERVICE.bulk_save_library(owner_username, mode=mode, rows=rows)
    sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return result


def update_radio_library_item(owner_username, item_id, display_title="", role="music", enabled=True):
    result = RADIO_SERVICE.update_library_item(
        owner_username,
        item_id,
        display_title=display_title,
        role=role,
        enabled=enabled,
    )
    sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return result


def remove_radio_library_item(owner_username, item_id):
    result = RADIO_SERVICE.remove_library_item(owner_username, item_id)
    sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return result


def store_uploaded_radio_audio(owner_username, file_storage):
    result = RADIO_SERVICE.store_uploaded_audio(owner_username, file_storage)
    sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return result


def store_uploaded_radio_audio_batch(owner_username, file_storages):
    result = RADIO_SERVICE.store_uploaded_audio_batch(owner_username, file_storages)
    sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return result


def queue_radio_station_track(owner_username, relative_path, queue_mode="queue_next"):
    result = RADIO_SERVICE.enqueue_manual_track(owner_username, relative_path, queue_mode=queue_mode)
    runtime_service = get_radio_runtime_service()
    runtime_service.refresh_station_queue_files(owner_username)
    if str(queue_mode or "").strip().lower() == "play_now":
        station_state = runtime_service.get_station_runtime_state(owner_username)
        if station_state.get("service_active") and not station_state.get("live_connected"):
            try:
                runtime_service.skip_station_track(owner_username)
            except Exception:
                pass
    return result


def cleanup_missing_radio_library_items(owner_username=None):
    changed = RADIO_SERVICE.cleanup_missing_library_items(owner_username)
    if changed:
        sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return changed


def remove_radio_file_references(relative_path):
    changed = RADIO_SERVICE.remove_file_references(relative_path)
    if changed:
        sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return changed


def rename_radio_station_owner(previous_username, next_username):
    get_radio_runtime_service().stop_and_disable_station(previous_username)
    changed = RADIO_SERVICE.rename_user_station(previous_username, next_username)
    if changed:
        sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return changed


def delete_radio_station_for_user(username):
    get_radio_runtime_service().stop_and_disable_station(username)
    changed = RADIO_SERVICE.delete_user_station(username)
    if changed:
        sync_radio_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
    return changed


def gerbera_namespace_for(node):
    if node is None:
        return GERBERA_CONFIG_NS
    tag = str(getattr(node, "tag", "") or "")
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0] or GERBERA_CONFIG_NS
    return GERBERA_CONFIG_NS


def gerbera_tag(name, namespace=None):
    ns = str(namespace or "").strip() or GERBERA_CONFIG_NS
    return "{%s}%s" % (ns, name)


def gerbera_sub_element(node, name):
    return ET.SubElement(node, gerbera_tag(name, gerbera_namespace_for(node)))


def gerbera_find(node, *path):
    current = node
    for item in path:
        if current is None:
            return None
        current = current.find(gerbera_tag(item, gerbera_namespace_for(current)))
    return current


def gerbera_ensure(node, *path):
    current = node
    for item in path:
        child = current.find(gerbera_tag(item, gerbera_namespace_for(current)))
        if child is None:
            child = gerbera_sub_element(current, item)
        current = child
    return current


def clear_xml_children(node):
    for child in list(node):
        node.remove(child)


def ensure_dlna_export_root_directory():
    if os.name != "nt" and os.path.islink(DLNA_EXPORT_ROOT):
        os.unlink(DLNA_EXPORT_ROOT)
    ensure_directory(DLNA_EXPORT_ROOT)


def cleanup_dlna_legacy_export_root():
    legacy_root = os.path.abspath(DLNA_LEGACY_EXPORT_ROOT)
    current_root = os.path.abspath(DLNA_EXPORT_ROOT)
    if legacy_root == current_root:
        return
    if not os.path.lexists(legacy_root):
        return
    remove_path_if_exists(legacy_root)


def build_dlna_user_root_id(username):
    return "user:%s" % normalize_username(username)


def parse_dlna_user_root_username(root_id):
    text = str(root_id or "").strip()
    if not text.startswith("user:"):
        return ""
    try:
        return normalize_username(text.split(":", 1)[1])
    except Exception:
        return ""


def get_dlna_client_assigned_usernames(client):
    valid_usernames = {
        str(item.get("username") or "").strip()
        for item in (get_users_snapshot() or [])
        if str(item.get("username") or "").strip()
    }
    result = []
    seen = set()
    for raw_value in (client or {}).get("usernames") or []:
        try:
            username = normalize_username(raw_value)
        except Exception:
            continue
        if not username or username in seen or username not in valid_usernames:
            continue
        seen.add(username)
        result.append(username)
    return result


def get_dlna_referenced_usernames(dlna_config=None):
    config = dlna_config or get_dlna_config_snapshot()
    usernames = []
    seen = set()
    for item in config.get("collections") or []:
        username = normalize_username(item.get("owner_username") or DEFAULT_ADMIN_USERNAME)
        if username in seen:
            continue
        seen.add(username)
        usernames.append(username)
    return usernames


def build_dlna_client_visible_root_ids(client, dlna_config=None):
    return set(get_dlna_client_visible_collection_ids(client, dlna_config))


def build_dlna_root_entry_map(dlna_config=None):
    config = dlna_config or get_dlna_config_snapshot()
    result = {}
    used_names = set()

    def add_root(root_id, title, kind, username="", dir_name_override=""):
        base_name = dlna_safe_dir_segment(
            dir_name_override or title,
            default="kolekcja" if kind == "collection" else "uzytkownik",
        )
        candidate = base_name
        suffix = 1
        while candidate.lower() in used_names:
            suffix += 1
            candidate = "%s (%s)" % (base_name, suffix)
        used_names.add(candidate.lower())
        result[root_id] = {
            "id": root_id,
            "kind": kind,
            "title": str(title or candidate),
            "dir_name": candidate,
            "username": str(username or "").strip(),
        }

    for item in config.get("collections") or []:
        add_root(
            item["id"],
            item["name"],
            "collection",
            username=item.get("owner_username") or DEFAULT_ADMIN_USERNAME,
            dir_name_override=item.get("folder_name") or item["name"],
        )
    return result


def build_dlna_root_layout_map(root_entry_map):
    layout_map = {}
    for root_id, entry in (root_entry_map or {}).items():
        dir_name = str((entry or {}).get("dir_name") or "").strip()
        if not dir_name:
            continue
        layout_map[dir_name] = {
            "id": str(root_id or ""),
            "kind": str((entry or {}).get("kind") or "collection"),
            "title": str((entry or {}).get("title") or dir_name),
            "username": str((entry or {}).get("username") or "").strip(),
        }
    return layout_map


def build_dlna_dynamic_container_specs(dlna_config, collection_dir_map):
    config = dlna_config or get_dlna_config_snapshot()
    root_entry_map = build_dlna_root_entry_map(config)
    layout_map = build_dlna_root_layout_map(root_entry_map)
    enabled_clients = [item for item in (config.get("clients") or []) if item.get("enabled", True)]
    relevant_root_ids = set()

    if enabled_clients:
        for client in enabled_clients:
            relevant_root_ids.update(build_dlna_client_visible_root_ids(client, config))
    else:
        relevant_root_ids.update(root_entry_map.keys())

    specs = []
    for root_id, entry in (root_entry_map or {}).items():
        dir_name = str((entry or {}).get("dir_name") or "").strip()
        if not dir_name:
            continue
        if relevant_root_ids and root_id not in relevant_root_ids:
            continue
        physical_dir = os.path.join(DLNA_EXPORT_ROOT, str(dir_name)).replace("\\", "/").rstrip("/") + "/"
        filter_path = physical_dir.replace('"', '\\"')
        specs.append({
            "collection_id": root_id,
            "location": "/" + str(dir_name),
            "title": str((layout_map.get(str(dir_name)) or {}).get("title") or dir_name),
            "filter": 'upnp:class derivedfrom "object.item" and location contains "%s"' % filter_path,
        })

    specs.sort(key=lambda item: (build_natural_sort_key(item["title"]), build_natural_sort_key(item["location"])))
    return specs


def build_dlna_virtual_layout_script(root_layout_map):
    encoded_root = json.dumps(DLNA_EXPORT_ROOT.replace("\\", "/"), ensure_ascii=False)
    encoded_layout = json.dumps(root_layout_map or {}, ensure_ascii=False, indent=2, sort_keys=True)
    return """var DLNA_EXPORT_ROOT = %s;
var DLNA_ROOT_LAYOUT = %s;

function dlnaNormalizePath(value) {
  return String(value || '').replace(/\\\\/g, '/').replace(/\\/+/g, '/').replace(/\\/$/, '');
}

function dlnaBasename(value) {
  var normalized = dlnaNormalizePath(value);
  if (!normalized) {
    return '';
  }
  var parts = normalized.split('/');
  return parts.length ? parts[parts.length - 1] : normalized;
}

function dlnaGetRelativeParts(location, rootPath) {
  var normalizedLocation = dlnaNormalizePath(location);
  var normalizedRoot = dlnaNormalizePath(rootPath || DLNA_EXPORT_ROOT);
  if (normalizedRoot && normalizedLocation.indexOf(normalizedRoot + '/') === 0) {
    normalizedLocation = normalizedLocation.substring(normalizedRoot.length + 1);
  }
  var rawParts = normalizedLocation.split('/');
  var result = [];
  for (var idx = 0; idx < rawParts.length; idx++) {
    if (rawParts[idx]) {
      result.push(rawParts[idx]);
    }
  }
  return result;
}

function dlnaGetRootMeta(parts) {
  var rootKey = parts.length ? parts[0] : '';
  if (rootKey && DLNA_ROOT_LAYOUT[rootKey]) {
    return DLNA_ROOT_LAYOUT[rootKey];
  }
  return { title: rootKey || 'Pozostałe', kind: 'collection' };
}

function dlnaBuildContainerSortKey(title, depth) {
  var normalizedTitle = String(title || '');
  if (depth >= 2 && normalizedTitle === 'Wszystkie Pliki') {
    return '0000_Wszystkie Pliki';
  }
  if (depth >= 2 && /^\\d{4}-\\d{2}-\\d{2}$/.test(normalizedTitle)) {
    return '1000_' + normalizedTitle;
  }
  var normalizedSortTitle = dlnaNormalizeSortText(normalizedTitle);
  if (depth === 0) {
    return '2000_' + normalizedSortTitle;
  }
  if (depth === 1) {
    return '3000_' + normalizedSortTitle;
  }
  return '4000_' + normalizedSortTitle;
}

function dlnaNormalizeSortText(value) {
  return String(value || '').toLowerCase().replace(/(\\d+)/g, function(match) {
    return ('000000000000' + match).slice(-12);
  });
}

function dlnaBuildObjectSortKey(title, parts) {
  var normalizedTitle = dlnaNormalizeSortText(title || '');
  if (parts.length > 2 && parts[2] === 'Wszystkie Pliki') {
    return '0000_' + normalizedTitle;
  }
  if (parts.length > 2 && /^\\d{4}-\\d{2}-\\d{2}$/.test(parts[2] || '')) {
    return '1000_' + normalizedTitle;
  }
  return '2000_' + normalizedTitle;
}

function dlnaCreateNamedContainer(title, depth) {
  return {
    title: title,
    objectType: OBJECT_TYPE_CONTAINER,
    searchable: true,
    upnpclass: UPNP_CLASS_CONTAINER,
    metaData: {},
    sortKey: dlnaBuildContainerSortKey(title, depth || 0)
  };
}

function dlnaBuildContainerDefs(parts) {
  var rootMeta = dlnaGetRootMeta(parts);
  var titles = [];
  if (rootMeta.title) {
    titles.push(rootMeta.title);
  }
  if (rootMeta.kind === 'user') {
    if (parts.length > 1 && parts[1]) {
      titles.push(parts[1]);
    }
    if (parts.length > 2 && parts[2]) {
      titles.push(parts[2]);
    }
  }
  if (!titles.length) {
    titles.push('Pozostałe');
  }
  var defs = [];
  for (var idx = 0; idx < titles.length; idx++) {
    defs.push(dlnaCreateNamedContainer(titles[idx], idx));
  }
  return defs;
}

function dlnaImportByCollection(obj, cont, rootPath, autoscanId, containerType) {
  var parts = dlnaGetRelativeParts(obj.location, rootPath);
  obj.title = obj.title || dlnaBasename(obj.location);
  obj.sortKey = dlnaBuildObjectSortKey(obj.title, parts);
  var container = addContainerTree(dlnaBuildContainerDefs(parts));
  var result = [];
  result.push(addCdsObject(obj, container, rootPath));
  return result;
}

function importAudio(obj, cont, rootPath, autoscanId, containerType) {
  return dlnaImportByCollection(obj, cont, rootPath, autoscanId, containerType);
}

function importImage(obj, cont, rootPath, autoscanId, containerType) {
  return dlnaImportByCollection(obj, cont, rootPath, autoscanId, containerType);
}

function importVideo(obj, cont, rootPath, autoscanId, containerType) {
  return dlnaImportByCollection(obj, cont, rootPath, autoscanId, containerType);
}
""" % (encoded_root, encoded_layout)


def build_dlna_legacy_import_script(root_layout_map):
    encoded_root = json.dumps(DLNA_EXPORT_ROOT.replace("\\", "/"), ensure_ascii=False)
    encoded_layout = json.dumps(root_layout_map or {}, ensure_ascii=False, indent=2, sort_keys=True)
    return """var DLNA_EXPORT_ROOT = %s;
var DLNA_ROOT_LAYOUT = %s;

function dlnaNormalizePath(value) {
  return String(value || '').replace(/\\\\/g, '/').replace(/\\/+/g, '/').replace(/\\/$/, '');
}

function dlnaBasename(value) {
  var normalized = dlnaNormalizePath(value);
  if (!normalized) {
    return '';
  }
  var parts = normalized.split('/');
  return parts.length ? parts[parts.length - 1] : normalized;
}

function dlnaGetRelativeParts(location) {
  var normalizedLocation = dlnaNormalizePath(location);
  var normalizedRoot = dlnaNormalizePath(DLNA_EXPORT_ROOT);
  if (normalizedRoot && normalizedLocation.indexOf(normalizedRoot + '/') === 0) {
    normalizedLocation = normalizedLocation.substring(normalizedRoot.length + 1);
  }
  var rawParts = normalizedLocation.split('/');
  var result = [];
  for (var idx = 0; idx < rawParts.length; idx++) {
    if (rawParts[idx]) {
      result.push(rawParts[idx]);
    }
  }
  return result;
}

function dlnaGetRootMeta(parts) {
  var rootKey = parts.length ? parts[0] : '';
  if (rootKey && DLNA_ROOT_LAYOUT[rootKey]) {
    return DLNA_ROOT_LAYOUT[rootKey];
  }
  return { title: rootKey || 'Pozostałe', kind: 'collection' };
}

function dlnaLegacyBuildChain(obj) {
  var parts = dlnaGetRelativeParts(obj.location);
  var rootMeta = dlnaGetRootMeta(parts);
  var chain = new Array(rootMeta.title || 'Pozostałe');
  if (rootMeta.kind === 'user') {
    if (parts.length > 1 && parts[1]) {
      chain.push(parts[1]);
    }
    if (parts.length > 2 && parts[2]) {
      chain.push(parts[2]);
    }
  }
  return chain;
}

function dlnaLegacyAddByCollection(obj) {
  var parts = dlnaGetRelativeParts(obj.location);
  obj.title = obj.title || dlnaBasename(obj.location);
  obj.sortKey = dlnaBuildObjectSortKey(obj.title, parts);
  addCdsObject(obj, createContainerChain(dlnaLegacyBuildChain(obj)), UPNP_CLASS_CONTAINER);
}

function addAudio(obj) {
  dlnaLegacyAddByCollection(obj);
}

function addImage(obj) {
  dlnaLegacyAddByCollection(obj);
}

function addVideo(obj) {
  dlnaLegacyAddByCollection(obj);
}
""" % (encoded_root, encoded_layout)


def write_dlna_virtual_layout_scripts(dlna_config, root_entry_map):
    ensure_dlna_runtime_dirs()
    root_layout_map = build_dlna_root_layout_map(root_entry_map)
    clear_directory_contents(DLNA_CUSTOM_SCRIPT_DIR)
    with open(DLNA_VIRTUAL_LAYOUT_SCRIPT_FILE, "w", encoding="utf-8") as fh:
        fh.write(build_dlna_virtual_layout_script(root_layout_map))
    clear_directory_contents(DLNA_LEGACY_SCRIPT_DIR)
    with open(DLNA_LEGACY_IMPORT_SCRIPT_FILE, "w", encoding="utf-8") as fh:
        fh.write(build_dlna_legacy_import_script(root_layout_map))
    return root_layout_map


def dlna_safe_dir_segment(value, default="kolekcja"):
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x1f/\\\\]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text[:96] or default)


def dlna_safe_export_file_name(value, default="media"):
    base_name = os.path.basename(str(value or "").strip())
    stem, ext = os.path.splitext(base_name)
    safe_stem = dlna_safe_dir_segment(stem or base_name, default=default)
    safe_ext = re.sub(r"[^A-Za-z0-9._-]+", "", str(ext or ""))[:16]
    if safe_ext and not safe_ext.startswith("."):
        safe_ext = "." + safe_ext
    return ("%s%s" % (safe_stem, safe_ext)).strip() or default


def build_dlna_export_link_name(item, used_names):
    source_name = (
        os.path.basename(str(item.get("relative_path") or "").replace("\\", "/"))
        or str(item.get("name") or "").strip()
        or "media"
    )
    candidate = dlna_safe_export_file_name(source_name, default="media")
    lowered = candidate.lower()
    if lowered not in used_names:
        used_names.add(lowered)
        return candidate

    stem, ext = os.path.splitext(candidate)
    digest = hashlib.sha1(str(item.get("relative_path") or source_name).encode("utf-8", errors="ignore")).hexdigest()[:6]
    candidate = "%s [%s]%s" % (stem, digest, ext)
    lowered = candidate.lower()
    counter = 2
    while lowered in used_names:
        candidate = "%s [%s-%s]%s" % (stem, digest, counter, ext)
        lowered = candidate.lower()
        counter += 1
    used_names.add(lowered)
    return candidate


def ensure_directory(path):
    os.makedirs(path, exist_ok=True)
    return path


def remove_path_if_exists(path):
    if not os.path.lexists(path):
        return
    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
        return
    shutil.rmtree(path)


def clear_directory_contents(path):
    ensure_directory(path)
    root = os.path.abspath(path)
    for entry in os.listdir(root):
        candidate = os.path.join(root, entry)
        try:
            if os.path.commonpath([root, os.path.abspath(candidate)]) != root:
                continue
        except Exception:
            continue
        remove_path_if_exists(candidate)


def clear_dlna_database_files():
    ensure_dlna_runtime_dirs()
    for file_name in ("gerbera.db", "gerbera.db-shm", "gerbera.db-wal", "gerbera.db.backup", "gerbera.db-journal"):
        try:
            remove_path_if_exists(os.path.join(DLNA_HOME_DIR, file_name))
        except Exception:
            pass


def write_dlna_restart_guard_script():
    ensure_dlna_runtime_dirs()
    app_python_path = shlex.quote(sys.executable or os.path.join(APP_ROOT, ".venv", "bin", "python"))
    script_content = """#!/bin/bash
set -u

STATE_FILE=%s
EXPORT_ROOT=%s
LOG_FILE=%s
APP_ROOT=%s
APP_PYTHON=%s
RESET_AFTER_SEC=300
AUTO_PRUNE_TIMEOUT_SEC=25
MAX_PRESTART_DELAY_SEC=75

mkdir -p "$(dirname "$STATE_FILE")" "$(dirname "$LOG_FILE")" "$EXPORT_ROOT"

load_state() {
  RESTART_ATTEMPT=0
  LAST_START_TS=0
  if [ -f "$STATE_FILE" ]; then
    # shellcheck disable=SC1090
    . "$STATE_FILE" || true
  fi
  case "${RESTART_ATTEMPT:-}" in
    ''|*[!0-9]*) RESTART_ATTEMPT=0 ;;
  esac
  case "${LAST_START_TS:-}" in
    ''|*[!0-9]*) LAST_START_TS=0 ;;
  esac
}

save_state() {
  cat > "$STATE_FILE" <<EOF
RESTART_ATTEMPT=${RESTART_ATTEMPT:-0}
LAST_START_TS=${LAST_START_TS:-0}
EOF
}

log_line() {
  local message="$1"
  printf '%%s info: %%s\\n' "$(date '+%%Y-%%m-%%d %%H:%%M:%%S')" "$message" >> "$LOG_FILE"
  echo "$message"
}

prune_broken_symlinks() {
  if [ ! -d "$EXPORT_ROOT" ]; then
    return 0
  fi
  local removed_count=0
  while IFS= read -r broken_link; do
    [ -n "$broken_link" ] || continue
    rm -f "$broken_link" || true
    removed_count=$((removed_count + 1))
  done < <(find "$EXPORT_ROOT" -xtype l -print 2>/dev/null || true)
  find "$EXPORT_ROOT" -depth -type d -empty -delete 2>/dev/null || true
  if [ "$removed_count" -gt 0 ]; then
    log_line "DLNA guard usunął $removed_count połamanych linków z eksportu przed restartem Gerbery."
  fi
}

auto_prune_missing_rules() {
  if [ ! -x "$APP_PYTHON" ]; then
    return 0
  fi
  local timeout_bin=""
  if command -v timeout >/dev/null 2>&1; then
    timeout_bin=$(command -v timeout)
  fi
  local prune_output
  local prune_status=0
  prune_output=$(
    cd "$APP_ROOT" || exit 1
    if [ -n "$timeout_bin" ]; then
      PYTHONPATH="$APP_ROOT" "$timeout_bin" "${AUTO_PRUNE_TIMEOUT_SEC}s" "$APP_PYTHON" - <<'PY'
from flask_downloader.legacy_app import prune_missing_dlna_media_rules
result = prune_missing_dlna_media_rules(
    files=None,
    sync_runtime=False,
    restart_service_if_active=False,
)
if result.get("changed"):
    print(int(result.get("removed_count") or 0))
PY
    else
      PYTHONPATH="$APP_ROOT" "$APP_PYTHON" - <<'PY'
from flask_downloader.legacy_app import prune_missing_dlna_media_rules
result = prune_missing_dlna_media_rules(
    files=None,
    sync_runtime=False,
    restart_service_if_active=False,
)
if result.get("changed"):
    print(int(result.get("removed_count") or 0))
PY
    fi
  )
  prune_status=$?
  if [ "$prune_status" -eq 124 ]; then
    log_line "DLNA guard pominął auto-prune brakujących reguł, bo przekroczył ${AUTO_PRUNE_TIMEOUT_SEC}s."
    return 0
  fi
  if [ "$prune_status" -ne 0 ]; then
    return 0
  fi
  prune_output=$(printf '%%s' "$prune_output" | tr -d '\\r' | tail -n 1)
  case "$prune_output" in
    ''|*[!0-9]*)
      return 0
      ;;
  esac
  if [ "$prune_output" -gt 0 ]; then
    log_line "DLNA guard usunął $prune_output martwych reguł z konfiguracji przed restartem Gerbery."
  fi
}

case "${1:-}" in
  prestart)
    prune_broken_symlinks
    auto_prune_missing_rules
    load_state
    delay_seconds=0
    if [ "${RESTART_ATTEMPT:-0}" -eq 1 ]; then
      delay_seconds=10
    elif [ "${RESTART_ATTEMPT:-0}" -eq 2 ]; then
      delay_seconds=60
    elif [ "${RESTART_ATTEMPT:-0}" -ge 3 ]; then
      delay_seconds=1800
    fi
    if [ "$delay_seconds" -gt "$MAX_PRESTART_DELAY_SEC" ]; then
      log_line "DLNA guard skrócił backoff z ${delay_seconds}s do ${MAX_PRESTART_DELAY_SEC}s, żeby nie przekroczyć limitu startu systemd."
      delay_seconds=$MAX_PRESTART_DELAY_SEC
    fi
    if [ "$delay_seconds" -gt 0 ]; then
      log_line "DLNA padła wcześniej. Automatyczna próba ${RESTART_ATTEMPT} za ${delay_seconds}s."
      sleep "$delay_seconds"
    fi
    ;;
  mark-start)
    load_state
    LAST_START_TS=$(date +%%s)
    save_state
    ;;
  stop-post)
    load_state
    service_result="${SERVICE_RESULT:-}"
    exit_code="${EXIT_CODE:-}"
    exit_status="${EXIT_STATUS:-}"
    now_ts=$(date +%%s)
    runtime_seconds=0
    if [ "${LAST_START_TS:-0}" -gt 0 ]; then
      runtime_seconds=$((now_ts - LAST_START_TS))
    fi
    if [ "$service_result" = "success" ]; then
      RESTART_ATTEMPT=0
      LAST_START_TS=0
      save_state
      exit 0
    fi
    if [ "$runtime_seconds" -ge "$RESET_AFTER_SEC" ]; then
      RESTART_ATTEMPT=1
    else
      RESTART_ATTEMPT=$(( ${RESTART_ATTEMPT:-0} + 1 ))
      if [ "$RESTART_ATTEMPT" -lt 1 ]; then
        RESTART_ATTEMPT=1
      fi
    fi
    LAST_START_TS=0
    save_state
    log_line "Gerbera zatrzymała się nieoczekiwanie (SERVICE_RESULT=${service_result:-unknown}, EXIT_CODE=${exit_code:-unknown}, EXIT_STATUS=${exit_status:-unknown}, runtime=${runtime_seconds}s)."
    ;;
  reset)
    RESTART_ATTEMPT=0
    LAST_START_TS=0
    save_state
    ;;
esac
""" % (
        shlex.quote(DLNA_RESTART_STATE_FILE),
        shlex.quote(DLNA_EXPORT_ROOT),
        shlex.quote(DLNA_LOG_FILE),
        shlex.quote(APP_ROOT),
        app_python_path,
    )
    with open(DLNA_RESTART_GUARD_SCRIPT_FILE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(script_content)
    os.chmod(DLNA_RESTART_GUARD_SCRIPT_FILE, 0o755)


def reset_dlna_restart_backoff_state():
    ensure_dlna_runtime_dirs()
    try:
        subprocess.run(
            ["/bin/bash", DLNA_RESTART_GUARD_SCRIPT_FILE, "reset"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        try:
            with open(DLNA_RESTART_STATE_FILE, "w", encoding="utf-8") as fh:
                fh.write("RESTART_ATTEMPT=0\nLAST_START_TS=0\n")
        except Exception:
            pass


def is_linux_runtime():
    return os.name != "nt" and sys.platform.startswith("linux")


def get_current_runtime_user_name():
    if pwd is not None:
        try:
            return pwd.getpwuid(os.getuid()).pw_name
        except Exception:
            pass
    return os.environ.get("USER") or "root"


def get_current_runtime_group_name():
    if grp is not None:
        try:
            return grp.getgrgid(os.getgid()).gr_name
        except Exception:
            pass
    return os.environ.get("USER") or "root"


def systemd_quote_arg(value):
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def get_dlna_binary_path():
    path = shutil.which(DLNA_PACKAGE_NAME)
    if path:
        return path
    fallback = os.path.join("/usr", "bin", DLNA_PACKAGE_NAME)
    return fallback if os.path.isfile(fallback) else ""


def parse_leading_version_tuple(version_text):
    match = re.match(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?", str(version_text or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.groups(default="0"))


def dlna_version_at_least(version_text, *target_parts):
    current = parse_leading_version_tuple(version_text)
    target = tuple(int(part) for part in target_parts)
    if not current:
        return False
    if len(current) < len(target):
        current = current + (0,) * (len(target) - len(current))
    elif len(target) < len(current):
        target = target + (0,) * (len(current) - len(target))
    return current >= target


def get_dlna_feature_support(version_text=""):
    version_value = str(version_text or "").strip()
    supports_groups = dlna_version_at_least(version_value, 2, 4, 0)
    supports_client_allowed = dlna_version_at_least(version_value, 2, 3, 0)
    supports_group_allowed = dlna_version_at_least(version_value, 3, 0, 0)
    supports_logging_section = dlna_version_at_least(version_value, 2, 2, 0)

    notes = []
    if version_value and not supports_groups:
        notes.append("Ta wersja Gerbera nie obsługuje grup klientów, więc nie da się rozdzielać kolekcji per klient bez nowszego pakietu.")
    elif version_value and supports_groups and not supports_group_allowed:
        notes.append("Ta wersja Gerbera nie obsługuje pełnego blokowania grup, więc domyślni klienci dostają pustą bibliotekę zamiast twardego deny na poziomie config.xml.")

    return {
        "version_text": version_value,
        "supports_groups": supports_groups,
        "supports_client_allowed": supports_client_allowed,
        "supports_group_allowed": supports_group_allowed,
        "supports_logging_section": supports_logging_section,
        "notes": notes,
    }


def validate_dlna_gerbera_config(binary_path="", allow_runtime_probe=True):
    binary = str(binary_path or get_dlna_binary_path() or "").strip()
    if not binary:
        raise RuntimeError("Nie znaleziono binarki gerbera do walidacji config.xml.")

    result = subprocess.run(
        [binary, "--check-config", "--config", DLNA_CONFIG_XML_FILE, "--home", DLNA_HOME_DIR],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=45,
        check=False,
    )
    if result.returncode == 0:
        return {
            "supported": True,
            "message": "",
        }

    detail = (result.stderr or result.stdout or "").strip()
    lowered = detail.lower()
    if "unrecognized option" in lowered and "--check-config" in lowered:
        try:
            ET.parse(DLNA_CONFIG_XML_FILE)
        except Exception as exc:
            raise RuntimeError("Wygenerowany config.xml DLNA nie jest poprawnym XML: %s" % exc) from exc
        return {
            "supported": False,
            "message": "Ta wersja Gerbera nie obsługuje --check-config; potwierdzono tylko poprawność XML lokalnie i pominięto testowy start.",
        }

    raise RuntimeError(detail[-1600:] or "Walidacja config.xml Gerbera zakończyła się błędem.")


def terminate_spawned_process_tree(process, wait_timeout=5):
    if process is None:
        return

    try:
        if process.poll() is not None:
            return
    except Exception:
        return

    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass
        try:
            process.wait(timeout=max(1, int(wait_timeout or 5)))
            return
        except Exception:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
    else:
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=max(1, int(wait_timeout or 5)))
            return
        except Exception:
            pass
        try:
            process.kill()
        except Exception:
            pass

    try:
        process.wait(timeout=max(1, int(wait_timeout or 5)))
    except Exception:
        pass


def probe_dlna_gerbera_startup(binary_path=""):
    binary = str(binary_path or get_dlna_binary_path() or "").strip()
    if not binary:
        raise RuntimeError("Nie znaleziono binarki gerbera do testowego startu.")

    ensure_dlna_runtime_dirs()
    reset_dlna_log_file()
    env = dict(os.environ)
    env["HOME"] = DLNA_HOME_DIR
    env["GERBERA_HOME"] = DLNA_HOME_DIR

    command = [binary, "-c", DLNA_CONFIG_XML_FILE, "-m", DLNA_HOME_DIR]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=env,
        start_new_session=True,
    )

    output_lines = []

    def consume_output():
        if not process.stdout:
            return
        for raw_line in process.stdout:
            line = str(raw_line or "").strip()
            if line:
                output_lines.append(line)
                if len(output_lines) > 60:
                    del output_lines[:-60]

    output_thread = threading.Thread(target=consume_output, name="dlna-gerbera-probe", daemon=True)
    output_thread.start()

    try:
        deadline = time.time() + 6.0
        while time.time() < deadline:
            return_code = process.poll()
            if return_code is not None:
                break
            time.sleep(0.25)

        return_code = process.poll()
        if return_code is None:
            return {
                "supported": False,
                "message": "Ta wersja Gerbera nie obsługuje --check-config, ale testowy start configu zakończył się powodzeniem.",
            }

        detail = "\n".join(output_lines[-12:]).strip()
        if not detail:
            detail = "\n".join(read_recent_log_file_lines(DLNA_LOG_FILE, lines=12)).strip()
        raise RuntimeError(detail or "Gerbera zakończyła testowy start błędem bez komunikatu.")
    finally:
        terminate_spawned_process_tree(process, wait_timeout=5)
        if process.stdout:
            try:
                process.stdout.close()
            except Exception:
                pass
        output_thread.join(timeout=2)


def build_apt_query_env():
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["LANGUAGE"] = "C"
    return env


def get_linux_distribution_codename():
    os_release_path = os.path.join("/etc", "os-release")
    try:
        with open(os_release_path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = str(raw_line or "").strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() != "VERSION_CODENAME":
                    continue
                text = str(value or "").strip().strip("\"' ")
                if text:
                    return text
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["lsb_release", "-c", "--short"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
            env=build_apt_query_env(),
        )
        text = str(result.stdout or "").strip()
        if result.returncode == 0 and text:
            return text
    except Exception:
        pass

    raise RuntimeError("Nie udało się ustalić codename systemu Debian/Ubuntu potrzebnego do repo Gerbera.")


def get_dlna_official_repo_channel(channel_key=""):
    return DLNA_UPDATE_SERVICE.get_official_repo_channel(channel_key)


def read_dlna_official_repo_line():
    return DLNA_UPDATE_SERVICE.read_official_repo_line()


def get_dlna_repo_source_snapshot(policy=None):
    return DLNA_UPDATE_SERVICE.get_repo_source_snapshot(policy=policy)


def download_dlna_official_repo_key_bytes():
    return DLNA_UPDATE_SERVICE.download_official_repo_key_bytes()


def ensure_dlna_official_repo(channel_key="", progress_callback=None):
    return DLNA_UPDATE_SERVICE.ensure_official_repo(channel_key=channel_key, progress_callback=progress_callback)


def read_dpkg_installed_version(package_name):
    return DLNA_UPDATE_SERVICE.read_dpkg_installed_version(package_name)


def get_apt_package_policy(package_name):
    return DLNA_UPDATE_SERVICE.get_apt_package_policy(package_name)


def get_last_due_dlna_check_dt(now=None):
    return DLNA_UPDATE_SERVICE.get_last_due_check_dt(now=now)


def get_next_dlna_check_dt(now=None):
    return DLNA_UPDATE_SERVICE.get_next_check_dt(now=now)


def needs_scheduled_dlna_check(last_checked_at, now=None):
    return DLNA_UPDATE_SERVICE.needs_scheduled_check(last_checked_at, now=now)


def get_dlna_package_state_snapshot():
    return DLNA_UPDATE_SERVICE.get_package_state_snapshot()


def refresh_dlna_package_state(force=False):
    return DLNA_UPDATE_SERVICE.refresh_package_state(force=force)


def dlna_check_scheduler():
    while True:
        try:
            refresh_dlna_package_state(force=False)
            next_check_dt = get_next_dlna_check_dt()
            sleep_seconds = max(300, int(next_check_dt.timestamp() - time.time()))
        except Exception:
            sleep_seconds = 900
        time.sleep(sleep_seconds)


def dlna_autoheal_scheduler():
    while True:
        try:
            dlna_config = get_dlna_config_snapshot()
            package_state = get_dlna_package_state_snapshot()
            if dlna_config.get("enabled") and package_state.get("installed"):
                prune_missing_dlna_media_rules(
                    files=None,
                    sync_runtime=True,
                    restart_service_if_active=False,
                )
        except Exception:
            pass
        time.sleep(max(15, int(DLNA_AUTOHEAL_INTERVAL_SECONDS or 30)))


def start_dlna_scheduler_once():
    global DLNA_SCHEDULER_STARTED
    with DLNA_SCHEDULER_LOCK:
        if DLNA_SCHEDULER_STARTED:
            return
        thread = threading.Thread(target=dlna_check_scheduler, name="dlna-check-scheduler", daemon=True)
        thread.start()
        DLNA_SCHEDULER_STARTED = True


def start_dlna_autoheal_scheduler_once():
    global DLNA_AUTOHEAL_STARTED
    with DLNA_AUTOHEAL_LOCK:
        if DLNA_AUTOHEAL_STARTED:
            return
        thread = threading.Thread(target=dlna_autoheal_scheduler, name="dlna-autoheal-scheduler", daemon=True)
        thread.start()
        DLNA_AUTOHEAL_STARTED = True


def get_dlna_collection_catalog(dlna_config=None):
    return DLNA_LIBRARY_SERVICE.get_collection_catalog(dlna_config)


def get_dlna_named_collection_map(dlna_config=None):
    return DLNA_LIBRARY_SERVICE.get_named_collection_map(dlna_config)


def get_dlna_collection_dir_map(dlna_config=None):
    config = dlna_config or get_dlna_config_snapshot()
    result = {
        DLNA_ALL_COLLECTION_ID: DLNA_ALL_COLLECTION_NAME,
    }
    used_names = {DLNA_ALL_COLLECTION_NAME.lower()}
    for item in config.get("collections") or []:
        base_name = dlna_safe_dir_segment(item["name"], default="kolekcja")
        candidate = base_name
        suffix = 1
        while candidate.lower() in used_names:
            suffix += 1
            candidate = "%s (%s)" % (base_name, suffix)
        used_names.add(candidate.lower())
        result[item["id"]] = candidate
    return result


def get_dlna_library_candidates(files=None):
    return DLNA_LIBRARY_SERVICE.get_library_candidates(files)


def normalize_dlna_library_mode(value):
    return DLNA_LIBRARY_SERVICE.normalize_library_mode(value)


def build_dlna_library_presence_index(files=None):
    files = files if files is not None else get_server_files()
    file_keys = set()
    folder_keys = set()

    for item in files:
        storage_kind = normalize_storage_kind(item.get("storage_kind") or "video")
        relative_path = safe_relative_download_path(item.get("relative_path") or "")
        if not relative_path:
            continue

        file_keys.add((storage_kind, relative_path))
        current_folder = relative_path
        while "/" in current_folder:
            current_folder = current_folder.rsplit("/", 1)[0]
            if current_folder:
                folder_keys.add((storage_kind, current_folder))

    return {
        "file_keys": file_keys,
        "folder_keys": folder_keys,
    }


def prune_missing_dlna_media_rules(files=None, sync_runtime=True, restart_service_if_active=False):
    ok, message = ensure_share_ready(auto_remount=True)
    if not ok:
        return {
            "changed": False,
            "removed_count": 0,
            "removed_rules": [],
            "skipped": True,
            "reason": message,
            "config": get_dlna_config_snapshot(),
        }

    available_storage_ids = set()
    for candidate_storage_id in iter_storage_ids():
        candidate_root = os.path.abspath(get_user_storage_base_root(candidate_storage_id))
        if candidate_storage_id == "local" or os.path.isdir(candidate_root):
            available_storage_ids.add(candidate_storage_id)

    with APP_CONFIG_LOCK:
        dlna_config = copy.deepcopy(normalize_dlna_config(APP_CONFIG.get("dlna")))
        current_entries = list(dlna_config.get("entries") or [])

    kept_entries = []
    removed_rules = []
    for entry in current_entries:
        source_storage_id = normalize_storage_id(entry.get("source_storage_id") or "local", default="local")
        if source_storage_id not in available_storage_ids:
            kept_entries.append(entry)
            continue
        current_relative_path = safe_relative_download_path(entry.get("current_relative_path") or "")
        if not current_relative_path:
            removed_rules.append({
                "id": str(entry.get("id") or "").strip(),
                "kind": "file",
                "storage_kind": normalize_storage_kind(entry.get("source_storage_kind") or "video"),
                "relative_path": safe_relative_download_path(entry.get("source_relative_path") or ""),
                "current_relative_path": "",
            })
            continue
        current_path = DLNA_LIBRARY_SERVICE.get_collection_storage_path(source_storage_id, current_relative_path)
        if current_path and os.path.isfile(current_path):
            kept_entries.append(entry)
            continue

        removed_rules.append({
            "id": str(entry.get("id") or "").strip(),
            "kind": "file",
            "storage_kind": normalize_storage_kind(entry.get("source_storage_kind") or "video"),
            "relative_path": safe_relative_download_path(entry.get("source_relative_path") or ""),
            "current_relative_path": current_relative_path,
        })

    if not removed_rules:
        return {
            "changed": False,
            "removed_count": 0,
            "removed_rules": [],
            "skipped": False,
            "reason": "",
            "config": copy.deepcopy(dlna_config),
        }

    with APP_CONFIG_LOCK:
        latest_dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))
        removed_ids = {str(item.get("id") or "").strip() for item in removed_rules}
        latest_dlna_config["entries"] = [
            item
            for item in (latest_dlna_config.get("entries") or [])
            if str(item.get("id") or "").strip() not in removed_ids
        ]
        APP_CONFIG["dlna"] = normalize_dlna_config(latest_dlna_config)
        write_app_config_locked()
        updated_config = copy.deepcopy(APP_CONFIG["dlna"])

    if sync_runtime:
        sync_dlna_runtime_safe(
            restart_service_if_active=restart_service_if_active,
            force_full_rescan=bool(restart_service_if_active),
            include_pending_downloads=False,
        )

    return {
        "changed": True,
        "removed_count": len(removed_rules),
        "removed_rules": removed_rules,
        "skipped": False,
        "reason": "",
        "config": updated_config,
    }


def search_dlna_library(query="", limit=40, files=None):
    library = get_dlna_library_candidates(files=files)
    text = str(query or "").strip().lower()

    if text:
        folder_items = [item for item in library["folders"] if text in item["display_path"].lower()]
        file_items = [item for item in library["files"] if text in item["display_path"].lower()]
    else:
        folder_items = list(library["folders"])
        file_items = list(library["files"])

    return {
        "folders": folder_items[:limit],
        "files": file_items[:limit],
        "total_folders": len(folder_items),
        "total_files": len(file_items),
    }


def build_dlna_exact_rule_lookup(dlna_config=None):
    return DLNA_LIBRARY_SERVICE.build_exact_rule_lookup(dlna_config)


def normalize_dlna_collection_editor_id(collection_id, dlna_config=None):
    return DLNA_LIBRARY_SERVICE.normalize_collection_editor_id(collection_id, dlna_config)


def ensure_dlna_collection_membership_on_exact_rule(dlna_config, kind, storage_kind, relative_path, collection_id):
    return DLNA_LIBRARY_SERVICE.ensure_collection_membership_on_exact_rule(
        dlna_config,
        kind,
        storage_kind,
        relative_path,
        collection_id,
    )


def remove_dlna_collection_membership_from_exact_rule(dlna_config, kind, storage_kind, relative_path, collection_id):
    return DLNA_LIBRARY_SERVICE.remove_collection_membership_from_exact_rule(
        dlna_config,
        kind,
        storage_kind,
        relative_path,
        collection_id,
    )


def explode_dlna_collection_from_matching_folder_rules(dlna_config, collection_id, file_items, files=None):
    return DLNA_LIBRARY_SERVICE.explode_collection_from_matching_folder_rules(
        dlna_config,
        collection_id,
        file_items,
        files=files,
    )


def bulk_assign_dlna_collection_items(collection_id, items):
    return DLNA_LIBRARY_SERVICE.bulk_assign_collection_items(collection_id, items)


def build_dlna_collection_library_results(collection_id="", query="", mode="files", limit=200, dlna_config=None, files=None):
    return DLNA_LIBRARY_SERVICE.build_collection_library_results(
        collection_id=collection_id,
        query=query,
        mode=mode,
        limit=limit,
        dlna_config=dlna_config,
        files=files,
    )


def resolve_dlna_rule_matches(rule, files=None):
    return DLNA_LIBRARY_SERVICE.resolve_rule_matches(rule, files=files)


def get_dlna_effective_file_map(dlna_config=None, files=None):
    return DLNA_LIBRARY_SERVICE.get_effective_file_map(dlna_config, files=files)


def get_dlna_client_visible_collection_ids(client, dlna_config=None):
    return DLNA_LIBRARY_SERVICE.get_client_visible_collection_ids(client, dlna_config)


def build_dlna_media_rule_summaries(dlna_config=None, files=None):
    return DLNA_LIBRARY_SERVICE.build_media_rule_summaries(dlna_config, files=files)


def build_dlna_client_summaries(dlna_config=None, files=None):
    return DLNA_LIBRARY_SERVICE.build_client_summaries(dlna_config, files=files)


def get_dlna_summary_state(dlna_config=None, files=None):
    return DLNA_LIBRARY_SERVICE.get_summary_state(dlna_config, files=files)


def ensure_dlna_runtime_dirs():
    for path in (
        DLNA_TOOLS_ROOT,
        DLNA_RUNTIME_ROOT,
        DLNA_HOME_DIR,
        DLNA_EXPORT_ROOT,
        DLNA_WEBROOT_DIR,
        DLNA_ICONS_DIR,
        DLNA_CUSTOM_ASSETS_DIR,
        DLNA_CONFIG_DIR,
        DLNA_SCRIPT_DIR,
        DLNA_COMMON_SCRIPT_DIR,
        DLNA_CUSTOM_SCRIPT_DIR,
        DLNA_LEGACY_SCRIPT_DIR,
        DLNA_RUNTIME_BIN_DIR,
        DLNA_LOG_DIR,
    ):
        ensure_directory(path)


def get_dlna_custom_icon_source_file_candidates():
    ensure_dlna_runtime_dirs()
    candidates = []
    for extension in sorted(DLNA_ALLOWED_ICON_EXTENSIONS):
        candidates.append(os.path.join(DLNA_CUSTOM_ASSETS_DIR, "%s%s" % (DLNA_CUSTOM_ICON_SOURCE_BASENAME, extension)))
    return candidates


def get_dlna_custom_icon_source_file():
    for candidate in get_dlna_custom_icon_source_file_candidates():
        if os.path.isfile(candidate):
            return candidate
    return ""


def get_dlna_default_icon_file(size=120, extension="png"):
    return os.path.join(DLNA_SYSTEM_WEBROOT_DIR, "icons", "mt-icon%s.%s" % (int(size or 120), str(extension or "png").strip().lower()))


def get_dlna_runtime_icon_file(size=120, extension="png"):
    return os.path.join(DLNA_ICONS_DIR, "mt-icon%s.%s" % (int(size or 120), str(extension or "png").strip().lower()))


def sync_path_as_symlink_or_copy(source_path, target_path):
    if not os.path.exists(source_path):
        raise FileNotFoundError(source_path)
    remove_path_if_exists(target_path)
    ensure_directory(os.path.dirname(target_path))
    try:
        os.symlink(source_path, target_path)
    except Exception:
        shutil.copy2(source_path, target_path)


def build_dlna_icon_state(dlna_config=None):
    config = dlna_config or get_dlna_config_snapshot()
    icon_mode = "custom" if str(config.get("icon_mode") or "").strip().lower() == "custom" else "default"
    source_name = str(config.get("icon_source_name") or "").strip()
    try:
        updated_at = float(config.get("icon_updated_at") or 0.0)
    except Exception:
        updated_at = 0.0
    source_exists = bool(get_dlna_custom_icon_source_file())
    runtime_preview = get_dlna_runtime_icon_file(120, "png")
    preview_exists = os.path.isfile(runtime_preview)
    return {
        "mode": icon_mode,
        "mode_label": "Własna ikona" if icon_mode == "custom" and source_exists else "Domyślna ikona Gerbery",
        "source_name": source_name,
        "updated_at": updated_at,
        "updated_at_text": format_ts(updated_at) if updated_at else "",
        "source_exists": source_exists,
        "preview_exists": preview_exists,
        "preview_url": "/api/dlna/icon-preview?v=%s" % (int(updated_at or 0) if updated_at else 0),
    }


def run_dlna_icon_ffmpeg(source_path, target_path, size, extension):
    ffmpeg_binary, _ = resolve_ffmpeg_binary()
    if not ffmpeg_binary:
        raise RuntimeError("Brakuje ffmpeg potrzebnego do przygotowania ikon DLNA.")

    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == "png":
        filter_chain = (
            "scale=%(size)s:%(size)s:force_original_aspect_ratio=decrease,"
            "pad=%(size)s:%(size)s:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
        ) % {"size": int(size)}
        command = [
            ffmpeg_binary,
            "-y",
            "-loglevel",
            "error",
            "-i",
            source_path,
            "-vf",
            filter_chain,
            "-frames:v",
            "1",
            target_path,
        ]
    else:
        filter_chain = (
            "scale=%(size)s:%(size)s:force_original_aspect_ratio=decrease,"
            "pad=%(size)s:%(size)s:(ow-iw)/2:(oh-ih)/2:color=white"
        ) % {"size": int(size)}
        command = [
            ffmpeg_binary,
            "-y",
            "-loglevel",
            "error",
            "-i",
            source_path,
            "-vf",
            filter_chain,
            "-frames:v",
            "1",
        ]
        if normalized_extension == "jpg":
            command.extend(["-q:v", "2"])
        command.append(target_path)

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode != 0 or not os.path.isfile(target_path):
        raise RuntimeError(str(result.stderr or result.stdout or "Nie udało się przygotować wariantu ikony DLNA.").strip())


def generate_dlna_icon_variants(source_path, target_dir):
    ensure_directory(target_dir)
    for size, extension, _mime in DLNA_ICON_VARIANTS:
        target_path = os.path.join(target_dir, "mt-icon%s.%s" % (int(size), extension))
        run_dlna_icon_ffmpeg(source_path, target_path, size, extension)


def ensure_dlna_webroot_assets(dlna_config=None):
    config = dlna_config or get_dlna_config_snapshot()
    ensure_dlna_runtime_dirs()
    ensure_directory(DLNA_WEBROOT_DIR)
    if os.path.isdir(DLNA_SYSTEM_WEBROOT_DIR):
        for entry in os.listdir(DLNA_SYSTEM_WEBROOT_DIR):
            if entry == "icons":
                continue
            source_path = os.path.join(DLNA_SYSTEM_WEBROOT_DIR, entry)
            target_path = os.path.join(DLNA_WEBROOT_DIR, entry)
            sync_path_as_symlink_or_copy(source_path, target_path)

    clear_directory_contents(DLNA_ICONS_DIR)
    icon_mode = "custom" if str(config.get("icon_mode") or "").strip().lower() == "custom" else "default"
    custom_source_path = get_dlna_custom_icon_source_file()
    if icon_mode == "custom" and custom_source_path and os.path.isfile(custom_source_path):
        generate_dlna_icon_variants(custom_source_path, DLNA_ICONS_DIR)
        return

    for size, extension, _mime in DLNA_ICON_VARIANTS:
        source_path = get_dlna_default_icon_file(size, extension)
        target_path = get_dlna_runtime_icon_file(size, extension)
        sync_path_as_symlink_or_copy(source_path, target_path)


def validate_dlna_icon_upload(file_storage):
    if file_storage is None or not str(getattr(file_storage, "filename", "") or "").strip():
        raise ValueError("Najpierw wybierz plik ikony DLNA.")
    file_name = str(file_storage.filename or "").strip()
    extension = os.path.splitext(file_name)[1].strip().lower()
    if extension not in DLNA_ALLOWED_ICON_EXTENSIONS:
        raise ValueError("Ikona DLNA musi być plikiem PNG, JPG, BMP albo WEBP.")
    file_storage.stream.seek(0, os.SEEK_END)
    file_size = int(file_storage.stream.tell() or 0)
    file_storage.stream.seek(0)
    if file_size <= 0:
        raise ValueError("Wybrany plik ikony DLNA jest pusty.")
    if file_size > DLNA_CUSTOM_ICON_MAX_BYTES:
        raise ValueError("Ikona DLNA jest zbyt duża. Limit to 10 MB.")
    return file_name, extension


def store_dlna_custom_icon(file_storage):
    file_name, extension = validate_dlna_icon_upload(file_storage)
    ensure_dlna_runtime_dirs()
    temp_root = tempfile.mkdtemp(prefix="dlna-icon-", dir=DLNA_RUNTIME_ROOT)
    try:
        temp_source_path = os.path.join(temp_root, "source%s" % extension)
        file_storage.save(temp_source_path)
        temp_icons_dir = os.path.join(temp_root, "icons")
        generate_dlna_icon_variants(temp_source_path, temp_icons_dir)

        for candidate in get_dlna_custom_icon_source_file_candidates():
            remove_path_if_exists(candidate)

        final_source_path = os.path.join(DLNA_CUSTOM_ASSETS_DIR, "%s%s" % (DLNA_CUSTOM_ICON_SOURCE_BASENAME, extension))
        shutil.move(temp_source_path, final_source_path)

        dlna_config = get_dlna_config_snapshot()
        dlna_config["icon_mode"] = "custom"
        dlna_config["icon_source_name"] = file_name[:160]
        dlna_config["icon_updated_at"] = time.time()
        set_dlna_config(dlna_config)
        sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=False)
        return build_dlna_icon_state(dlna_config)
    finally:
        remove_path_if_exists(temp_root)


def reset_dlna_custom_icon():
    ensure_dlna_runtime_dirs()
    for candidate in get_dlna_custom_icon_source_file_candidates():
        remove_path_if_exists(candidate)
    dlna_config = get_dlna_config_snapshot()
    dlna_config["icon_mode"] = "default"
    dlna_config["icon_source_name"] = ""
    dlna_config["icon_updated_at"] = time.time()
    set_dlna_config(dlna_config)
    sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=False)
    return build_dlna_icon_state(dlna_config)


def filter_dlna_export_files(files, dlna_config=None, include_pending_downloads=True):
    items = list(files or [])
    if include_pending_downloads:
        return items

    config = normalize_dlna_config(dlna_config if dlna_config is not None else get_dlna_config_snapshot())
    pending_paths = set(normalize_dlna_pending_manual_sync_paths(config.get("pending_manual_sync_paths") or []))
    if not pending_paths:
        return items

    filtered_items = []
    for item in items:
        relative_path = canonicalize_managed_relative_path(item.get("relative_path") or "") or safe_relative_download_path(item.get("relative_path") or "")
        if relative_path and relative_path in pending_paths:
            continue
        filtered_items.append(item)
    return filtered_items


def rebuild_dlna_export_tree(dlna_config=None, files=None, include_pending_downloads=False):
    config = dlna_config or get_dlna_config_snapshot()
    files = files if files is not None else get_server_files()
    effective_map = get_dlna_effective_file_map(
        config,
        files=files,
        include_pending_downloads=include_pending_downloads,
    )
    root_entry_map = build_dlna_root_entry_map(config)
    package_state = get_dlna_package_state_snapshot()
    feature_support = get_dlna_feature_support(package_state.get("current_version_raw"))

    ensure_dlna_runtime_dirs()
    clear_directory_contents(DLNA_EXPORT_ROOT)

    created_links = 0
    used_names_by_export_dir = {}
    for absolute_path, item in effective_map.items():
        collection_ids = set(item.get("collection_ids") or set())
        for collection_id in collection_ids:
            export_entry = root_entry_map.get(collection_id) or {}
            export_dir_name = export_entry.get("dir_name")
            if not export_dir_name:
                continue

            used_names = used_names_by_export_dir.setdefault(str(export_dir_name).lower(), set())
            export_file_name = build_dlna_export_link_name(item, used_names)
            export_relative_path = os.path.join(export_dir_name, export_file_name)
            export_path = os.path.abspath(os.path.join(DLNA_EXPORT_ROOT, export_relative_path))
            ensure_directory(os.path.dirname(export_path))

            if os.path.lexists(export_path):
                remove_path_if_exists(export_path)

            os.symlink(absolute_path, export_path)
            created_links += 1

    return {
        "effective_media_count": len(effective_map),
        "created_links": created_links,
        "collection_dir_map": {
            root_id: entry.get("dir_name")
            for root_id, entry in root_entry_map.items()
            if str((entry or {}).get("kind") or "") == "collection"
        },
        "root_entry_map": root_entry_map,
    }


def parse_gerbera_config_xml(xml_text, source_label="stdout"):
    raw_text = str(xml_text or "")
    text = raw_text.strip()
    if not text:
        raise RuntimeError("Gerbera nie zwróciła pustej konfiguracji z %s." % source_label)
    for marker in ("<?xml", "<config"):
        marker_index = text.find(marker)
        if marker_index >= 0:
            text = text[marker_index:].strip()
            break
    try:
        return ET.ElementTree(ET.fromstring(text))
    except Exception as exc:
        raise RuntimeError("Nie udało się sparsować konfiguracji Gerbera z %s." % source_label) from exc


def try_generate_gerbera_config_via_flag(binary_path, *flag_args):
    ensure_dlna_runtime_dirs()
    temp_home_root = tempfile.mkdtemp(prefix="gerbera-create-config-", dir=DLNA_RUNTIME_ROOT)
    try:
        env = dict(os.environ)
        env["HOME"] = temp_home_root
        env.pop("GERBERA_HOME", None)

        result = subprocess.run(
            [binary_path, *flag_args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Gerbera nie wygenerowała config.xml.").strip()
            raise RuntimeError(detail[-1200:])
        return parse_gerbera_config_xml(result.stdout, source_label=" ".join(flag_args))
    finally:
        shutil.rmtree(temp_home_root, ignore_errors=True)


def try_generate_gerbera_config_via_runtime(binary_path):
    ensure_dlna_runtime_dirs()
    temp_home_root = tempfile.mkdtemp(prefix="gerbera-bootstrap-", dir=DLNA_RUNTIME_ROOT)
    config_path = os.path.join(temp_home_root, ".config", "gerbera", "config.xml")
    ensure_directory(os.path.dirname(config_path))

    env = dict(os.environ)
    env["HOME"] = temp_home_root
    env.pop("GERBERA_HOME", None)

    process = subprocess.Popen(
        [binary_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        env=env,
        start_new_session=True,
    )

    stderr_lines = []

    def read_stderr():
        if not process.stderr:
            return
        for raw_line in process.stderr:
            line = str(raw_line or "").strip()
            if line:
                stderr_lines.append(line)

    stderr_thread = threading.Thread(target=read_stderr, name="gerbera-bootstrap-stderr", daemon=True)
    stderr_thread.start()

    try:
        deadline = time.time() + 15.0
        parsed_tree = None
        while time.time() < deadline:
            if os.path.isfile(config_path) and os.path.getsize(config_path) > 0:
                try:
                    with open(config_path, "r", encoding="utf-8") as fh:
                        parsed_tree = parse_gerbera_config_xml(fh.read(), source_label=config_path)
                    break
                except Exception:
                    parsed_tree = None
            if process.poll() is not None and parsed_tree is None and not os.path.isfile(config_path):
                break
            time.sleep(0.2)

        if parsed_tree is None:
            detail = "\n".join(stderr_lines[-10:]).strip()
            raise RuntimeError(detail or "Gerbera nie wygenerowała config.xml przy starcie awaryjnym.")

        return parsed_tree
    finally:
        terminate_spawned_process_tree(process, wait_timeout=5)
        if process.stderr:
            try:
                process.stderr.close()
            except Exception:
                pass
        stderr_thread.join(timeout=2)
        shutil.rmtree(temp_home_root, ignore_errors=True)


def generate_gerbera_default_config_tree():
    binary_path = get_dlna_binary_path()
    if not binary_path:
        raise RuntimeError("Nie znaleziono binarki gerbera. Najpierw zainstaluj serwer DLNA.")
    errors = []

    try:
        return try_generate_gerbera_config_via_flag(binary_path, "--create-config")
    except Exception as exc:
        errors.append("--create-config: %s" % exc)

    try:
        return try_generate_gerbera_config_via_runtime(binary_path)
    except Exception as exc:
        errors.append("runtime fallback: %s" % exc)

    raise RuntimeError("Nie udało się wygenerować domyślnego config.xml dla Gerbera. " + " | ".join(errors))


def build_dlna_client_group_name(client):
    suffix = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(client.get("ip") or "").strip())
    suffix = suffix.strip("_") or str(client.get("id") or "client")
    return "client_%s" % suffix


def get_dlna_server_self_client_ips(dlna_config=None):
    config = dlna_config or get_dlna_config_snapshot()
    result = []
    seen = set()

    def add_ip(candidate):
        text = str(candidate or "").strip()
        if not text or text in seen:
            return
        try:
            address = ipaddress.ip_address(text)
        except Exception:
            return
        if address.version != 4:
            return
        if not address.is_loopback and address not in DLNA_ALLOWED_NETWORK:
            return
        seen.add(text)
        result.append(text)

    add_ip("127.0.0.1")
    add_ip(config.get("bind_ip") or "")

    try:
        hostname = socket.gethostname()
        for _, _, _, _, sockaddr in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            add_ip((sockaddr or ("",))[0])
    except Exception:
        pass

    probe = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.5)
        probe.connect(("192.168.0.1", 9))
        add_ip(probe.getsockname()[0])
    except Exception:
        pass
    finally:
        try:
            probe.close()
        except Exception:
            pass

    return result


def resolve_dlna_bind_interface_name(bind_ip):
    bind_text = str(bind_ip or "").strip()
    if not bind_text:
        return ""
    try:
        target_ip = ipaddress.ip_address(bind_text)
    except Exception:
        return ""
    if target_ip.version != 4:
        return ""

    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return ""

    if result.returncode != 0:
        return ""

    for raw_line in (result.stdout or "").splitlines():
        line = str(raw_line or "").strip()
        if not line or " inet " not in line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        interface_name = str(parts[1] or "").strip()
        address_text = str(parts[3] or "").strip().split("/", 1)[0]
        if address_text == bind_text:
            return interface_name
    return ""


def write_dlna_gerbera_config(dlna_config=None, files=None, include_pending_downloads=False):
    config = dlna_config or get_dlna_config_snapshot()
    ensure_dlna_runtime_dirs()
    ensure_dlna_webroot_assets(config)
    ensure_dlna_export_root_directory()
    cleanup_dlna_legacy_export_root()
    export_state = rebuild_dlna_export_tree(
        config,
        files=files,
        include_pending_downloads=include_pending_downloads,
    )
    root_entry_map = export_state["root_entry_map"]
    package_state = get_dlna_package_state_snapshot()
    package_version = package_state.get("current_version_raw")
    supports_custom_virtual_layout = dlna_version_at_least(package_version, 2, 0, 0)
    write_dlna_virtual_layout_scripts(config, root_entry_map)
    feature_support = get_dlna_feature_support(package_state.get("current_version_raw"))
    tree = generate_gerbera_default_config_tree()
    root = tree.getroot()

    server_el = gerbera_ensure(root, "server")
    gerbera_ensure(server_el, "name").text = config["server_name"]
    gerbera_ensure(server_el, "port").text = str(config["port"])
    home_el = gerbera_ensure(server_el, "home")
    home_el.text = DLNA_HOME_DIR
    home_el.attrib.pop("override", None)
    gerbera_ensure(server_el, "webroot").text = DLNA_WEBROOT_DIR

    bind_ip = config.get("bind_ip") or ""
    ip_el = gerbera_find(server_el, "ip")
    interface_el = gerbera_find(server_el, "interface")
    bind_interface_name = resolve_dlna_bind_interface_name(bind_ip)
    if bind_interface_name:
        if interface_el is None:
            interface_el = gerbera_sub_element(server_el, "interface")
        interface_el.text = bind_interface_name
        if ip_el is not None:
            server_el.remove(ip_el)
    else:
        if interface_el is not None:
            server_el.remove(interface_el)
        if bind_ip:
            if ip_el is None:
                ip_el = gerbera_sub_element(server_el, "ip")
            ip_el.text = bind_ip
        elif ip_el is not None:
            server_el.remove(ip_el)

    ui_el = gerbera_ensure(server_el, "ui")
    ui_el.set("enabled", "no")
    containers_el = gerbera_ensure(server_el, "containers")
    clear_xml_children(containers_el)
    containers_el.set("enabled", "no")
    pc_directory_el = gerbera_ensure(server_el, "pc-directory")
    pc_directory_el.set("upnp-hide", "yes")

    if feature_support["supports_logging_section"]:
        logging_el = gerbera_ensure(server_el, "logging")
        logging_el.set("rotate-file-size", str(DLNA_LOG_MAX_BYTES))
        logging_el.set("rotate-file-count", "1")

    storage_el = gerbera_ensure(server_el, "storage")
    if dlna_version_at_least(package_version, 2, 6, 0):
        storage_el.set("enable-sort-key", "yes")
    else:
        storage_el.attrib.pop("enable-sort-key", None)
    sqlite_el = gerbera_ensure(storage_el, "sqlite3")
    sqlite_el.set("enabled", "yes")
    gerbera_ensure(sqlite_el, "database-file").text = "gerbera.db"

    mysql_el = gerbera_find(storage_el, "mysql")
    if mysql_el is not None:
        mysql_el.set("enabled", "no")
    postgres_el = gerbera_find(storage_el, "postgres")
    if postgres_el is not None:
        postgres_el.set("enabled", "no")

    import_el = gerbera_ensure(root, "import")
    import_el.set("hidden-files", "no")
    import_el.set("follow-symlinks", "yes")
    import_el.set("import-mode", "grb")

    scripting_el = gerbera_ensure(import_el, "scripting")
    virtual_layout_el = gerbera_ensure(scripting_el, "virtual-layout")
    virtual_layout_el.set("type", "js" if supports_custom_virtual_layout else "builtin")
    virtual_layout_el.attrib.pop("audio-layout", None)
    virtual_layout_el.attrib.pop("video-layout", None)
    virtual_layout_el.attrib.pop("image-layout", None)
    if not supports_custom_virtual_layout:
        script_folder_el = gerbera_find(scripting_el, "script-folder")
        if script_folder_el is not None:
            scripting_el.remove(script_folder_el)
        import_function_el = gerbera_find(scripting_el, "import-function")
        if import_function_el is not None:
            scripting_el.remove(import_function_el)

        common_script_el = gerbera_find(scripting_el, "common-script")
        if common_script_el is None:
            common_script_el = gerbera_sub_element(scripting_el, "common-script")
        common_script_el.text = "/usr/share/gerbera/js/common.js"

        clear_xml_children(virtual_layout_el)
        import_script_el = gerbera_sub_element(virtual_layout_el, "import-script")
        import_script_el.text = DLNA_LEGACY_IMPORT_SCRIPT_FILE
    else:
        clear_xml_children(virtual_layout_el)
        script_folder_el = gerbera_find(scripting_el, "script-folder")
        if script_folder_el is None:
            script_folder_el = gerbera_sub_element(scripting_el, "script-folder")
        clear_xml_children(script_folder_el)
        gerbera_sub_element(script_folder_el, "common").text = "/usr/share/gerbera/js"
        gerbera_sub_element(script_folder_el, "custom").text = DLNA_CUSTOM_SCRIPT_DIR

        legacy_common_script_el = gerbera_find(scripting_el, "common-script")
        if legacy_common_script_el is not None:
            scripting_el.remove(legacy_common_script_el)

        import_function_el = gerbera_find(scripting_el, "import-function")
        if import_function_el is None:
            import_function_el = gerbera_sub_element(scripting_el, "import-function")
        clear_xml_children(import_function_el)
        gerbera_sub_element(import_function_el, "audio-file").text = "importAudio"
        gerbera_sub_element(import_function_el, "video-file").text = "importVideo"
        gerbera_sub_element(import_function_el, "image-file").text = "importImage"
        playlist_el = gerbera_sub_element(import_function_el, "playlist")
        playlist_el.set("create-link", "yes")
        playlist_el.text = "importPlaylist"
        gerbera_sub_element(import_function_el, "meta-file").text = "importMetadata"

    autoscan_el = gerbera_ensure(import_el, "autoscan")
    autoscan_el.set("use-inotify", "auto")
    autoscan_el.set("inotify-attrib", "yes")
    clear_xml_children(autoscan_el)
    autoscan_dir_el = gerbera_sub_element(autoscan_el, "directory")
    autoscan_dir_el.set("location", DLNA_EXPORT_ROOT)
    autoscan_dir_el.set("mode", "inotify")
    autoscan_dir_el.set("recursive", "yes")
    autoscan_dir_el.set("hidden-files", "no")

    clients_el = gerbera_ensure(root, "clients")
    clients_el.set("enabled", "yes")
    clear_xml_children(clients_el)
    all_root_ids = set(root_entry_map.keys())

    def build_root_hide_locations(root_id):
        root_entry = root_entry_map.get(root_id) or {}
        collection_dir_name = root_entry.get("dir_name")
        if not collection_dir_name:
            return []
        physical_location = os.path.join(DLNA_EXPORT_ROOT, collection_dir_name)
        if supports_custom_virtual_layout:
            return ["/" + str(collection_dir_name).strip("/"), physical_location]
        return [physical_location]

    if feature_support["supports_groups"]:
        default_group_el = gerbera_sub_element(clients_el, "group")
        default_group_el.set("name", "default")
        if feature_support["supports_group_allowed"]:
            default_group_el.set("allowed", "no")

        for root_id in sorted(all_root_ids):
            for hide_location in build_root_hide_locations(root_id):
                hide_el = gerbera_sub_element(default_group_el, "hide")
                hide_el.set("location", hide_location)

        self_group_el = gerbera_sub_element(clients_el, "group")
        self_group_el.set("name", "server_self")
        if feature_support["supports_group_allowed"]:
            self_group_el.set("allowed", "yes")

        for self_ip in get_dlna_server_self_client_ips(config):
            self_client_el = gerbera_sub_element(clients_el, "client")
            self_client_el.set("ip", self_ip)
            self_client_el.set("group", "server_self")
            if feature_support["supports_client_allowed"]:
                self_client_el.set("allowed", "yes")

    for client in config.get("clients") or []:
        group_name = build_dlna_client_group_name(client)
        if feature_support["supports_groups"]:
            group_el = gerbera_sub_element(clients_el, "group")
            group_el.set("name", group_name)
            if feature_support["supports_group_allowed"]:
                group_el.set("allowed", "yes" if client.get("enabled", True) else "no")

            visible_root_ids = build_dlna_client_visible_root_ids(client, config)
            hidden_root_ids = all_root_ids - visible_root_ids
            for root_id in sorted(hidden_root_ids):
                for hide_location in build_root_hide_locations(root_id):
                    hide_el = gerbera_sub_element(group_el, "hide")
                    hide_el.set("location", hide_location)

        client_el = gerbera_sub_element(clients_el, "client")
        client_el.set("ip", client["ip"])
        if feature_support["supports_groups"]:
            client_el.set("group", group_name)
        if feature_support["supports_client_allowed"]:
            client_el.set("allowed", "yes" if client.get("enabled", True) else "no")

    root_namespace = gerbera_namespace_for(root)
    if root_namespace in (GERBERA_CONFIG_NS, GERBERA_LEGACY_CONFIG_NS):
        ET.register_namespace("", root_namespace)
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ")
    tree.write(DLNA_CONFIG_XML_FILE, encoding="utf-8", xml_declaration=True)
    return export_state


def write_dlna_service_unit():
    binary_path = get_dlna_binary_path()
    if not binary_path:
        raise RuntimeError("Nie znaleziono binarki gerbera. Najpierw zainstaluj serwer DLNA.")

    ensure_dlna_runtime_dirs()
    write_dlna_restart_guard_script()
    package_state = get_dlna_package_state_snapshot()
    feature_support = get_dlna_feature_support(package_state.get("current_version_raw"))
    log_arg = (
        "--rotatelog=%s" % systemd_quote_arg(DLNA_LOG_FILE)
        if feature_support["supports_logging_section"]
        else "-l %s" % systemd_quote_arg(DLNA_LOG_FILE)
    )
    unit_content = """[Unit]
Description=Flask Downloader DLNA Server
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=%s
Group=%s
WorkingDirectory=%s
Environment=GERBERA_HOME=%s
ExecStartPre=/bin/bash %s prestart
ExecStart=%s %s -c %s -m %s
ExecStartPost=/bin/bash %s mark-start
ExecStopPost=/bin/bash %s stop-post
Restart=always
RestartSec=0
TimeoutStartSec=120
TimeoutStopSec=120
KillMode=control-group

[Install]
WantedBy=multi-user.target
""" % (
        get_current_runtime_user_name(),
        get_current_runtime_group_name(),
        APP_ROOT,
        DLNA_HOME_DIR,
        systemd_quote_arg(DLNA_RESTART_GUARD_SCRIPT_FILE),
        systemd_quote_arg(binary_path),
        log_arg,
        systemd_quote_arg(DLNA_CONFIG_XML_FILE),
        systemd_quote_arg(DLNA_HOME_DIR),
        systemd_quote_arg(DLNA_RESTART_GUARD_SCRIPT_FILE),
        systemd_quote_arg(DLNA_RESTART_GUARD_SCRIPT_FILE),
    )
    try:
        if os.path.isfile(DLNA_SERVICE_UNIT_FILE):
            with open(DLNA_SERVICE_UNIT_FILE, "r", encoding="utf-8", errors="replace") as fh:
                existing_content = str(fh.read() or "")
            if existing_content == unit_content:
                return
    except Exception:
        pass
    write_text_file_with_optional_sudo(DLNA_SERVICE_UNIT_FILE, unit_content)


def write_text_file_with_optional_sudo(path, text, *, encoding="utf-8", timeout=60):
    normalized_path = os.path.abspath(str(path or "").strip())
    if not normalized_path:
        raise RuntimeError("Brak ścieżki docelowej do zapisu pliku systemowego.")

    if os.name != "nt":
        try:
            if os.geteuid() != 0:
                sudo_binary = shutil.which("sudo")
                writer_candidates = (
                    "/usr/local/lib/flask-downloader/write-system-file",
                    "/usr/local/libexec/flask-downloader/write-system-file",
                )
                writer_binary = next(
                    (candidate for candidate in writer_candidates if os.path.isfile(candidate) and os.access(candidate, os.X_OK)),
                    "",
                )
                if sudo_binary:
                    completed_process = subprocess.run(
                        [sudo_binary, "-n", writer_binary or (shutil.which("tee") or "/usr/bin/tee"), normalized_path],
                        input=str(text or ""),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=timeout,
                        check=False,
                    )
                    if completed_process.returncode == 0:
                        return
                    detail = (completed_process.stderr or "").strip()
                    if any(
                        marker in detail.lower()
                        for marker in (
                            "access denied",
                            "interactive authentication required",
                            "authentication is required",
                            "a password is required",
                            "sudo:",
                            "permission denied",
                        )
                    ):
                        raise RuntimeError(
                            "Brakuje uprawnień do zapisu pliku systemowego %s. "
                            "Uruchom ponownie instalator albo sprawdź regułę sudoers dla użytkownika usługi."
                            % normalized_path
                        )
                    raise RuntimeError(
                        detail
                        or "Nie udało się zapisać pliku systemowego %s." % normalized_path
                    )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                "Nie udało się zapisać pliku systemowego %s: %s" % (normalized_path, exc)
            ) from exc

    with open(normalized_path, "w", encoding=encoding) as fh:
        fh.write(str(text or ""))


def build_systemctl_command_args(*args):
    systemctl_binary = shutil.which("systemctl") or "/bin/systemctl"
    command = [systemctl_binary, *args]
    if os.name != "nt":
        try:
            if os.geteuid() != 0:
                sudo_binary = shutil.which("sudo")
                if sudo_binary:
                    command = [sudo_binary, "-n", systemctl_binary, *args]
        except Exception:
            pass
    return command


def run_systemctl_command(*args, timeout=60):
    result = run_systemctl_command_result(*args, timeout=timeout)
    if result["returncode"] != 0:
        raise RuntimeError(result["detail"])
    return result["completed_process"]


def run_systemctl_command_result(*args, timeout=60):
    if not is_linux_runtime():
        raise RuntimeError("Obsługa systemd dla DLNA wymaga Linuxa.")

    try:
        completed_process = subprocess.run(
            build_systemctl_command_args(*args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        timed_out = False
        detail = (completed_process.stderr or completed_process.stdout or "").strip()
        if not detail:
            detail = "Polecenie systemctl zakończyło się błędem." if completed_process.returncode != 0 else ""
        if completed_process.returncode != 0 and any(
            marker in detail.lower()
            for marker in (
                "access denied",
                "interactive authentication required",
                "authentication is required",
                "a password is required",
                "sudo:",
            )
        ):
            detail = (
                "Brakuje uprawnień do sterowania usługami systemd z poziomu panelu. "
                "Uruchom ponownie instalator jako root, aby odtworzył reguły sudoers dla usera usługi Flask. "
                "Szczegóły: %s"
            ) % detail
    except subprocess.TimeoutExpired as exc:
        completed_process = None
        timed_out = True
        stdout_text = str(exc.stdout or "")
        stderr_text = str(exc.stderr or "")
        detail = (stderr_text or stdout_text or "").strip()
        if not detail:
            detail = "Polecenie systemctl przekroczyło limit czasu."
        return {
            "completed_process": completed_process,
            "returncode": 124,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "detail": detail[-1200:] if detail else "",
            "timed_out": timed_out,
        }
    return {
        "completed_process": completed_process,
        "returncode": completed_process.returncode,
        "stdout": completed_process.stdout or "",
        "stderr": completed_process.stderr or "",
        "detail": detail[-1200:] if detail else "",
        "timed_out": timed_out,
    }


def list_tcp_port_listeners(port, bind_ip=""):
    if not is_linux_runtime():
        return []

    try:
        normalized_port = int(str(port or "").strip())
    except Exception:
        return []

    result = subprocess.run(
        ["ss", "-ltnp"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        return []

    bind_text = str(bind_ip or "").strip()
    listeners = []
    seen = set()
    for raw_line in (result.stdout or "").splitlines():
        line = str(raw_line or "").strip()
        if not line or ("LISTEN" not in line) or (":%s" % normalized_port not in line):
            continue
        if bind_text and (("%s:%s" % (bind_text, normalized_port)) not in line):
            continue

        pid_match = re.search(r"pid=(\d+)", line)
        name_match = re.search(r'users:\(\("([^"]+)"', line)
        if not pid_match:
            continue

        pid_value = int(pid_match.group(1))
        process_name = name_match.group(1) if name_match else "unknown"
        key = (pid_value, process_name)
        if key in seen:
            continue
        seen.add(key)
        listeners.append({
            "pid": pid_value,
            "process_name": process_name,
            "raw_line": line,
        })
    return listeners


def ensure_no_conflicting_dlna_listener(port, bind_ip=""):
    bind_text = str(bind_ip or "").strip()
    our_state = get_generic_service_state(DLNA_SERVICE_NAME)
    our_main_pid = str(our_state.get("main_pid") or "").strip()
    ignored_pids = {0}
    try:
        if our_main_pid:
            ignored_pids.add(int(our_main_pid))
    except Exception:
        pass

    listeners = [
        item for item in list_tcp_port_listeners(port, bind_ip=bind_text)
        if int(item.get("pid") or 0) not in ignored_pids
    ]
    if not listeners:
        return {"resolved": False, "message": ""}

    package_service_state = get_generic_service_state(DLNA_SYSTEM_SERVICE_NAME)
    package_service_pid = 0
    try:
        package_service_pid = int(str(package_service_state.get("main_pid") or "0").strip() or "0")
    except Exception:
        package_service_pid = 0

    package_listener = None
    for item in listeners:
        if package_service_pid and int(item.get("pid") or 0) == package_service_pid:
            package_listener = item
            break

    if package_listener and package_service_state.get("active_state") == "active":
        run_systemctl_command_result("stop", DLNA_SYSTEM_SERVICE_NAME, timeout=90)
        run_systemctl_command_result("disable", DLNA_SYSTEM_SERVICE_NAME, timeout=90)
        time.sleep(1.5)
        listeners = [
            item for item in list_tcp_port_listeners(port, bind_ip=bind_text)
            if int(item.get("pid") or 0) not in ignored_pids
        ]
        if not listeners:
            return {
                "resolved": True,
                "message": "Wyłączono kolidującą usługę systemową gerbera, która zajmowała port %s." % port,
            }

    conflict_descriptions = []
    for item in listeners:
        conflict_descriptions.append(
            "%s (PID %s)" % (item.get("process_name") or "nieznany proces", item.get("pid") or "?")
        )
    raise RuntimeError(
        "Port DLNA %s%s jest już zajęty przez: %s."
        % (
            bind_text + ":" if bind_text else "",
            port,
            ", ".join(conflict_descriptions) or "nieznany proces",
        )
    )


def wait_for_dlna_service_stable(timeout=8.0):
    deadline = time.time() + max(1.0, float(timeout or 0.0))
    last_state = get_dlna_service_state()

    while time.time() < deadline:
        state = get_dlna_service_state()
        last_state = state
        active_state = str(state.get("active_state") or "")
        uptime_seconds = state.get("service_uptime_seconds")

        if active_state in ("failed", "inactive"):
            break

        if active_state == "active" and isinstance(uptime_seconds, (int, float)) and uptime_seconds >= 2.0:
            return state

        time.sleep(0.5)

    return last_state


def wait_for_dlna_service_stopped(timeout=10.0):
    deadline = time.time() + max(1.0, float(timeout or 0.0))
    last_state = get_dlna_service_state()

    while time.time() < deadline:
        state = get_dlna_service_state()
        last_state = state
        active_state = str(state.get("active_state") or "")
        main_pid = str(state.get("main_pid") or "").strip()

        if active_state in ("inactive", "failed", "unknown") and main_pid in ("", "0"):
            return state

        time.sleep(0.5)

    return last_state


def format_dlna_service_error(state):
    recent_log_excerpt = str((state or {}).get("recent_log_excerpt") or "").strip()
    diagnostic_text = str((state or {}).get("diagnostic_text") or "").strip()
    parts = []
    if diagnostic_text:
        parts.append(diagnostic_text)
    if recent_log_excerpt:
        parts.append(recent_log_excerpt)
    return " | ".join(parts)


def build_dlna_service_failure_detail(state, fallback_detail=""):
    parts = []
    fallback_text = str(fallback_detail or "").strip()
    if fallback_text:
        parts.append(fallback_text)
    formatted_state_error = format_dlna_service_error(state)
    if formatted_state_error and formatted_state_error not in parts:
        parts.append(formatted_state_error)
    return " | ".join(parts)


def ensure_dlna_service_started(enable_unit=False, timeout=90, failure_label="startu"):
    if enable_unit:
        run_systemctl_command("enable", DLNA_SERVICE_NAME, timeout=timeout)

    dlna_config = get_dlna_config_snapshot()
    ensure_no_conflicting_dlna_listener(dlna_config.get("port"), dlna_config.get("bind_ip"))
    reset_dlna_restart_backoff_state()
    run_systemctl_command_result("reset-failed", DLNA_SERVICE_NAME, timeout=30)
    start_result = run_systemctl_command_result("start", DLNA_SERVICE_NAME, timeout=timeout)
    service_state = wait_for_dlna_service_stable(timeout=8.0)
    if service_state.get("active_state") == "active":
        return service_state

    detail = build_dlna_service_failure_detail(service_state, start_result.get("detail"))
    raise RuntimeError("Usługa DLNA nie utrzymała %s. %s" % (failure_label, detail or "Sprawdź log usługi DLNA."))


def _ensure_dlna_service_stopped_legacy(timeout=90, reset_failed_after_stop=True):
    stop_result = run_systemctl_command_result("stop", DLNA_SERVICE_NAME, timeout=timeout)
    wait_timeout = 45.0 if stop_result.get("timed_out") else 12.0
    service_state = wait_for_dlna_service_stopped(timeout=wait_timeout)
    main_pid = str(service_state.get("main_pid") or "").strip()
    active_state = str(service_state.get("active_state") or "")

    kill_result = {"detail": "", "returncode": 0}
    if active_state in ("active", "deactivating") or main_pid not in ("", "0"):
        if stop_result.get("timed_out"):
            kill_result = run_systemctl_command_result(
                "kill",
                "--signal=SIGKILL",
                DLNA_SERVICE_NAME,
                timeout=30,
            )
            service_state = wait_for_dlna_service_stopped(timeout=20.0)
            main_pid = str(service_state.get("main_pid") or "").strip()
            active_state = str(service_state.get("active_state") or "")
        if active_state in ("active", "deactivating") or main_pid not in ("", "0"):
            detail = build_dlna_service_failure_detail(
                service_state,
                " | ".join(
                    str(part or "").strip()
                    for part in (stop_result.get("detail"), kill_result.get("detail"))
                    if str(part or "").strip()
                ),
            )
        raise RuntimeError("Nie udało się zatrzymać poprzedniej instancji DLNA. %s" % (detail or "Sprawdź log usługi DLNA."))

    if reset_failed_after_stop or active_state == "failed":
        run_systemctl_command_result("reset-failed", DLNA_SERVICE_NAME, timeout=30)
        service_state = get_dlna_service_state()
    return service_state


def ensure_dlna_service_stopped(timeout=90, reset_failed_after_stop=True):
    stop_result = run_systemctl_command_result("stop", DLNA_SERVICE_NAME, timeout=timeout)
    wait_timeout = 45.0 if stop_result.get("timed_out") else 12.0
    service_state = wait_for_dlna_service_stopped(timeout=wait_timeout)
    main_pid = str(service_state.get("main_pid") or "").strip()
    active_state = str(service_state.get("active_state") or "")
    kill_result = {"detail": "", "returncode": 0}

    if active_state in ("active", "deactivating") or main_pid not in ("", "0"):
        if stop_result.get("timed_out"):
            kill_result = run_systemctl_command_result(
                "kill",
                "--signal=SIGKILL",
                DLNA_SERVICE_NAME,
                timeout=30,
            )
            service_state = wait_for_dlna_service_stopped(timeout=20.0)
            main_pid = str(service_state.get("main_pid") or "").strip()
            active_state = str(service_state.get("active_state") or "")

    if active_state in ("active", "deactivating") or main_pid not in ("", "0"):
        detail = build_dlna_service_failure_detail(
            service_state,
            " | ".join(
                str(part or "").strip()
                for part in (stop_result.get("detail"), kill_result.get("detail"))
                if str(part or "").strip()
            ),
        )
        raise RuntimeError("Nie udało się zatrzymać poprzedniej instancji DLNA. %s" % (detail or "Sprawdź log usługi DLNA."))

    if reset_failed_after_stop or active_state == "failed":
        run_systemctl_command_result("reset-failed", DLNA_SERVICE_NAME, timeout=30)
        service_state = get_dlna_service_state()
    return service_state


DLNA_RUNTIME_SERVICE = DlnaRuntimeService(
    sync_lock=DLNA_SYNC_LOCK,
    ensure_dlna_runtime_dirs=ensure_dlna_runtime_dirs,
    ensure_share_ready=ensure_share_ready,
    get_server_files=get_server_files,
    prune_missing_dlna_media_rules=prune_missing_dlna_media_rules,
    get_dlna_config_snapshot=get_dlna_config_snapshot,
    normalize_dlna_config=normalize_dlna_config,
    set_dlna_config=set_dlna_config,
    filter_dlna_export_files=filter_dlna_export_files,
    clear_dlna_manual_sync_needed=clear_dlna_manual_sync_needed,
    get_dlna_package_state_snapshot=get_dlna_package_state_snapshot,
    get_generic_service_state=get_generic_service_state,
    ensure_dlna_service_started_impl=ensure_dlna_service_started,
    ensure_dlna_service_stopped_impl=ensure_dlna_service_stopped,
    clear_dlna_database_files=clear_dlna_database_files,
    write_dlna_gerbera_config=write_dlna_gerbera_config,
    validate_dlna_gerbera_config=validate_dlna_gerbera_config,
    write_dlna_service_unit=write_dlna_service_unit,
    run_systemctl_command=run_systemctl_command,
    save_dlna_runtime_status=save_dlna_runtime_status,
    get_dlna_feature_support=get_dlna_feature_support,
    format_dlna_service_error=format_dlna_service_error,
    run_systemctl_command_result=run_systemctl_command_result,
    ensure_no_conflicting_dlna_listener=ensure_no_conflicting_dlna_listener,
    wait_for_dlna_service_stable=wait_for_dlna_service_stable,
    wait_for_dlna_service_stopped=wait_for_dlna_service_stopped,
    dlna_virtual_layout_version=DLNA_VIRTUAL_LAYOUT_VERSION,
    dlna_service_name=DLNA_SERVICE_NAME,
    dlna_system_service_name=DLNA_SYSTEM_SERVICE_NAME,
    dlna_config_xml_file=DLNA_CONFIG_XML_FILE,
    dlna_export_root=DLNA_EXPORT_ROOT,
    dlna_service_unit_file=DLNA_SERVICE_UNIT_FILE,
    set_dlna_runtime_phase=set_dlna_runtime_phase,
)


def sync_dlna_runtime(restart_service_if_active=False, force_full_rescan=False, include_pending_downloads=True):
    return DLNA_RUNTIME_SERVICE.sync_runtime(
        restart_service_if_active=restart_service_if_active,
        force_full_rescan=force_full_rescan,
        include_pending_downloads=include_pending_downloads,
    )


def sync_dlna_runtime_safe(restart_service_if_active=False, force_full_rescan=False, include_pending_downloads=True):
    return DLNA_RUNTIME_SERVICE.sync_runtime_safe(
        restart_service_if_active=restart_service_if_active,
        force_full_rescan=force_full_rescan,
        include_pending_downloads=include_pending_downloads,
    )


def get_dlna_service_state():
    return DLNA_RUNTIME_SERVICE.get_service_state()


def set_dlna_service_enabled(enabled):
    return DLNA_RUNTIME_SERVICE.set_service_enabled(enabled)


def restart_dlna_service_now():
    return DLNA_RUNTIME_SERVICE.restart_service_now()


def classify_dlna_apt_progress(output_line, stage):
    line = str(output_line or "").strip().lower()
    if stage == "update":
        if line.startswith("hit:") or line.startswith("get:") or line.startswith("ign:"):
            return 14.0, "Odświeżanie repozytoriów apt"
        if "reading package lists" in line:
            return 22.0, "Budowanie listy pakietów"
        return 12.0, "Sprawdzanie repozytoriów apt"

    if "already the newest version" in line:
        return 88.0, "Pakiet jest już aktualny"
    if "the following new packages will be installed" in line:
        return 46.0, "Przygotowanie instalacji"
    if "the following packages will be upgraded" in line:
        return 50.0, "Przygotowanie aktualizacji"
    if "need to get" in line:
        return 56.0, "Pobieranie pakietów"
    if line.startswith("get:") or line.startswith("fetch:"):
        return 60.0, "Pobieranie pakietów"
    if "unpacking" in line:
        return 74.0, "Rozpakowywanie pakietu"
    if "setting up " in line:
        return 86.0, "Konfigurowanie pakietu"
    if "processing triggers for" in line:
        return 92.0, "Finalizacja instalacji"
    if "reading package lists" in line or "building dependency tree" in line or "reading state information" in line:
        return 40.0, "Analiza zależności"
    return 44.0, "Przetwarzanie przez apt"


def run_streamed_command(command, env=None, timeout=900, progress_callback=None, stage="install"):
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    output_lines = []
    output_lock = threading.Lock()

    def consume_output():
        if not process.stdout:
            return

        for raw_line in process.stdout:
            line = str(raw_line or "").strip()
            if not line:
                continue

            with output_lock:
                output_lines.append(line)
                if len(output_lines) > 20:
                    del output_lines[:-20]

            if progress_callback:
                progress_percent, status_label = classify_dlna_apt_progress(line, stage)
                progress_callback(
                    status="running",
                    status_label=status_label,
                    progress_percent=progress_percent,
                    detail=line,
                )

    output_thread = threading.Thread(target=consume_output, name="dlna-cmd-output", daemon=True)
    output_thread.start()

    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=10)
        except Exception:
            pass
        raise RuntimeError("Polecenie %s przekroczyło limit czasu." % " ".join(command))
    finally:
        if process.stdout:
            try:
                process.stdout.close()
            except Exception:
                pass
        output_thread.join(timeout=2)

    with output_lock:
        output = "\n".join(output_lines).strip()

    if return_code != 0:
        raise RuntimeError(output or "Polecenie %s zakończyło się błędem." % " ".join(command))

    return output


def install_or_update_dlna_server(progress_callback=None):
    if not is_linux_runtime():
        return False, "Automatyczna instalacja serwera DLNA wymaga Linuxa z apt i systemd."

    env = build_apt_query_env()
    env["DEBIAN_FRONTEND"] = "noninteractive"

    with DLNA_INSTALL_LOCK:
        try:
            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Przygotowanie",
                    progress_percent=6.0,
                    detail="Sprawdzam stan pakietu Gerbera i odświeżam listę repozytoriów apt.",
                )

            before_state = get_dlna_package_state_snapshot()
            ensure_dlna_official_repo(channel_key=DLNA_PREFERRED_REPO_CHANNEL, progress_callback=progress_callback)
            run_streamed_command(
                ["apt-get", "update"],
                env=env,
                timeout=900,
                progress_callback=progress_callback,
                stage="update",
            )

            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Instalowanie",
                    progress_percent=36.0,
                    detail="Uruchamiam apt-get install dla pakietu gerbera z oficjalnego repo Gerbera.",
                )

            run_streamed_command(
                ["apt-get", "install", "-y", DLNA_PACKAGE_NAME],
                env=env,
                timeout=1800,
                progress_callback=progress_callback,
                stage="install",
            )

            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Konfiguracja",
                    progress_percent=95.0,
                    detail="Generuję konfigurację Gerbera i przygotowuję katalog eksportu DLNA.",
                )

            save_dlna_update_state("", time.time(), "")
            after_state = refresh_dlna_package_state(force=True)
            package_version_changed = before_state.get("current_version_raw") != after_state.get("current_version_raw")

            if package_version_changed:
                if progress_callback:
                    progress_callback(
                        status="running",
                        status_label="Migracja bazy",
                        progress_percent=93.0,
                        detail="Wykryto zmianę wersji Gerbera. Czyszczę stary indeks DLNA, aby nowy pakiet zbudował bazę od zera.",
                    )
                clear_dlna_database_files()

            sync_dlna_runtime(restart_service_if_active=False)
            after_state = refresh_dlna_package_state(force=True)

            if get_dlna_config_snapshot().get("enabled"):
                try:
                    ensure_dlna_service_started(enable_unit=True, timeout=90, failure_label="startu po instalacji")
                except Exception as exc:
                    return False, "Pakiet Gerbera zainstalowano, ale nie udało się uruchomić usługi DLNA: %s" % exc

            message = "Serwer DLNA przygotowano."
            if before_state["current_version_raw"] and after_state["current_version_raw"] and before_state["current_version_raw"] != after_state["current_version_raw"]:
                message = "Serwer DLNA zaktualizowano z %s do %s." % (
                    before_state["current_version_raw"],
                    after_state["current_version_raw"],
                )
            elif after_state["current_version_raw"]:
                message = "Serwer DLNA jest gotowy (%s)." % after_state["current_version_raw"]

            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Gotowe",
                    progress_percent=100.0,
                    detail=message,
                )
            return True, message
        except Exception as exc:
            save_dlna_update_state("", time.time(), str(exc))
            save_dlna_runtime_status(last_sync_error=str(exc))
            return False, "Instalacja lub aktualizacja serwera DLNA nie powiodła się: %s" % str(exc)


def parse_boolean_flag(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "tak"):
        return True
    if text in ("0", "false", "no", "off", "nie"):
        return False
    return bool(default)


def update_dlna_general_settings(server_name, bind_ip, port):
    return DLNA_LIBRARY_SERVICE.update_general_settings(server_name, bind_ip, port)


def create_dlna_collection(name, description=""):
    return DLNA_LIBRARY_SERVICE.create_collection(name, description)


def update_dlna_collection(collection_id, name, description=""):
    return DLNA_LIBRARY_SERVICE.update_collection(collection_id, name, description)


def delete_dlna_collection(collection_id):
    return DLNA_LIBRARY_SERVICE.delete_collection(collection_id)


def normalize_dlna_client_collection_ids(collection_ids, dlna_config=None):
    return DLNA_LIBRARY_SERVICE.normalize_client_collection_ids(collection_ids, dlna_config)


def create_dlna_client(ip, description="", enabled=True, collection_ids=None, usernames=None):
    return DLNA_LIBRARY_SERVICE.create_client(ip, description, enabled, collection_ids, usernames)


def update_dlna_client(client_id, ip, description="", enabled=True, collection_ids=None, usernames=None):
    return DLNA_LIBRARY_SERVICE.update_client(client_id, ip, description, enabled, collection_ids, usernames)


def delete_dlna_client(client_id):
    return DLNA_LIBRARY_SERVICE.delete_client(client_id)


def normalize_dlna_media_rule_collection_ids(collection_ids, dlna_config=None):
    return DLNA_LIBRARY_SERVICE.normalize_media_rule_collection_ids(collection_ids, dlna_config)


def create_dlna_media_rule(kind, storage_kind, relative_path, collection_ids=None, enabled=True):
    return DLNA_LIBRARY_SERVICE.create_media_rule(
        kind,
        storage_kind,
        relative_path,
        collection_ids,
        enabled,
    )


def update_dlna_media_rule(rule_id, collection_ids=None, enabled=True):
    return DLNA_LIBRARY_SERVICE.update_media_rule(rule_id, collection_ids, enabled)


def delete_dlna_media_rule(rule_id):
    return DLNA_LIBRARY_SERVICE.delete_media_rule(rule_id)


DLNA_LIBRARY_SERVICE = DlnaLibraryService(
    get_mount_info=get_mount_info,
    get_server_files=get_server_files,
    prune_missing_dlna_media_rules=prune_missing_dlna_media_rules,
    get_dlna_config_snapshot=get_dlna_config_snapshot,
    set_dlna_config=set_dlna_config,
    refresh_dlna_package_state=refresh_dlna_package_state,
    get_dlna_service_state=get_dlna_service_state,
    get_all_maintenance_task_snapshots=get_all_maintenance_task_snapshots,
    normalize_dlna_config=normalize_dlna_config,
    normalize_storage_kind=normalize_storage_kind,
    safe_relative_download_path=safe_relative_download_path,
    resolve_download_path=resolve_download_path,
    format_relative_path_for_user=format_relative_path_for_user,
    format_bytes_text=format_bytes_text,
    format_ts=format_ts,
    normalize_dlna_server_name=normalize_dlna_server_name,
    normalize_dlna_bind_ip=normalize_dlna_bind_ip,
    normalize_dlna_port=normalize_dlna_port,
    normalize_dlna_collection_name=normalize_dlna_collection_name,
    normalize_dlna_client_ip=normalize_dlna_client_ip,
    normalize_dlna_description=normalize_dlna_description,
    sync_dlna_runtime_safe=sync_dlna_runtime_safe,
    get_users_snapshot=get_users_snapshot,
    get_current_username=get_current_username,
    is_admin_authenticated=is_admin_authenticated,
    can_access_owner=can_access_owner,
    get_storage_root=get_storage_root,
    default_admin_username=DEFAULT_ADMIN_USERNAME,
    dlna_all_collection_id=DLNA_ALL_COLLECTION_ID,
    dlna_all_collection_name=DLNA_ALL_COLLECTION_NAME,
    dlna_export_root=DLNA_EXPORT_ROOT,
    dlna_config_xml_file=DLNA_CONFIG_XML_FILE,
    dlna_service_unit_file=DLNA_SERVICE_UNIT_FILE,
    get_dlna_icon_state=build_dlna_icon_state,
)


def get_assignable_dlna_collections_for_current_user():
    return DLNA_LIBRARY_SERVICE.get_assignable_collections_for_user(
        username=get_current_username(),
        is_admin=is_admin_authenticated(),
    )


def assign_file_to_dlna_collection(storage_kind, relative_path, collection_id, sync_runtime=True, return_details=False):
    parsed_relative = parse_managed_relative_path(relative_path)
    effective_relative_path = safe_relative_download_path(
        (parsed_relative or {}).get("user_relative_path") or relative_path
    )
    if is_temporary_download_artifact_name(os.path.basename(effective_relative_path or "")):
        raise ValueError("Nie można dodać do DLNA pliku tymczasowego z trwającego pobierania.")
    return DLNA_LIBRARY_SERVICE.assign_file_to_collection(
        storage_kind,
        relative_path,
        collection_id,
        sync_runtime=sync_runtime,
        allow_background=not has_request_context(),
        return_details=return_details,
    )

PAGE_STATE_SERVICE = PageStateService(
    get_mount_info=get_mount_info,
    get_config_snapshot=get_config_snapshot,
    get_daily_download_dir=get_daily_download_dir,
    get_all_maintenance_task_snapshots=get_all_maintenance_task_snapshots,
    get_storage_disk_state=get_storage_disk_state,
    refresh_ffmpeg_update_state=refresh_ffmpeg_update_state,
    refresh_yt_dlp_update_state=refresh_yt_dlp_update_state,
    refresh_app_update_state=refresh_app_update_state,
    refresh_dlna_package_state=refresh_dlna_package_state,
    refresh_radio_backend_package_state=refresh_radio_backend_package_state,
    get_dlna_service_state=get_dlna_service_state,
    get_radio_backend_service_state=get_radio_backend_service_state,
    get_flask_service_state=get_flask_service_state,
    build_user_management_rows=build_user_management_rows,
    get_dlna_page_state=DLNA_LIBRARY_SERVICE.get_page_state,
    get_authenticated_user=get_authenticated_user,
    is_admin_authenticated=is_admin_authenticated,
    pop_ui_flash=pop_ui_flash,
    render_template=render_template,
    base_page_template=BASE_PAGE_TEMPLATE,
    request_path_getter=lambda: request.path,
)


def stream_upstream_response(stream_url, page_url, fmt, download=False, download_filename=None):
    upstream_headers = build_upstream_headers(page_url, fmt)

    if request.headers.get("Range"):
        upstream_headers["Range"] = request.headers.get("Range")
    elif not download:
        upstream_headers["Range"] = "bytes=0-"

    upstream = requests.get(
        stream_url,
        headers=upstream_headers,
        stream=True,
        allow_redirects=True,
        timeout=(15, 120),
    )

    allowed_headers = {
        "Content-Type",
        "Content-Length",
        "Content-Range",
        "Accept-Ranges",
        "Last-Modified",
        "ETag",
        "Cache-Control",
    }

    response_headers = {}
    for header_name, header_value in upstream.headers.items():
        if header_name in allowed_headers:
            response_headers[header_name] = header_value

    if "Content-Type" not in response_headers:
        response_headers["Content-Type"] = guess_content_type(fmt.get("ext"))

    if download:
        response_headers["Content-Disposition"] = 'attachment; filename="%s"' % (
            safe_filename(download_filename or "video.bin")
        )

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=1024 * 512):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(
        generate(),
        status=upstream.status_code,
        headers=response_headers,
        direct_passthrough=True,
    )


build_dlna_json_response = partial(
    build_stateful_json_response,
    jsonify,
    state_builders={
        "dlna_state": get_dlna_page_state,
        "settings_state": get_settings_page_state,
    },
)

def configure_app(app):
    app.secret_key = CONFIG_APP_SECRET_KEY
    register_application_routes(app, globals())
    start_background_schedulers(globals())
    return app
