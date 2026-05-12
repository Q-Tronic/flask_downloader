import os
import time
from urllib.parse import quote


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

    def get_user_storage_base_root(self):
        return self._get_config_snapshot()["user_storage_root"]

    def get_user_root(self, username):
        return os.path.join(self.get_user_storage_base_root(), self._normalize_username(username))

    def get_user_storage_root(self, username, storage_kind="video"):
        return os.path.join(self.get_user_root(username), self._normalize_storage_kind(storage_kind))

    def build_managed_relative_path(self, owner_username, storage_kind="video", user_relative_path=""):
        owner = self._normalize_username(owner_username)
        kind = self._normalize_storage_kind(storage_kind)
        relative_path = self.safe_relative_download_path(user_relative_path)
        if relative_path:
            return "%s/%s/%s" % (owner, kind, relative_path)
        return "%s/%s" % (owner, kind)

    def parse_managed_relative_path(self, value):
        relative_path = self.safe_relative_download_path(value)
        if not relative_path:
            return None

        parts = relative_path.split("/")
        if len(parts) < 3:
            return None

        try:
            owner_username = self._normalize_username(parts[0])
        except Exception:
            return None

        raw_storage_kind = str(parts[1] or "").strip().lower()
        if raw_storage_kind not in ("video", "audio"):
            return None

        user_relative_path = "/".join(parts[2:]).strip("/")
        if not user_relative_path:
            return None

        return {
            "owner_username": owner_username,
            "storage_kind": raw_storage_kind,
            "relative_path": relative_path,
            "user_relative_path": user_relative_path,
        }

    def get_managed_path_info(self, path):
        candidate = os.path.abspath(str(path or ""))
        base_root = os.path.abspath(self.get_user_storage_base_root())
        if not candidate:
            return None

        try:
            if os.path.commonpath([base_root, candidate]) != base_root:
                return None
        except Exception:
            return None

        try:
            relative_path = os.path.relpath(candidate, base_root).replace("\\", "/")
        except Exception:
            return None

        return self.parse_managed_relative_path(relative_path)

    def get_storage_root(self, storage_kind="video", owner_username=None):
        if owner_username:
            return self.get_user_storage_root(owner_username, storage_kind)
        return self.get_user_storage_base_root()

    def get_managed_storage_roots(self):
        roots = []
        base_root = os.path.abspath(self.get_user_storage_base_root())
        if not os.path.isdir(base_root):
            return roots

        for entry in sorted(os.listdir(base_root)):
            candidate_user_root = os.path.join(base_root, entry)
            if not os.path.isdir(candidate_user_root):
                continue
            try:
                owner_username = self._normalize_username(entry)
            except Exception:
                continue
            for storage_kind in ("video", "audio"):
                roots.append((owner_username, storage_kind, os.path.join(candidate_user_root, storage_kind)))
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
            return parsed["relative_path"]
        if suffix:
            return "%s/%s" % (parsed["storage_kind"], suffix)
        return parsed["storage_kind"]

    def build_managed_file_url(self, owner_username, storage_kind, relative_path):
        parsed = self.parse_managed_relative_path(relative_path)
        user_relative_path = self.safe_relative_download_path(parsed["user_relative_path"] if parsed else relative_path)
        owner = self._normalize_username((parsed or {}).get("owner_username") or owner_username or self._default_admin_username)
        kind = self._normalize_storage_kind((parsed or {}).get("storage_kind") or storage_kind or "video")
        return "/server-files/%s/%s/%s" % (
            quote(owner, safe=""),
            quote(kind, safe=""),
            quote(user_relative_path, safe="/"),
        )

    @staticmethod
    def get_daily_folder_name(ts=None):
        return time.strftime("%Y-%m-%d", time.localtime(ts or time.time()))

    def get_daily_download_dir(self, ts=None, media_kind="video", owner_username=None):
        owner = self._normalize_username(owner_username or self._get_current_username() or self._default_admin_username)
        return os.path.join(self.get_user_storage_root(owner, media_kind), self.get_daily_folder_name(ts))

    def get_relative_download_path(self, path, media_kind=None, owner_username=None):
        candidate = os.path.abspath(str(path or ""))
        if not candidate:
            return ""

        info = self.get_managed_path_info(candidate)
        if info:
            return info["relative_path"]

        if owner_username:
            try:
                storage_kind = self._normalize_storage_kind(media_kind or "video")
                owner = self._normalize_username(owner_username)
                user_root = os.path.abspath(self.get_user_storage_root(owner, storage_kind))
                if os.path.commonpath([user_root, candidate]) == user_root:
                    user_relative_path = os.path.relpath(candidate, user_root).replace("\\", "/")
                    return self.build_managed_relative_path(owner, storage_kind, user_relative_path)
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

    def resolve_download_path(self, relative_path, media_kind="video", owner_username=None):
        managed_info = self.parse_managed_relative_path(relative_path)
        if managed_info:
            global_relative_path = managed_info["relative_path"]
        else:
            safe_path = self.safe_relative_download_path(relative_path)
            if not safe_path:
                return ""
            try:
                owner = self._normalize_username(owner_username or self._get_current_username() or self._default_admin_username)
            except Exception:
                owner = self._default_admin_username
            global_relative_path = self.build_managed_relative_path(owner, media_kind, safe_path)

        base_root = os.path.abspath(self.get_user_storage_base_root())
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

        root = os.path.abspath(self.get_user_storage_root(info["owner_username"], info["storage_kind"]))
        current = os.path.abspath(os.path.dirname(path))

        while current.startswith(root) and current != root:
            try:
                os.rmdir(current)
            except OSError:
                break
            current = os.path.abspath(os.path.dirname(current))

    @staticmethod
    def is_temporary_download_artifact_name(name):
        lower = str(name or "").lower()
        return (
            lower.endswith(".part")
            or ".part-" in lower
            or lower.endswith(".ytdl")
            or ".ytdl" in lower
        )

    def get_server_files(self, scope_username=""):
        ok, _ = self._ensure_share_ready(auto_remount=True)
        if not ok:
            return []

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

            for owner_username, storage_kind, root in self.get_managed_storage_roots():
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

                        relative_path = self.get_relative_download_path(path, storage_kind, owner_username)
                        display_path = self.format_relative_path_for_user(relative_path, viewer_username=viewer_username, is_admin=admin_view)
                        files.append({
                            "owner_username": owner_username,
                            "name": name,
                            "storage_kind": storage_kind,
                            "storage_label": "Audio" if storage_kind == "audio" else "Wideo",
                            "relative_path": relative_path,
                            "user_relative_path": self.safe_relative_download_path((self.parse_managed_relative_path(relative_path) or {}).get("user_relative_path") or ""),
                            "display_path": display_path,
                            "size": st.st_size,
                            "mtime": st.st_mtime,
                            "mtime_text": self._format_ts(st.st_mtime),
                            "url": self.build_managed_file_url(owner_username, storage_kind, relative_path),
                        })
        except Exception:
            return []

        files.sort(key=lambda item: item["mtime"], reverse=True)
        return files
