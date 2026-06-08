import os
import re
import shutil
import time
import uuid

from flask_downloader.utils.formatting import build_natural_sort_key


DLNA_LIBRARY_ROOT_NAME = "flask_downloader_dlna"
DLNA_SUPPORTED_VIDEO_EXTENSIONS = {
    ".3gp", ".avi", ".asf", ".flv", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4",
    ".mpeg", ".mpg", ".mts", ".ts", ".webm", ".wmv",
}
DLNA_SUPPORTED_IMAGE_EXTENSIONS = {
    ".avif", ".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".jxl", ".png", ".tif", ".tiff", ".webp",
}


class DlnaLibraryService:
    def __init__(
        self,
        *,
        get_mount_info,
        get_server_files,
        prune_missing_dlna_media_rules,
        get_dlna_config_snapshot,
        set_dlna_config,
        refresh_dlna_package_state,
        get_dlna_service_state,
        get_all_maintenance_task_snapshots,
        normalize_dlna_config,
        normalize_storage_kind,
        safe_relative_download_path,
        resolve_download_path,
        format_relative_path_for_user,
        format_bytes_text,
        format_ts,
        normalize_dlna_server_name,
        normalize_dlna_bind_ip,
        normalize_dlna_port,
        normalize_dlna_collection_name,
        normalize_dlna_client_ip,
        normalize_dlna_description,
        sync_dlna_runtime_safe,
        get_users_snapshot,
        get_current_username,
        is_admin_authenticated,
        can_access_owner,
        get_storage_root,
        default_admin_username,
        dlna_all_collection_id,
        dlna_all_collection_name,
        dlna_export_root,
        dlna_config_xml_file,
        dlna_service_unit_file,
        get_dlna_icon_state,
    ):
        self._get_mount_info = get_mount_info
        self._get_server_files = get_server_files
        self._prune_missing_dlna_media_rules = prune_missing_dlna_media_rules
        self._get_dlna_config_snapshot = get_dlna_config_snapshot
        self._set_dlna_config = set_dlna_config
        self._refresh_dlna_package_state = refresh_dlna_package_state
        self._get_dlna_service_state = get_dlna_service_state
        self._get_all_maintenance_task_snapshots = get_all_maintenance_task_snapshots
        self._normalize_dlna_config = normalize_dlna_config
        self._normalize_storage_kind = normalize_storage_kind
        self._safe_relative_download_path = safe_relative_download_path
        self._resolve_download_path = resolve_download_path
        self._format_relative_path_for_user = format_relative_path_for_user
        self._format_bytes_text = format_bytes_text
        self._format_ts = format_ts
        self._normalize_dlna_server_name = normalize_dlna_server_name
        self._normalize_dlna_bind_ip = normalize_dlna_bind_ip
        self._normalize_dlna_port = normalize_dlna_port
        self._normalize_dlna_collection_name = normalize_dlna_collection_name
        self._normalize_dlna_client_ip = normalize_dlna_client_ip
        self._normalize_dlna_description = normalize_dlna_description
        self._sync_dlna_runtime_safe = sync_dlna_runtime_safe
        self._get_users_snapshot = get_users_snapshot
        self._get_current_username = get_current_username
        self._is_admin_authenticated = is_admin_authenticated
        self._can_access_owner = can_access_owner
        self._get_storage_root = get_storage_root
        self._default_admin_username = default_admin_username
        self._dlna_all_collection_id = dlna_all_collection_id
        self._dlna_all_collection_name = dlna_all_collection_name
        self._dlna_export_root = dlna_export_root
        self._dlna_config_xml_file = dlna_config_xml_file
        self._dlna_service_unit_file = dlna_service_unit_file
        self._get_dlna_icon_state = get_dlna_icon_state

    @staticmethod
    def _parse_boolean_flag(value, default=False):
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in ("1", "true", "yes", "on", "tak"):
            return True
        if text in ("0", "false", "no", "off", "nie"):
            return False
        return bool(default)

    @staticmethod
    def _normalize_storage_id(value, default="local"):
        return "network" if str(value or "").strip().lower() == "network" else str(default or "local")

    @staticmethod
    def _sanitize_collection_folder_name(value, fallback="Bukiet"):
        text = re.sub(r"\s+", " ", str(value or "").strip())
        text = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]+', " ", text)
        text = re.sub(r"\s+", " ", text).strip().rstrip(". ")
        if not text:
            text = str(fallback or "Bukiet").strip() or "Bukiet"
        return text[:96]

    @staticmethod
    def _normalize_file_name(value):
        name = str(value or "").strip()
        name = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]+', " ", name)
        name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
        return name[:240]

    @staticmethod
    def _file_extension(path):
        return os.path.splitext(str(path or "").strip())[1].strip().lower()

    def _detect_media_kind(self, path):
        extension = self._file_extension(path)
        if extension in DLNA_SUPPORTED_IMAGE_EXTENSIONS:
            return "image"
        if extension in DLNA_SUPPORTED_VIDEO_EXTENSIONS:
            return "video"
        return ""

    def _is_supported_dlna_file(self, path):
        return bool(self._detect_media_kind(path))

    def _get_current_viewer_username(self):
        try:
            return str(self._get_current_username() or "").strip() or self._default_admin_username
        except Exception:
            return self._default_admin_username

    def _viewer_is_admin(self):
        try:
            return bool(self._is_admin_authenticated())
        except Exception:
            return False

    def _viewer_can_manage_owner(self, owner_username):
        owner = str(owner_username or "").strip() or self._default_admin_username
        if self._viewer_is_admin():
            return True
        return owner == self._get_current_viewer_username()

    def _normalize_visible_collections(self, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        viewer = self._get_current_viewer_username()
        admin_view = self._viewer_is_admin()
        result = []
        for item in config.get("collections") or []:
            owner_username = str(item.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username
            if not admin_view and owner_username != viewer:
                continue
            result.append(item)
        result.sort(key=lambda item: (build_natural_sort_key(item.get("name") or ""), item.get("id") or ""))
        return result

    def _get_all_collection_map(self, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        return {
            str(item.get("id") or "").strip(): item
            for item in (config.get("collections") or [])
            if str(item.get("id") or "").strip()
        }

    def _get_collection_by_id(self, collection_id, dlna_config=None):
        return self._get_all_collection_map(dlna_config).get(str(collection_id or "").strip())

    def _get_entries(self, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        return list(config.get("entries") or [])

    def _get_pending_sync_paths(self, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        pending = set()
        for item in config.get("pending_manual_sync_paths") or []:
            value = self._safe_relative_download_path(item)
            if value:
                pending.add(value)
        return pending

    def _entry_is_pending_publication(self, entry, pending_paths=None):
        if pending_paths is None:
            pending_paths = self._get_pending_sync_paths()
        if not pending_paths:
            return False
        source_relative_path = self._safe_relative_download_path(entry.get("source_relative_path") or "")
        current_relative_path = self._safe_relative_download_path(entry.get("current_relative_path") or "")
        return (
            bool(source_relative_path and source_relative_path in pending_paths)
            or bool(current_relative_path and current_relative_path in pending_paths)
        )

    def _get_entry_map(self, dlna_config=None):
        return {
            str(item.get("id") or "").strip(): item
            for item in self._get_entries(dlna_config)
            if str(item.get("id") or "").strip()
        }

    def get_entry_for_source_path(self, storage_kind, relative_path, dlna_config=None):
        key = (
            self._normalize_storage_id((self._parse_source_relative_path(relative_path) or {}).get("storage_id") or "local"),
            str(relative_path or "").strip(),
        )
        return self._build_source_entry_lookup(dlna_config).get(key)

    def _get_entries_for_collection(self, collection_id, dlna_config=None):
        normalized_collection_id = str(collection_id or "").strip()
        return [
            item
            for item in self._get_entries(dlna_config)
            if str(item.get("collection_id") or "").strip() == normalized_collection_id
        ]

    def _build_source_entry_lookup(self, dlna_config=None):
        lookup = {}
        for item in self._get_entries(dlna_config):
            key = (
                self._normalize_storage_id(item.get("source_storage_id") or "local"),
                str(item.get("source_relative_path") or "").strip(),
            )
            if key[1]:
                lookup[key] = item
        return lookup

    def _parse_source_relative_path(self, relative_path):
        safe_path = str(relative_path or "").strip().replace("\\", "/")
        if not safe_path:
            return None
        parts = [segment for segment in safe_path.split("/") if segment]
        if len(parts) < 4 or not parts[0].startswith("@"):
            return None
        storage_id = self._normalize_storage_id(parts[0][1:] or "local")
        owner_username = str(parts[1] or "").strip() or self._default_admin_username
        storage_kind = self._normalize_storage_kind(parts[2] or "video")
        user_relative_path = "/".join(parts[3:]).strip("/")
        if not user_relative_path:
            return None
        return {
            "storage_id": storage_id,
            "owner_username": owner_username,
            "storage_kind": storage_kind,
            "user_relative_path": user_relative_path,
        }

    def _get_storage_base_root(self, storage_id):
        user_storage_root = os.path.abspath(self._get_storage_root(storage_id=self._normalize_storage_id(storage_id)))
        return os.path.abspath(os.path.dirname(user_storage_root))

    def get_collection_storage_root(self, storage_id):
        return os.path.join(self._get_storage_base_root(storage_id), DLNA_LIBRARY_ROOT_NAME)

    def get_collection_storage_path(self, storage_id, current_relative_path):
        safe_path = self._safe_relative_download_path(current_relative_path)
        if not safe_path:
            return ""
        target_root = os.path.abspath(self.get_collection_storage_root(storage_id))
        candidate = os.path.abspath(os.path.join(target_root, safe_path))
        try:
            if os.path.commonpath([target_root, candidate]) != target_root:
                return ""
        except Exception:
            return ""
        return candidate

    def _get_entry_current_path(self, entry):
        storage_id = self._normalize_storage_id(entry.get("source_storage_id") or "local")
        return self.get_collection_storage_path(storage_id, entry.get("current_relative_path") or "")

    def _get_entry_source_path(self, entry):
        return self._resolve_download_path(
            entry.get("source_relative_path") or "",
            entry.get("source_storage_kind") or "video",
            owner_username=entry.get("owner_username") or self._default_admin_username,
            storage_id=entry.get("source_storage_id") or "local",
        )

    def _build_collection_entry_relative_path(self, collection, file_name):
        folder_name = self._sanitize_collection_folder_name(collection.get("folder_name") or collection.get("name") or "", fallback=collection.get("name") or "Bukiet")
        return "%s/%s" % (folder_name, self._normalize_file_name(file_name))

    def _pick_unique_collection_file_name(self, collection, storage_id, file_name, dlna_config=None, exclude_entry_id=""):
        normalized_name = self._normalize_file_name(file_name)
        if not normalized_name:
            normalized_name = "plik"
        stem, extension = os.path.splitext(normalized_name)
        stem = stem.strip() or "plik"
        extension = extension.strip()
        collection_id = str(collection.get("id") or "").strip()
        existing_names = set()
        for item in self._get_entries_for_collection(collection_id, dlna_config):
            if exclude_entry_id and str(item.get("id") or "").strip() == str(exclude_entry_id or "").strip():
                continue
            if self._normalize_storage_id(item.get("source_storage_id") or "local") != self._normalize_storage_id(storage_id):
                continue
            existing_names.add(str(item.get("file_name") or "").strip().lower())
        candidate = normalized_name
        suffix = 1
        while candidate.lower() in existing_names or os.path.exists(self.get_collection_storage_path(storage_id, self._build_collection_entry_relative_path(collection, candidate))):
            suffix += 1
            candidate = "%s (%s)%s" % (stem, suffix, extension)
        return candidate

    def _prepare_collection_item(self, item, entry_lookup, selected_collection_id):
        relative_path = str(item.get("relative_path") or "").strip()
        source_storage_id = self._normalize_storage_id(item.get("storage_id") or "local")
        entry = entry_lookup.get((source_storage_id, relative_path))
        selected = bool(entry and str(entry.get("collection_id") or "").strip() == str(selected_collection_id or "").strip())
        other_collection_name = str((entry or {}).get("collection_name") or "").strip()
        media_kind = self._detect_media_kind(item.get("name") or relative_path)
        return {
            "kind": "file",
            "entry_id": str((entry or {}).get("id") or "").strip(),
            "storage_id": source_storage_id,
            "storage_kind": self._normalize_storage_kind(item.get("storage_kind") or "video"),
            "relative_path": relative_path,
            "display_path": str(item.get("display_path") or relative_path),
            "title": str(item.get("name") or os.path.basename(relative_path) or relative_path),
            "detail_text": "%s • %s • %s" % (
                "Zdjęcie" if media_kind == "image" else "Wideo",
                self._format_bytes_text(item.get("size") or 0),
                str(item.get("mtime_text") or "brak daty"),
            ),
            "selected": selected,
            "selected_via": "direct" if selected else "none",
            "active_in_dlna": bool(entry),
            "media_kind": media_kind,
            "blocked_by_other_collection": bool(entry and not selected),
            "blocked_collection_name": other_collection_name if entry and not selected else "",
        }

    def _ensure_collection_manageable(self, collection, allow_admin=True):
        if not collection:
            raise ValueError("Nie znaleziono wskazanego bukietu DLNA.")
        owner_username = str(collection.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username
        if allow_admin and self._viewer_is_admin():
            return
        if owner_username != self._get_current_viewer_username():
            raise ValueError("Nie możesz zarządzać bukietem innego użytkownika.")

    def get_collection_catalog(self, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        entries = self._get_entries(config)
        item_count_map = {}
        for item in entries:
            collection_id = str(item.get("collection_id") or "").strip()
            if not collection_id:
                continue
            item_count_map[collection_id] = item_count_map.get(collection_id, 0) + 1

        result = []
        for item in self._normalize_visible_collections(config):
            owner_username = str(item.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username
            result.append({
                "id": item["id"],
                "name": item["name"],
                "description": item.get("description") or "",
                "owner_username": owner_username,
                "folder_name": item.get("folder_name") or self._sanitize_collection_folder_name(item.get("name") or "Bukiet"),
                "item_count": int(item_count_map.get(item["id"], 0)),
                "can_manage": self._viewer_can_manage_owner(owner_username),
                "builtin": False,
            })
        return result

    def get_available_users(self):
        users = []
        for user in self._get_users_snapshot() or []:
            username = str((user or {}).get("username") or "").strip()
            if not username:
                continue
            users.append({
                "username": username,
                "role": str((user or {}).get("role") or "user").strip().lower() or "user",
                "enabled": bool((user or {}).get("enabled", True)),
            })
        users.sort(key=lambda item: (0 if item["role"] == "admin" else 1, item["username"].lower()))
        return users

    def get_named_collection_map(self, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        return {
            item["id"]: {
                "id": item["id"],
                "name": item["name"],
                "description": item.get("description") or "",
                "owner_username": str(item.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username,
                "folder_name": item.get("folder_name") or self._sanitize_collection_folder_name(item.get("name") or "Bukiet"),
            }
            for item in self._normalize_visible_collections(config)
        }

    def get_assignable_collections_for_user(self, username="", is_admin=False, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        normalized_username = str(username or "").strip()
        result = []
        for item in config.get("collections") or []:
            owner_username = str(item.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username
            if not is_admin and owner_username != normalized_username:
                continue
            result.append({
                "id": item["id"],
                "name": item["name"],
                "description": item.get("description") or "",
                "owner_username": owner_username,
            })
        result.sort(key=lambda item: build_natural_sort_key(item["name"]))
        return result

    def get_library_candidates(self, files=None):
        files = files if files is not None else self._get_server_files()
        supported_files = []
        for item in files:
            storage_kind = self._normalize_storage_kind(item.get("storage_kind") or "video")
            relative_path = str(item.get("relative_path") or "").strip()
            owner_username = str(item.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username
            if storage_kind == "audio":
                continue
            if not relative_path or not self._is_supported_dlna_file(item.get("name") or relative_path):
                continue
            supported_files.append({
                "storage_id": self._normalize_storage_id(item.get("storage_id") or "local"),
                "storage_kind": storage_kind,
                "relative_path": relative_path,
                "display_path": str(item.get("display_path") or relative_path),
                "name": str(item.get("name") or os.path.basename(relative_path) or relative_path),
                "owner_username": owner_username,
                "size": int(item.get("size") or 0),
                "mtime": float(item.get("mtime") or 0.0),
                "mtime_text": str(item.get("mtime_text") or ""),
                "media_kind": self._detect_media_kind(item.get("name") or relative_path) or "video",
            })
        supported_files.sort(key=lambda item: build_natural_sort_key(item["display_path"]))
        return {"files": supported_files}

    def build_exact_rule_lookup(self, dlna_config=None):
        return {}

    def normalize_collection_editor_id(self, collection_id, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        normalized_id = str(collection_id or "").strip()
        visible = {
            str(item.get("id") or "").strip()
            for item in self._normalize_visible_collections(config)
        }
        return normalized_id if normalized_id in visible else ""

    def normalize_client_collection_ids(self, collection_ids, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        named_collection_ids = set(self._get_all_collection_map(config).keys())
        result = []
        seen = set()
        for item in collection_ids or []:
            value = str(item or "").strip()
            if not value or value in seen or value not in named_collection_ids:
                continue
            seen.add(value)
            result.append(value)
        return result

    def normalize_client_usernames(self, usernames):
        valid_usernames = {
            str(item.get("username") or "").strip()
            for item in (self.get_available_users() or [])
            if str(item.get("username") or "").strip()
        }
        result = []
        seen = set()
        for item in usernames or []:
            value = str(item or "").strip()
            if not value or value in seen or value not in valid_usernames:
                continue
            seen.add(value)
            result.append(value)
        return result

    def normalize_media_rule_collection_ids(self, collection_ids, dlna_config=None):
        return self.normalize_client_collection_ids(collection_ids, dlna_config)

    def resolve_rule_matches(self, rule, files=None):
        return []

    def get_effective_file_map(self, dlna_config=None, files=None, include_pending_downloads=False):
        config = dlna_config or self._get_dlna_config_snapshot()
        collection_map = self._get_all_collection_map(config)
        pending_paths = self._get_pending_sync_paths(config)
        effective = {}
        for entry in self._get_entries(config):
            collection = collection_map.get(str(entry.get("collection_id") or "").strip())
            if not collection:
                continue
            if not include_pending_downloads and self._entry_is_pending_publication(entry, pending_paths):
                continue
            absolute_path = self._get_entry_current_path(entry)
            if not absolute_path or not os.path.isfile(absolute_path):
                continue
            effective[absolute_path] = {
                "storage_kind": self._normalize_storage_kind(entry.get("source_storage_kind") or "video"),
                "relative_path": str(entry.get("source_relative_path") or "").strip(),
                "display_path": self._format_relative_path_for_user(
                    entry.get("source_relative_path") or "",
                    viewer_username=self._get_current_viewer_username(),
                    is_admin=self._viewer_is_admin(),
                ),
                "size": os.path.getsize(absolute_path),
                "mtime": os.path.getmtime(absolute_path),
                "collection_ids": {collection["id"]},
                "rule_ids": set(),
            }
        return effective

    def get_client_visible_collection_ids(self, client, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        named_map = self._get_all_collection_map(config)
        visible_ids = {
            str(item or "").strip()
            for item in (client.get("collection_ids") or [])
            if str(item or "").strip() in named_map
        }
        assigned_usernames = set(self.get_client_assigned_usernames(client))
        if assigned_usernames:
            for collection in config.get("collections") or []:
                collection_id = str(collection.get("id") or "").strip()
                owner_username = str(collection.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username
                if collection_id and collection_id in named_map and owner_username in assigned_usernames:
                    visible_ids.add(collection_id)
        return visible_ids

    def get_client_assigned_usernames(self, client):
        return self.normalize_client_usernames((client or {}).get("usernames") or [])

    def build_media_rule_summaries(self, dlna_config=None, files=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        collection_map = self._get_all_collection_map(config)
        viewer = self._get_current_viewer_username()
        admin_view = self._viewer_is_admin()
        pending_paths = self._get_pending_sync_paths(config)
        summaries = []
        for entry in self._get_entries(config):
            collection = collection_map.get(str(entry.get("collection_id") or "").strip())
            if not collection:
                continue
            owner_username = str(collection.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username
            if not admin_view and owner_username != viewer:
                continue
            current_path = self._get_entry_current_path(entry)
            current_exists = bool(current_path and os.path.isfile(current_path))
            pending_publication = self._entry_is_pending_publication(entry, pending_paths)
            source_display_path = self._format_relative_path_for_user(
                entry.get("source_relative_path") or "",
                viewer_username=viewer,
                is_admin=admin_view,
            )
            summaries.append({
                "id": str(entry.get("id") or "").strip(),
                "kind": "file",
                "storage_kind": self._normalize_storage_kind(entry.get("source_storage_kind") or "video"),
                "relative_path": str(entry.get("source_relative_path") or "").strip(),
                "display_path": source_display_path,
                "enabled": current_exists and not pending_publication,
                "matched_files": 1 if current_exists and not pending_publication else 0,
                "exists": current_exists,
                "collection_ids": [collection["id"]],
                "collection_names": [collection["name"]],
                "owner_username": owner_username,
                "current_relative_path": str(entry.get("current_relative_path") or "").strip(),
                "current_exists": current_exists,
                "file_name": str(entry.get("file_name") or "").strip(),
                "pending_publication": pending_publication,
            })
        summaries.sort(
            key=lambda item: (
                build_natural_sort_key(", ".join(item.get("collection_names") or [])),
                build_natural_sort_key(item.get("display_path") or item.get("file_name") or ""),
            )
        )
        return summaries

    def build_client_summaries(self, dlna_config=None, files=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        collection_catalog = {
            item["id"]: item
            for item in self.get_collection_catalog(config)
        }
        all_collection_map = self._get_all_collection_map(config)
        available_user_map = {
            str(item.get("username") or "").strip(): item
            for item in (self.get_available_users() or [])
            if str(item.get("username") or "").strip()
        }
        pending_paths = self._get_pending_sync_paths(config)
        entry_count_map = {}
        for entry in self._get_entries(config):
            collection_id = str(entry.get("collection_id") or "").strip()
            if not collection_id:
                continue
            if self._entry_is_pending_publication(entry, pending_paths):
                continue
            current_path = self._get_entry_current_path(entry)
            if current_path and os.path.isfile(current_path):
                entry_count_map[collection_id] = entry_count_map.get(collection_id, 0) + 1

        client_items = []
        for client in config.get("clients") or []:
            visible_collection_ids = self.get_client_visible_collection_ids(client, config)
            assigned_usernames = self.get_client_assigned_usernames(client)
            visible_media_count = 0
            for collection_id in visible_collection_ids:
                visible_media_count += int(entry_count_map.get(collection_id, 0))
            client_items.append({
                "id": client["id"],
                "ip": client["ip"],
                "description": client.get("description") or "",
                "enabled": bool(client.get("enabled", True)),
                "collection_ids": list(visible_collection_ids),
                "collection_names": [
                    all_collection_map[item]["name"]
                    for item in visible_collection_ids
                    if item in all_collection_map
                ],
                "usernames": assigned_usernames,
                "user_labels": [
                    {
                        "username": username,
                        "role": str((available_user_map.get(username) or {}).get("role") or "user").strip().lower() or "user",
                        "text": "%s (%s)" % (
                            username,
                            "Administrator" if str((available_user_map.get(username) or {}).get("role") or "user").strip().lower() == "admin" else "Użytkownik",
                        ),
                    }
                    for username in assigned_usernames
                ],
                "visible_media_count": visible_media_count,
            })

        client_items.sort(key=lambda item: item["ip"])
        return client_items

    def get_summary_state(self, dlna_config=None, files=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        visible_collections = self._normalize_visible_collections(config)
        visible_collection_ids = {item["id"] for item in visible_collections}
        pending_paths = self._get_pending_sync_paths(config)
        visible_entries = []
        for item in self._get_entries(config):
            if str(item.get("collection_id") or "").strip() not in visible_collection_ids:
                continue
            if self._entry_is_pending_publication(item, pending_paths):
                continue
            current_path = self._get_entry_current_path(item)
            if current_path and os.path.isfile(current_path):
                visible_entries.append(item)
        runtime_phase = str(config.get("runtime_phase") or "idle").strip().lower() or "idle"
        return {
            "named_collection_count": len(visible_collections),
            "client_count": len(config.get("clients") or []) if self._viewer_is_admin() else 0,
            "active_client_count": len([item for item in (config.get("clients") or []) if item.get("enabled", True)]) if self._viewer_is_admin() else 0,
            "media_rule_count": len(visible_entries),
            "active_folder_rule_count": 0,
            "active_file_rule_count": len(visible_entries),
            "effective_media_count": len(visible_entries),
            "last_sync_at": config.get("last_sync_at") or 0.0,
            "last_sync_text": self._format_ts(config.get("last_sync_at")) if config.get("last_sync_at") else "jeszcze nie synchronizowano",
            "last_sync_error": config.get("last_sync_error") or "",
            "export_root": self._dlna_export_root,
            "config_file": self._dlna_config_xml_file,
            "service_unit_file": self._dlna_service_unit_file,
            "runtime_phase": runtime_phase,
            "runtime_phase_label": {
                "idle": "Bezczynny",
                "starting": "Uruchamianie",
                "rebuilding": "Przebudowa biblioteki",
                "running": "Działa",
                "error": "Błąd",
            }.get(runtime_phase, "Nieznany"),
            "runtime_phase_detail": str(config.get("runtime_phase_detail") or "").strip(),
            "runtime_phase_started_at": float(config.get("runtime_phase_started_at") or 0.0),
            "runtime_phase_started_text": self._format_ts(config.get("runtime_phase_started_at")) if config.get("runtime_phase_started_at") else "",
        }

    def get_page_state(self):
        dlna_config = self._normalize_dlna_config(self._get_dlna_config_snapshot())
        visible_collections = self.get_collection_catalog(dlna_config)
        return {
            "mount": self._get_mount_info(auto_remount=False),
            "dlna_config": dlna_config,
            "dlna_icon_state": self._get_dlna_icon_state(dlna_config),
            "permissions": {
                "logged_in": True,
                "is_admin": self._viewer_is_admin(),
                "current_username": self._get_current_viewer_username(),
            },
            "collections": visible_collections,
            "available_users": self.get_available_users() if self._viewer_is_admin() else [],
            "media_rules": self.build_media_rule_summaries(dlna_config),
            "clients": self.build_client_summaries(dlna_config),
            "summary": self.get_summary_state(dlna_config),
            "dlna_package_state": self._refresh_dlna_package_state(force=False) if self._viewer_is_admin() else {},
            "dlna_service_state": self._get_dlna_service_state() if self._viewer_is_admin() else {},
            "maintenance_tasks": self._get_all_maintenance_task_snapshots() if self._viewer_is_admin() else {},
        }

    def ensure_collection_membership_on_exact_rule(self, dlna_config, kind, storage_kind, relative_path, collection_id):
        raise ValueError("Ręczne wpisy DLNA nie są już obsługiwane. Użyj bukietów i zaznaczania plików.")

    def remove_collection_membership_from_exact_rule(self, dlna_config, kind, storage_kind, relative_path, collection_id):
        return False

    def explode_collection_from_matching_folder_rules(self, dlna_config, collection_id, file_items, files=None):
        return False

    def _build_collection_editor_pool(self, collection, query_text="", files=None, collection_map=None):
        owner_username = str(collection.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username
        collection_id = str(collection.get("id") or "").strip()
        config = self._get_dlna_config_snapshot()
        collection_map = collection_map or self._get_all_collection_map(config)
        files = files if files is not None else self._get_server_files(
            scope_username=owner_username,
            allow_auto_remount=False,
        )
        viewer = self._get_current_viewer_username()
        admin_view = self._viewer_is_admin()
        entry_lookup = self._build_source_entry_lookup(config)
        selected_entries = self._get_entries_for_collection(collection_id, config)
        results = []

        for item in files:
            if str(item.get("owner_username") or "").strip() != owner_username:
                continue
            if self._normalize_storage_kind(item.get("storage_kind") or "video") == "audio":
                continue
            if not self._is_supported_dlna_file(item.get("name") or item.get("relative_path") or ""):
                continue
            prepared = self._prepare_collection_item(item, entry_lookup, collection_id)
            if prepared["blocked_by_other_collection"] and not prepared["selected"]:
                continue
            haystack = "%s %s" % (prepared["title"], prepared["display_path"])
            if query_text and query_text not in haystack.lower():
                continue
            results.append(prepared)

        for entry in selected_entries:
            current_path = self._get_entry_current_path(entry)
            collection_name = str(collection.get("name") or "").strip()
            title = str(entry.get("file_name") or os.path.basename(current_path) or "").strip()
            source_display_path = self._format_relative_path_for_user(
                entry.get("source_relative_path") or "",
                viewer_username=viewer,
                is_admin=admin_view,
            )
            detail_text = "W bukiecie \"%s\" • źródło: %s" % (collection_name, source_display_path or "brak")
            haystack = "%s %s %s" % (title, source_display_path, detail_text)
            if query_text and query_text not in haystack.lower():
                continue
            results.append({
                "kind": "file",
                "entry_id": str(entry.get("id") or "").strip(),
                "storage_id": self._normalize_storage_id(entry.get("source_storage_id") or "local"),
                "storage_kind": self._normalize_storage_kind(entry.get("source_storage_kind") or "video"),
                "relative_path": str(entry.get("source_relative_path") or "").strip(),
                "display_path": source_display_path,
                "title": title,
                "detail_text": detail_text,
                "selected": True,
                "selected_via": "direct",
                "active_in_dlna": bool(current_path and os.path.isfile(current_path)),
                "media_kind": str(entry.get("media_kind") or "video"),
                "blocked_by_other_collection": False,
                "blocked_collection_name": "",
                "missing": not bool(current_path and os.path.isfile(current_path)),
            })

        dedup = {}
        for item in results:
            key = str(item.get("entry_id") or "").strip() or ("%s|%s" % (item["storage_id"], item["relative_path"]))
            previous = dedup.get(key)
            if previous and previous.get("selected"):
                continue
            dedup[key] = item

        merged_items = list(dedup.values())
        merged_items.sort(
            key=lambda item: (
                0 if item.get("selected") else 1,
                build_natural_sort_key(item.get("display_path") or item.get("title") or ""),
                build_natural_sort_key(item.get("title") or ""),
            )
        )
        return merged_items

    def bulk_assign_collection_items(self, collection_id, items):
        config = self._get_dlna_config_snapshot()
        collection = self._get_collection_by_id(collection_id, config)
        self._ensure_collection_manageable(collection)
        normalized_collection_id = str(collection.get("id") or "").strip()
        changed = False
        by_entry_id = self._get_entry_map(config)

        normalized_items = []
        seen_keys = set()
        for raw_item in items or []:
            if not isinstance(raw_item, dict):
                continue
            entry_id = str(raw_item.get("entry_id") or "").strip()
            storage_id = self._normalize_storage_id(raw_item.get("storage_id") or "local")
            storage_kind = self._normalize_storage_kind(raw_item.get("storage_kind") or "video")
            relative_path = str(raw_item.get("relative_path") or "").strip()
            checked = self._parse_boolean_flag(raw_item.get("checked"), default=False)
            key = entry_id or ("%s|%s" % (storage_id, relative_path))
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            normalized_items.append({
                "entry_id": entry_id,
                "storage_id": storage_id,
                "storage_kind": storage_kind,
                "relative_path": relative_path,
                "checked": checked,
            })

        for item in normalized_items:
            if item["checked"]:
                if item["entry_id"]:
                    entry = by_entry_id.get(item["entry_id"])
                    if entry and str(entry.get("collection_id") or "").strip() == normalized_collection_id:
                        continue
                if self.assign_file_to_collection(
                    item["storage_kind"],
                    item["relative_path"],
                    normalized_collection_id,
                    dlna_config=config,
                    persist=False,
                    sync_runtime=False,
                ):
                    changed = True
                continue

            if not item["entry_id"]:
                continue
            entry = by_entry_id.get(item["entry_id"])
            if not entry or str(entry.get("collection_id") or "").strip() != normalized_collection_id:
                continue
            if self._remove_entry(entry, collection, config, persist=False):
                changed = True
                by_entry_id.pop(item["entry_id"], None)

        if changed:
            self._set_dlna_config(config)
            self._sync_dlna_runtime_safe(restart_service_if_active=False, force_full_rescan=False, include_pending_downloads=False)

        return {
            "changed": changed,
            "updated_items": len(normalized_items),
            "collection_id": normalized_collection_id,
        }

    def build_collection_library_results(self, collection_id="", query="", mode="files", limit=200, dlna_config=None, files=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        collection = self._get_collection_by_id(collection_id, config)
        if not collection:
            return {
                "items": [],
                "total_items": 0,
                "shown_items": 0,
                "mode": "files",
                "collection_id": "",
                "collection_name": "",
            }
        self._ensure_collection_manageable(collection)
        query_text = str(query or "").strip().lower()
        items = self._build_collection_editor_pool(collection, query_text=query_text, files=files, collection_map=self._get_all_collection_map(config))
        limited_items = items[:max(1, min(500, int(limit or 200)))]
        return {
            "items": limited_items,
            "total_items": len(items),
            "shown_items": len(limited_items),
            "mode": "files",
            "collection_id": str(collection.get("id") or "").strip(),
            "collection_name": str(collection.get("name") or "").strip(),
        }

    def update_general_settings(self, server_name, bind_ip, port):
        if not self._viewer_is_admin():
            raise ValueError("Tylko administrator może zmieniać ustawienia serwera DLNA.")
        dlna_config = self._get_dlna_config_snapshot()
        dlna_config["server_name"] = self._normalize_dlna_server_name(server_name)
        dlna_config["bind_ip"] = self._normalize_dlna_bind_ip(bind_ip)
        dlna_config["port"] = self._normalize_dlna_port(port)
        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
        return self._get_dlna_config_snapshot()

    def create_collection(self, name, description=""):
        dlna_config = self._get_dlna_config_snapshot()
        normalized_name = self._normalize_dlna_collection_name(name)
        normalized_folder_name = self._sanitize_collection_folder_name(normalized_name, fallback=normalized_name)
        current_owner = self._get_current_viewer_username()
        for item in dlna_config.get("collections") or []:
            if str(item.get("name") or "").strip().lower() == normalized_name.lower():
                raise ValueError("Bukiet o tej nazwie już istnieje u innego użytkownika.")
            if str(item.get("folder_name") or "").strip().lower() == normalized_folder_name.lower():
                raise ValueError("Po oczyszczeniu nazwy ten bukiet miałby taki sam folder jak istniejący bukiet.")

        collection = {
            "id": uuid.uuid4().hex,
            "name": normalized_name,
            "description": self._normalize_dlna_description(description, max_len=320),
            "owner_username": current_owner,
            "folder_name": normalized_folder_name,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        dlna_config.setdefault("collections", []).append(collection)
        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=False, force_full_rescan=False, include_pending_downloads=False)
        return collection

    def _rename_collection_entries(self, collection, next_folder_name, dlna_config):
        collection_id = str(collection.get("id") or "").strip()
        for entry in self._get_entries_for_collection(collection_id, dlna_config):
            current_path = self._get_entry_current_path(entry)
            current_exists = bool(current_path and os.path.isfile(current_path))
            storage_id = self._normalize_storage_id(entry.get("source_storage_id") or "local")
            target_relative_path = self._safe_relative_download_path("%s/%s" % (next_folder_name, entry.get("file_name") or ""))
            target_path = self.get_collection_storage_path(storage_id, target_relative_path)
            if not target_path:
                raise ValueError("Nie udało się przygotować nowej ścieżki bukietu.")
            if current_exists and os.path.abspath(current_path) != os.path.abspath(target_path):
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                if os.path.exists(target_path):
                    raise ValueError("Docelowy plik %s już istnieje. Zmień nazwę bukietu albo zwolnij ten plik." % os.path.basename(target_path))
                shutil.move(current_path, target_path)
            entry["current_relative_path"] = target_relative_path

    def update_collection(self, collection_id, name, description=""):
        collection_id = str(collection_id or "").strip()
        if not collection_id:
            raise ValueError("Brak identyfikatora bukietu.")

        dlna_config = self._get_dlna_config_snapshot()
        collection = self._get_collection_by_id(collection_id, dlna_config)
        self._ensure_collection_manageable(collection)
        normalized_name = self._normalize_dlna_collection_name(name)
        normalized_folder_name = self._sanitize_collection_folder_name(normalized_name, fallback=normalized_name)
        for item in dlna_config.get("collections") or []:
            if str(item.get("id") or "").strip() == collection_id:
                continue
            if str(item.get("name") or "").strip().lower() == normalized_name.lower():
                raise ValueError("Bukiet o tej nazwie już istnieje u innego użytkownika.")
            if str(item.get("folder_name") or "").strip().lower() == normalized_folder_name.lower():
                raise ValueError("Po oczyszczeniu nazwy ten bukiet miałby taki sam folder jak istniejący bukiet.")

        if normalized_folder_name != str(collection.get("folder_name") or "").strip():
            self._rename_collection_entries(collection, normalized_folder_name, dlna_config)

        for item in dlna_config.get("collections") or []:
            if str(item.get("id") or "").strip() != collection_id:
                continue
            item["name"] = normalized_name
            item["folder_name"] = normalized_folder_name
            item["description"] = self._normalize_dlna_description(description, max_len=320)
            item["updated_at"] = time.time()
            break

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=False, force_full_rescan=False, include_pending_downloads=False)

    def _remove_entry(self, entry, collection, dlna_config, *, persist=True):
        current_path = self._get_entry_current_path(entry)
        source_path = self._get_entry_source_path(entry)
        if current_path and os.path.isfile(current_path) and source_path:
            if os.path.exists(source_path):
                raise ValueError("Nie mogę odłożyć pliku z powrotem do oryginalnej lokalizacji, bo plik już tam istnieje.")
            os.makedirs(os.path.dirname(source_path), exist_ok=True)
            shutil.move(current_path, source_path)
        entries = [
            item
            for item in (dlna_config.get("entries") or [])
            if str(item.get("id") or "").strip() != str(entry.get("id") or "").strip()
        ]
        dlna_config["entries"] = entries
        if persist:
            self._set_dlna_config(dlna_config)
        return True

    def delete_collection(self, collection_id):
        collection_id = str(collection_id or "").strip()
        if not collection_id:
            raise ValueError("Brak identyfikatora bukietu.")

        dlna_config = self._get_dlna_config_snapshot()
        collection = self._get_collection_by_id(collection_id, dlna_config)
        self._ensure_collection_manageable(collection)

        for entry in list(self._get_entries_for_collection(collection_id, dlna_config)):
            self._remove_entry(entry, collection, dlna_config, persist=False)

        dlna_config["collections"] = [
            item
            for item in (dlna_config.get("collections") or [])
            if str(item.get("id") or "").strip() != collection_id
        ]
        for client in dlna_config.get("clients") or []:
            client["collection_ids"] = [item for item in (client.get("collection_ids") or []) if item != collection_id]

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=False, force_full_rescan=False, include_pending_downloads=False)

    def assign_file_to_collection(
        self,
        storage_kind,
        relative_path,
        collection_id,
        *,
        sync_runtime=True,
        allow_background=False,
        return_details=False,
        dlna_config=None,
        persist=True,
    ):
        dlna_config = dlna_config if isinstance(dlna_config, dict) else self._get_dlna_config_snapshot()
        collection = self._get_collection_by_id(collection_id, dlna_config)
        if allow_background:
            if not collection:
                raise ValueError("Nie znaleziono wskazanego bukietu DLNA.")
        else:
            self._ensure_collection_manageable(collection)
        collection_owner = str(collection.get("owner_username") or self._default_admin_username).strip() or self._default_admin_username

        source_relative_path = str(relative_path or "").strip()
        source_path = self._resolve_download_path(
            source_relative_path,
            storage_kind or "video",
            owner_username=collection_owner,
        )
        if not source_path or not os.path.isfile(source_path):
            raise ValueError("Nie znaleziono wskazanego pliku do dodania do bukietu.")

        source_file_name = os.path.basename(source_path)
        media_kind = self._detect_media_kind(source_file_name)
        if not media_kind:
            raise ValueError("Do DLNA można dodawać tylko pliki wideo i zdjęcia. Czyste audio jest pomijane.")

        source_storage_id = "local"
        source_owner_username = collection_owner
        normalized_source_kind = self._normalize_storage_kind(storage_kind or "video")
        parsed_source = self._parse_source_relative_path(source_relative_path)
        if parsed_source:
            source_storage_id = self._normalize_storage_id(parsed_source.get("storage_id") or "local")
            source_owner_username = str(parsed_source.get("owner_username") or collection_owner).strip() or collection_owner
            normalized_source_kind = self._normalize_storage_kind(parsed_source.get("storage_kind") or normalized_source_kind)

        if source_owner_username != collection_owner:
            raise ValueError("Do bukietu możesz dodać tylko pliki właściciela tego bukietu.")

        source_key = (source_storage_id, source_relative_path)
        existing_entry = self._build_source_entry_lookup(dlna_config).get(source_key)
        if existing_entry:
            if str(existing_entry.get("collection_id") or "").strip() == str(collection_id or "").strip():
                if return_details:
                    return {
                        "changed": False,
                        "entry": existing_entry,
                        "collection": collection,
                        "target_path": self._get_entry_current_path(existing_entry),
                    }
                return False
            target_collection = self._get_collection_by_id(existing_entry.get("collection_id"), dlna_config)
            raise ValueError(
                "Ten plik znajduje się już w bukiecie \"%s\"." % (
                    str((target_collection or {}).get("name") or "innego użytkownika").strip() or "innego użytkownika"
                )
            )

        file_name = self._pick_unique_collection_file_name(collection, source_storage_id, source_file_name, dlna_config=dlna_config)
        target_relative_path = self._build_collection_entry_relative_path(collection, file_name)
        target_path = self.get_collection_storage_path(source_storage_id, target_relative_path)
        if not target_path:
            raise ValueError("Nie udało się przygotować katalogu bukietu DLNA.")
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.move(source_path, target_path)

        entry = {
            "id": uuid.uuid4().hex,
            "collection_id": str(collection.get("id") or "").strip(),
            "owner_username": source_owner_username,
            "source_storage_id": source_storage_id,
            "source_storage_kind": normalized_source_kind,
            "source_relative_path": source_relative_path,
            "current_relative_path": target_relative_path,
            "file_name": file_name,
            "media_kind": media_kind,
            "added_at": time.time(),
        }
        dlna_config.setdefault("entries", []).append(entry)
        if persist:
            self._set_dlna_config(dlna_config)
        if sync_runtime:
            self._sync_dlna_runtime_safe(restart_service_if_active=False, force_full_rescan=False, include_pending_downloads=False)
        if return_details:
            return {
                "changed": True,
                "entry": entry,
                "collection": collection,
                "target_path": target_path,
            }
        return True

    def create_client(self, ip, description="", enabled=True, collection_ids=None, usernames=None):
        if not self._viewer_is_admin():
            raise ValueError("Tylko administrator może zarządzać klientami DLNA.")
        dlna_config = self._get_dlna_config_snapshot()
        normalized_ip = self._normalize_dlna_client_ip(ip)
        if any(item["ip"] == normalized_ip for item in (dlna_config.get("clients") or [])):
            raise ValueError("Klient z tym adresem IP już istnieje.")

        client = {
            "id": uuid.uuid4().hex,
            "ip": normalized_ip,
            "description": self._normalize_dlna_description(description, max_len=200),
            "enabled": bool(enabled),
            "collection_ids": self.normalize_client_collection_ids(collection_ids or [], dlna_config),
            "usernames": self.normalize_client_usernames(usernames or []),
        }
        dlna_config.setdefault("clients", []).append(client)
        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True, include_pending_downloads=False)
        return client

    def update_client(self, client_id, ip, description="", enabled=True, collection_ids=None, usernames=None):
        if not self._viewer_is_admin():
            raise ValueError("Tylko administrator może zarządzać klientami DLNA.")
        client_id = str(client_id or "").strip()
        if not client_id:
            raise ValueError("Brak identyfikatora klienta.")

        dlna_config = self._get_dlna_config_snapshot()
        normalized_ip = self._normalize_dlna_client_ip(ip)
        for item in dlna_config.get("clients") or []:
            if item["id"] != client_id and item["ip"] == normalized_ip:
                raise ValueError("Inny klient używa już tego adresu IP.")

        found = False
        for item in dlna_config.get("clients") or []:
            if item["id"] != client_id:
                continue
            item["ip"] = normalized_ip
            item["description"] = self._normalize_dlna_description(description, max_len=200)
            item["enabled"] = bool(enabled)
            item["collection_ids"] = self.normalize_client_collection_ids(collection_ids or [], dlna_config)
            item["usernames"] = self.normalize_client_usernames(usernames or [])
            found = True
            break

        if not found:
            raise ValueError("Nie znaleziono wskazanego klienta.")

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True, include_pending_downloads=False)

    def delete_client(self, client_id):
        if not self._viewer_is_admin():
            raise ValueError("Tylko administrator może zarządzać klientami DLNA.")
        client_id = str(client_id or "").strip()
        if not client_id:
            raise ValueError("Brak identyfikatora klienta.")

        dlna_config = self._get_dlna_config_snapshot()
        before_count = len(dlna_config.get("clients") or [])
        dlna_config["clients"] = [item for item in (dlna_config.get("clients") or []) if item["id"] != client_id]
        if len(dlna_config["clients"]) == before_count:
            raise ValueError("Nie znaleziono wskazanego klienta.")

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True, include_pending_downloads=False)

    def create_media_rule(self, kind, storage_kind, relative_path, collection_ids=None, enabled=True):
        raise ValueError("Ręczne wpisy DLNA zostały zastąpione fizycznymi bukietami.")

    def update_media_rule(self, rule_id, collection_ids=None, enabled=True):
        raise ValueError("Ręczne wpisy DLNA zostały zastąpione fizycznymi bukietami.")

    def delete_media_rule(self, rule_id):
        raise ValueError("Ręczne wpisy DLNA zostały zastąpione fizycznymi bukietami.")
