import copy
import hashlib
import json
import os
import re
import time
import uuid


RADIO_SCHEMA_VERSION = 4
VALID_STREAM_FORMATS = ("mp3", "aac")
VALID_PLAY_MODES = ("random", "sequential")
VALID_ERDS_MODES = ("titles", "fixed", "rotation")
VALID_LIBRARY_ITEM_ROLES = ("music", "jingle", "promo")
VALID_LIBRARY_SOURCE_TYPES = ("download", "upload")
VALID_LIBRARY_MODES = ("manual", "all_user_audio")
VALID_MANUAL_QUEUE_MODES = ("play_now", "queue_next")
VALID_HISTORY_SOURCE_MODES = ("autodj", "live")
AAC_MIN_BITRATE_KBPS = 160
AAC_DEFAULT_BITRATE_KBPS = 192
RADIO_PLAYBACK_HISTORY_MAX_ITEMS = 40
RADIO_MANUAL_QUEUE_MAX_ITEMS = 25


def slugify_text(value, default="radio"):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:64] or default


def normalize_text(value, max_len=240):
    return str(value or "").strip()[:max_len]


def generate_radio_secret(length=20):
    return uuid.uuid4().hex[: max(8, int(length or 20))]


def normalize_positive_int(value, default, min_value, max_value):
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def build_default_station_source_username(owner_username):
    slug = slugify_text(owner_username, default="radio")
    return ("source-" + slug)[:64]


def build_default_station_live_port(owner_username):
    owner = str(owner_username or "").strip().lower() or "radio"
    digest = hashlib.md5(owner.encode("utf-8", errors="ignore")).hexdigest()
    return 12000 + (int(digest[:4], 16) % 8000)


def normalize_source_username(value, default="source"):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text).strip("-.")
    return text[:64] or str(default or "source")


def normalize_live_mount_name(value, default="live"):
    mount = str(value or "").strip().strip("/")
    mount = re.sub(r"[^a-zA-Z0-9_.-]+", "-", mount).strip("-.")
    return mount[:64] or str(default or "live")


def default_radio_global_config():
    return {
        "enabled": True,
        "backend": "icecast",
        "bind_ip": "",
        "port": 8000,
        "public_base_url": "",
        "hostname": "",
        "location": "Polska",
        "admin_contact": "",
        "source_password": "radio-source",
        "admin_username": "admin",
        "admin_password": "radio-admin",
        "max_listeners": 200,
        "default_stream_format": "mp3",
        "default_bitrate_kbps": 192,
        "metadata_refresh_seconds": 20,
        "autostart_backend": False,
    }


def default_station_entry(owner_username):
    owner = str(owner_username or "").strip()
    slug = slugify_text(owner, default="radio")
    stream_format = "mp3"
    return {
        "owner_username": owner,
        "enabled": False,
        "name": "Radio %s" % owner,
        "slug": slug,
        "mount_name": "%s.%s" % (slug, stream_format),
        "description": "",
        "genre": "",
        "autostart": False,
        "stream": {
            "format": stream_format,
            "bitrate_kbps": 192,
        },
        "source": {
            "username": build_default_station_source_username(owner),
            "password": generate_radio_secret(20),
        },
        "live": {
            "enabled": True,
            "port": build_default_station_live_port(owner),
            "mount_name": "live",
            "show_name": "",
            "dj_name": "",
        },
        "autopilot": {
            "play_mode": "random",
            "crossfade_seconds": 2,
            "scan_interval_seconds": 30,
            "jingle_every_tracks": 0,
            "repeat_guard_percent": 100,
        },
        "erds": {
            "mode": "rotation",
            "fixed_text": "",
            "suppress_track_titles": False,
            "rotation_interval_seconds": 20,
            "templates": [
                "Aktualnie słucha {sluchacze} {sluchacze_odmiana}",
                "Dzisiaj jest {Dzientygodnia} - {data} - {godzina}",
                "Słuchasz {nazwa_stacji}",
            ],
        },
        "library": {
            "mode": "manual",
            "excluded_relative_paths": [],
            "items": [],
        },
        "manual_queue": {
            "play_now": [],
            "queue_next": [],
        },
        "history": {
            "items": [],
            "last_signature": "",
        },
        "stats": {
            "listener_record": 0,
        },
    }


def default_radio_store():
    return {
        "schema_version": RADIO_SCHEMA_VERSION,
        "backend_update_state": {
            "checked_at": 0.0,
            "check_error": "",
            "package_versions": {},
        },
        "global": default_radio_global_config(),
        "stations": {},
    }


def normalize_global_radio_config(raw):
    defaults = default_radio_global_config()
    if not isinstance(raw, dict):
        return defaults

    bind_ip = normalize_text(raw.get("bind_ip"), max_len=120)
    public_base_url = normalize_text(raw.get("public_base_url"), max_len=240).rstrip("/")
    backend = normalize_text(raw.get("backend"), max_len=40).lower() or "icecast"
    stream_format = normalize_text(raw.get("default_stream_format"), max_len=12).lower() or "mp3"
    if stream_format not in VALID_STREAM_FORMATS:
        stream_format = "mp3"

    return {
        "enabled": bool(raw.get("enabled", defaults["enabled"])),
        "backend": backend,
        "bind_ip": bind_ip,
        "port": normalize_positive_int(raw.get("port"), defaults["port"], 1, 65535),
        "public_base_url": public_base_url,
        "hostname": normalize_text(raw.get("hostname"), max_len=120),
        "location": normalize_text(raw.get("location"), max_len=120) or defaults["location"],
        "admin_contact": normalize_text(raw.get("admin_contact"), max_len=160),
        "source_password": normalize_text(raw.get("source_password"), max_len=160) or defaults["source_password"],
        "admin_username": normalize_text(raw.get("admin_username"), max_len=80) or defaults["admin_username"],
        "admin_password": normalize_text(raw.get("admin_password"), max_len=160) or defaults["admin_password"],
        "max_listeners": normalize_positive_int(raw.get("max_listeners"), defaults["max_listeners"], 1, 50000),
        "default_stream_format": stream_format,
        "default_bitrate_kbps": normalize_positive_int(raw.get("default_bitrate_kbps"), defaults["default_bitrate_kbps"], 64, 320),
        "metadata_refresh_seconds": normalize_positive_int(raw.get("metadata_refresh_seconds"), defaults["metadata_refresh_seconds"], 5, 3600),
        "autostart_backend": bool(raw.get("autostart_backend", defaults["autostart_backend"])),
    }


def normalize_backend_update_state(raw):
    state = {
        "checked_at": 0.0,
        "check_error": "",
        "package_versions": {},
    }
    if not isinstance(raw, dict):
        return state

    try:
        state["checked_at"] = float(raw.get("checked_at") or 0.0)
    except Exception:
        state["checked_at"] = 0.0
    state["check_error"] = normalize_text(raw.get("check_error"), max_len=1200)

    package_versions = {}
    raw_package_versions = raw.get("package_versions") or {}
    if isinstance(raw_package_versions, dict):
        for key, value in raw_package_versions.items():
            package_name = normalize_text(key, max_len=80).lower()
            if not package_name:
                continue
            package_versions[package_name] = {
                "installed": normalize_text((value or {}).get("installed"), max_len=80),
                "candidate": normalize_text((value or {}).get("candidate"), max_len=80),
            }
    state["package_versions"] = package_versions
    return state


def normalize_stream_config(raw, defaults):
    payload = dict(defaults or {})
    if isinstance(raw, dict):
        fmt = normalize_text(raw.get("format"), max_len=12).lower() or payload.get("format") or "mp3"
        if fmt not in VALID_STREAM_FORMATS:
            fmt = payload.get("format") or "mp3"
        payload["format"] = fmt
        default_bitrate = int(payload.get("bitrate_kbps") or 192)
        minimum_bitrate = 64
        if fmt == "aac":
            default_bitrate = max(AAC_DEFAULT_BITRATE_KBPS, default_bitrate)
            minimum_bitrate = AAC_MIN_BITRATE_KBPS
        payload["bitrate_kbps"] = normalize_positive_int(raw.get("bitrate_kbps"), default_bitrate, minimum_bitrate, 320)
    return payload


def normalize_source_config(raw, defaults, *, owner_username):
    payload = dict(defaults or {})
    default_username = normalize_source_username(payload.get("username"), build_default_station_source_username(owner_username))
    default_password = normalize_text(payload.get("password"), max_len=160) or generate_radio_secret(20)
    payload["username"] = default_username
    payload["password"] = default_password
    if isinstance(raw, dict):
        payload["username"] = normalize_source_username(raw.get("username"), default_username)
        payload["password"] = normalize_text(raw.get("password"), max_len=160) or default_password
    return payload


def normalize_live_config(raw, defaults, *, owner_username):
    payload = dict(defaults or {})
    default_port = normalize_positive_int(payload.get("port"), build_default_station_live_port(owner_username), 1024, 65535)
    payload["enabled"] = bool(payload.get("enabled", True))
    payload["port"] = default_port
    payload["mount_name"] = normalize_live_mount_name(payload.get("mount_name"), "live")
    payload["show_name"] = normalize_text(payload.get("show_name"), max_len=160)
    payload["dj_name"] = normalize_text(payload.get("dj_name"), max_len=120)
    if isinstance(raw, dict):
        payload["enabled"] = bool(raw.get("enabled", payload["enabled"]))
        payload["port"] = normalize_positive_int(raw.get("port"), default_port, 1024, 65535)
        payload["mount_name"] = normalize_live_mount_name(raw.get("mount_name"), payload["mount_name"])
        payload["show_name"] = normalize_text(raw.get("show_name"), max_len=160) or payload["show_name"]
        payload["dj_name"] = normalize_text(raw.get("dj_name"), max_len=120) or payload["dj_name"]
    return payload


def normalize_station_stats(raw, defaults):
    payload = dict(defaults or {})
    payload["listener_record"] = normalize_positive_int(payload.get("listener_record"), 0, 0, 50000)
    if isinstance(raw, dict):
        payload["listener_record"] = normalize_positive_int(raw.get("listener_record"), payload["listener_record"], 0, 50000)
    return payload


def normalize_manual_queue_mode(value, default="queue_next"):
    mode = normalize_text(value, max_len=20).lower() or default
    if mode not in VALID_MANUAL_QUEUE_MODES:
        return default
    return mode


def normalize_history_source_mode(value, default="autodj"):
    mode = normalize_text(value, max_len=20).lower() or default
    if mode not in VALID_HISTORY_SOURCE_MODES:
        return default
    return mode


def normalize_autopilot_config(raw, defaults):
    payload = dict(defaults or {})
    if isinstance(raw, dict):
        play_mode = normalize_text(raw.get("play_mode"), max_len=20).lower()
        if play_mode in VALID_PLAY_MODES:
            payload["play_mode"] = play_mode
        payload["crossfade_seconds"] = normalize_positive_int(raw.get("crossfade_seconds"), int(payload.get("crossfade_seconds") or 2), 0, 12)
        payload["scan_interval_seconds"] = normalize_positive_int(raw.get("scan_interval_seconds"), int(payload.get("scan_interval_seconds") or 30), 5, 3600)
        payload["jingle_every_tracks"] = normalize_positive_int(raw.get("jingle_every_tracks"), int(payload.get("jingle_every_tracks") or 0), 0, 100)
        payload["repeat_guard_percent"] = normalize_positive_int(raw.get("repeat_guard_percent"), int(payload.get("repeat_guard_percent") or 100), 0, 100)
    return payload


def normalize_erds_templates(raw_templates, fallback_templates):
    templates = []
    seen = set()
    for raw in raw_templates or []:
        text = normalize_text(raw, max_len=220)
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        templates.append(text)
        if len(templates) >= 20:
            break
    if templates:
        return templates
    return list(fallback_templates or [])


def normalize_erds_config(raw, defaults):
    payload = dict(defaults or {})
    if not isinstance(raw, dict):
        payload["templates"] = list(payload.get("templates") or [])
        return payload

    mode = normalize_text(raw.get("mode"), max_len=20).lower()
    if mode in VALID_ERDS_MODES:
        payload["mode"] = mode
    payload["fixed_text"] = normalize_text(raw.get("fixed_text"), max_len=220)
    payload["suppress_track_titles"] = bool(raw.get("suppress_track_titles", payload.get("suppress_track_titles", False)))
    payload["rotation_interval_seconds"] = normalize_positive_int(raw.get("rotation_interval_seconds"), int(payload.get("rotation_interval_seconds") or 20), 5, 3600)
    payload["templates"] = normalize_erds_templates(raw.get("templates"), payload.get("templates") or [])
    return payload


def normalize_library_item_role(value, default="music"):
    role = normalize_text(value, max_len=20).lower() or default
    if role not in VALID_LIBRARY_ITEM_ROLES:
        return default
    return role


def normalize_library_source_type(value, default="download"):
    source_type = normalize_text(value, max_len=20).lower() or default
    if source_type not in VALID_LIBRARY_SOURCE_TYPES:
        return default
    return source_type


def normalize_library_mode(value, default="manual"):
    mode = normalize_text(value, max_len=40).lower() or default
    if mode not in VALID_LIBRARY_MODES:
        return default
    return mode


def normalize_library_item(raw, *, owner_username, parse_managed_relative_path, canonicalize_relative_path=None):
    if not isinstance(raw, dict):
        return None

    relative_path = normalize_text(raw.get("relative_path"), max_len=600).replace("\\", "/").strip("/")
    if callable(canonicalize_relative_path):
        relative_path = canonicalize_relative_path(
            relative_path,
            owner_username=owner_username,
            storage_kind="audio",
        )
    if not relative_path:
        return None

    parsed = parse_managed_relative_path(relative_path)
    if not parsed:
        return None
    if str(parsed.get("owner_username") or "").strip() != str(owner_username or "").strip():
        return None
    if str(parsed.get("storage_kind") or "").strip() != "audio":
        return None

    item_id = normalize_text(raw.get("id"), max_len=64) or ("trk_" + uuid.uuid4().hex[:12])
    display_title = normalize_text(raw.get("display_title"), max_len=180)
    source_type = normalize_library_source_type(raw.get("source_type"), default="download")
    role = normalize_library_item_role(raw.get("role"), default="music")
    try:
        added_at = float(raw.get("added_at") or 0.0)
    except Exception:
        added_at = 0.0

    return {
        "id": item_id,
        "source_type": source_type,
        "relative_path": relative_path,
        "display_title": display_title,
        "role": role,
        "enabled": bool(raw.get("enabled", True)),
        "added_at": added_at or time.time(),
    }


def normalize_manual_queue_item(raw, *, owner_username, parse_managed_relative_path, canonicalize_relative_path=None):
    if not isinstance(raw, dict):
        return None

    relative_path = normalize_text(raw.get("relative_path"), max_len=600).replace("\\", "/").strip("/")
    if callable(canonicalize_relative_path):
        relative_path = canonicalize_relative_path(
            relative_path,
            owner_username=owner_username,
            storage_kind="audio",
        )
    if not relative_path:
        return None

    parsed = parse_managed_relative_path(relative_path)
    if not parsed:
        return None
    if str(parsed.get("owner_username") or "").strip() != str(owner_username or "").strip():
        return None
    if str(parsed.get("storage_kind") or "").strip() != "audio":
        return None

    queue_item_id = normalize_text(raw.get("id"), max_len=64) or ("q_" + uuid.uuid4().hex[:12])
    display_title = normalize_text(raw.get("display_title"), max_len=180)
    queue_mode = normalize_manual_queue_mode(raw.get("queue_mode"), default="queue_next")
    try:
        requested_at = float(raw.get("requested_at") or 0.0)
    except Exception:
        requested_at = 0.0

    return {
        "id": queue_item_id,
        "relative_path": relative_path,
        "display_title": display_title,
        "queue_mode": queue_mode,
        "requested_at": requested_at or time.time(),
    }


def normalize_manual_queue(raw, *, owner_username, parse_managed_relative_path, canonicalize_relative_path=None):
    payload = {
        "play_now": [],
        "queue_next": [],
    }
    if not isinstance(raw, dict):
        return payload

    for queue_mode in VALID_MANUAL_QUEUE_MODES:
        seen_paths = set()
        next_items = []
        for raw_item in raw.get(queue_mode) or []:
            normalized_item = normalize_manual_queue_item(
                raw_item,
                owner_username=owner_username,
                parse_managed_relative_path=parse_managed_relative_path,
                canonicalize_relative_path=canonicalize_relative_path,
            )
            if not normalized_item:
                continue
            lowered = normalized_item["relative_path"].lower()
            if lowered in seen_paths:
                continue
            seen_paths.add(lowered)
            normalized_item["queue_mode"] = queue_mode
            next_items.append(normalized_item)
            if len(next_items) >= RADIO_MANUAL_QUEUE_MAX_ITEMS:
                break
        payload[queue_mode] = next_items
    return payload


def normalize_history_item(raw):
    if not isinstance(raw, dict):
        return None

    history_item_id = normalize_text(raw.get("id"), max_len=64) or ("hist_" + uuid.uuid4().hex[:12])
    display_title = normalize_text(raw.get("display_title"), max_len=180)
    if not display_title:
        return None
    relative_path = normalize_text(raw.get("relative_path"), max_len=600).replace("\\", "/").strip("/")
    try:
        played_at = float(raw.get("played_at") or 0.0)
    except Exception:
        played_at = 0.0

    return {
        "id": history_item_id,
        "display_title": display_title,
        "relative_path": relative_path,
        "source_mode": normalize_history_source_mode(raw.get("source_mode"), default="autodj"),
        "queue_mode": normalize_manual_queue_mode(raw.get("queue_mode"), default="queue_next") if raw.get("queue_mode") else "",
        "program_name": normalize_text(raw.get("program_name"), max_len=180),
        "dj_name": normalize_text(raw.get("dj_name"), max_len=120),
        "played_at": played_at or time.time(),
    }


def normalize_history(raw):
    payload = {
        "items": [],
        "last_signature": "",
    }
    if not isinstance(raw, dict):
        return payload

    payload["last_signature"] = normalize_text(raw.get("last_signature"), max_len=240)
    seen_ids = set()
    items = []
    for raw_item in raw.get("items") or []:
        normalized_item = normalize_history_item(raw_item)
        if not normalized_item:
            continue
        item_id = str(normalized_item.get("id") or "").strip()
        if item_id and item_id in seen_ids:
            continue
        if item_id:
            seen_ids.add(item_id)
        items.append(normalized_item)
        if len(items) >= RADIO_PLAYBACK_HISTORY_MAX_ITEMS:
            break
    payload["items"] = items
    return payload


def normalize_station_entry(raw, *, owner_username, parse_managed_relative_path, canonicalize_relative_path=None):
    owner = str(owner_username or "").strip()
    defaults = default_station_entry(owner)
    if not isinstance(raw, dict):
        return defaults

    slug = slugify_text(raw.get("slug") or raw.get("name") or owner, default=defaults["slug"])
    stream = normalize_stream_config(raw.get("stream"), defaults["stream"])
    source = normalize_source_config(raw.get("source"), defaults.get("source") or {}, owner_username=owner)
    live = normalize_live_config(raw.get("live"), defaults.get("live") or {}, owner_username=owner)
    stats = normalize_station_stats(raw.get("stats"), defaults.get("stats") or {})
    stream_format = str((stream or {}).get("format") or defaults["stream"]["format"]).strip().lower() or "mp3"
    mount_extension = ".aac" if stream_format == "aac" else ".mp3"
    raw_mount_name = normalize_text(raw.get("mount_name"), max_len=160).strip().lstrip("/")
    if raw_mount_name.lower().endswith(".mp3"):
        raw_mount_name = raw_mount_name[:-4]
    if raw_mount_name.lower().endswith(".aac"):
        raw_mount_name = raw_mount_name[:-4]
    mount_name = slugify_text(raw_mount_name or slug, default=slug)
    if not mount_name.endswith(mount_extension):
        mount_name += mount_extension

    raw_library = raw.get("library") or {}
    library_mode = normalize_library_mode(
        raw_library.get("mode") if isinstance(raw_library, dict) else "",
        default=(defaults["library"] or {}).get("mode") or "manual",
    )

    seen_relative_paths = set()
    items = []
    for item in (raw_library if isinstance(raw_library, dict) else {}).get("items") or []:
        normalized_item = normalize_library_item(item, owner_username=owner, parse_managed_relative_path=parse_managed_relative_path)
        if callable(canonicalize_relative_path) and normalized_item:
            normalized_item["relative_path"] = canonicalize_relative_path(
                normalized_item["relative_path"],
                owner_username=owner,
                storage_kind="audio",
            )
        if not normalized_item:
            continue
        relative_path = normalized_item["relative_path"].lower()
        if relative_path in seen_relative_paths:
            continue
        seen_relative_paths.add(relative_path)
        items.append(normalized_item)

    excluded_relative_paths = []
    seen_excluded = set()
    for raw_path in (raw_library if isinstance(raw_library, dict) else {}).get("excluded_relative_paths") or []:
        normalized_path = normalize_text(raw_path, max_len=600).replace("\\", "/").strip("/")
        if callable(canonicalize_relative_path):
            normalized_path = canonicalize_relative_path(
                normalized_path,
                owner_username=owner,
                storage_kind="audio",
            )
        if not normalized_path:
            continue
        parsed = parse_managed_relative_path(normalized_path)
        if not parsed:
            continue
        if str(parsed.get("owner_username") or "").strip() != owner:
            continue
        if str(parsed.get("storage_kind") or "").strip() != "audio":
            continue
        lowered = normalized_path.lower()
        if lowered in seen_excluded:
            continue
        seen_excluded.add(lowered)
        excluded_relative_paths.append(normalized_path)

    manual_queue = normalize_manual_queue(
        (raw.get("manual_queue") or {}) if isinstance(raw, dict) else {},
        owner_username=owner,
        parse_managed_relative_path=parse_managed_relative_path,
        canonicalize_relative_path=canonicalize_relative_path,
    )
    history = normalize_history((raw.get("history") or {}) if isinstance(raw, dict) else {})

    return {
        "owner_username": owner,
        "enabled": bool(raw.get("enabled", defaults["enabled"])),
        "name": normalize_text(raw.get("name"), max_len=120) or defaults["name"],
        "slug": slug,
        "mount_name": mount_name,
        "description": normalize_text(raw.get("description"), max_len=240),
        "genre": normalize_text(raw.get("genre"), max_len=120),
        "autostart": bool(raw.get("autostart", defaults["autostart"])),
        "stream": stream,
        "source": source,
        "live": live,
        "autopilot": normalize_autopilot_config(raw.get("autopilot"), defaults["autopilot"]),
        "erds": normalize_erds_config(raw.get("erds"), defaults["erds"]),
        "library": {
            "mode": library_mode,
            "excluded_relative_paths": excluded_relative_paths,
            "items": items,
        },
        "manual_queue": manual_queue,
        "history": history,
        "stats": stats,
    }


def normalize_radio_store(raw, *, normalize_username, parse_managed_relative_path, canonicalize_relative_path=None):
    defaults = default_radio_store()
    if not isinstance(raw, dict):
        return defaults

    stations = {}
    raw_stations = raw.get("stations") or {}
    if isinstance(raw_stations, dict):
        for key, value in raw_stations.items():
            try:
                owner_username = normalize_username(key)
            except Exception:
                continue
            stations[owner_username] = normalize_station_entry(
                value,
                owner_username=owner_username,
                parse_managed_relative_path=parse_managed_relative_path,
                canonicalize_relative_path=canonicalize_relative_path,
            )

    return {
        "schema_version": max(RADIO_SCHEMA_VERSION, normalize_positive_int(raw.get("schema_version"), RADIO_SCHEMA_VERSION, 1, 999)),
        "backend_update_state": normalize_backend_update_state(raw.get("backend_update_state")),
        "global": normalize_global_radio_config(raw.get("global")),
        "stations": stations,
    }


def load_radio_store(radios_file, *, normalize_username, parse_managed_relative_path, canonicalize_relative_path=None):
    store = default_radio_store()
    changed = False

    try:
        if os.path.isfile(radios_file):
            with open(radios_file, "r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}
            store = normalize_radio_store(
                raw,
                normalize_username=normalize_username,
                parse_managed_relative_path=parse_managed_relative_path,
                canonicalize_relative_path=canonicalize_relative_path,
            )
            changed = store != raw
    except Exception:
        store = default_radio_store()
        changed = True

    if changed or not os.path.isfile(radios_file):
        write_radio_store(radios_file, store)
    return store


def write_radio_store(radios_file, store):
    payload = copy.deepcopy(store or default_radio_store())
    with open(radios_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
