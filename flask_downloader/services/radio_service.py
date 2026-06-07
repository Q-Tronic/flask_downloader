import copy
import os
import time
import uuid

from flask_downloader.stores.radios_store import (
    VALID_ERDS_MODES,
    default_station_entry,
    normalize_autopilot_config,
    normalize_erds_config,
    normalize_global_radio_config,
    normalize_live_config,
    normalize_positive_int,
    normalize_source_config,
    normalize_station_entry,
    normalize_stream_config,
    normalize_text,
    slugify_text,
)


POLISH_WEEKDAYS = (
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
    "sobota",
    "niedziela",
)

ALLOWED_UPLOAD_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}


class RadioService:
    PLAYBACK_HISTORY_MAX_ITEMS = 10
    MANUAL_QUEUE_MAX_ITEMS = 25

    def __init__(
        self,
        *,
        radios_store,
        radios_lock,
        write_radio_store_locked,
        get_radio_store_snapshot,
        normalize_username,
        parse_managed_relative_path,
        build_managed_relative_path,
        safe_relative_download_path,
        resolve_download_path,
        get_relative_download_path,
        build_managed_file_url,
        format_relative_path_for_user,
        get_current_username,
        is_admin_authenticated,
        get_users_snapshot,
        get_server_files,
        get_mount_info,
        safe_filename,
        get_daily_download_dir,
        ensure_share_ready,
        format_ts,
        build_calendar_placeholder_values=None,
    ):
        self._radios_store = radios_store
        self._radios_lock = radios_lock
        self._write_radio_store_locked = write_radio_store_locked
        self._get_radio_store_snapshot = get_radio_store_snapshot
        self._normalize_username = normalize_username
        self._parse_managed_relative_path = parse_managed_relative_path
        self._build_managed_relative_path = build_managed_relative_path
        self._safe_relative_download_path = safe_relative_download_path
        self._resolve_download_path = resolve_download_path
        self._get_relative_download_path = get_relative_download_path
        self._build_managed_file_url = build_managed_file_url
        self._format_relative_path_for_user = format_relative_path_for_user
        self._get_current_username = get_current_username
        self._is_admin_authenticated = is_admin_authenticated
        self._get_users_snapshot = get_users_snapshot
        self._get_server_files = get_server_files
        self._get_mount_info = get_mount_info
        self._safe_filename = safe_filename
        self._get_daily_download_dir = get_daily_download_dir
        self._ensure_share_ready = ensure_share_ready
        self._format_ts = format_ts
        self._build_calendar_placeholder_values = build_calendar_placeholder_values

    @staticmethod
    def format_bytes(size):
        if size in (None, "", False):
            return "nieznany"
        try:
            value = float(size)
        except Exception:
            return "nieznany"
        if value <= 0:
            return "0 B"
        units = ("B", "KB", "MB", "GB", "TB")
        unit_index = 0
        while value >= 1024 and unit_index < len(units) - 1:
            value /= 1024.0
            unit_index += 1
        return ("%d %s" if unit_index == 0 else "%.2f %s") % (value, units[unit_index])

    @staticmethod
    def format_listener_word(count):
        try:
            number = max(0, int(count))
        except Exception:
            number = 0
        if number == 1:
            return "osoba"
        mod10 = number % 10
        mod100 = number % 100
        if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
            return "osoby"
        return "osób"

    @staticmethod
    def make_public_stream_url(global_config, station):
        if not station:
            return ""
        mount_name = str((station or {}).get("mount_name") or "").strip().lstrip("/")
        if not mount_name:
            return ""
        base_url = str((global_config or {}).get("public_base_url") or "").strip().rstrip("/")
        if base_url:
            return "%s/%s" % (base_url, mount_name)
        bind_ip = str((global_config or {}).get("bind_ip") or "").strip() or "localhost"
        port = int((global_config or {}).get("port") or 8000)
        return "http://%s:%s/%s" % (bind_ip, port, mount_name)

    def _normalize_owner(self, owner_username):
        return self._normalize_username(owner_username)

    def _ensure_station_locked(self, owner_username):
        owner = self._normalize_owner(owner_username)
        stations = self._radios_store.setdefault("stations", {})
        station = stations.get(owner)
        if station is None:
            station = default_station_entry(owner)
            stations[owner] = station
        return station

    def _cleanup_station_library_items_locked(self, station, owner_username):
        keep_items = []
        changed = False
        for item in ((station or {}).get("library") or {}).get("items") or []:
            relative_path = self._safe_relative_download_path(item.get("relative_path") or "")
            path = self._resolve_download_path(relative_path, "audio", owner_username=owner_username)
            if not relative_path or not path or not os.path.isfile(path):
                changed = True
                continue
            keep_items.append(item)
        if changed:
            station.setdefault("library", {})["items"] = keep_items
        excluded_paths = []
        for raw_path in ((station or {}).get("library") or {}).get("excluded_relative_paths") or []:
            relative_path = self._safe_relative_download_path(raw_path)
            path = self._resolve_download_path(relative_path, "audio", owner_username=owner_username)
            if not relative_path or not path or not os.path.isfile(path):
                changed = True
                continue
            excluded_paths.append(relative_path)
        if excluded_paths != list(((station or {}).get("library") or {}).get("excluded_relative_paths") or []):
            station.setdefault("library", {})["excluded_relative_paths"] = excluded_paths
            changed = True
        manual_queue = dict((station or {}).get("manual_queue") or {})
        for queue_key in ("play_now", "queue_next"):
            cleaned_queue = []
            for item in manual_queue.get(queue_key) or []:
                relative_path = self._safe_relative_download_path(item.get("relative_path") or "")
                path = self._resolve_download_path(relative_path, "audio", owner_username=owner_username)
                if not relative_path or not path or not os.path.isfile(path):
                    changed = True
                    continue
                cleaned_queue.append(item)
            if cleaned_queue != list(manual_queue.get(queue_key) or []):
                station.setdefault("manual_queue", {})[queue_key] = cleaned_queue
                changed = True
        history_items = []
        for item in (((station or {}).get("history") or {}).get("items")) or []:
            next_item = dict(item or {})
            relative_path = self._safe_relative_download_path(next_item.get("relative_path") or "")
            if relative_path:
                path = self._resolve_download_path(relative_path, "audio", owner_username=owner_username)
                if not path or not os.path.isfile(path):
                    next_item["relative_path"] = ""
                    changed = True
            history_items.append(next_item)
        if history_items != list((((station or {}).get("history") or {}).get("items")) or []):
            station.setdefault("history", {})["items"] = history_items
            changed = True
        return changed

    def cleanup_missing_library_items(self, owner_username=None):
        changed = False
        with self._radios_lock:
            target_owner = self._normalize_owner(owner_username) if owner_username else ""
            stations = self._radios_store.get("stations") or {}
            for owner, station in stations.items():
                if target_owner and owner != target_owner:
                    continue
                changed = self._cleanup_station_library_items_locked(station, owner) or changed
            if changed:
                self._write_radio_store_locked()
        return changed

    def ensure_station_exists(self, owner_username):
        owner = self._normalize_owner(owner_username)
        created = False
        with self._radios_lock:
            if owner not in (self._radios_store.get("stations") or {}):
                self._ensure_station_locked(owner)
                self._write_radio_store_locked()
                created = True
        return created

    def create_station(self, owner_username):
        created = self.ensure_station_exists(owner_username)
        station = self.get_station_snapshot(owner_username)
        return created, station

    def get_station_snapshot(self, owner_username):
        owner = self._normalize_owner(owner_username)
        snapshot = self._get_radio_store_snapshot()
        station = (snapshot.get("stations") or {}).get(owner)
        return copy.deepcopy(station) if station else None

    def delete_station(self, owner_username):
        owner = self._normalize_owner(owner_username)
        with self._radios_lock:
            stations = self._radios_store.get("stations") or {}
            if owner not in stations:
                raise ValueError("To radio nie istnieje jeszcze.")
            del stations[owner]
            self._write_radio_store_locked()

    def update_global_settings(self, payload):
        normalized = normalize_global_radio_config(payload)
        with self._radios_lock:
            self._radios_store["global"] = normalized
            self._write_radio_store_locked()
        return copy.deepcopy(normalized)

    def update_station(self, owner_username, payload):
        owner = self._normalize_owner(owner_username)
        with self._radios_lock:
            current = copy.deepcopy(self._ensure_station_locked(owner))
            merged = copy.deepcopy(current)
            global_config = dict(self._radios_store.get("global") or {})
            stations = self._radios_store.setdefault("stations", {})

            merged["enabled"] = bool(payload.get("enabled", merged.get("enabled")))
            merged["name"] = normalize_text(payload.get("name"), max_len=120) or merged.get("name") or ("Radio %s" % owner)
            merged["description"] = normalize_text(payload.get("description"), max_len=240)
            merged["genre"] = normalize_text(payload.get("genre"), max_len=120)
            merged["autostart"] = bool(payload.get("autostart", merged.get("autostart")))

            next_slug = slugify_text(payload.get("slug") or merged["name"] or owner, default=merged.get("slug") or owner)
            merged["slug"] = next_slug
            stream_payload = payload.get("stream")
            next_stream = normalize_stream_config(stream_payload, merged.get("stream") or {})
            stream_format = str((next_stream or {}).get("format") or "mp3").strip().lower() or "mp3"
            mount_extension = ".aac" if stream_format == "aac" else ".mp3"
            raw_mount_name = normalize_text(payload.get("mount_name"), max_len=160) or str(merged.get("mount_name") or next_slug)
            raw_mount_name = raw_mount_name.strip().lstrip("/")
            if raw_mount_name.lower().endswith(".mp3"):
                raw_mount_name = raw_mount_name[:-4]
            if raw_mount_name.lower().endswith(".aac"):
                raw_mount_name = raw_mount_name[:-4]
            mount_base = slugify_text(raw_mount_name or next_slug, default=next_slug)
            if not mount_base.endswith(mount_extension):
                mount_base += mount_extension
            merged["mount_name"] = mount_base

            merged["stream"] = next_stream
            merged["source"] = normalize_source_config(payload.get("source"), merged.get("source") or {}, owner_username=owner)
            merged["live"] = normalize_live_config(payload.get("live"), merged.get("live") or {}, owner_username=owner)
            merged["autopilot"] = normalize_autopilot_config(payload.get("autopilot"), merged.get("autopilot") or {})
            erds_payload = copy.deepcopy(payload.get("erds") or {})
            if "templates_text" in payload and "templates" not in erds_payload:
                erds_payload["templates"] = [
                    line.strip()
                    for line in str(payload.get("templates_text") or "").splitlines()
                    if str(line or "").strip()
                ]
            merged["erds"] = normalize_erds_config(erds_payload, merged.get("erds") or {})
            merged["library"] = current.get("library") or {"items": []}

            normalized = normalize_station_entry(
                merged,
                owner_username=owner,
                parse_managed_relative_path=self._parse_managed_relative_path,
            )
            live_config = dict(normalized.get("live") or {})
            requested_live_port = normalize_positive_int(live_config.get("port"), 0, 1024, 65535)
            backend_port = normalize_positive_int(global_config.get("port"), 8000, 1, 65535)
            if requested_live_port == backend_port:
                raise ValueError("Port live takeover nie może być taki sam jak publiczny port backendu radia.")
            for other_owner, other_station in stations.items():
                if str(other_owner or "").strip() == owner:
                    continue
                other_source_username = str((((other_station or {}).get("source") or {}).get("username")) or "").strip().lower()
                current_source_username = str((normalized.get("source") or {}).get("username") or "").strip().lower()
                if current_source_username and other_source_username == current_source_username:
                    raise ValueError("Login do nadawania %s jest już używany przez radio użytkownika %s." % (current_source_username, other_owner))
                other_live_port = normalize_positive_int((((other_station or {}).get("live") or {}).get("port")), 0, 0, 65535)
                if other_live_port and other_live_port == requested_live_port:
                    raise ValueError("Port live takeover %s jest już używany przez radio użytkownika %s." % (requested_live_port, other_owner))

            stations[owner] = normalized
            self._write_radio_store_locked()
        return self.get_station_snapshot(owner)

    def build_erds_preview_lines(self, station, listener_count=0, now_ts=None, runtime_context=None, global_config=None, skip_track_templates_when_live=False):
        if not station:
            return []

        now_struct = time.localtime(now_ts or time.time())
        weekday_lower = POLISH_WEEKDAYS[now_struct.tm_wday]
        weekday_title = weekday_lower.capitalize()
        listener_count = max(0, int(listener_count or 0))
        runtime_context = dict(runtime_context or {})
        global_config = dict(global_config or {})
        live_config = dict((station or {}).get("live") or {})
        station_stats = dict((station or {}).get("stats") or {})
        max_listeners = max(0, int(global_config.get("max_listeners") or 0))
        listener_record = max(
            0,
            int(runtime_context.get("listener_record") or 0),
            int(station_stats.get("listener_record") or 0),
        )
        live_connected = bool(runtime_context.get("live_connected"))
        current_program_name = str((live_config.get("show_name") or runtime_context.get("current_program_name") or "")).strip()
        current_dj_name = str((live_config.get("dj_name") or runtime_context.get("current_dj_name") or "")).strip()
        current_track_title = str(runtime_context.get("current_track_title") or "").strip()
        replacements = {
            "sluchacze": str(listener_count),
            "sluchaczy": str(listener_count),
            "sluchacze_odmiana": self.format_listener_word(listener_count),
            "sluchaczy_odmiana": self.format_listener_word(listener_count),
            "data": time.strftime("%d.%m.%Y", now_struct),
            "godzina": time.strftime("%H:%M", now_struct),
            "dzientygodnia": weekday_lower,
            "Dzientygodnia": weekday_title,
            "nazwa_stacji": str((station or {}).get("name") or ""),
            "audycja": current_program_name or "Brak audycji",
            "dj": current_dj_name or "AutoDJ",
            "utwor": current_track_title or "Brak utworu",
            "max_sluchaczy": str(max_listeners),
            "rekord_sluchaczy": str(listener_record),
            "rekord_sluchaczy_odmiana": self.format_listener_word(listener_record),
        }
        if callable(self._build_calendar_placeholder_values):
            try:
                replacements.update(dict(self._build_calendar_placeholder_values(now_ts=now_ts) or {}))
            except Exception:
                pass

        def render_template(template_text):
            rendered = str(template_text or "")
            for key, value in replacements.items():
                rendered = rendered.replace("{%s}" % key, str(value))
            return rendered.strip()

        erds = (station or {}).get("erds") or {}
        mode = str(erds.get("mode") or "").strip().lower()
        if mode not in VALID_ERDS_MODES:
            mode = "rotation"

        if mode == "titles":
            return [
                "Tryb tytułów: metadane będą pochodziły z odtwarzanego pliku audio.",
                render_template("Dzisiaj jest {Dzientygodnia} - {data} - {godzina}"),
            ]

        if mode == "fixed":
            fixed_template = str(erds.get("fixed_text") or "")
            if skip_track_templates_when_live and live_connected and "{utwor}" in fixed_template:
                return []
            fixed_text = render_template(fixed_template)
            return [fixed_text] if fixed_text else []

        lines = []
        for raw_template in erds.get("templates") or []:
            template_text = str(raw_template or "")
            if skip_track_templates_when_live and live_connected and "{utwor}" in template_text:
                continue
            rendered = render_template(template_text)
            if rendered:
                lines.append(rendered)
        return lines

    def _infer_source_type_from_relative_path(self, relative_path):
        normalized_path = str(relative_path or "").replace("\\", "/").lower()
        return "upload" if "/radio-uploads/" in normalized_path else "download"

    @staticmethod
    def _format_source_type_label(source_type):
        return "Wgrany plik" if str(source_type or "") == "upload" else "Plik z pobrań"

    @staticmethod
    def _normalize_library_role_value(role):
        normalized_role = str(role or "music").strip().lower() or "music"
        if normalized_role not in ("music", "jingle", "promo"):
            return "music"
        return normalized_role

    @staticmethod
    def _normalize_library_mode_value(mode):
        normalized_mode = str(mode or "manual").strip().lower() or "manual"
        if normalized_mode not in ("manual", "all_user_audio"):
            return "manual"
        return normalized_mode

    @staticmethod
    def _get_library_mode_label(mode):
        return "Cała biblioteka użytkownika" if str(mode or "") == "all_user_audio" else "Ręczny wybór"

    @staticmethod
    def _get_manual_queue_mode_label(mode):
        return "Teraz" if str(mode or "") == "play_now" else "Następny"

    @staticmethod
    def _get_history_source_mode_label(mode):
        return "Live DJ" if str(mode or "") == "live" else "AutoDJ"

    def _get_station_library_mode(self, station):
        return self._normalize_library_mode_value((((station or {}).get("library") or {}).get("mode") or "manual"))

    def _get_station_excluded_path_set(self, station):
        excluded_paths = set()
        for raw_path in ((station or {}).get("library") or {}).get("excluded_relative_paths") or []:
            normalized_path = self._safe_relative_download_path(raw_path)
            if normalized_path:
                excluded_paths.add(normalized_path.lower())
        return excluded_paths

    def _get_station_library_item_map(self, station):
        item_map = {}
        for item in ((station or {}).get("library") or {}).get("items") or []:
            normalized_path = self._safe_relative_download_path(item.get("relative_path") or "")
            if not normalized_path:
                continue
            item_map[normalized_path.lower()] = dict(item or {})
        return item_map

    def _get_station_manual_queue(self, station):
        manual_queue = dict((station or {}).get("manual_queue") or {})
        return {
            "play_now": list(manual_queue.get("play_now") or []),
            "queue_next": list(manual_queue.get("queue_next") or []),
        }

    @staticmethod
    def _find_catalog_item_by_relative_path(catalog_rows, relative_path):
        normalized_path = str(relative_path or "").strip().lower()
        if not normalized_path:
            return None
        for item in catalog_rows or []:
            if str(item.get("relative_path") or "").strip().lower() == normalized_path:
                return item
        return None

    def _build_audio_catalog_rows(self, owner_username):
        owner = self._normalize_owner(owner_username)
        rows = []
        for item in self._get_server_files(scope_username=owner):
            if str(item.get("storage_kind") or "") != "audio":
                continue
            relative_path = self._safe_relative_download_path(item.get("relative_path") or "")
            if not relative_path:
                continue
            name = str(item.get("name") or os.path.basename(relative_path) or "")
            source_type = self._infer_source_type_from_relative_path(relative_path)
            rows.append({
                "relative_path": relative_path,
                "display_path": str(item.get("display_path") or relative_path),
                "user_relative_path": str(item.get("user_relative_path") or ""),
                "name": name,
                "default_display_title": os.path.splitext(name)[0],
                "size": int(item.get("size") or 0),
                "size_text": self.format_bytes(item.get("size") or 0),
                "mtime_text": str(item.get("mtime_text") or ""),
                "url": str(item.get("url") or ""),
                "source_type": source_type,
                "source_type_label": self._format_source_type_label(source_type),
            })
        return rows

    def build_library_table_rows(self, owner_username, station):
        owner = self._normalize_owner(owner_username)
        library_mode = self._get_station_library_mode(station)
        excluded_paths = self._get_station_excluded_path_set(station)
        item_map = self._get_station_library_item_map(station)
        rows = []

        for catalog_item in self._build_audio_catalog_rows(owner):
            relative_path = str(catalog_item.get("relative_path") or "")
            path_key = relative_path.lower()
            override_item = item_map.get(path_key) or {}
            default_display_title = str(catalog_item.get("default_display_title") or "")
            included = False
            if library_mode == "all_user_audio":
                included = path_key not in excluded_paths
                if override_item and not bool(override_item.get("enabled", True)):
                    included = False
            elif override_item and bool(override_item.get("enabled", True)):
                included = True

            display_title = normalize_text(override_item.get("display_title"), max_len=180) or default_display_title
            role = self._normalize_library_role_value(override_item.get("role") or "music")
            rows.append({
                "item_id": str(override_item.get("id") or ("auto:" + relative_path)),
                "relative_path": relative_path,
                "display_path": str(catalog_item.get("display_path") or relative_path),
                "user_relative_path": str(catalog_item.get("user_relative_path") or ""),
                "name": str(catalog_item.get("name") or ""),
                "display_title": display_title,
                "default_display_title": default_display_title,
                "role": role,
                "included": bool(included),
                "source_type": str(catalog_item.get("source_type") or "download"),
                "source_type_label": str(catalog_item.get("source_type_label") or self._format_source_type_label(catalog_item.get("source_type"))),
                "size": int(catalog_item.get("size") or 0),
                "size_text": str(catalog_item.get("size_text") or ""),
                "mtime_text": str(catalog_item.get("mtime_text") or ""),
                "url": str(catalog_item.get("url") or ""),
                "is_override": bool(override_item),
                "is_excluded": bool(library_mode == "all_user_audio" and not included),
            })

        rows.sort(key=lambda item: ((0 if item.get("included") else 1), (item.get("display_path") or "").lower()))
        return rows

    def build_station_library_rows(self, owner_username, station):
        rows = []
        for item in self.build_library_table_rows(owner_username, station):
            if not item.get("included"):
                continue
            rows.append({
                "id": str(item.get("item_id") or ""),
                "display_title": str(item.get("display_title") or ""),
                "relative_path": str(item.get("relative_path") or ""),
                "display_path": str(item.get("display_path") or ""),
                "url": str(item.get("url") or ""),
                "role": self._normalize_library_role_value(item.get("role") or "music"),
                "enabled": True,
                "source_type": str(item.get("source_type") or "download"),
                "size": int(item.get("size") or 0),
                "size_text": str(item.get("size_text") or ""),
                "mtime_text": str(item.get("mtime_text") or ""),
                "added_at_text": "",
            })
        return rows

    def build_available_audio_rows(self, owner_username, station):
        rows = []
        for item in self.build_library_table_rows(owner_username, station):
            rows.append({
                "relative_path": str(item.get("relative_path") or ""),
                "display_path": str(item.get("display_path") or ""),
                "user_relative_path": str(item.get("user_relative_path") or ""),
                "name": str(item.get("name") or ""),
                "size": int(item.get("size") or 0),
                "size_text": str(item.get("size_text") or ""),
                "mtime_text": str(item.get("mtime_text") or ""),
                "url": str(item.get("url") or ""),
                "already_in_radio": bool(item.get("included")),
                "source_type_label": str(item.get("source_type_label") or ""),
            })
        return rows

    def build_manual_queue_rows(self, owner_username, station):
        owner = self._normalize_owner(owner_username)
        catalog_rows = self._build_audio_catalog_rows(owner)
        queue_rows = []
        manual_queue = self._get_station_manual_queue(station)
        for queue_mode in ("play_now", "queue_next"):
            for index, item in enumerate(manual_queue.get(queue_mode) or []):
                relative_path = self._safe_relative_download_path(item.get("relative_path") or "")
                catalog_item = self._find_catalog_item_by_relative_path(catalog_rows, relative_path) or {}
                display_title = normalize_text(item.get("display_title"), max_len=180) or str(catalog_item.get("default_display_title") or os.path.splitext(os.path.basename(relative_path))[0])
                requested_at_text = ""
                try:
                    requested_at_value = float(item.get("requested_at") or 0.0)
                except Exception:
                    requested_at_value = 0.0
                if requested_at_value > 0:
                    requested_at_text = self._format_ts(requested_at_value)
                queue_rows.append({
                    "id": str(item.get("id") or ""),
                    "relative_path": relative_path,
                    "display_title": display_title,
                    "display_path": str(catalog_item.get("display_path") or relative_path),
                    "user_relative_path": str(catalog_item.get("user_relative_path") or ""),
                    "queue_mode": queue_mode,
                    "queue_mode_label": self._get_manual_queue_mode_label(queue_mode),
                    "requested_at_text": requested_at_text,
                    "url": str(catalog_item.get("url") or ""),
                })
                if len(queue_rows) >= self.MANUAL_QUEUE_MAX_ITEMS:
                    return queue_rows
        return queue_rows

    def build_history_rows(self, owner_username, station):
        owner = self._normalize_owner(owner_username)
        catalog_rows = self._build_audio_catalog_rows(owner)
        history_rows = []
        history_items = list((((station or {}).get("history") or {}).get("items")) or [])
        for item in history_items[: self.PLAYBACK_HISTORY_MAX_ITEMS]:
            relative_path = self._safe_relative_download_path(item.get("relative_path") or "")
            catalog_item = self._find_catalog_item_by_relative_path(catalog_rows, relative_path) or {}
            played_at_text = ""
            try:
                played_at_value = float(item.get("played_at") or 0.0)
            except Exception:
                played_at_value = 0.0
            if played_at_value > 0:
                played_at_text = self._format_ts(played_at_value)
            history_rows.append({
                "id": str(item.get("id") or ""),
                "display_title": normalize_text(item.get("display_title"), max_len=180),
                "relative_path": relative_path,
                "display_path": str(catalog_item.get("display_path") or relative_path),
                "source_mode": str(item.get("source_mode") or "autodj"),
                "source_mode_label": self._get_history_source_mode_label(item.get("source_mode")),
                "queue_mode": str(item.get("queue_mode") or ""),
                "queue_mode_label": self._get_manual_queue_mode_label(item.get("queue_mode")) if item.get("queue_mode") else "",
                "program_name": normalize_text(item.get("program_name"), max_len=180),
                "dj_name": normalize_text(item.get("dj_name"), max_len=120),
                "played_at_text": played_at_text,
                "url": str(catalog_item.get("url") or ""),
            })
        return history_rows

    def get_page_state(self, owner_username=""):
        target_owner = self._normalize_owner(owner_username or self._get_current_username() or "")
        self.cleanup_missing_library_items(target_owner)
        snapshot = self._get_radio_store_snapshot()
        station = copy.deepcopy((snapshot.get("stations") or {}).get(target_owner))
        library_mode = self._get_station_library_mode(station) if station else "manual"
        library_rows = self.build_station_library_rows(target_owner, station) if station else []
        library_table_rows = self.build_library_table_rows(target_owner, station) if station else self._build_audio_catalog_rows(target_owner)
        available_audio_rows = self.build_available_audio_rows(target_owner, station)
        manual_queue_rows = self.build_manual_queue_rows(target_owner, station) if station else []
        history_rows = self.build_history_rows(target_owner, station) if station else []
        erds_preview = self.build_erds_preview_lines(
            station,
            listener_count=0,
            global_config=snapshot.get("global") or {},
        ) if station else []
        library_enabled_count = sum(1 for item in library_rows if item.get("enabled"))
        upload_count = sum(1 for item in library_rows if item.get("source_type") == "upload")
        download_count = sum(1 for item in library_rows if item.get("source_type") != "upload")
        available_users = []
        if self._is_admin_authenticated():
            available_users = [
                {
                    "username": str(item.get("username") or ""),
                    "role": str(item.get("role") or ""),
                    "enabled": bool(item.get("enabled", True)),
                }
                for item in (self._get_users_snapshot() or [])
                if str(item.get("username") or "").strip()
            ]

        return {
            "scope_username": target_owner,
            "can_manage_global": bool(self._is_admin_authenticated()),
            "global_config": copy.deepcopy(snapshot.get("global") or {}),
            "station_exists": bool(station),
            "station": station,
            "mount": self._get_mount_info(
                auto_remount=False,
                viewer_username=target_owner,
                is_admin=self._is_admin_authenticated(),
            ),
            "available_users": available_users,
            "available_audio_rows": available_audio_rows,
            "library_rows": library_rows,
            "library_table_rows": library_table_rows,
            "manual_queue_rows": manual_queue_rows,
            "history_rows": history_rows,
            "library_mode": library_mode,
            "library_mode_label": self._get_library_mode_label(library_mode),
            "erds_preview_lines": erds_preview,
            "erds_placeholders": [
                {"name": "{sluchacze}", "description": "Liczba słuchaczy, np. 6"},
                {"name": "{sluchacze_odmiana}", "description": "Odmiana słowa osoba: osoba / osoby / osób"},
                {"name": "{data}", "description": "Bieżąca data, np. 17.05.2026"},
                {"name": "{godzina}", "description": "Bieżąca godzina, np. 14:11"},
                {"name": "{dzientygodnia}", "description": "Nazwa dnia małą literą, np. niedziela"},
                {"name": "{Dzientygodnia}", "description": "Nazwa dnia wielką literą, np. Niedziela"},
                {"name": "{imieniny}", "description": "Imieniny dnia w mianowniku, np. Jan, Piotr, Paweł."},
                {"name": "{imieniny_odmiana}", "description": "Imieniny dnia w odmienionej formie, np. Jana, Piotra, Pawła."},
                {"name": "{nazwa_stacji}", "description": "Nazwa bieżącej stacji radiowej"},
                {"name": "{audycja}", "description": "Nazwa audycji ustawiona w panelu stacji."},
                {"name": "{dj}", "description": "Nazwa DJ-a / AutoDJ ustawiona w panelu stacji."},
                {"name": "{utwor}", "description": "Aktualnie grany utwór z AutoDJ. Przy wejściu live taki tekst nie jest wysyłany na serwer."},
                {"name": "{swieta}", "description": "Najbliższe święto ustawowe w Polsce."},
                {"name": "{dni_do_swiat}", "description": "Za ile dni wypada najbliższe święto ustawowe w Polsce."},
                {"name": "{swieta_nietypowe}", "description": "Najbliższe święto nietypowe z lokalnej bazy kalendarza."},
                {"name": "{dni_do_swiat_nietypowych}", "description": "Za ile dni wypada najbliższe święto nietypowe."},
                {"name": "{max_sluchaczy}", "description": "Limit słuchaczy z konfiguracji serwera radia."},
                {"name": "{rekord_sluchaczy}", "description": "Najwyższa zapisana liczba słuchaczy jednocześnie dla tego radia."},
                {"name": "{rekord_sluchaczy_odmiana}", "description": "Odmiana rekordu słuchaczy: osoba / osoby / osób."},
            ],
            "summary": {
                "public_stream_url": self.make_public_stream_url(snapshot.get("global") or {}, station),
                "library_count": len(library_rows),
                "library_enabled_count": library_enabled_count,
                "upload_count": upload_count,
                "download_count": download_count,
                "available_audio_count": len(library_table_rows),
                "erds_preview_count": len(erds_preview),
                "manual_queue_count": len(manual_queue_rows),
                "history_count": len(history_rows),
                "library_mode": library_mode,
                "library_mode_label": self._get_library_mode_label(library_mode),
            },
        }

    def enqueue_manual_track(self, owner_username, relative_path, *, queue_mode="queue_next"):
        owner = self._normalize_owner(owner_username)
        normalized_relative_path = self._safe_relative_download_path(relative_path)
        if not normalized_relative_path:
            raise ValueError("Nie wybrano poprawnego pliku audio do kolejki ręcznej.")

        normalized_queue_mode = "play_now" if str(queue_mode or "").strip().lower() == "play_now" else "queue_next"
        catalog_item = self._find_catalog_item_by_relative_path(self._build_audio_catalog_rows(owner), normalized_relative_path)
        if not catalog_item:
            raise ValueError("Wybrany plik audio nie istnieje już w bibliotece użytkownika.")

        display_title = str(catalog_item.get("default_display_title") or catalog_item.get("name") or os.path.splitext(os.path.basename(normalized_relative_path))[0]).strip()
        queue_item = {
            "id": "queue_" + uuid.uuid4().hex[:12],
            "relative_path": normalized_relative_path,
            "display_title": display_title,
            "queue_mode": normalized_queue_mode,
            "requested_at": time.time(),
        }

        with self._radios_lock:
            station = (self._radios_store.get("stations") or {}).get(owner)
            if not isinstance(station, dict):
                raise ValueError("Najpierw utwórz radio dla tego użytkownika.")
            manual_queue = station.setdefault("manual_queue", {})
            play_now_items = [
                item for item in list(manual_queue.get("play_now") or [])
                if str(item.get("relative_path") or "").strip().lower() != normalized_relative_path.lower()
            ]
            next_items = [
                item for item in list(manual_queue.get("queue_next") or [])
                if str(item.get("relative_path") or "").strip().lower() != normalized_relative_path.lower()
            ]
            if normalized_queue_mode == "play_now":
                play_now_items.insert(0, queue_item)
            else:
                next_items.append(queue_item)
            manual_queue["play_now"] = play_now_items[: self.MANUAL_QUEUE_MAX_ITEMS]
            manual_queue["queue_next"] = next_items[: self.MANUAL_QUEUE_MAX_ITEMS]
            self._write_radio_store_locked()

        return {
            "queue_mode": normalized_queue_mode,
            "queue_mode_label": self._get_manual_queue_mode_label(normalized_queue_mode),
            "display_title": display_title,
            "relative_path": normalized_relative_path,
        }

    def add_library_paths(self, owner_username, relative_paths, source_type="download"):
        owner = self._normalize_owner(owner_username)

        added = 0
        skipped = 0
        errors = []

        with self._radios_lock:
            station = self._ensure_station_locked(owner)
            library_mode = self._get_station_library_mode(station)
            station_library = station.setdefault("library", {})
            existing_paths = {
                str(item.get("relative_path") or "").strip().lower()
                for item in (station_library.get("items") or [])
            }
            excluded_paths = list(station_library.get("excluded_relative_paths") or [])
            excluded_map = {str(path or "").strip().lower(): str(path or "").strip() for path in excluded_paths}
            for raw_relative_path in relative_paths or []:
                relative_path = self._safe_relative_download_path(raw_relative_path)
                parsed = self._parse_managed_relative_path(relative_path)
                if not parsed or parsed.get("owner_username") != owner or parsed.get("storage_kind") != "audio":
                    skipped += 1
                    errors.append("Pominięto nieprawidłową ścieżkę audio: %s" % raw_relative_path)
                    continue
                if relative_path.lower() in existing_paths:
                    skipped += 1
                    continue
                path = self._resolve_download_path(relative_path, "audio", owner_username=owner)
                if not path or not os.path.isfile(path):
                    skipped += 1
                    errors.append("Plik nie istnieje już na serwerze: %s" % relative_path)
                    continue
                lowered = relative_path.lower()
                if library_mode == "all_user_audio":
                    if lowered in excluded_map:
                        excluded_paths = [path_value for path_value in excluded_paths if str(path_value or "").strip().lower() != lowered]
                        excluded_map.pop(lowered, None)
                        added += 1
                    elif lowered not in existing_paths:
                        added += 1
                    continue
                station.setdefault("library", {}).setdefault("items", []).append({
                    "id": "trk_" + uuid.uuid4().hex[:12],
                    "source_type": source_type,
                    "relative_path": relative_path,
                    "display_title": os.path.splitext(os.path.basename(path))[0],
                    "role": "music",
                    "enabled": True,
                    "added_at": time.time(),
                })
                existing_paths.add(relative_path.lower())
                added += 1

            if added:
                station_library["excluded_relative_paths"] = excluded_paths
                self._cleanup_station_library_items_locked(station, owner)
                self._write_radio_store_locked()

        return {
            "added": added,
            "skipped": skipped,
            "errors": errors,
        }

    def bulk_save_library(self, owner_username, *, mode="manual", rows=None):
        owner = self._normalize_owner(owner_username)
        normalized_mode = self._normalize_library_mode_value(mode)
        catalog_rows = self._build_audio_catalog_rows(owner)
        catalog_map = {
            str(item.get("relative_path") or "").strip().lower(): item
            for item in catalog_rows
            if str(item.get("relative_path") or "").strip()
        }
        if not isinstance(rows, list):
            rows = []

        with self._radios_lock:
            station = self._ensure_station_locked(owner)
            previous_items = self._get_station_library_item_map(station)
            seen_paths = set()
            next_items = []
            excluded_relative_paths = []
            included_count = 0

            for raw_row in rows:
                if not isinstance(raw_row, dict):
                    continue
                relative_path = self._safe_relative_download_path(raw_row.get("relative_path") or "")
                lowered = relative_path.lower()
                if not relative_path or lowered in seen_paths:
                    continue
                seen_paths.add(lowered)
                catalog_item = catalog_map.get(lowered)
                if not catalog_item:
                    continue

                included = bool(raw_row.get("included"))
                role = self._normalize_library_role_value(raw_row.get("role") or "music")
                default_display_title = str(catalog_item.get("default_display_title") or "")
                display_title = normalize_text(raw_row.get("display_title"), max_len=180) or default_display_title
                previous_item = previous_items.get(lowered) or {}
                source_type = str(catalog_item.get("source_type") or self._infer_source_type_from_relative_path(relative_path))

                if normalized_mode == "manual":
                    if not included:
                        continue
                    next_items.append({
                        "id": str(previous_item.get("id") or ("trk_" + uuid.uuid4().hex[:12])),
                        "source_type": source_type,
                        "relative_path": relative_path,
                        "display_title": display_title,
                        "role": role,
                        "enabled": True,
                        "added_at": float(previous_item.get("added_at") or time.time()),
                    })
                    included_count += 1
                    continue

                if not included:
                    excluded_relative_paths.append(relative_path)
                    continue

                included_count += 1
                if display_title != default_display_title or role != "music" or previous_item:
                    next_items.append({
                        "id": str(previous_item.get("id") or ("trk_" + uuid.uuid4().hex[:12])),
                        "source_type": source_type,
                        "relative_path": relative_path,
                        "display_title": display_title,
                        "role": role,
                        "enabled": True,
                        "added_at": float(previous_item.get("added_at") or time.time()),
                    })

            station["library"] = {
                "mode": normalized_mode,
                "excluded_relative_paths": excluded_relative_paths,
                "items": next_items,
            }
            self._cleanup_station_library_items_locked(station, owner)
            self._write_radio_store_locked()

        return {
            "mode": normalized_mode,
            "included_count": included_count,
            "excluded_count": len(excluded_relative_paths),
            "tracked_count": len(next_items),
        }

    def update_library_item(self, owner_username, item_id, *, display_title="", role="music", enabled=True):
        owner = self._normalize_owner(owner_username)
        normalized_title = normalize_text(display_title, max_len=180)
        normalized_role = str(role or "music").strip().lower() or "music"
        if normalized_role not in ("music", "jingle", "promo"):
            normalized_role = "music"
        with self._radios_lock:
            station = self._ensure_station_locked(owner)
            for item in ((station or {}).get("library") or {}).get("items") or []:
                if str(item.get("id") or "") != str(item_id or ""):
                    continue
                item["display_title"] = normalized_title
                item["role"] = normalized_role
                item["enabled"] = bool(enabled)
                self._write_radio_store_locked()
                return
        raise ValueError("Nie znaleziono wpisu biblioteki do edycji.")

    def remove_library_item(self, owner_username, item_id):
        owner = self._normalize_owner(owner_username)
        with self._radios_lock:
            station = self._ensure_station_locked(owner)
            items = list(((station or {}).get("library") or {}).get("items") or [])
            next_items = [item for item in items if str(item.get("id") or "") != str(item_id or "")]
            if len(next_items) == len(items):
                raise ValueError("Nie znaleziono wpisu biblioteki do usunięcia.")
            station.setdefault("library", {})["items"] = next_items
            self._write_radio_store_locked()

    def _store_uploaded_audio_file(self, owner_username, file_storage):
        owner = self._normalize_owner(owner_username)
        if file_storage is None:
            raise ValueError("Nie wybrano pliku do wgrania.")
        original_name = str(getattr(file_storage, "filename", "") or "").strip()
        if not original_name:
            raise ValueError("Nie wybrano pliku do wgrania.")

        extension = os.path.splitext(original_name)[1].lower()
        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError("Do biblioteki radia możesz wgrywać tylko pliki audio, np. mp3, m4a, flac, wav, ogg albo opus.")

        ok, message = self._ensure_share_ready(auto_remount=True)
        if not ok:
            raise ValueError("Udział sieciowy offline. %s" % message)

        target_dir = os.path.join(self._get_daily_download_dir(media_kind="audio", owner_username=owner), "radio-uploads")
        os.makedirs(target_dir, exist_ok=True)
        clean_name = self._safe_filename(original_name, default="radio-upload%s" % extension)
        name_root, name_ext = os.path.splitext(clean_name)
        target_path = os.path.join(target_dir, clean_name)
        counter = 1
        while os.path.exists(target_path):
            target_path = os.path.join(target_dir, "%s_%d%s" % (name_root, counter, name_ext))
            counter += 1
        file_storage.save(target_path)

        relative_path = self._get_relative_download_path(target_path, media_kind="audio", owner_username=owner)
        if not relative_path:
            relative_path = self._build_managed_relative_path(
                owner,
                "audio",
                os.path.relpath(target_path, self._get_daily_download_dir(media_kind="audio", owner_username=owner)).replace("\\", "/"),
            )
        return relative_path

    def store_uploaded_audio(self, owner_username, file_storage):
        relative_path = self._store_uploaded_audio_file(owner_username, file_storage)
        self.add_library_paths(owner_username, [relative_path], source_type="upload")
        return relative_path

    def store_uploaded_audio_batch(self, owner_username, file_storages):
        owner = self._normalize_owner(owner_username)
        files = [item for item in (file_storages or []) if item is not None]
        if not files:
            raise ValueError("Nie wybrano żadnych plików audio do wgrania.")

        uploaded_relative_paths = []
        results = []
        for file_storage in files:
            original_name = str(getattr(file_storage, "filename", "") or "").strip() or "plik-audio"
            try:
                relative_path = self._store_uploaded_audio_file(owner, file_storage)
                uploaded_relative_paths.append(relative_path)
                results.append({
                    "filename": original_name,
                    "ok": True,
                    "relative_path": relative_path,
                })
            except Exception as exc:
                results.append({
                    "filename": original_name,
                    "ok": False,
                    "error": str(exc),
                })

        if uploaded_relative_paths:
            self.add_library_paths(owner, uploaded_relative_paths, source_type="upload")

        uploaded_count = sum(1 for item in results if item.get("ok"))
        failed_count = len(results) - uploaded_count
        return {
            "uploaded_count": uploaded_count,
            "failed_count": failed_count,
            "uploaded_relative_paths": uploaded_relative_paths,
            "results": results,
        }

    def remove_file_references(self, relative_path):
        safe_relative_path = self._safe_relative_download_path(relative_path)
        if not safe_relative_path:
            return False

        changed = False
        with self._radios_lock:
            for station in (self._radios_store.get("stations") or {}).values():
                items = list(((station or {}).get("library") or {}).get("items") or [])
                next_items = [
                    item for item in items
                    if str(item.get("relative_path") or "").strip() != safe_relative_path
                ]
                manual_queue = dict((station or {}).get("manual_queue") or {})
                play_now_items = [
                    item for item in list(manual_queue.get("play_now") or [])
                    if str(item.get("relative_path") or "").strip() != safe_relative_path
                ]
                next_queue_items = [
                    item for item in list(manual_queue.get("queue_next") or [])
                    if str(item.get("relative_path") or "").strip() != safe_relative_path
                ]
                history_items = []
                history_changed = False
                for item in list((((station or {}).get("history") or {}).get("items")) or []):
                    if str(item.get("relative_path") or "").strip() == safe_relative_path:
                        history_changed = True
                        next_item = dict(item or {})
                        next_item["relative_path"] = ""
                        history_items.append(next_item)
                        continue
                    history_items.append(item)
                excluded_paths = [
                    path_value for path_value in list(((station or {}).get("library") or {}).get("excluded_relative_paths") or [])
                    if str(path_value or "").strip() != safe_relative_path
                ]
                if len(next_items) != len(items):
                    station.setdefault("library", {})["items"] = next_items
                    changed = True
                if play_now_items != list(manual_queue.get("play_now") or []):
                    station.setdefault("manual_queue", {})["play_now"] = play_now_items
                    changed = True
                if next_queue_items != list(manual_queue.get("queue_next") or []):
                    station.setdefault("manual_queue", {})["queue_next"] = next_queue_items
                    changed = True
                if excluded_paths != list(((station or {}).get("library") or {}).get("excluded_relative_paths") or []):
                    station.setdefault("library", {})["excluded_relative_paths"] = excluded_paths
                    changed = True
                if history_changed:
                    station.setdefault("history", {})["items"] = history_items
                    changed = True
            if changed:
                self._write_radio_store_locked()
        return changed

    def rename_user_station(self, previous_username, next_username):
        previous_owner = self._normalize_owner(previous_username)
        next_owner = self._normalize_owner(next_username)
        if previous_owner == next_owner:
            return False

        changed = False
        with self._radios_lock:
            stations = self._radios_store.get("stations") or {}
            station = stations.pop(previous_owner, None)
            if station is None:
                return False
            station["owner_username"] = next_owner
            next_items = []
            for item in ((station or {}).get("library") or {}).get("items") or []:
                parsed = self._parse_managed_relative_path(item.get("relative_path") or "")
                if parsed and parsed.get("owner_username") == previous_owner:
                    item["relative_path"] = self._build_managed_relative_path(
                        next_owner,
                        parsed.get("storage_kind") or "audio",
                        parsed.get("user_relative_path") or "",
                        storage_id=parsed.get("storage_id") or "local",
                    )
                    changed = True
                next_items.append(item)
            next_excluded_paths = []
            for raw_path in ((station or {}).get("library") or {}).get("excluded_relative_paths") or []:
                parsed = self._parse_managed_relative_path(raw_path or "")
                if parsed and parsed.get("owner_username") == previous_owner:
                    next_excluded_paths.append(self._build_managed_relative_path(
                        next_owner,
                        parsed.get("storage_kind") or "audio",
                        parsed.get("user_relative_path") or "",
                        storage_id=parsed.get("storage_id") or "local",
                    ))
                    changed = True
                elif raw_path:
                    next_excluded_paths.append(raw_path)
            next_play_now = []
            for item in ((station or {}).get("manual_queue") or {}).get("play_now") or []:
                next_item = dict(item or {})
                parsed = self._parse_managed_relative_path(next_item.get("relative_path") or "")
                if parsed and parsed.get("owner_username") == previous_owner:
                    next_item["relative_path"] = self._build_managed_relative_path(
                        next_owner,
                        parsed.get("storage_kind") or "audio",
                        parsed.get("user_relative_path") or "",
                        storage_id=parsed.get("storage_id") or "local",
                    )
                    changed = True
                next_play_now.append(next_item)
            next_queue_next = []
            for item in ((station or {}).get("manual_queue") or {}).get("queue_next") or []:
                next_item = dict(item or {})
                parsed = self._parse_managed_relative_path(next_item.get("relative_path") or "")
                if parsed and parsed.get("owner_username") == previous_owner:
                    next_item["relative_path"] = self._build_managed_relative_path(
                        next_owner,
                        parsed.get("storage_kind") or "audio",
                        parsed.get("user_relative_path") or "",
                        storage_id=parsed.get("storage_id") or "local",
                    )
                    changed = True
                next_queue_next.append(next_item)
            next_history_items = []
            for item in ((station or {}).get("history") or {}).get("items") or []:
                next_item = dict(item or {})
                parsed = self._parse_managed_relative_path(next_item.get("relative_path") or "")
                if parsed and parsed.get("owner_username") == previous_owner:
                    next_item["relative_path"] = self._build_managed_relative_path(
                        next_owner,
                        parsed.get("storage_kind") or "audio",
                        parsed.get("user_relative_path") or "",
                        storage_id=parsed.get("storage_id") or "local",
                    )
                    changed = True
                next_history_items.append(next_item)
            station.setdefault("library", {})["items"] = next_items
            station.setdefault("library", {})["excluded_relative_paths"] = next_excluded_paths
            station.setdefault("manual_queue", {})["play_now"] = next_play_now
            station.setdefault("manual_queue", {})["queue_next"] = next_queue_next
            station.setdefault("history", {})["items"] = next_history_items
            stations[next_owner] = normalize_station_entry(
                station,
                owner_username=next_owner,
                parse_managed_relative_path=self._parse_managed_relative_path,
            )
            self._write_radio_store_locked()
        return True

    def delete_user_station(self, username):
        owner = self._normalize_owner(username)
        with self._radios_lock:
            if owner not in (self._radios_store.get("stations") or {}):
                return False
            del self._radios_store["stations"][owner]
            self._write_radio_store_locked()
        return True
