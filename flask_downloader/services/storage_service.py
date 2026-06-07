import os
import re
import time
from urllib.parse import quote

from flask_downloader.utils.formatting import build_natural_sort_key


MANAGED_STORAGE_PREFIX = "@"


class ManagedStorageService:
    def __init__(
        self,
        *,
        get_config_snapshot,
        normalize_username,
        normalize_storage_kind,
        get_current_username,
        default_admin_username,
        has_request_context,
        is_admin_authenticated,
        ensure_share_ready,
        format_ts,
    ):
        self._get_config_snapshot = get_config_snapshot
        self._normalize_username = normalize_username
        self._normalize_storage_kind = normalize_storage_kind
        self._get_current_username = get_current_username
        self._default_admin_username = default_admin_username
        self._has_request_context = has_request_context
        self._is_admin_authenticated = is_admin_authenticated
        self._ensure_share_ready = ensure_share_ready
        self._format_ts = format_ts

    @staticmethod
    def _normalize_storage_id(value, default="local"):
        return "network" if str(value or "").strip().lower() == "network" else str(default or "local")

    @staticmethod
    def _normalize_network_mode(value, default="managed_smb"):
        text = str(value or "").strip().lower()
        if text == "external_path":
            return "external_path"
        return str(default or "managed_smb")

    def get_default_write_storage_id(self):
        storage = dict((self._get_config_snapshot() or {}).get("storage") or {})
        return self._normalize_storage_id(
            storage.get("default_write_storage_id") or storage.get("active_backend") or "local",
            default="local",
        )

    def get_storage_entry(self, storage_id=None):
        config = dict((self._get_config_snapshot() or {}).get("storage") or {})
        normalized_id = self._normalize_storage_id(storage_id or self.get_default_write_storage_id())
        if normalized_id == "network":
            network = dict(config.get("network") or {})
            return {
                "id": "network",
                "type": "network",
                "mode": self._normalize_network_mode(network.get("mode") or network.get("management_mode")),
                "label": str(network.get("label") or "Udział sieciowy").strip() or "Udział sieciowy",
                "root": os.path.abspath(str(network.get("mount_dir") or "").strip() or "."),
                "configured": bool(str(network.get("share") or "").strip() or str(network.get("mount_dir") or "").strip()),
                "raw": network,
            }
        local = dict(config.get("local") or {})
        return {
            "id": "local",
            "type": "local",
            "mode": "local",
            "label": str(local.get("label") or "Lokalny storage").strip() or "Lokalny storage",
            "root": os.path.abspath(str(local.get("root") or "").strip() or "."),
            "configured": True,
            "raw": local,
        }

    def get_storage_root_path(self, storage_id=None):
        return self.get_storage_entry(storage_id).get("root") or os.path.abspath(".")

    def get_storage_roots(self):
        return {
            "local": self.get_storage_root_path("local"),
            "network": self.get_storage_root_path("network"),
        }

    def get_user_storage_base_root(self, storage_id=None):
        return os.path.join(self.get_storage_root_path(storage_id), "flask_downloader_users")

    def get_user_root(self, username, storage_id=None):
        return os.path.join(
            self.get_user_storage_base_root(storage_id),
            self._normalize_username(username),
        )

    def get_user_storage_root(self, username, storage_kind="video", storage_id=None):
        return os.path.join(
            self.get_user_root(username, storage_id),
            self._normalize_storage_kind(storage_kind),
        )

    def build_managed_relative_path(self, owner_username, storage_kind="video", user_relative_path="", storage_id=None):
        owner = self._normalize_username(owner_username)
        kind = self._normalize_storage_kind(storage_kind)
        relative_path = self.safe_relative_download_path(user_relative_path)
        normalized_storage_id = self._normalize_storage_id(storage_id or self.get_default_write_storage_id())
        prefix = "%s%s/%s/%s" % (MANAGED_STORAGE_PREFIX, normalized_storage_id, owner, kind)
        if relative_path:
            return "%s/%s" % (prefix, relative_path)
        return prefix

    def parse_managed_relative_path(self, value):
        relative_path = self.safe_relative_download_path(value)
        if not relative_path:
            return None

        parts = relative_path.split("/")
        storage_id = ""
        owner_index = 0
        kind_index = 1
        user_path_index = 2

        if parts and str(parts[0] or "").startswith(MANAGED_STORAGE_PREFIX):
            if len(parts) < 4:
                return None
            storage_id = self._normalize_storage_id(str(parts[0])[1:], default=self.get_default_write_storage_id())
            owner_index = 1
            kind_index = 2
            user_path_index = 3
        elif len(parts) < 3:
            return None
        else:
            storage_id = self.get_default_write_storage_id()

        try:
            owner_username = self._normalize_username(parts[owner_index])
        except Exception:
            return None

        raw_storage_kind = str(parts[kind_index] or "").strip().lower()
        if raw_storage_kind not in ("video", "audio"):
            return None

        user_relative_path = "/".join(parts[user_path_index:]).strip("/")
        if not user_relative_path:
            return None

        return {
            "storage_id": storage_id,
            "owner_username": owner_username,
            "storage_kind": raw_storage_kind,
            "relative_path": relative_path,
            "user_relative_path": user_relative_path,
            "is_legacy": not str(parts[0] or "").startswith(MANAGED_STORAGE_PREFIX),
        }

    def get_managed_path_info(self, path):
        candidate = os.path.abspath(str(path or ""))
        if not candidate:
            return None

        for storage_id, base_root in self.get_storage_roots().items():
            absolute_root = os.path.abspath(self.get_user_storage_base_root(storage_id))
            try:
                if os.path.commonpath([absolute_root, candidate]) != absolute_root:
                    continue
            except Exception:
                continue

            try:
                relative_path = os.path.relpath(candidate, absolute_root).replace("\\", "/").strip("/")
            except Exception:
                continue
            parts = [segment for segment in relative_path.split("/") if segment]
            if len(parts) < 3:
                continue
            raw_storage_kind = str(parts[1] or "").strip().lower()
            if raw_storage_kind not in ("video", "audio"):
                continue
            try:
                owner_username = self._normalize_username(parts[0])
            except Exception:
                continue
            user_relative_path = "/".join(parts[2:]).strip("/")
            if not user_relative_path:
                continue
            return {
                "storage_id": self._normalize_storage_id(storage_id, default=self.get_default_write_storage_id()),
                "owner_username": owner_username,
                "storage_kind": raw_storage_kind,
                "relative_path": self.build_managed_relative_path(
                    owner_username,
                    raw_storage_kind,
                    user_relative_path,
                    storage_id=storage_id,
                ),
                "user_relative_path": user_relative_path,
                "is_legacy": False,
            }
        return None

    def get_storage_root(self, storage_kind="video", owner_username=None, storage_id=None):
        if owner_username:
            return self.get_user_storage_root(owner_username, storage_kind, storage_id=storage_id)
        return self.get_user_storage_base_root(storage_id)

    def get_managed_storage_roots(self):
        roots = []
        for storage_id, base_root in self.get_storage_roots().items():
            absolute_root = os.path.abspath(self.get_user_storage_base_root(storage_id))
            if not os.path.isdir(absolute_root):
                continue
            for entry in sorted(os.listdir(absolute_root)):
                candidate_user_root = os.path.join(absolute_root, entry)
                if not os.path.isdir(candidate_user_root):
                    continue
                try:
                    owner_username = self._normalize_username(entry)
                except Exception:
                    continue
                for storage_kind in ("video", "audio"):
                    roots.append((
                        storage_id,
                        owner_username,
                        storage_kind,
                        os.path.join(candidate_user_root, storage_kind),
                    ))
        return roots

    def get_storage_kind_for_path(self, path):
        info = self.get_managed_path_info(path)
        if info:
            return info["storage_kind"]
        return "video"

    def get_path_owner_username(self, path):
        info = self.get_managed_path_info(path)
        return (info or {}).get("owner_username") or self._default_admin_username

    def format_relative_path_for_user(self, relative_path, viewer_username="", is_admin=False):
        parsed = self.parse_managed_relative_path(relative_path)
        if not parsed:
            return self.safe_relative_download_path(relative_path)

        suffix = parsed["user_relative_path"]
        if is_admin:
            return "%s/%s/%s" % (
                parsed["storage_id"],
                parsed["owner_username"],
                parsed["storage_kind"],
            ) + ("/%s" % suffix if suffix else "")
        if suffix:
            return "%s/%s" % (parsed["storage_kind"], suffix)
        return parsed["storage_kind"]

    def build_managed_file_url(self, owner_username, storage_kind, relative_path):
        parsed = self.parse_managed_relative_path(relative_path)
        user_relative_path = self.safe_relative_download_path(parsed["user_relative_path"] if parsed else relative_path)
        owner = self._normalize_username((parsed or {}).get("owner_username") or owner_username or self._default_admin_username)
        kind = self._normalize_storage_kind((parsed or {}).get("storage_kind") or storage_kind or "video")
        storage_id = self._normalize_storage_id((parsed or {}).get("storage_id") or self.get_default_write_storage_id())
        return "/server-files/%s/%s/%s?storage=%s" % (
            quote(owner, safe=""),
            quote(kind, safe=""),
            quote(user_relative_path, safe="/"),
            quote(storage_id, safe=""),
        )

    @staticmethod
    def get_daily_folder_name(ts=None):
        return time.strftime("%Y-%m-%d", time.localtime(ts or time.time()))

    def get_daily_download_dir(self, ts=None, media_kind="video", owner_username=None, storage_id=None):
        owner = self._normalize_username(owner_username or self._get_current_username() or self._default_admin_username)
        return os.path.join(
            self.get_user_storage_root(owner, media_kind, storage_id=storage_id),
            self.get_daily_folder_name(ts),
        )

    def get_relative_download_path(self, path, media_kind=None, owner_username=None, storage_id=None):
        candidate = os.path.abspath(str(path or ""))
        if not candidate:
            return ""

        info = self.get_managed_path_info(candidate)
        if info:
            return self.build_managed_relative_path(
                info["owner_username"],
                info["storage_kind"],
                info["user_relative_path"],
                storage_id=info["storage_id"],
            )

        if owner_username:
            try:
                kind = self._normalize_storage_kind(media_kind or "video")
                owner = self._normalize_username(owner_username)
                normalized_storage_id = self._normalize_storage_id(storage_id or self.get_default_write_storage_id())
                user_root = os.path.abspath(self.get_user_storage_root(owner, kind, storage_id=normalized_storage_id))
                if os.path.commonpath([user_root, candidate]) == user_root:
                    user_relative_path = os.path.relpath(candidate, user_root).replace("\\", "/")
                    return self.build_managed_relative_path(
                        owner,
                        kind,
                        user_relative_path,
                        storage_id=normalized_storage_id,
                    )
            except Exception:
                return ""
        return ""

    @staticmethod
    def safe_relative_download_path(value):
        path = str(value or "").strip().replace("\\", "/")
        if not path:
            return ""

        normalized = os.path.normpath(path).replace("\\", "/").lstrip("/")
        if normalized in ("", ".", "..") or normalized.startswith("../"):
            return ""

        return normalized

    def resolve_download_path(self, relative_path, media_kind="video", owner_username=None, storage_id=None):
        managed_info = self.parse_managed_relative_path(relative_path)
        if managed_info:
            normalized_storage_id = self._normalize_storage_id(
                managed_info.get("storage_id") or storage_id or self.get_default_write_storage_id()
            )
            owner = self._normalize_username(
                managed_info.get("owner_username") or owner_username or self._get_current_username() or self._default_admin_username
            )
            kind = self._normalize_storage_kind(managed_info.get("storage_kind") or media_kind or "video")
            user_relative_path = self.safe_relative_download_path(managed_info.get("user_relative_path") or "")
        else:
            user_relative_path = self.safe_relative_download_path(relative_path)
            if not user_relative_path:
                return ""
            normalized_storage_id = self._normalize_storage_id(storage_id or self.get_default_write_storage_id())
            try:
                owner = self._normalize_username(owner_username or self._get_current_username() or self._default_admin_username)
            except Exception:
                owner = self._default_admin_username
            kind = self._normalize_storage_kind(media_kind or "video")

        base_root = os.path.abspath(self.get_user_storage_base_root(normalized_storage_id))
        global_relative_path = os.path.join(owner, kind, user_relative_path).replace("\\", "/")
        path = os.path.abspath(os.path.join(base_root, global_relative_path))

        try:
            if os.path.commonpath([base_root, path]) != base_root:
                return ""
        except Exception:
            return ""

        return path

    def cleanup_empty_download_dirs(self, path):
        info = self.get_managed_path_info(path)
        if not info:
            return

        root = os.path.abspath(
            self.get_user_storage_root(
                info["owner_username"],
                info["storage_kind"],
                storage_id=info["storage_id"],
            )
        )
        current = os.path.abspath(os.path.dirname(path))

        while current.startswith(root) and current != root:
            try:
                os.rmdir(current)
            except OSError:
                break
            current = os.path.abspath(os.path.dirname(current))

    @staticmethod
    def is_temporary_download_artifact_name(name):
        lower = str(name or "").lower().strip()
        return (
            lower.endswith(".part")
            or ".part-" in lower
            or lower.endswith(".ytdl")
            or ".ytdl" in lower
            or bool(re.search(r"(?i)\.(?:temp|f[0-9a-z][0-9a-z-]*)\.[^.\\/]+$", lower))
        )

    def get_server_files(self, scope_username="", allow_auto_remount=False):
        try:
            self._ensure_share_ready(auto_remount=bool(allow_auto_remount))
        except Exception:
            pass

        files = []
        seen_paths = set()
        try:
            viewer_username = self._get_current_username() if self._has_request_context() else self._default_admin_username
            admin_view = self._is_admin_authenticated() if self._has_request_context() else True
            selected_owner = ""
            if admin_view and scope_username:
                try:
                    selected_owner = self._normalize_username(scope_username)
                except Exception:
                    selected_owner = ""

            for storage_id, owner_username, storage_kind, root in self.get_managed_storage_roots():
                if selected_owner and owner_username != selected_owner:
                    continue
                if not admin_view and owner_username != viewer_username:
                    continue
                if not os.path.isdir(root):
                    continue

                for current_root, _, filenames in os.walk(root):
                    for name in filenames:
                        if self.is_temporary_download_artifact_name(name):
                            continue

                        path = os.path.abspath(os.path.join(current_root, name))
                        if path in seen_paths:
                            continue
                        seen_paths.add(path)

                        try:
                            st = os.stat(path)
                        except Exception:
                            continue

                        relative_path = self.get_relative_download_path(
                            path,
                            storage_kind,
                            owner_username,
                            storage_id=storage_id,
                        )
                        display_path = self.format_relative_path_for_user(
                            relative_path,
                            viewer_username=viewer_username,
                            is_admin=admin_view,
                        )
                        parsed = self.parse_managed_relative_path(relative_path) or {}
                        files.append({
                            "storage_id": storage_id,
                            "owner_username": owner_username,
                            "name": name,
                            "storage_kind": storage_kind,
                            "storage_label": "Audio" if storage_kind == "audio" else "Wideo",
                            "relative_path": relative_path,
                            "user_relative_path": self.safe_relative_download_path(parsed.get("user_relative_path") or ""),
                            "display_path": display_path,
                            "size": st.st_size,
                            "mtime": st.st_mtime,
                            "mtime_text": self._format_ts(st.st_mtime),
                            "url": self.build_managed_file_url(owner_username, storage_kind, relative_path),
                        })
        except Exception:
            return []

        files.sort(
            key=lambda item: (
                build_natural_sort_key(item.get("display_path") or ""),
                build_natural_sort_key(item.get("name") or ""),
            )
        )
        return files
