import os
import re
import shutil
import tarfile
import tempfile
import time


class AppUpdateService:
    VERSION_PATTERN = re.compile(r"^V(?P<major>\d+)\.(?P<year>\d{2})\.(?P<month>\d{2})\.(?P<seq>\d{3})$")

    def __init__(
        self,
        *,
        project_root,
        version_file,
        requirements_file,
        venv_pip_path,
        requests_module,
        format_ts,
        is_linux_runtime,
        repo_owner,
        repo_name,
        repo_branch,
        read_update_state,
        save_update_state,
        schedule_service_restart,
        finalize_update_detached,
    ):
        self._project_root = os.path.abspath(str(project_root or "").strip() or ".")
        self._version_file = os.path.abspath(str(version_file or "").strip() or os.path.join(self._project_root, "VERSION"))
        self._requirements_file = os.path.abspath(str(requirements_file or "").strip() or os.path.join(self._project_root, "requirements.txt"))
        self._venv_pip_path = os.path.abspath(str(venv_pip_path or "").strip() or os.path.join(self._project_root, ".venv", "bin", "pip"))
        self._requests = requests_module
        self._format_ts = format_ts
        self._is_linux_runtime = is_linux_runtime
        self._repo_owner = str(repo_owner or "").strip() or "Q-Tronic"
        self._repo_name = str(repo_name or "").strip() or "flask_downloader"
        self._repo_branch = str(repo_branch or "").strip() or "main"
        self._read_update_state = read_update_state
        self._save_update_state = save_update_state
        self._schedule_service_restart = schedule_service_restart
        self._finalize_update_detached = finalize_update_detached

    @staticmethod
    def default_update_state():
        return {
            "latest_version": "",
            "checked_at": 0.0,
            "check_error": "",
        }

    @classmethod
    def normalize_update_state(cls, value):
        state = cls.default_update_state()
        if not isinstance(value, dict):
            return state

        try:
            checked_at = float(value.get("checked_at") or 0.0)
        except Exception:
            checked_at = 0.0

        state.update({
            "latest_version": str(value.get("latest_version") or "").strip(),
            "checked_at": checked_at,
            "check_error": str(value.get("check_error") or "").strip(),
        })
        return state

    @classmethod
    def _parse_version_tuple(cls, value):
        match = cls.VERSION_PATTERN.match(str(value or "").strip())
        if not match:
            return None
        return (
            int(match.group("major")),
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("seq")),
        )

    @classmethod
    def is_update_available_for_versions(cls, latest_version, current_version):
        latest_text = str(latest_version or "").strip()
        current_text = str(current_version or "").strip()
        if not latest_text or not current_text or latest_text == current_text:
            return False

        latest_tuple = cls._parse_version_tuple(latest_text)
        current_tuple = cls._parse_version_tuple(current_text)
        if latest_tuple and current_tuple:
            return latest_tuple > current_tuple
        return latest_text != current_text

    def _fetch_text(self, url):
        response = self._requests.get(
            url,
            headers={"User-Agent": "VLC-Stream-Extractor-App-Updater"},
            timeout=(10, 30),
        )
        response.raise_for_status()
        return str(response.text or "")

    def get_current_version(self):
        try:
            with open(self._version_file, "r", encoding="utf-8") as fh:
                return str(fh.read() or "").strip()
        except Exception:
            return ""

    def fetch_latest_version(self):
        raw_url = "https://raw.githubusercontent.com/%s/%s/%s/VERSION" % (
            self._repo_owner,
            self._repo_name,
            self._repo_branch,
        )
        raw_text = self._fetch_text(raw_url)
        version_text = str((raw_text.splitlines() or [""])[0]).strip()
        if not self._parse_version_tuple(version_text):
            raise RuntimeError("GitHub zwrócił nieprawidłowy numer wersji aplikacji: %s" % (version_text or "brak"))
        return version_text

    def needs_scheduled_check(self, checked_at, *, now=None):
        current_ts = float((now or time.time()) or 0.0)
        try:
            checked_ts = float(checked_at or 0.0)
        except Exception:
            checked_ts = 0.0
        return checked_ts <= 0 or (current_ts - checked_ts) >= 6 * 3600

    def get_update_state_snapshot(self):
        raw = self.normalize_update_state(self._read_update_state())
        current_version = self.get_current_version() or "brak"
        latest_version = raw["latest_version"]
        update_available = self.is_update_available_for_versions(latest_version, current_version)
        linux_supported = bool(self._is_linux_runtime())

        if raw["check_error"]:
            status_pill_kind = "error"
            status_pill_label = "Błąd sprawdzenia"
        elif not latest_version:
            status_pill_kind = "muted"
            status_pill_label = "Jeszcze nie sprawdzono"
        elif update_available:
            status_pill_kind = "queued"
            status_pill_label = "Dostępna aktualizacja"
        else:
            status_pill_kind = "success"
            status_pill_label = "Aktualna"

        action_note_text = "Aplikacja nie wymaga teraz aktualizacji."
        if not linux_supported:
            action_note_text = "Panel może tylko sprawdzić wersję. Automatyczna aktualizacja z panelu WWW wymaga Linuxa."
        elif raw["check_error"]:
            action_note_text = "Najpierw popraw błąd sprawdzenia wersji albo ponów próbę później."

        return {
            "current_version": current_version,
            "latest_version": latest_version or "jeszcze nie sprawdzono",
            "latest_version_raw": latest_version,
            "checked_at": raw["checked_at"],
            "checked_at_text": self._format_ts(raw["checked_at"]),
            "check_error": raw["check_error"],
            "repo_label": "%s/%s" % (self._repo_owner, self._repo_name),
            "repo_branch": self._repo_branch,
            "linux_supported": linux_supported,
            "update_available": update_available,
            "action_needed": linux_supported and update_available,
            "action_button_label": "Zaktualizuj aplikację z GitHuba",
            "action_note_text": action_note_text,
            "status_pill_kind": status_pill_kind,
            "status_pill_label": status_pill_label,
        }

    def refresh_update_state(self, force=False):
        snapshot = self.normalize_update_state(self._read_update_state())
        if not force and not self.needs_scheduled_check(snapshot["checked_at"]) and snapshot["latest_version"]:
            return self.get_update_state_snapshot()

        latest_version = snapshot["latest_version"]
        check_error = ""
        checked_at = time.time()
        try:
            latest_version = self.fetch_latest_version()
        except Exception as exc:
            check_error = str(exc or "").strip()

        self._save_update_state(latest_version, checked_at, check_error)
        return self.get_update_state_snapshot()

    def _copy_repo_payload(self, source_root, target_root):
        excluded_names = {".git", ".venv", ".github", "backups", "dlna"}
        excluded_relative_paths = {
            ".env",
            "data/config.json",
            "data/jobs.json",
            "data/users.json",
            "data/radios.json",
            "data/calendar_cache.json",
            "data/name_days_pl.json",
            "data/unusual_holidays_pl.json",
            "tools/ffmpeg",
            "tools/dlna/runtime",
        }

        for root, dirnames, filenames in os.walk(source_root):
            rel_root = os.path.relpath(root, source_root).replace("\\", "/")
            if rel_root == ".":
                rel_root = ""

            dirnames[:] = [
                name for name in dirnames
                if name not in excluded_names
                and ("%s/%s" % (rel_root, name) if rel_root else name) not in excluded_relative_paths
            ]

            for filename in filenames:
                rel_path = ("%s/%s" % (rel_root, filename) if rel_root else filename).replace("\\", "/")
                if rel_path in excluded_relative_paths:
                    continue
                source_path = os.path.join(root, filename)
                target_path = os.path.join(target_root, rel_path.replace("/", os.sep))
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(source_path, target_path)

    def _backup_current_code(self, destination_path):
        excluded_names = {".venv", "backups", "dlna", ".git", ".github"}
        excluded_relative_paths = {
            ".env",
            "data",
            "tools/ffmpeg",
            "tools/dlna/runtime",
        }

        with tarfile.open(destination_path, "w:gz") as archive:
            for root, dirnames, filenames in os.walk(self._project_root):
                rel_root = os.path.relpath(root, self._project_root).replace("\\", "/")
                if rel_root == ".":
                    rel_root = ""

                dirnames[:] = [
                    name for name in dirnames
                    if name not in excluded_names
                    and ("%s/%s" % (rel_root, name) if rel_root else name) not in excluded_relative_paths
                ]

                for filename in filenames:
                    rel_path = ("%s/%s" % (rel_root, filename) if rel_root else filename).replace("\\", "/")
                    if rel_path in excluded_relative_paths:
                        continue
                    archive.add(
                        os.path.join(root, filename),
                        arcname=rel_path,
                        recursive=False,
                    )

    def update_from_github(self, progress_callback=None):
        if not self._is_linux_runtime():
            return False, "Automatyczna aktualizacja aplikacji z panelu WWW wymaga Linuxa."

        latest_state = self.refresh_update_state(force=True)
        if not latest_state["update_available"]:
            return True, "Masz już najnowszą wersję aplikacji (%s)." % latest_state["current_version"]

        archive_url = "https://codeload.github.com/%s/%s/tar.gz/refs/heads/%s" % (
            self._repo_owner,
            self._repo_name,
            self._repo_branch,
        )
        current_version = self.get_current_version() or "brak"

        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = os.path.join(tmp_dir, "repo.tar.gz")
            extract_dir = os.path.join(tmp_dir, "extract")
            os.makedirs(extract_dir, exist_ok=True)

            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Pobieranie",
                    progress_percent=12.0,
                    detail="Pobieram najnowszy kod aplikacji z GitHuba.",
                )

            with self._requests.get(
                archive_url,
                headers={"User-Agent": "VLC-Stream-Extractor-App-Updater"},
                timeout=(15, 180),
                stream=True,
            ) as response:
                response.raise_for_status()
                with open(archive_path, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=1024 * 512):
                        if chunk:
                            fh.write(chunk)

            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Rozpakowywanie",
                    progress_percent=28.0,
                    detail="Rozpakowuję archiwum repozytorium i przygotowuję payload aktualizacji.",
                )

            with tarfile.open(archive_path, "r:gz") as archive:
                archive.extractall(extract_dir)

            extracted_dirs = [
                os.path.join(extract_dir, item)
                for item in os.listdir(extract_dir)
                if os.path.isdir(os.path.join(extract_dir, item))
            ]
            if not extracted_dirs:
                raise RuntimeError("Nie udało się rozpakować archiwum aplikacji z GitHuba.")
            source_root = extracted_dirs[0]

            backups_root = os.path.join(self._project_root, "backups")
            os.makedirs(backups_root, exist_ok=True)
            backup_path = os.path.join(
                backups_root,
                "code-update-%s.tgz" % time.strftime("%Y%m%d-%H%M%S", time.localtime()),
            )
            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Backup",
                    progress_percent=42.0,
                    detail="Tworzę backup bieżącego kodu aplikacji w katalogu backups/.",
                )
            self._backup_current_code(backup_path)

            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Podmiana plików",
                    progress_percent=62.0,
                    detail="Podmieniam pliki aplikacji bez naruszania data/, .env i runtime.",
                )
            self._copy_repo_payload(source_root, self._project_root)

            has_python_dependencies = os.path.isfile(self._requirements_file) and os.path.isfile(self._venv_pip_path)
            if progress_callback:
                dependency_detail = (
                    "Przygotowuję bezpieczną finalizację zależności poza żywym procesem panelu WWW."
                    if has_python_dependencies
                    else "Przygotowuję bezpieczny restart po podmianie kodu bez aktualizacji zależności."
                )
                progress_callback(
                    status="running",
                    status_label="Zależności",
                    progress_percent=82.0,
                    detail=dependency_detail,
                )
            detached_finalize = self._finalize_update_detached(
                pip_path=self._venv_pip_path if has_python_dependencies else "",
                requirements_file=self._requirements_file if has_python_dependencies else "",
            )

            new_version = self.get_current_version() or latest_state["latest_version_raw"] or current_version
            self._save_update_state(new_version, time.time(), "")

            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Restart",
                    progress_percent=96.0,
                    detail="Kod aplikacji jest gotowy. Za chwilę odłączony helper bezpiecznie zatrzyma panel, zaktualizuje zależności i uruchomi usługę ponownie.",
                )
            finalize_detail = "Finalizacja aktualizacji została uruchomiona w tle"
            if detached_finalize.get("log_file"):
                finalize_detail += " (log: %s)" % detached_finalize["log_file"]
            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Restart",
                    progress_percent=98.0,
                    detail=finalize_detail + ". Panel może być chwilowo niedostępny podczas zatrzymania i ponownego startu usługi.",
                )

            message = "Aplikacja została zaktualizowana z %s do %s. Finalizacja zależności i restart usługi zostały odłączone od panelu, więc strona może zniknąć na chwilę i wrócić po starcie." % (
                current_version,
                new_version,
            )
            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Gotowe",
                    progress_percent=100.0,
                    detail=message,
                )
            return True, message


__all__ = ["AppUpdateService"]
