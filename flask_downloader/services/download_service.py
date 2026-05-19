import os
import re


class DownloadPathService:
    def __init__(
        self,
        *,
        mount_point,
        get_user_storage_base_root,
        get_user_storage_root,
        normalize_username,
        normalize_storage_kind,
        get_current_username,
        default_admin_username,
        ensure_share_ready,
        safe_filename,
        get_daily_download_dir,
        is_temporary_download_artifact_name,
        cleanup_empty_download_dirs,
        cleanup_download_artifacts=None,
    ):
        self._mount_point = mount_point
        self._get_user_storage_base_root = get_user_storage_base_root
        self._get_user_storage_root = get_user_storage_root
        self._normalize_username = normalize_username
        self._normalize_storage_kind = normalize_storage_kind
        self._get_current_username = get_current_username
        self._default_admin_username = default_admin_username
        self._ensure_share_ready = ensure_share_ready
        self._safe_filename = safe_filename
        self._get_daily_download_dir = get_daily_download_dir
        self._is_temporary_download_artifact_name = is_temporary_download_artifact_name
        self._cleanup_empty_download_dirs = cleanup_empty_download_dirs
        self._cleanup_download_artifacts = cleanup_download_artifacts

    def check_download_dir_ready(self, storage_kind="video", owner_username=None):
        kind = self._normalize_storage_kind(storage_kind or "video")
        download_root = (
            self._get_user_storage_base_root()
            if owner_username is None
            else self._get_user_storage_root(owner_username, kind)
        )

        if not os.path.isdir(download_root):
            try:
                os.makedirs(download_root, exist_ok=True)
            except Exception as exc:
                return False, "Nie udało się utworzyć katalogu %s: %s" % (download_root, exc)

        if not os.path.isdir(download_root):
            return False, "Katalog docelowy nie istnieje: %s" % download_root

        if not os.access(download_root, os.R_OK | os.W_OK | os.X_OK):
            return False, "Brak dostępu do katalogu docelowego: %s" % download_root

        try:
            os.listdir(download_root)
        except Exception as exc:
            return False, "Katalog docelowy jest niedostępny: %s" % exc

        if owner_username is None:
            return True, "Katalog bazowy użytkowników gotowy: %s" % download_root
        return True, "Katalog docelowy gotowy: %s" % download_root

    def ensure_download_dir_ready(self, storage_kind="video", owner_username=None):
        ok, message = self._ensure_share_ready(auto_remount=True)
        if not ok:
            raise RuntimeError(message)

        owner = self._normalize_username(
            owner_username or self._get_current_username() or self._default_admin_username
        )
        root_ok, root_message = self.check_download_dir_ready(storage_kind, owner)
        if not root_ok:
            raise RuntimeError(root_message)

    def allocate_target_path(self, filename, media_kind="video", owner_username=None):
        kind = self._normalize_storage_kind(media_kind or "video")
        owner = self._normalize_username(
            owner_username or self._get_current_username() or self._default_admin_username
        )
        self.ensure_download_dir_ready(kind, owner)

        clean_filename = self._safe_filename(filename, default="video.bin")
        name, ext = os.path.splitext(clean_filename)
        day_dir = self._get_daily_download_dir(media_kind=kind, owner_username=owner)
        os.makedirs(day_dir, exist_ok=True)
        candidate = os.path.join(day_dir, clean_filename)
        counter = 1

        while os.path.exists(candidate) or os.path.exists(candidate + ".part"):
            candidate = os.path.join(day_dir, "%s_%d%s" % (name, counter, ext))
            counter += 1

        return candidate

    @staticmethod
    def get_download_artifact_roots(path):
        roots = set()
        current = os.path.abspath(str(path or ""))

        if not current or current == os.path.abspath("."):
            return roots

        roots.add(current)

        while current:
            next_path = current
            lowered = next_path.lower()

            if lowered.endswith(".ytdl"):
                next_path = next_path[:-5]

            stripped = re.sub(r"(?i)\.part(?:-[^\\/]+)?(?:\.part)?$", "", next_path)
            if stripped != next_path:
                next_path = stripped

            if next_path == current:
                break

            current = os.path.abspath(next_path)
            roots.add(current)

        return {root for root in roots if root and root != os.path.abspath(".")}

    def cleanup_download_artifacts(self, paths):
        seen = set()
        for raw_path in paths:
            if not raw_path or raw_path == "-":
                continue

            for base_path in self.get_download_artifact_roots(raw_path):
                candidates = {
                    base_path,
                    base_path + ".part",
                    base_path + ".ytdl",
                }

                parent_dir = os.path.dirname(base_path)
                base_name = os.path.basename(base_path)
                if os.path.isdir(parent_dir):
                    try:
                        for entry in os.listdir(parent_dir):
                            entry_path = os.path.join(parent_dir, entry)
                            entry_roots = self.get_download_artifact_roots(entry_path)

                            if entry == base_name:
                                candidates.add(entry_path)
                                continue

                            if base_path in entry_roots and self._is_temporary_download_artifact_name(entry):
                                candidates.add(entry_path)
                    except Exception:
                        pass

                for candidate in candidates:
                    if candidate in seen:
                        continue
                    seen.add(candidate)

                    if not os.path.exists(candidate):
                        continue

                    try:
                        os.remove(candidate)
                        self._cleanup_empty_download_dirs(candidate)
                    except Exception:
                        pass

    def finalize_overwritten_download(self, target_path, final_filename, replace_paths, owner_username=None, storage_kind="video"):
        normalized_target_path = os.path.abspath(str(target_path or ""))
        if not normalized_target_path:
            return normalized_target_path

        owner = self._normalize_username(
            owner_username or self._get_current_username() or self._default_admin_username
        )
        preferred_final_path = os.path.abspath(
            os.path.join(
                self._get_daily_download_dir(media_kind=storage_kind, owner_username=owner),
                self._safe_filename(final_filename, default="video.bin"),
            )
        )
        cleanup_targets = {
            os.path.abspath(path)
            for path in (replace_paths or [])
            if path and os.path.abspath(path) != normalized_target_path
        }

        cleanup_fn = self._cleanup_download_artifacts or self.cleanup_download_artifacts
        if cleanup_targets:
            cleanup_fn(cleanup_targets)

        if preferred_final_path != normalized_target_path:
            if os.path.exists(preferred_final_path):
                cleanup_fn({preferred_final_path})
            os.makedirs(os.path.dirname(preferred_final_path), exist_ok=True)
            os.replace(normalized_target_path, preferred_final_path)
            self._cleanup_empty_download_dirs(normalized_target_path)
            normalized_target_path = preferred_final_path

        return normalized_target_path
