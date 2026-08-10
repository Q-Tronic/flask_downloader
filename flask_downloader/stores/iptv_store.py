import copy
import json
import os
import re
import shutil
import tempfile
import time
import uuid

from werkzeug.security import generate_password_hash


IPTV_SCHEMA_VERSION = 1
IPTV_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,48}$")
IPTV_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
IPTV_PASSWORD_RE = re.compile(r"^[a-zA-Z0-9._~-]{6,64}$")


def default_iptv_store():
    return {
        "schema_version": IPTV_SCHEMA_VERSION,
        "settings": {
            "enabled": True,
            "bind_host": "0.0.0.0",
            "port": 9988,
            "public_base_url": "",
            "refresh_hour": 2,
            "refresh_minute": 0,
            "epg_days": 7,
            "last_scheduler_run_date": "",
        },
        "profiles": [],
        "users": [],
    }


def normalize_profile_id(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "-", text).strip("-_")
    if not IPTV_PROFILE_ID_RE.fullmatch(text):
        raise ValueError("Identyfikator profilu musi mieć od 2 do 32 znaków.")
    return text


def normalize_iptv_username(value):
    text = str(value or "").strip()
    if not IPTV_USERNAME_RE.fullmatch(text):
        raise ValueError("Login IPTV musi mieć 3-48 znaków i może zawierać litery, cyfry, kropkę, myślnik lub podkreślenie.")
    return text


def _normalize_int(value, default, minimum, maximum):
    try:
        normalized = int(str(value).strip())
    except Exception:
        normalized = int(default)
    return max(int(minimum), min(int(maximum), normalized))


def _normalize_float(value, default=0.0):
    try:
        return max(0.0, float(value or 0.0))
    except Exception:
        return float(default)


def _normalize_bouquet_selection(value):
    result = []
    seen = set()
    for raw in value if isinstance(value, list) else []:
        if isinstance(raw, dict):
            reference = str(raw.get("reference") or "").strip()
            name = str(raw.get("name") or "").strip()[:160]
        else:
            reference = str(raw or "").strip()
            name = ""
        if not reference or reference in seen:
            continue
        seen.add(reference)
        result.append({"reference": reference, "name": name})
    return result


def default_profile_runtime():
    return {
        "status": "idle",
        "status_label": "Nie odświeżano",
        "progress_percent": 0.0,
        "detail": "",
        "last_refresh_at": 0.0,
        "last_success_at": 0.0,
        "last_error": "",
        "channel_count": 0,
        "category_count": 0,
        "epg_event_count": 0,
        "vod_count": 0,
        "refresh_started_at": 0.0,
        "refresh_finished_at": 0.0,
    }


def normalize_profile(raw):
    if not isinstance(raw, dict):
        return None
    try:
        profile_id = normalize_profile_id(raw.get("id") or raw.get("name"))
    except ValueError:
        return None

    name = str(raw.get("name") or profile_id).strip()[:80] or profile_id
    runtime = default_profile_runtime()
    raw_runtime = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
    runtime.update({
        "status": str(raw_runtime.get("status") or runtime["status"]).strip()[:32],
        "status_label": str(raw_runtime.get("status_label") or runtime["status_label"]).strip()[:120],
        "progress_percent": max(0.0, min(100.0, _normalize_float(raw_runtime.get("progress_percent")))),
        "detail": str(raw_runtime.get("detail") or "").strip()[:500],
        "last_refresh_at": _normalize_float(raw_runtime.get("last_refresh_at")),
        "last_success_at": _normalize_float(raw_runtime.get("last_success_at")),
        "last_error": str(raw_runtime.get("last_error") or "").strip()[:1000],
        "channel_count": _normalize_int(raw_runtime.get("channel_count"), 0, 0, 100000),
        "category_count": _normalize_int(raw_runtime.get("category_count"), 0, 0, 10000),
        "epg_event_count": _normalize_int(raw_runtime.get("epg_event_count"), 0, 0, 10000000),
        "vod_count": _normalize_int(raw_runtime.get("vod_count"), 0, 0, 1000000),
        "refresh_started_at": _normalize_float(raw_runtime.get("refresh_started_at")),
        "refresh_finished_at": _normalize_float(raw_runtime.get("refresh_finished_at")),
    })

    vod_source_ids = []
    seen_sources = set()
    for item in raw.get("vod_source_ids") if isinstance(raw.get("vod_source_ids"), list) else []:
        source_id = str(item or "").strip()[:180]
        if source_id and source_id not in seen_sources:
            seen_sources.add(source_id)
            vod_source_ids.append(source_id)

    return {
        "id": profile_id,
        "name": name,
        "host": str(raw.get("host") or "").strip()[:255],
        "web_port": _normalize_int(raw.get("web_port"), 1234, 1, 65535),
        "stream_port": _normalize_int(raw.get("stream_port"), 8001, 1, 65535),
        "username": str(raw.get("username") or "root").strip()[:80] or "root",
        "password_saved": bool(raw.get("password_saved", False)),
        "enabled": bool(raw.get("enabled", True)),
        "dvb_only": bool(raw.get("dvb_only", True)),
        "max_streams": _normalize_int(raw.get("max_streams"), 2, 1, 16),
        "selected_bouquets": _normalize_bouquet_selection(raw.get("selected_bouquets")),
        "vod_enabled": bool(raw.get("vod_enabled", False)),
        "vod_source_ids": vod_source_ids,
        "created_at": _normalize_float(raw.get("created_at"), time.time()) or time.time(),
        "updated_at": _normalize_float(raw.get("updated_at"), time.time()) or time.time(),
        "runtime": runtime,
    }


def normalize_iptv_user(raw, valid_profile_ids):
    if not isinstance(raw, dict):
        return None
    try:
        username = normalize_iptv_username(raw.get("username"))
        profile_id = normalize_profile_id(raw.get("profile_id"))
    except ValueError:
        return None
    if profile_id not in valid_profile_ids:
        return None
    password_hash = str(raw.get("password_hash") or "").strip()
    if not password_hash:
        return None
    user_id = str(raw.get("id") or uuid.uuid4().hex).strip()[:64] or uuid.uuid4().hex
    allowed_category_ids = []
    for value in raw.get("allowed_category_ids") if isinstance(raw.get("allowed_category_ids"), list) else []:
        text = str(value or "").strip()
        if text and text not in allowed_category_ids:
            allowed_category_ids.append(text)
    return {
        "id": user_id,
        "username": username,
        "profile_id": profile_id,
        "password_hash": password_hash,
        "enabled": bool(raw.get("enabled", True)),
        "expires_at": _normalize_float(raw.get("expires_at")),
        "max_connections": _normalize_int(raw.get("max_connections"), 1, 1, 8),
        "vod_enabled": bool(raw.get("vod_enabled", True)),
        "allowed_category_ids": allowed_category_ids,
        "created_at": _normalize_float(raw.get("created_at"), time.time()) or time.time(),
        "updated_at": _normalize_float(raw.get("updated_at"), time.time()) or time.time(),
    }


def normalize_iptv_store(raw):
    defaults = default_iptv_store()
    if not isinstance(raw, dict):
        return defaults

    raw_settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
    settings = copy.deepcopy(defaults["settings"])
    settings.update({
        "enabled": bool(raw_settings.get("enabled", settings["enabled"])),
        "bind_host": str(raw_settings.get("bind_host") or settings["bind_host"]).strip()[:255],
        "port": _normalize_int(raw_settings.get("port"), settings["port"], 1, 65535),
        "public_base_url": str(raw_settings.get("public_base_url") or "").strip().rstrip("/")[:500],
        "refresh_hour": _normalize_int(raw_settings.get("refresh_hour"), settings["refresh_hour"], 0, 23),
        "refresh_minute": _normalize_int(raw_settings.get("refresh_minute"), settings["refresh_minute"], 0, 59),
        "epg_days": _normalize_int(raw_settings.get("epg_days"), settings["epg_days"], 1, 14),
        "last_scheduler_run_date": str(raw_settings.get("last_scheduler_run_date") or "").strip()[:20],
    })

    profiles = []
    profile_ids = set()
    for item in raw.get("profiles") if isinstance(raw.get("profiles"), list) else []:
        profile = normalize_profile(item)
        if not profile or profile["id"] in profile_ids:
            continue
        profile_ids.add(profile["id"])
        profiles.append(profile)
    profiles.sort(key=lambda item: item["name"].casefold())

    users = []
    usernames = set()
    for item in raw.get("users") if isinstance(raw.get("users"), list) else []:
        user = normalize_iptv_user(item, profile_ids)
        if not user or user["username"].casefold() in usernames:
            continue
        usernames.add(user["username"].casefold())
        users.append(user)
    users.sort(key=lambda item: (item["profile_id"], item["username"].casefold()))

    return {
        "schema_version": IPTV_SCHEMA_VERSION,
        "settings": settings,
        "profiles": profiles,
        "users": users,
    }


def _atomic_write_json(path, payload):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".%s." % os.path.basename(path), suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        if os.path.isfile(path):
            backup_path = path + ".bak"
            backup_temp = backup_path + ".tmp"
            shutil.copy2(path, backup_temp)
            os.replace(backup_temp, backup_path)
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def write_iptv_store(path, payload):
    normalized = normalize_iptv_store(payload)
    _atomic_write_json(path, normalized)
    return normalized


def load_iptv_store(path):
    for candidate in (path, path + ".bak"):
        try:
            if not os.path.isfile(candidate):
                continue
            with open(candidate, "r", encoding="utf-8") as handle:
                normalized = normalize_iptv_store(json.load(handle) or {})
            if candidate != path:
                _atomic_write_json(path, normalized)
            return normalized
        except Exception:
            continue
    normalized = default_iptv_store()
    _atomic_write_json(path, normalized)
    return normalized


def hash_iptv_password(password):
    text = str(password or "")
    if not IPTV_PASSWORD_RE.fullmatch(text):
        raise ValueError("Hasło IPTV musi mieć 6-64 znaki i może zawierać litery, cyfry oraz . _ ~ -.")
    return generate_password_hash(text)


__all__ = [
    "IPTV_SCHEMA_VERSION",
    "default_iptv_store",
    "default_profile_runtime",
    "hash_iptv_password",
    "load_iptv_store",
    "normalize_iptv_store",
    "normalize_iptv_username",
    "normalize_profile",
    "normalize_profile_id",
    "write_iptv_store",
]
