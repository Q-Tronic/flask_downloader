#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import platform
import re
import shlex
import shutil
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
    Flask,
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
    APP_PORT as CONFIG_APP_PORT,
    APP_SECRET_KEY as CONFIG_APP_SECRET_KEY,
    APP_SERVICE_NAME as CONFIG_SYSTEMD_SERVICE_NAME,
    AUDIO_DOWNLOAD_DIR as CONFIG_AUDIO_DOWNLOAD_DIR,
    DLNA_DEFAULT_PORT as CONFIG_DLNA_DEFAULT_PORT,
    DLNA_PREFERRED_REPO_CHANNEL as CONFIG_DLNA_PREFERRED_REPO_CHANNEL,
    DLNA_SERVICE_NAME as CONFIG_DLNA_SERVICE_NAME,
    DOWNLOAD_DIR as CONFIG_DOWNLOAD_DIR,
    MOUNT_POINT as CONFIG_MOUNT_POINT,
    SMB_CREDENTIALS_FILE as CONFIG_SMB_CREDENTIALS_FILE,
    SMB_SHARE as CONFIG_SMB_SHARE,
    USER_STORAGE_ROOT as CONFIG_USER_STORAGE_ROOT,
)
from flask_downloader.paths import (
    CONFIG_FILE,
    DATA_DIR,
    JOBS_FILE,
    LEGACY_CONFIG_FILE,
    PROJECT_ROOT,
    USERS_FILE,
    ensure_data_layout,
)
from flask_downloader.routes.auth import register_auth_routes
from flask_downloader.routes.dlna import register_dlna_routes
from flask_downloader.routes.downloads import register_download_routes
from flask_downloader.routes.main import register_main_routes
from flask_downloader.routes.settings import register_settings_routes
from flask_downloader.routes.users import register_user_management_routes
from flask_downloader.services.jobs_service import DownloadJobsService, JobViewService
from flask_downloader.services.maintenance_service import MaintenanceTaskService
from flask_downloader.services.storage_service import ManagedStorageService
from flask_downloader.services.system_service import SystemServiceHelper
from flask_downloader.services.download_service import DownloadPathService
from flask_downloader.services.source_service import SourceMediaService
from flask_downloader.services.ffmpeg_service import FfmpegMaintenanceService
from flask_downloader.services.ytdlp_service import YtDlpMaintenanceService
from flask_downloader.services.dlna_service import DlnaLibraryService
from flask_downloader.services.dlna_runtime_service import DlnaRuntimeService
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
from flask_downloader.utils import auth as auth_utils

app = Flask(
    __name__,
    template_folder=os.path.join(PROJECT_ROOT, "templates"),
    static_folder=os.path.join(PROJECT_ROOT, "static"),
)
app.secret_key = CONFIG_APP_SECRET_KEY
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
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"
USER_STORAGE_ROOT = CONFIG_USER_STORAGE_ROOT
DEFAULT_ADMIN_VIDEO_ROOT = os.path.join(USER_STORAGE_ROOT, DEFAULT_ADMIN_USERNAME, "video")
DEFAULT_ADMIN_AUDIO_ROOT = os.path.join(USER_STORAGE_ROOT, DEFAULT_ADMIN_USERNAME, "audio")
USER_STORAGE_LAYOUT_VERSION = 2

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
SYSTEMD_SERVICE_NAME = CONFIG_SYSTEMD_SERVICE_NAME
DLNA_PACKAGE_NAME = "gerbera"
DLNA_SYSTEM_SERVICE_NAME = "gerbera"
DLNA_CHECK_HOUR = 4
DLNA_SERVICE_NAME = CONFIG_DLNA_SERVICE_NAME
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
DLNA_CONFIG_DIR = os.path.join(DLNA_RUNTIME_ROOT, "config")
DLNA_SCRIPT_DIR = os.path.join(DLNA_CONFIG_DIR, "js")
DLNA_COMMON_SCRIPT_DIR = os.path.join(DLNA_SCRIPT_DIR, "common")
DLNA_CUSTOM_SCRIPT_DIR = os.path.join(DLNA_SCRIPT_DIR, "custom")
DLNA_LEGACY_SCRIPT_DIR = os.path.join(DLNA_SCRIPT_DIR, "legacy")
DLNA_LOG_DIR = os.path.join(DLNA_RUNTIME_ROOT, "logs")
DLNA_LOG_FILE = os.path.join(DLNA_LOG_DIR, "gerbera.log")
DLNA_LOG_MAX_BYTES = 5 * 1024 * 1024
DLNA_LOG_BROWSER_MAX_BYTES = 1024 * 1024
DLNA_LOG_TAIL_READ_BYTES = 256 * 1024
DLNA_CONFIG_XML_FILE = os.path.join(DLNA_CONFIG_DIR, "config.xml")
DLNA_VIRTUAL_LAYOUT_SCRIPT_FILE = os.path.join(DLNA_CUSTOM_SCRIPT_DIR, "zz_flask_dlna_layout.js")
DLNA_LEGACY_IMPORT_SCRIPT_FILE = os.path.join(DLNA_LEGACY_SCRIPT_DIR, "flask_dlna_import.js")
GERBERA_SYSTEM_SCRIPT_DIR = os.path.join("/usr", "share", "gerbera", "js")
DLNA_SERVICE_UNIT_FILE = os.path.join("/etc", "systemd", "system", "%s.service" % DLNA_SERVICE_NAME)
DLNA_DEFAULT_PORT = CONFIG_DLNA_DEFAULT_PORT
DLNA_ALLOWED_NETWORK = ipaddress.ip_network("192.168.0.0/16")
DLNA_ALL_COLLECTION_ID = "__all_active__"
DLNA_ALL_COLLECTION_NAME = "Wszystkie aktywne media"
DLNA_VIRTUAL_LAYOUT_VERSION = 4
GERBERA_CONFIG_NS = "http://gerbera.io/config/2"
GERBERA_LEGACY_CONFIG_NS = "http://mediatomb.cc/config/2"

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
FFMPEG_INSTALL_LOCK = threading.Lock()
FFMPEG_SCHEDULER_LOCK = threading.Lock()
FFMPEG_SCHEDULER_STARTED = False
DLNA_INSTALL_LOCK = threading.Lock()
DLNA_SCHEDULER_LOCK = threading.Lock()
DLNA_SCHEDULER_STARTED = False
DLNA_SYNC_LOCK = threading.Lock()
MAINTENANCE_TASKS_LOCK = threading.Lock()
MAINTENANCE_TASKS = {
    "yt_dlp_update": create_maintenance_task_state("Aktualizacja yt-dlp"),
    "ffmpeg_install": create_maintenance_task_state("Instalacja ffmpeg"),
    "dlna_install": create_maintenance_task_state("Instalacja serwera DLNA"),
}
MAINTENANCE_SERVICE = MaintenanceTaskService(
    MAINTENANCE_TASKS,
    MAINTENANCE_TASKS_LOCK,
    create_maintenance_task_state,
    lambda ts: format_ts(ts),
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


APP_CONFIG_LOCK = threading.Lock()
USER_STORE_LOCK = threading.Lock()


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
            and job.get("status") in ("queued", "downloading")
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

    return build_managed_relative_path(next_owner, parsed["storage_kind"], parsed["user_relative_path"])


def compute_rebased_user_filepath(path, previous_username, next_username, storage_kind="video"):
    text = str(path or "").strip()
    if not text:
        return text

    previous_owner = normalize_username(previous_username)
    next_owner = normalize_username(next_username)
    normalized_storage_kind = normalize_storage_kind(storage_kind or "video")
    candidate = os.path.abspath(text)
    previous_root = os.path.abspath(get_user_storage_root(previous_owner, normalized_storage_kind))
    next_root = os.path.abspath(get_user_storage_root(next_owner, normalized_storage_kind))
    try:
        if os.path.commonpath([previous_root, candidate]) != previous_root:
            return candidate
        suffix = os.path.relpath(candidate, previous_root).replace("\\", "/")
    except Exception:
        return candidate
    return os.path.abspath(os.path.join(next_root, suffix.replace("/", os.sep)))


def move_user_storage_root(previous_username, next_username):
    previous_owner = normalize_username(previous_username)
    next_owner = normalize_username(next_username)
    previous_root = os.path.abspath(get_user_root(previous_owner))
    next_root = os.path.abspath(get_user_root(next_owner))
    base_root = os.path.abspath(get_user_storage_base_root())

    if previous_root == next_root:
        ensure_directory(get_user_storage_root(next_owner, "video"))
        ensure_directory(get_user_storage_root(next_owner, "audio"))
        return next_root

    try:
        if os.path.commonpath([base_root, previous_root]) != base_root or os.path.commonpath([base_root, next_root]) != base_root:
            raise ValueError("Ścieżka użytkownika wykracza poza katalog bazowy.")
    except Exception as exc:
        raise ValueError("Nie można bezpiecznie przenieść katalogu użytkownika.") from exc

    if os.path.lexists(next_root):
        raise ValueError("Docelowy katalog użytkownika już istnieje na dysku. Wybierz inny login.")

    if os.path.isdir(previous_root):
        shutil.move(previous_root, next_root)

    ensure_directory(get_user_storage_root(next_owner, "video"))
    ensure_directory(get_user_storage_root(next_owner, "audio"))
    return next_root


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
                current_root = os.path.abspath(get_user_root(next_owner))
                previous_root = os.path.abspath(get_user_root(previous_owner))
                if os.path.isdir(current_root) and not os.path.lexists(previous_root):
                    shutil.move(current_root, previous_root)

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
    for storage_kind in ("video", "audio"):
        root = get_user_storage_root(owner, storage_kind)
        if not os.path.isdir(root):
            continue
        for _, _, filenames in os.walk(root):
            for name in filenames:
                if not is_temporary_download_artifact_name(name):
                    total += 1
    return total


def count_user_jobs(username):
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
        prefix = normalized_username + "/"
        for rule in dlna_config.get("media_rules") or []:
            relative_path = safe_relative_download_path(rule.get("relative_path") or "")
            if relative_path.startswith(prefix):
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

    user_root = os.path.abspath(get_user_root(normalized_username))
    base_root = os.path.abspath(get_user_storage_base_root())
    try:
        if os.path.commonpath([base_root, user_root]) != base_root:
            raise ValueError("Ścieżka użytkownika wykracza poza katalog bazowy.")
    except Exception as exc:
        raise ValueError("Nie można bezpiecznie usunąć katalogu użytkownika.") from exc

    if os.path.isdir(user_root):
        shutil.rmtree(user_root)

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
        "collections": [],
        "clients": [],
        "media_rules": [],
        "layout_version": 0,
        "last_sync_at": 0.0,
        "last_sync_error": "",
    }


def default_app_config():
    return {
        "user_storage_root": USER_STORAGE_ROOT,
        "user_storage_layout_version": USER_STORAGE_LAYOUT_VERSION,
        "download_root": DEFAULT_ADMIN_VIDEO_ROOT,
        "audio_download_root": DEFAULT_ADMIN_AUDIO_ROOT,
        "job_retention_days": DEFAULT_COMPLETED_JOB_RETENTION_DAYS,
        "yt_dlp_update_state": {
            "latest_version": "",
            "checked_at": 0.0,
            "check_error": "",
        },
        "ffmpeg_update_state": default_ffmpeg_update_state(),
        "dlna_update_state": default_dlna_update_state(),
        "dlna": default_dlna_config(),
    }


def normalize_storage_root(value):
    path = os.path.abspath(str(value or "").strip())
    mount_root = os.path.abspath(MOUNT_POINT)

    if not path:
        raise ValueError("Katalog pobierania nie może być pusty.")

    if os.path.commonpath([mount_root, path]) != mount_root:
        raise ValueError("Katalog pobierania musi znajdować się w obrębie %s." % MOUNT_POINT)

    return path.rstrip("/\\") or mount_root


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


def normalize_dlna_update_state(value):
    state = default_dlna_update_state()

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


def normalize_dlna_server_name(value):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        raise ValueError("Nazwa serwera DLNA nie może być pusta.")
    return text[:120]


def normalize_dlna_bind_ip(value):
    text = str(value or "").strip()
    if not text:
        return ""

    try:
        address = ipaddress.ip_address(text)
    except Exception as exc:
        raise ValueError("Adres IP serwera DLNA jest nieprawidłowy.") from exc

    if address.version != 4 or address not in DLNA_ALLOWED_NETWORK:
        raise ValueError("Adres IP serwera DLNA musi należeć do sieci %s." % DLNA_ALLOWED_NETWORK)

    return str(address)


def normalize_dlna_port(value):
    try:
        port = int(str(value or "").strip())
    except Exception as exc:
        raise ValueError("Port DLNA musi być liczbą całkowitą.") from exc

    if port < 49152 or port > 65535:
        raise ValueError("Port DLNA musi mieścić się w zakresie 49152-65535.")

    return port


def normalize_dlna_collection_name(value):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        raise ValueError("Nazwa kolekcji nie może być pusta.")
    return text[:80]


def normalize_dlna_description(value, max_len=240):
    return re.sub(r"\s+", " ", str(value or "").strip())[:max_len]


def normalize_dlna_collection_id(value, fallback=None):
    text = re.sub(r"[^a-zA-Z0-9_-]+", "", str(value or "").strip())
    if text:
        return text[:48]
    if fallback:
        return fallback[:48]
    return uuid.uuid4().hex


def normalize_dlna_collection_entry(raw, existing_ids=None):
    if not isinstance(raw, dict):
        return None

    try:
        name = normalize_dlna_collection_name(raw.get("name"))
    except Exception:
        return None

    collection_id = normalize_dlna_collection_id(raw.get("id"))
    if existing_ids is not None:
        while collection_id in existing_ids or collection_id == DLNA_ALL_COLLECTION_ID:
            collection_id = uuid.uuid4().hex
        existing_ids.add(collection_id)

    return {
        "id": collection_id,
        "name": name,
        "description": normalize_dlna_description(raw.get("description"), max_len=320),
    }


def normalize_dlna_client_ip(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("Adres IP klienta nie może być pusty.")

    try:
        address = ipaddress.ip_address(text)
    except Exception as exc:
        raise ValueError("Adres IP klienta jest nieprawidłowy.") from exc

    if address.version != 4 or address not in DLNA_ALLOWED_NETWORK:
        raise ValueError("Adres IP klienta musi należeć do sieci %s." % DLNA_ALLOWED_NETWORK)

    return str(address)


def normalize_dlna_client_entry(raw, valid_collection_ids, valid_usernames):
    if not isinstance(raw, dict):
        return None

    try:
        ip = normalize_dlna_client_ip(raw.get("ip"))
    except Exception:
        return None

    collection_ids = []
    seen = set()
    for item in raw.get("collection_ids") or []:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        if value != DLNA_ALL_COLLECTION_ID and value not in valid_collection_ids:
            continue
        seen.add(value)
        collection_ids.append(value)

    usernames = []
    seen_usernames = set()
    for item in raw.get("usernames") or []:
        try:
            value = normalize_username(item)
        except Exception:
            continue
        if not value or value in seen_usernames or value not in valid_usernames:
            continue
        seen_usernames.add(value)
        usernames.append(value)

    return {
        "id": normalize_dlna_collection_id(raw.get("id")),
        "ip": ip,
        "description": normalize_dlna_description(raw.get("description"), max_len=200),
        "enabled": bool(raw.get("enabled", True)),
        "collection_ids": collection_ids,
        "usernames": usernames,
    }


def normalize_dlna_config_storage_kind(value):
    return "audio" if str(value or "").strip().lower() == "audio" else "video"


def normalize_dlna_config_relative_path(value):
    path = str(value or "").strip().replace("\\", "/")
    if not path:
        return ""

    normalized = os.path.normpath(path).replace("\\", "/").lstrip("/")
    if normalized in ("", ".", "..") or normalized.startswith("../"):
        return ""

    return normalized


def normalize_dlna_media_rule_entry(raw, valid_collection_ids):
    if not isinstance(raw, dict):
        return None

    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in ("file", "folder"):
        return None

    relative_path = normalize_dlna_config_relative_path(raw.get("relative_path") or raw.get("path") or "")
    if not relative_path:
        return None

    collection_ids = []
    seen = set()
    for item in raw.get("collection_ids") or []:
        value = str(item or "").strip()
        if not value or value in seen or value == DLNA_ALL_COLLECTION_ID:
            continue
        if value not in valid_collection_ids:
            continue
        seen.add(value)
        collection_ids.append(value)

    return {
        "id": normalize_dlna_collection_id(raw.get("id")),
        "kind": kind,
        "storage_kind": normalize_dlna_config_storage_kind(raw.get("storage_kind") or "video"),
        "relative_path": relative_path,
        "enabled": bool(raw.get("enabled", True)),
        "collection_ids": collection_ids,
    }


def normalize_dlna_config(value):
    state = default_dlna_config()

    if not isinstance(value, dict):
        return state

    try:
        server_name = normalize_dlna_server_name(value.get("server_name", state["server_name"]))
    except Exception:
        server_name = state["server_name"]

    try:
        bind_ip = normalize_dlna_bind_ip(value.get("bind_ip", state["bind_ip"]))
    except Exception:
        bind_ip = state["bind_ip"]

    try:
        port = normalize_dlna_port(value.get("port", state["port"]))
    except Exception:
        port = state["port"]

    collection_items = []
    collection_ids = set()
    for raw in value.get("collections") or []:
        item = normalize_dlna_collection_entry(raw, existing_ids=collection_ids)
        if item:
            collection_items.append(item)

    valid_collection_ids = {item["id"] for item in collection_items}
    valid_usernames = {
        str(item.get("username") or "").strip()
        for item in (get_users_snapshot() or [])
        if str(item.get("username") or "").strip()
    }
    client_items = []
    seen_ips = set()
    for raw in value.get("clients") or []:
        item = normalize_dlna_client_entry(raw, valid_collection_ids, valid_usernames)
        if not item or item["ip"] in seen_ips:
            continue
        seen_ips.add(item["ip"])
        client_items.append(item)

    rule_items = []
    seen_rules = set()
    for raw in value.get("media_rules") or []:
        item = normalize_dlna_media_rule_entry(raw, valid_collection_ids)
        if not item:
            continue
        key = (item["kind"], item["storage_kind"], item["relative_path"])
        if key in seen_rules:
            continue
        seen_rules.add(key)
        rule_items.append(item)

    try:
        last_sync_at = float(value.get("last_sync_at") or 0.0)
    except Exception:
        last_sync_at = 0.0
    try:
        layout_version = max(0, int(value.get("layout_version") or 0))
    except Exception:
        layout_version = 0

    state.update({
        "enabled": bool(value.get("enabled")),
        "server_name": server_name,
        "bind_ip": bind_ip,
        "port": port,
        "collections": collection_items,
        "clients": client_items,
        "media_rules": rule_items,
        "layout_version": layout_version,
        "last_sync_at": last_sync_at,
        "last_sync_error": str(value.get("last_sync_error") or "").strip(),
    })
    return state


def load_app_config():
    return config_store_load_app_config(
        CONFIG_FILE,
        default_app_config,
        normalize_user_storage_root,
        normalize_download_root,
        normalize_audio_download_root,
        normalize_retention_days,
        normalize_yt_dlp_update_state,
        normalize_ffmpeg_update_state,
        normalize_dlna_update_state,
        normalize_dlna_config,
    )


def recover_legacy_dlna_config_if_needed(config_data):
    current_data = copy.deepcopy(config_data or {})
    current_dlna = normalize_dlna_config(current_data.get("dlna"))
    current_data["dlna"] = current_dlna

    if current_dlna.get("collections") or current_dlna.get("clients") or current_dlna.get("media_rules"):
        return current_data, False

    if not os.path.isfile(LEGACY_CONFIG_FILE):
        return current_data, False

    try:
        with open(LEGACY_CONFIG_FILE, "r", encoding="utf-8") as fh:
            legacy_raw = json.load(fh) or {}
    except Exception:
        return current_data, False

    legacy_dlna = normalize_dlna_config((legacy_raw or {}).get("dlna"))
    if not (legacy_dlna.get("collections") or legacy_dlna.get("clients") or legacy_dlna.get("media_rules")):
        return current_data, False

    current_data["dlna"] = legacy_dlna
    return current_data, True


APP_CONFIG, LEGACY_DLNA_CONFIG_RECOVERED = recover_legacy_dlna_config_if_needed(load_app_config())
if LEGACY_DLNA_CONFIG_RECOVERED:
    config_store_write_app_config(CONFIG_FILE, APP_CONFIG)


def write_app_config_locked():
    config_store_write_app_config(CONFIG_FILE, APP_CONFIG)


def save_app_config(download_root, audio_download_root, job_retention_days):
    previous_config = get_config_snapshot()
    previous_user_root = os.path.abspath(previous_config.get("user_storage_root") or USER_STORAGE_ROOT)
    normalized_user_root = normalize_user_storage_root(download_root)
    next_user_root = os.path.abspath(normalized_user_root)
    normalized_days = normalize_retention_days(job_retention_days)

    payload = {
        "user_storage_root": normalized_user_root,
        "user_storage_layout_version": USER_STORAGE_LAYOUT_VERSION,
        "download_root": os.path.join(normalized_user_root, DEFAULT_ADMIN_USERNAME, "video"),
        "audio_download_root": os.path.join(normalized_user_root, DEFAULT_ADMIN_USERNAME, "audio"),
        "job_retention_days": normalized_days,
    }

    path_map = {}
    if previous_user_root != next_user_root and os.path.isdir(previous_user_root):
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
        write_app_config_locked()

    return dict(payload)


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


STORAGE_SERVICE = ManagedStorageService(
    get_config_snapshot=get_config_snapshot,
    normalize_username=normalize_username,
    normalize_storage_kind=normalize_storage_kind,
    get_current_username=lambda: get_current_username(),
    default_admin_username=DEFAULT_ADMIN_USERNAME,
    has_request_context=has_request_context,
    is_admin_authenticated=lambda: is_admin_authenticated(),
    ensure_share_ready=lambda auto_remount=True: ensure_share_ready(auto_remount=auto_remount),
    format_ts=lambda ts: format_ts(ts),
)


def get_user_storage_base_root():
    return STORAGE_SERVICE.get_user_storage_base_root()


def get_user_root(username):
    return STORAGE_SERVICE.get_user_root(username)


def get_user_storage_root(username, storage_kind="video"):
    return STORAGE_SERVICE.get_user_storage_root(username, storage_kind)


def build_managed_relative_path(owner_username, storage_kind="video", user_relative_path=""):
    return STORAGE_SERVICE.build_managed_relative_path(owner_username, storage_kind, user_relative_path)


def parse_managed_relative_path(value):
    return STORAGE_SERVICE.parse_managed_relative_path(value)


def get_managed_path_info(path):
    return STORAGE_SERVICE.get_managed_path_info(path)


def get_storage_root(storage_kind="video", owner_username=None):
    return STORAGE_SERVICE.get_storage_root(storage_kind, owner_username)


def get_managed_storage_roots():
    return STORAGE_SERVICE.get_managed_storage_roots()


def get_storage_kind_for_path(path):
    return STORAGE_SERVICE.get_storage_kind_for_path(path)


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


def get_relative_download_path(path, media_kind=None, owner_username=None):
    return STORAGE_SERVICE.get_relative_download_path(path, media_kind=media_kind, owner_username=owner_username)


def safe_relative_download_path(value):
    return STORAGE_SERVICE.safe_relative_download_path(value)


def resolve_download_path(relative_path, media_kind="video", owner_username=None):
    return STORAGE_SERVICE.resolve_download_path(relative_path, media_kind=media_kind, owner_username=owner_username)


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
    allowed_statuses = {"queued", "downloading", "completed", "failed", "canceled"}
    raw_owner_username = raw.get("owner_username") or DEFAULT_ADMIN_USERNAME

    try:
        owner_username = normalize_username(raw_owner_username)
    except Exception:
        owner_username = DEFAULT_ADMIN_USERNAME

    job = {
        "job_id": str(raw.get("job_id") or default_job_id),
        "owner_username": owner_username,
        "page_url": str(raw.get("page_url") or ""),
        "format_id": str(raw.get("format_id") or ""),
        "storage_kind": normalize_storage_kind(raw.get("storage_kind") or "video"),
        "status": str(raw.get("status") or "failed"),
        "status_label": str(raw.get("status_label") or "Nieznany"),
        "title": str(raw.get("title") or ""),
        "label": str(raw.get("label") or ""),
        "filename": str(raw.get("filename") or ""),
        "planned_filename": str(raw.get("planned_filename") or raw.get("filename") or ""),
        "filepath": str(raw.get("filepath") or ""),
        "relative_path": safe_relative_download_path(raw.get("relative_path") or ""),
        "downloaded_bytes": 0,
        "total_bytes": None,
        "progress_percent": None,
        "error": str(raw.get("error") or ""),
        "created_at": now_ts,
        "started_at": None,
        "finished_at": None,
        "overwrite_existing": bool(raw.get("overwrite_existing")),
        "replace_paths": [str(path) for path in (raw.get("replace_paths") or []) if path],
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
        "storage_kind": normalize_storage_kind(job.get("storage_kind") or "video"),
        "status": str(job.get("status") or ""),
        "status_label": str(job.get("status_label") or ""),
        "title": str(job.get("title") or ""),
        "label": str(job.get("label") or ""),
        "filename": str(job.get("filename") or ""),
        "planned_filename": str(job.get("planned_filename") or ""),
        "filepath": str(job.get("filepath") or ""),
        "relative_path": safe_relative_download_path(job.get("relative_path") or ""),
        "downloaded_bytes": int(job.get("downloaded_bytes") or 0),
        "total_bytes": int(job.get("total_bytes")) if job.get("total_bytes") not in (None, "", False) else None,
        "progress_percent": float(job.get("progress_percent")) if job.get("progress_percent") not in (None, "", False) else None,
        "error": str(job.get("error") or ""),
        "created_at": float(job.get("created_at") or 0.0),
        "started_at": float(job.get("started_at")) if job.get("started_at") not in (None, "", False) else None,
        "finished_at": float(job.get("finished_at")) if job.get("finished_at") not in (None, "", False) else None,
        "overwrite_existing": bool(job.get("overwrite_existing")),
        "replace_paths": [str(path) for path in (job.get("replace_paths") or []) if path],
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
        parsed_relative = parse_managed_relative_path(relative_path)
        if parsed_relative is None and relative_path:
            job["relative_path"] = build_managed_relative_path(owner_username, storage_kind, relative_path)
            changed = True
        elif parsed_relative and (
            parsed_relative["owner_username"] != owner_username
            or parsed_relative["storage_kind"] != storage_kind
        ):
            job["relative_path"] = build_managed_relative_path(owner_username, storage_kind, parsed_relative["user_relative_path"])
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


def migrate_legacy_dlna_rules(config):
    if not isinstance(config, dict):
        return config, False

    changed = False
    media_rules = []
    for raw_rule in config.get("media_rules") or []:
        if not isinstance(raw_rule, dict):
            continue

        rule = dict(raw_rule)
        storage_kind = normalize_storage_kind(rule.get("storage_kind") or "video")
        relative_path = safe_relative_download_path(rule.get("relative_path") or "")
        parsed = parse_managed_relative_path(relative_path)
        if relative_path and parsed is None:
            rule["relative_path"] = build_managed_relative_path(DEFAULT_ADMIN_USERNAME, storage_kind, relative_path)
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
        migrated_dlna_config, dlna_changed = migrate_legacy_dlna_rules(normalize_dlna_config(APP_CONFIG.get("dlna")))
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

            jobs[job_id] = job

        if changed:
            jobs_store_write_jobs_payload(
                JOBS_FILE,
                [serialize_job_for_storage(job) for job in jobs.values()],
            )
    except Exception:
        return {}

    return jobs


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


def safe_next_url(value):
    return auth_utils.safe_next_url(value)


def set_ui_flash(message, kind="success"):
    auth_utils.set_ui_flash(message, kind)


def pop_ui_flash():
    return auth_utils.pop_ui_flash()


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


def wants_json_response():
    return auth_utils.wants_json_response()


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


def build_dlna_json_response(ok=True, message="", kind="success", status_code=200, **extra):
    payload = {
        "ok": bool(ok),
        "message": str(message or ""),
        "kind": str(kind or ("success" if ok else "error")),
        "dlna_state": get_dlna_page_state(),
        "settings_state": get_settings_page_state(),
    }
    payload.update(extra)
    response = jsonify(payload)
    if status_code and status_code != 200:
        return response, status_code
    return response


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
        "dlna_package_state": get_dlna_package_state_snapshot(),
        "dlna_service_state": get_dlna_service_state(),
        "tasks": get_all_maintenance_task_snapshots(),
    }


def get_settings_page_state(include_user_rows=False):
    state = {
        "mount": get_mount_info(auto_remount=True),
        "config": get_config_snapshot(),
        "today_download_dir": get_daily_download_dir(),
        "today_audio_download_dir": get_daily_download_dir(media_kind="audio"),
        "maintenance_tasks": get_all_maintenance_task_snapshots(),
        "ffmpeg_state": refresh_ffmpeg_update_state(force=False),
        "yt_dlp_state": refresh_yt_dlp_update_state(force=False),
        "dlna_package_state": refresh_dlna_package_state(force=False),
        "dlna_service_state": get_dlna_service_state(),
        "service_state": get_flask_service_state(),
    }
    if include_user_rows:
        state["user_rows"] = build_user_management_rows()
    return state


def get_dlna_page_state():
    return DLNA_LIBRARY_SERVICE.get_page_state()


def render_page(page_title, active_page, content_template, **context):
    auth_user = get_authenticated_user()
    admin_logged_in = is_admin_authenticated()
    current_user = auth_user or {}
    template_context = dict(context)
    return render_template(
        BASE_PAGE_TEMPLATE,
        page_template=content_template,
        page_title=page_title,
        active_page=active_page,
        current_path=request.path,
        admin_logged_in=admin_logged_in,
        logged_in=bool(auth_user),
        current_user=current_user,
        current_role=str(current_user.get("role") or ""),
        flash=pop_ui_flash(),
        **template_context,
    )


class DownloadCancelledError(Exception):
    pass


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
    value = str(value or "").strip()
    value = re.sub(r'[\\\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._ ")
    return value[:180] or default


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


def make_label(fmt):
    return SOURCE_MEDIA_SERVICE.make_label(fmt)


def normalize_info(info):
    return SOURCE_MEDIA_SERVICE.normalize_info(info)


def filter_formats(info):
    return SOURCE_MEDIA_SERVICE.filter_formats(info)


def extract_video_data(page_url, force_refresh=False):
    return SOURCE_MEDIA_SERVICE.extract_video_data(page_url, force_refresh=force_refresh)


def build_proxy_url(page_url, format_id):
    return SOURCE_MEDIA_SERVICE.build_proxy_url(page_url, format_id)


def build_download_url(page_url, format_id):
    return SOURCE_MEDIA_SERVICE.build_download_url(page_url, format_id)


def build_result_with_proxy_urls(result, request_root):
    return SOURCE_MEDIA_SERVICE.build_result_with_proxy_urls(result, request_root)


def find_format(result, format_id):
    return SOURCE_MEDIA_SERVICE.find_format(result, format_id)


def format_bytes_text(num_bytes):
    return SOURCE_MEDIA_SERVICE.format_bytes_text(num_bytes)


def get_source_download_match_state(result, format_id, owner_username=None):
    return SOURCE_MEDIA_SERVICE.get_source_download_match_state(result, format_id, owner_username=owner_username)


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


def run_command(cmd):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
        return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
    except Exception as exc:
        return 999, "", str(exc)


def mount_share_direct():
    options = (
        "credentials=%s,"
        "iocharset=utf8,"
        "uid=www-data,"
        "gid=www-data,"
        "file_mode=0664,"
        "dir_mode=0775,"
        "noperm,"
        "nofail,"
        "_netdev,"
        "vers=3.0,"
        "prefixpath=WP.to.XXX"
    ) % SMB_CREDENTIALS_FILE

    commands = [
        ["/usr/bin/mount", MOUNT_POINT],
        ["/bin/mount", MOUNT_POINT],
        ["/usr/bin/mount", "-t", "cifs", SMB_SHARE, MOUNT_POINT, "-o", options],
        ["/bin/mount", "-t", "cifs", SMB_SHARE, MOUNT_POINT, "-o", options],
        ["/usr/bin/mount", "-a"],
        ["/bin/mount", "-a"],
        ["/usr/bin/sudo", "-n", "/usr/bin/mount", MOUNT_POINT],
        ["/usr/bin/sudo", "-n", "/bin/mount", MOUNT_POINT],
        ["/usr/bin/sudo", "-n", "/usr/bin/mount", "-a"],
        ["/usr/bin/sudo", "-n", "/bin/mount", "-a"],
    ]

    errors = []

    for cmd in commands:
        if not os.path.exists(cmd[0]):
            continue

        code, out, err = run_command(cmd)

        if code == 0 and os.path.ismount(MOUNT_POINT):
            return True, "Zamontowano udział: %s -> %s" % (SMB_SHARE, MOUNT_POINT)

        text = " ".join(cmd) + " :: " + (err or out or "nieznany błąd")
        errors.append(text)

        if os.path.ismount(MOUNT_POINT):
            return True, "Zamontowano udział: %s -> %s" % (SMB_SHARE, MOUNT_POINT)

    return False, "\\n".join(errors[-4:]) if errors else "Nie udało się wykonać polecenia montowania."


def check_download_dir_ready(storage_kind="video", owner_username=None):
    return DOWNLOAD_PATH_SERVICE.check_download_dir_ready(storage_kind=storage_kind, owner_username=owner_username)


def ensure_share_ready(auto_remount=True):
    global LAST_MOUNT_ATTEMPT_TS

    ok, message = check_download_dir_ready("video")
    if ok:
        set_mount_status(True, message)
        return True, message

    now = time.time()
    if auto_remount and (now - LAST_MOUNT_ATTEMPT_TS >= MOUNT_RETRY_COOLDOWN):
        LAST_MOUNT_ATTEMPT_TS = now
        try:
            os.makedirs(MOUNT_POINT, exist_ok=True)
        except Exception:
            pass

        mounted, mount_message = mount_share_direct()
        if mounted:
            ok, message = check_download_dir_ready()
            if ok:
                set_mount_status(True, message)
                return True, message
            set_mount_status(False, message)
            return False, message

        set_mount_status(False, "Automatyczne ponowne montowanie nie powiodło się.\\n%s" % mount_message)
        return False, LAST_MOUNT_STATUS["message"]

    set_mount_status(False, message)
    return False, message


def get_mount_info(auto_remount=True, viewer_username=None, is_admin=None):
    online, message = ensure_share_ready(auto_remount=auto_remount)
    admin_view = is_admin_authenticated() if is_admin is None else bool(is_admin)
    username = str(viewer_username or get_current_username() or "").strip()
    video_dir = get_daily_download_dir(owner_username=username or DEFAULT_ADMIN_USERNAME)
    audio_dir = get_daily_download_dir(media_kind="audio", owner_username=username or DEFAULT_ADMIN_USERNAME)
    public_message = message if admin_view else (
        "Przestrzeń użytkowników jest gotowa."
        if online else
        "Przestrzeń użytkowników jest teraz niedostępna."
    )
    return {
        "online": online,
        "message": public_message,
        "mount_point": MOUNT_POINT,
        "download_root": get_download_root() if admin_view else "",
        "audio_download_root": get_audio_download_root() if admin_view else "",
        "download_dir": video_dir if admin_view else "video/%s" % get_daily_folder_name(),
        "audio_download_dir": audio_dir if admin_view else "audio/%s" % get_daily_folder_name(),
        "user_storage_root": get_user_storage_base_root() if admin_view else "",
        "owner_username": username,
        "checked_at": LAST_MOUNT_STATUS["checked_at"],
    }


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


def mark_job_cancel_requested(job_id):
    return DOWNLOAD_JOBS_SERVICE.mark_job_cancel_requested(job_id)


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

    try:
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

        if is_job_cancelled(job_id):
            raise DownloadCancelledError("Pobieranie anulowane przed rozpoczęciem.")

        ensure_download_dir_ready(storage_kind, owner_username)

        result = extract_video_data(page_url, force_refresh=True)
        fmt = find_format(result, format_id)
        if not fmt:
            raise RuntimeError("Nie znaleziono wskazanego formatu.")

        if not filename:
            filename = build_download_filename(result["title"], fmt)

        temp_filename = replace_filename_extension(filename, get_download_intermediate_ext(fmt))
        if storage_kind == "audio":
            ensure_ffmpeg_available_for_audio_conversion()

        target_path = allocate_target_path(temp_filename, media_kind=storage_kind, owner_username=owner_username)
        seen_paths.add(target_path)

        update_job(
            job_id,
            status="downloading",
            status_label="Pobieranie i konwersja" if storage_kind == "audio" else "Pobieranie",
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
            persist=True,
        )

        if is_job_cancelled(job_id):
            raise DownloadCancelledError("Pobieranie anulowane przed otwarciem strumienia.")

        def progress_hook(status):
            nonlocal downloaded, total_bytes, target_path, relative_path

            hook_filename = status.get("filename")
            hook_tmpfilename = status.get("tmpfilename")
            info_dict = status.get("info_dict") or {}

            for path in (hook_filename, hook_tmpfilename, info_dict.get("filepath")):
                if path and path != "-":
                    seen_paths.add(os.path.abspath(path))

            if is_job_cancelled(job_id):
                raise DownloadCancelledError("Pobieranie zostało przerwane przez użytkownika.")

            status_name = status.get("status") or ""
            downloaded = int(status.get("downloaded_bytes") or downloaded or 0)
            total_candidate = status.get("total_bytes") or status.get("total_bytes_estimate") or total_bytes
            total_bytes = int(total_candidate) if isinstance(total_candidate, (int, float)) else total_candidate

            current_filename = hook_filename or info_dict.get("filepath") or target_path
            if current_filename and current_filename != "-":
                target_path = os.path.abspath(current_filename)
                relative_path = get_relative_download_path(target_path, storage_kind, owner_username)

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
                    relative_path=relative_path or get_relative_download_path(target_path, storage_kind, owner_username),
                )
                return

            if status_name == "downloading":
                update_job(
                    job_id,
                    downloaded_bytes=downloaded,
                    total_bytes=total_bytes,
                    progress_percent=progress_percent if progress_percent is not None else 0.0,
                    relative_path=relative_path or get_relative_download_path(target_path, storage_kind, owner_username),
                )

        ydl_download_opts = apply_ffmpeg_location({
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "http_headers": {
                "User-Agent": USER_AGENT,
            },
            "format": str(fmt.get("download_format") or format_id),
            "outtmpl": target_path,
            "noplaylist": True,
            "overwrites": False,
            "progress_hooks": [progress_hook],
        })

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
            filepath = item.get("filepath")
            if filepath:
                seen_paths.add(os.path.abspath(filepath))

        final_path = download_info.get("filepath")
        if not final_path and requested_downloads:
            final_path = requested_downloads[-1].get("filepath")

        if final_path:
            target_path = os.path.abspath(final_path)
            seen_paths.add(target_path)

        relative_path = get_relative_download_path(target_path, storage_kind, owner_username)

        actual_size = 0
        try:
            actual_size = os.path.getsize(target_path)
        except Exception:
            actual_size = downloaded

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
            status_label="Ukończone",
            downloaded_bytes=downloaded,
            progress_percent=100.0,
            finished_at=time.time(),
            filepath=target_path,
            filename=os.path.basename(target_path),
            relative_path=relative_path,
            persist=True,
        )
        sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)

    except DownloadCancelledError as exc:
        cleanup_download_artifacts(seen_paths)

        update_job(
            job_id,
            status="canceled",
            status_label="Anulowane",
            error=str(exc),
            finished_at=time.time(),
            progress_percent=0.0,
            downloaded_bytes=downloaded,
            filepath="",
            filename=filename,
            relative_path="",
            persist=True,
        )

    except Exception as exc:
        cleanup_download_artifacts(seen_paths)

        update_job(
            job_id,
            status="failed",
            status_label="Niepowodzenie",
            error=str(exc),
            finished_at=time.time(),
            filepath="",
            relative_path="",
            persist=True,
        )

    finally:
        cleanup_job_cancel_handle(job_id)


def get_jobs_snapshot():
    return DOWNLOAD_JOBS_SERVICE.get_jobs_snapshot()


def format_ts(ts):
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def format_duration(seconds):
    try:
        total = int(max(0, float(seconds or 0)))
    except Exception:
        return "nieznany"

    days, rem = divmod(total, 24 * 60 * 60)
    hours, rem = divmod(rem, 60 * 60)
    minutes, secs = divmod(rem, 60)
    parts = []

    if days:
        parts.append("%sd" % days)
    if hours:
        parts.append("%sg" % hours)
    if minutes:
        parts.append("%smin" % minutes)
    if secs or not parts:
        parts.append("%ss" % secs)

    return " ".join(parts[:3])


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
    ensure_share_ready=ensure_share_ready,
    sync_dlna_runtime_safe=lambda restart_service_if_active=True, force_full_rescan=False: sync_dlna_runtime_safe(
        restart_service_if_active=restart_service_if_active,
        force_full_rescan=force_full_rescan,
    ),
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
    return DOWNLOAD_JOBS_SERVICE.delete_managed_file(
        relative_path,
        storage_kind=storage_kind,
        owner_username=owner_username,
    )


def get_server_files(scope_username=""):
    return STORAGE_SERVICE.get_server_files(scope_username=scope_username)


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
    for client in config.get("clients") or []:
        for username in get_dlna_client_assigned_usernames(client):
            if username in seen:
                continue
            seen.add(username)
            usernames.append(username)
    return usernames


def build_dlna_client_visible_root_ids(client, dlna_config=None):
    visible_root_ids = set(get_dlna_client_visible_collection_ids(client, dlna_config))
    for username in get_dlna_client_assigned_usernames(client):
        visible_root_ids.add(build_dlna_user_root_id(username))
    return visible_root_ids


def build_dlna_root_entry_map(dlna_config=None):
    config = dlna_config or get_dlna_config_snapshot()
    result = {}
    used_names = set()

    def add_root(root_id, title, kind, username=""):
        base_name = dlna_safe_dir_segment(title, default="kolekcja" if kind == "collection" else "uzytkownik")
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

    add_root(DLNA_ALL_COLLECTION_ID, DLNA_ALL_COLLECTION_NAME, "collection")
    for item in config.get("collections") or []:
        add_root(item["id"], item["name"], "collection")
    for username in get_dlna_referenced_usernames(config):
        add_root(build_dlna_user_root_id(username), username, "user", username=username)
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

    specs.sort(key=lambda item: (item["title"].lower(), item["location"].lower()))
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
  if (depth === 0) {
    return '2000_' + normalizedTitle.toLowerCase();
  }
  if (depth === 1) {
    return '3000_' + normalizedTitle.toLowerCase();
  }
  return '4000_' + normalizedTitle.toLowerCase();
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
  obj.sortKey = '';
  obj.title = obj.title || dlnaBasename(obj.location);
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
  if (parts.length > 2 && parts[2] === 'Wszystkie Pliki') {
    obj.sortKey = '0000_' + (obj.title || dlnaBasename(obj.location));
  } else {
    obj.sortKey = '';
  }
  obj.title = obj.title || dlnaBasename(obj.location);
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
        if process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=5)
            except Exception:
                pass
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
    key = str(channel_key or DLNA_PREFERRED_REPO_CHANNEL).strip().lower()
    if key not in DLNA_OFFICIAL_REPO_CHANNELS:
        key = DLNA_PREFERRED_REPO_CHANNEL
    data = dict(DLNA_OFFICIAL_REPO_CHANNELS.get(key) or {})
    data["key"] = key
    return data


def read_dlna_official_repo_line():
    try:
        with open(DLNA_OFFICIAL_REPO_LIST_FILE, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = str(raw_line or "").strip()
                if line and not line.startswith("#"):
                    return line
    except Exception:
        return ""
    return ""


def get_dlna_repo_source_snapshot(policy=None):
    raw_policy = str((policy or {}).get("raw_output") or "")
    repo_line = read_dlna_official_repo_line()
    source = {
        "channel_key": "system",
        "label": "Pakiet Debian / apt",
        "repo_line": repo_line,
    }

    if "pkg.gerbera.io/debian-git" in repo_line or "pkg.gerbera.io/debian-git" in raw_policy:
        channel = get_dlna_official_repo_channel("latest")
        source["channel_key"] = channel["key"]
        source["label"] = channel["label"]
        return source

    if "pkg.gerbera.io/debian/" in repo_line or "pkg.gerbera.io/debian/" in raw_policy:
        channel = get_dlna_official_repo_channel("stable")
        source["channel_key"] = channel["key"]
        source["label"] = channel["label"]
        return source

    return source


def download_dlna_official_repo_key_bytes():
    wget_path = shutil.which("wget")
    if wget_path:
        result = subprocess.run(
            [wget_path, "-qO-", DLNA_OFFICIAL_REPO_KEY_URL],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
            env=build_apt_query_env(),
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout

    response = requests.get(DLNA_OFFICIAL_REPO_KEY_URL, headers={"User-Agent": USER_AGENT}, timeout=45)
    response.raise_for_status()
    return response.content


def ensure_dlna_official_repo(channel_key="", progress_callback=None):
    if not is_linux_runtime():
        raise RuntimeError("Oficjalne repo Gerbera można skonfigurować tylko na serwerze Linux z apt.")

    channel = get_dlna_official_repo_channel(channel_key)
    codename = get_linux_distribution_codename()
    repo_line = "deb [signed-by=%s] https://pkg.gerbera.io/%s/ %s main" % (
        DLNA_OFFICIAL_REPO_KEYRING_FILE,
        channel["apt_path"],
        codename,
    )

    if progress_callback:
        progress_callback(
            status="running",
            status_label="Repozytorium",
            progress_percent=14.0,
            detail="Konfiguruję %s dla systemu %s." % (channel["label"], codename),
        )

    key_bytes = download_dlna_official_repo_key_bytes()
    if not key_bytes:
        raise RuntimeError("Nie udało się pobrać klucza GPG oficjalnego repo Gerbera.")

    gpg_binary = shutil.which("gpg")
    if not gpg_binary:
        raise RuntimeError("Brakuje binarki gpg potrzebnej do instalacji oficjalnego repo Gerbera.")

    ensure_directory(os.path.dirname(DLNA_OFFICIAL_REPO_KEYRING_FILE))
    ensure_directory(os.path.dirname(DLNA_OFFICIAL_REPO_LIST_FILE))

    ascii_tmp = ""
    gpg_tmp = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as ascii_fh:
            ascii_fh.write(key_bytes)
            ascii_tmp = ascii_fh.name
        with tempfile.NamedTemporaryFile(delete=False) as gpg_fh:
            gpg_tmp = gpg_fh.name

        result = subprocess.run(
            [gpg_binary, "--dearmor", "--yes", "--output", gpg_tmp, ascii_tmp],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
            env=build_apt_query_env(),
        )
        if result.returncode != 0 or not os.path.isfile(gpg_tmp) or os.path.getsize(gpg_tmp) <= 0:
            detail = (result.stderr or result.stdout or "gpg --dearmor zakończył się błędem.").strip()
            raise RuntimeError(detail[-1200:])

        os.replace(gpg_tmp, DLNA_OFFICIAL_REPO_KEYRING_FILE)
        try:
            os.chmod(DLNA_OFFICIAL_REPO_KEYRING_FILE, 0o644)
        except Exception:
            pass

        with open(DLNA_OFFICIAL_REPO_LIST_FILE, "w", encoding="utf-8") as fh:
            fh.write(repo_line + "\n")
    finally:
        for path in (ascii_tmp, gpg_tmp):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    return {
        "channel_key": channel["key"],
        "channel_label": channel["label"],
        "codename": codename,
        "repo_line": repo_line,
    }


def read_dpkg_installed_version(package_name):
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}|${Version}", package_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        check=False,
        env=build_apt_query_env(),
    )
    if result.returncode != 0:
        return ""

    output = str(result.stdout or "").strip()
    if not output:
        return ""

    parts = output.split("|", 1)
    if len(parts) != 2:
        return ""

    status_text = parts[0].strip().lower()
    version_text = parts[1].strip()
    if "install ok installed" not in status_text or not version_text:
        return ""
    return version_text


def get_apt_package_policy(package_name):
    if not is_linux_runtime():
        raise RuntimeError("Automatyczna obsługa pakietów DLNA wymaga Linuxa z apt.")

    result = subprocess.run(
        ["apt-cache", "policy", package_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
        env=build_apt_query_env(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Nie udało się odczytać stanu pakietu.").strip()
        raise RuntimeError(detail[-1200:])

    installed = read_dpkg_installed_version(package_name)
    candidate = ""
    for raw_line in (result.stdout or "").splitlines():
        line = raw_line.strip()
        if line.lower().startswith("installed:"):
            installed = line.split(":", 1)[1].strip()
        elif line.lower().startswith("candidate:"):
            candidate = line.split(":", 1)[1].strip()

    if installed == "(none)":
        installed = ""
    if candidate == "(none)":
        candidate = ""

    return {
        "installed": installed,
        "candidate": candidate,
        "raw_output": result.stdout or "",
    }


def get_last_due_dlna_check_dt(now=None):
    now = now or datetime.now()
    due = now.replace(hour=DLNA_CHECK_HOUR, minute=0, second=0, microsecond=0)
    if now < due:
        due -= timedelta(days=1)
    return due


def get_next_dlna_check_dt(now=None):
    return get_last_due_dlna_check_dt(now=now) + timedelta(days=1)


def needs_scheduled_dlna_check(last_checked_at, now=None):
    due_dt = get_last_due_dlna_check_dt(now=now)
    return not last_checked_at or float(last_checked_at or 0.0) < due_dt.timestamp()


def get_dlna_package_state_snapshot():
    with APP_CONFIG_LOCK:
        raw_state = normalize_dlna_update_state(APP_CONFIG.get("dlna_update_state"))
        dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))

    current_version = ""
    latest_version = raw_state["latest_version"]
    check_error = raw_state["check_error"]
    policy = None

    try:
        policy = get_apt_package_policy(DLNA_PACKAGE_NAME)
        current_version = policy["installed"]
        if policy["candidate"]:
            latest_version = policy["candidate"]
    except Exception as exc:
        if not check_error:
            check_error = str(exc)

    repo_source = get_dlna_repo_source_snapshot(policy=policy)
    preferred_channel = get_dlna_official_repo_channel()
    installed = bool(current_version)
    update_available = bool(installed and latest_version and latest_version != current_version)
    needs_repo_switch = repo_source["channel_key"] != preferred_channel["key"]
    action_needed = (not installed) or update_available or needs_repo_switch

    if installed and needs_repo_switch:
        status_pill_label = "Dostępna migracja do nowszego repo Gerbera"
        status_pill_kind = "queued"
    elif update_available:
        status_pill_label = "Dostępna aktualizacja serwera DLNA"
        status_pill_kind = "queued"
    elif installed:
        status_pill_label = "Serwer DLNA jest aktualny"
        status_pill_kind = "success"
    else:
        status_pill_label = "Serwer DLNA nie jest zainstalowany"
        status_pill_kind = "error"

    return {
        "package_name": DLNA_PACKAGE_NAME,
        "current_version": current_version or "brak",
        "latest_version": latest_version or "brak danych",
        "current_version_raw": current_version,
        "latest_version_raw": latest_version,
        "checked_at": raw_state["checked_at"],
        "checked_at_text": format_ts(raw_state["checked_at"]) if raw_state["checked_at"] else "jeszcze nie sprawdzano",
        "check_error": check_error,
        "installed": installed,
        "update_available": update_available,
        "needs_repo_switch": needs_repo_switch,
        "action_needed": action_needed,
        "status_pill_label": status_pill_label,
        "status_pill_kind": status_pill_kind,
        "action_button_label": (
            "Przełącz na oficjalne repo i zaktualizuj DLNA"
            if installed and needs_repo_switch
            else ("Zaktualizuj serwer DLNA" if update_available else "Zainstaluj serwer DLNA")
        ),
        "source_label": repo_source["label"],
        "source_channel_key": repo_source["channel_key"],
        "enabled_in_app": bool(dlna_config.get("enabled")),
    }


def refresh_dlna_package_state(force=False):
    snapshot = get_dlna_package_state_snapshot()
    should_check = force or not snapshot["latest_version_raw"] or needs_scheduled_dlna_check(snapshot["checked_at"])

    if not should_check:
        return snapshot

    latest_version = snapshot["latest_version_raw"]
    check_error = ""
    try:
        policy = get_apt_package_policy(DLNA_PACKAGE_NAME)
        latest_version = policy["candidate"] or policy["installed"] or latest_version
    except Exception as exc:
        check_error = str(exc)

    save_dlna_update_state(latest_version, time.time(), check_error)
    return get_dlna_package_state_snapshot()


def dlna_check_scheduler():
    while True:
        try:
            refresh_dlna_package_state(force=False)
            next_check_dt = get_next_dlna_check_dt()
            sleep_seconds = max(300, int(next_check_dt.timestamp() - time.time()))
        except Exception:
            sleep_seconds = 900
        time.sleep(sleep_seconds)


def start_dlna_scheduler_once():
    global DLNA_SCHEDULER_STARTED
    with DLNA_SCHEDULER_LOCK:
        if DLNA_SCHEDULER_STARTED:
            return
        thread = threading.Thread(target=dlna_check_scheduler, name="dlna-check-scheduler", daemon=True)
        thread.start()
        DLNA_SCHEDULER_STARTED = True


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

    files = files if files is not None else get_server_files()
    presence_index = build_dlna_library_presence_index(files=files)
    file_keys = presence_index["file_keys"]
    folder_keys = presence_index["folder_keys"]

    with APP_CONFIG_LOCK:
        dlna_config = normalize_dlna_config(APP_CONFIG.get("dlna"))
        current_rules = list(dlna_config.get("media_rules") or [])
        kept_rules = []
        removed_rules = []

        for rule in current_rules:
            kind = str(rule.get("kind") or "").strip().lower()
            storage_kind = normalize_storage_kind(rule.get("storage_kind") or "video")
            relative_path = safe_relative_download_path(rule.get("relative_path") or "")
            exists = (storage_kind, relative_path) in (folder_keys if kind == "folder" else file_keys)
            if exists:
                kept_rules.append(rule)
                continue

            removed_rules.append({
                "id": str(rule.get("id") or "").strip(),
                "kind": kind,
                "storage_kind": storage_kind,
                "relative_path": relative_path,
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

        dlna_config["media_rules"] = kept_rules
        APP_CONFIG["dlna"] = normalize_dlna_config(dlna_config)
        write_app_config_locked()
        updated_config = copy.deepcopy(APP_CONFIG["dlna"])

    if sync_runtime:
        sync_dlna_runtime_safe(
            restart_service_if_active=restart_service_if_active,
            force_full_rescan=True,
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
        DLNA_CONFIG_DIR,
        DLNA_SCRIPT_DIR,
        DLNA_COMMON_SCRIPT_DIR,
        DLNA_CUSTOM_SCRIPT_DIR,
        DLNA_LEGACY_SCRIPT_DIR,
        DLNA_LOG_DIR,
    ):
        ensure_directory(path)


def rebuild_dlna_export_tree(dlna_config=None, files=None):
    config = dlna_config or get_dlna_config_snapshot()
    files = files if files is not None else get_server_files()
    effective_map = get_dlna_effective_file_map(config, files=files)
    root_entry_map = build_dlna_root_entry_map(config)
    package_state = get_dlna_package_state_snapshot()
    feature_support = get_dlna_feature_support(package_state.get("current_version_raw"))

    ensure_dlna_runtime_dirs()
    clear_directory_contents(DLNA_EXPORT_ROOT)

    created_links = 0
    used_names_by_export_dir = {}
    for absolute_path, item in effective_map.items():
        collection_ids = set(item.get("collection_ids") or set())
        if feature_support["supports_groups"]:
            collection_ids.add(DLNA_ALL_COLLECTION_ID)
        elif not collection_ids:
            collection_ids.add(DLNA_ALL_COLLECTION_ID)

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

    referenced_usernames = get_dlna_referenced_usernames(config)
    for username in referenced_usernames:
        root_entry = root_entry_map.get(build_dlna_user_root_id(username)) or {}
        root_dir_name = str(root_entry.get("dir_name") or "").strip()
        if not root_dir_name:
            continue

        user_files = [
            item for item in files
            if normalize_username(item.get("owner_username") or DEFAULT_ADMIN_USERNAME) == username
        ]

        for item in user_files:
            storage_kind = normalize_storage_kind(item.get("storage_kind") or "video")
            storage_dir_name = "Audio" if storage_kind == "audio" else "Video"
            user_relative_path = safe_relative_download_path(item.get("user_relative_path") or "")
            bucket_names = ["Wszystkie Pliki"]
            if user_relative_path:
                first_segment = user_relative_path.split("/", 1)[0]
                if re.match(r"^\d{4}-\d{2}-\d{2}$", first_segment):
                    bucket_names.append(first_segment)
            for bucket_name in bucket_names:
                export_dir_key = "%s/%s/%s" % (root_dir_name, storage_dir_name, bucket_name)
                used_names = used_names_by_export_dir.setdefault(export_dir_key.lower(), set())
                export_file_name = build_dlna_export_link_name(item, used_names)
                export_relative_path = os.path.join(root_dir_name, storage_dir_name, bucket_name, export_file_name)
                export_path = os.path.abspath(os.path.join(DLNA_EXPORT_ROOT, export_relative_path))
                ensure_directory(os.path.dirname(export_path))
                if os.path.lexists(export_path):
                    remove_path_if_exists(export_path)
                absolute_path = resolve_download_path(
                    item.get("relative_path") or "",
                    storage_kind,
                    owner_username=username,
                )
                if not absolute_path or not os.path.isfile(absolute_path):
                    continue
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
        try:
            if process.poll() is None:
                process.kill()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except Exception:
            pass
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


def write_dlna_gerbera_config(dlna_config=None):
    config = dlna_config or get_dlna_config_snapshot()
    ensure_dlna_runtime_dirs()
    ensure_dlna_export_root_directory()
    cleanup_dlna_legacy_export_root()
    export_state = rebuild_dlna_export_tree(config)
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

    ip_el = gerbera_find(server_el, "ip")
    bind_ip = config.get("bind_ip") or ""
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
StartLimitIntervalSec=45
StartLimitBurst=3

[Service]
Type=simple
User=%s
Group=%s
WorkingDirectory=%s
Environment=GERBERA_HOME=%s
ExecStart=%s %s -c %s -m %s
Restart=on-failure
RestartSec=5
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
        systemd_quote_arg(binary_path),
        log_arg,
        systemd_quote_arg(DLNA_CONFIG_XML_FILE),
        systemd_quote_arg(DLNA_HOME_DIR),
    )
    with open(DLNA_SERVICE_UNIT_FILE, "w", encoding="utf-8") as fh:
        fh.write(unit_content)


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
            ["systemctl", *args],
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
    run_systemctl_command_result("reset-failed", DLNA_SERVICE_NAME, timeout=30)
    start_result = run_systemctl_command_result("start", DLNA_SERVICE_NAME, timeout=timeout)
    service_state = wait_for_dlna_service_stable(timeout=8.0)
    if service_state.get("active_state") == "active":
        return service_state

    detail = build_dlna_service_failure_detail(service_state, start_result.get("detail"))
    raise RuntimeError("Usługa DLNA nie utrzymała %s. %s" % (failure_label, detail or "Sprawdź log usługi DLNA."))


def ensure_dlna_service_stopped(timeout=90, reset_failed_after_stop=True):
    stop_result = run_systemctl_command_result("stop", DLNA_SERVICE_NAME, timeout=timeout)
    wait_timeout = 25.0 if stop_result.get("timed_out") else 12.0
    service_state = wait_for_dlna_service_stopped(timeout=wait_timeout)
    main_pid = str(service_state.get("main_pid") or "").strip()
    active_state = str(service_state.get("active_state") or "")

    if active_state == "active" or main_pid not in ("", "0"):
        detail = build_dlna_service_failure_detail(service_state, stop_result.get("detail"))
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
)


def sync_dlna_runtime(restart_service_if_active=False, force_full_rescan=False):
    return DLNA_RUNTIME_SERVICE.sync_runtime(
        restart_service_if_active=restart_service_if_active,
        force_full_rescan=force_full_rescan,
    )


def sync_dlna_runtime_safe(restart_service_if_active=False, force_full_rescan=False):
    return DLNA_RUNTIME_SERVICE.sync_runtime_safe(
        restart_service_if_active=restart_service_if_active,
        force_full_rescan=force_full_rescan,
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
    default_admin_username=DEFAULT_ADMIN_USERNAME,
    dlna_all_collection_id=DLNA_ALL_COLLECTION_ID,
    dlna_all_collection_name=DLNA_ALL_COLLECTION_NAME,
    dlna_export_root=DLNA_EXPORT_ROOT,
    dlna_config_xml_file=DLNA_CONFIG_XML_FILE,
    dlna_service_unit_file=DLNA_SERVICE_UNIT_FILE,
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

register_auth_routes(app, {
    "verify_user_credentials": verify_user_credentials,
    "set_session_user": set_session_user,
    "clear_session_user": clear_session_user,
    "set_ui_flash": set_ui_flash,
    "safe_next_url": safe_next_url,
    "is_authenticated": is_authenticated,
    "get_current_username": get_current_username,
    "update_user_password": update_user_password,
    "get_user_by_username": get_user_by_username,
})


register_main_routes(app, {
    "quote": quote,
    "FAVICON_SVG": FAVICON_SVG,
    "render_page": render_page,
    "get_mount_info": get_mount_info,
    "require_authenticated_page": require_authenticated_page,
    "is_valid_http_url": is_valid_http_url,
    "extract_video_data": extract_video_data,
    "build_result_with_proxy_urls": build_result_with_proxy_urls,
    "get_daily_download_dir": get_daily_download_dir,
    "get_yt_dlp_services_state": get_yt_dlp_services_state,
    "INDEX_CONTENT_TEMPLATE": INDEX_CONTENT_TEMPLATE,
    "DOWNLOADS_CONTENT_TEMPLATE": DOWNLOADS_CONTENT_TEMPLATE,
    "JOBS_CONTENT_TEMPLATE": JOBS_CONTENT_TEMPLATE,
    "SERVICES_CONTENT_TEMPLATE": SERVICES_CONTENT_TEMPLATE,
})


register_download_routes(app, {
    "require_authenticated_json": require_authenticated_json,
    "resolve_view_scope_username": resolve_view_scope_username,
    "get_users_snapshot": get_users_snapshot,
    "is_admin_authenticated": is_admin_authenticated,
    "get_current_username": get_current_username,
    "get_mount_info": get_mount_info,
    "get_server_files": get_server_files,
    "filter_jobs_for_viewer": filter_jobs_for_viewer,
    "get_jobs_snapshot": get_jobs_snapshot,
    "is_valid_http_url": is_valid_http_url,
    "extract_video_data": extract_video_data,
    "build_result_with_proxy_urls": build_result_with_proxy_urls,
    "find_format": find_format,
    "public_source_download_match_state": public_source_download_match_state,
    "get_source_download_match_state": get_source_download_match_state,
    "ensure_share_ready": ensure_share_ready,
    "normalize_storage_kind": normalize_storage_kind,
    "create_job": create_job,
    "build_download_filename": build_download_filename,
    "mark_job_cancel_requested": mark_job_cancel_requested,
    "delete_job": delete_job_record,
    "delete_managed_file": delete_managed_download_file,
    "build_m3u": build_m3u,
    "stream_upstream_response": stream_upstream_response,
    "build_intermediate_download_filename": build_intermediate_download_filename,
    "is_authenticated": is_authenticated,
    "build_managed_relative_path": build_managed_relative_path,
    "get_user_storage_root": get_user_storage_root,
})


register_user_management_routes(app, {
    "is_admin_authenticated": is_admin_authenticated,
    "wants_json_response": wants_json_response,
    "require_admin_json": require_admin_json,
    "set_ui_flash": set_ui_flash,
    "create_user_account": create_user_account,
    "update_user_password": update_user_password,
    "update_user_account": update_user_account,
    "delete_user_account": delete_user_account,
    "get_settings_page_state": get_settings_page_state,
    "ensure_directory": ensure_directory,
    "get_user_storage_root": get_user_storage_root,
    "normalize_username": normalize_username,
    "get_current_username": get_current_username,
})


register_settings_routes(app, {
    "is_admin_authenticated": is_admin_authenticated,
    "wants_json_response": wants_json_response,
    "require_admin_json": require_admin_json,
    "set_ui_flash": set_ui_flash,
    "render_page": render_page,
    "SETTINGS_CONTENT_TEMPLATE": SETTINGS_CONTENT_TEMPLATE,
    "get_settings_page_state": get_settings_page_state,
    "save_app_config": save_app_config,
    "ensure_share_ready": ensure_share_ready,
    "sync_dlna_runtime_safe": sync_dlna_runtime_safe,
    "refresh_ffmpeg_update_state": refresh_ffmpeg_update_state,
    "start_maintenance_task": start_maintenance_task,
    "install_or_update_ffmpeg": install_or_update_ffmpeg,
    "refresh_yt_dlp_update_state": refresh_yt_dlp_update_state,
    "update_yt_dlp_package": update_yt_dlp_package,
    "refresh_dlna_package_state": refresh_dlna_package_state,
    "build_dlna_json_response": build_dlna_json_response,
    "install_or_update_dlna_server": install_or_update_dlna_server,
    "parse_boolean_flag": parse_boolean_flag,
    "set_dlna_service_enabled": set_dlna_service_enabled,
    "restart_dlna_service_now": restart_dlna_service_now,
    "schedule_flask_service_restart": schedule_flask_service_restart,
    "SYSTEMD_SERVICE_NAME": SYSTEMD_SERVICE_NAME,
})


register_dlna_routes(app, {
    "is_admin_authenticated": is_admin_authenticated,
    "wants_json_response": wants_json_response,
    "require_admin_json": require_admin_json,
    "set_ui_flash": set_ui_flash,
    "render_page": render_page,
    "DLNA_CONTENT_TEMPLATE": DLNA_CONTENT_TEMPLATE,
    "get_dlna_page_state": get_dlna_page_state,
    "DLNA_SERVICE_NAME": DLNA_SERVICE_NAME,
    "DLNA_ALL_COLLECTION_NAME": DLNA_ALL_COLLECTION_NAME,
    "read_text_log_file_for_browser": read_text_log_file_for_browser,
    "DLNA_LOG_FILE": DLNA_LOG_FILE,
    "DLNA_LOG_BROWSER_MAX_BYTES": DLNA_LOG_BROWSER_MAX_BYTES,
    "build_dlna_collection_library_results": build_dlna_collection_library_results,
    "update_dlna_general_settings": update_dlna_general_settings,
    "build_dlna_json_response": build_dlna_json_response,
    "refresh_dlna_package_state": refresh_dlna_package_state,
    "sync_dlna_runtime_safe": sync_dlna_runtime_safe,
    "start_maintenance_task": start_maintenance_task,
    "install_or_update_dlna_server": install_or_update_dlna_server,
    "parse_boolean_flag": parse_boolean_flag,
    "set_dlna_service_enabled": set_dlna_service_enabled,
    "restart_dlna_service_now": restart_dlna_service_now,
    "sync_dlna_runtime": sync_dlna_runtime,
    "create_dlna_collection": create_dlna_collection,
    "update_dlna_collection": update_dlna_collection,
    "delete_dlna_collection": delete_dlna_collection,
    "create_dlna_client": create_dlna_client,
    "update_dlna_client": update_dlna_client,
    "delete_dlna_client": delete_dlna_client,
    "create_dlna_media_rule": create_dlna_media_rule,
    "update_dlna_media_rule": update_dlna_media_rule,
    "bulk_assign_dlna_collection_items": bulk_assign_dlna_collection_items,
    "delete_dlna_media_rule": delete_dlna_media_rule,
})


start_ffmpeg_scheduler_once()
start_yt_dlp_scheduler_once()
start_dlna_scheduler_once()


if __name__ == "__main__":
    app.run(host=CONFIG_APP_HOST, port=CONFIG_APP_PORT, debug=False, threaded=True)
