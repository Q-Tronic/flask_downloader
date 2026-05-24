import copy
import hashlib
import os
import random
import re
import socket
import shutil
import subprocess
import threading
import time
import uuid
from xml.etree import ElementTree as ET


class RadioRuntimeService:
    PACKAGE_NAMES = ("icecast2", "liquidsoap")
    RADIO_LOG_MAX_BYTES = 5 * 1024 * 1024
    ICECAST_LOG_MAX_KBYTES = 5120

    def __init__(
        self,
        *,
        radios_store,
        radios_lock,
        write_radio_store_locked,
        get_radio_store_snapshot,
        normalize_username,
        resolve_download_path,
        format_ts,
        app_service_user,
        app_service_group,
        app_root,
        runtime_root,
        backend_service_name,
        station_service_template_name,
        requests_module,
        is_linux_runtime,
        get_generic_service_state,
        run_systemctl_command,
        run_systemctl_command_result,
        systemd_quote_arg,
        build_erds_preview_lines,
        build_library_table_rows,
    ):
        self._radios_store = radios_store
        self._radios_lock = radios_lock
        self._write_radio_store_locked = write_radio_store_locked
        self._get_radio_store_snapshot = get_radio_store_snapshot
        self._normalize_username = normalize_username
        self._resolve_download_path = resolve_download_path
        self._format_ts = format_ts
        self._app_service_user, self._app_service_group = self._resolve_runtime_identity(
            app_service_user=app_service_user,
            app_service_group=app_service_group,
        )
        self._backend_service_user, self._backend_service_group = self._resolve_backend_identity(
            fallback_user=self._app_service_user,
            fallback_group=self._app_service_group,
        )
        self._app_root = os.path.abspath(str(app_root or "").strip() or ".")
        self._backend_service_name = str(backend_service_name or "").strip() or "flask-downloader-radio"
        self._station_service_template_name = str(station_service_template_name or "").strip() or "flask-downloader-radio-station@"
        self._runtime_root = self._resolve_runtime_root(
            runtime_root=runtime_root,
            app_root=self._app_root,
            backend_service_name=self._backend_service_name,
            backend_service_user=self._backend_service_user,
        )
        self._requests = requests_module
        self._is_linux_runtime = is_linux_runtime
        self._get_generic_service_state = get_generic_service_state
        self._run_systemctl_command = run_systemctl_command
        self._run_systemctl_command_result = run_systemctl_command_result
        self._systemd_quote_arg = systemd_quote_arg
        self._build_erds_preview_lines = build_erds_preview_lines
        self._build_library_table_rows = build_library_table_rows

        self._config_dir = os.path.join(self._runtime_root, "config")
        self._scripts_dir = os.path.join(self._runtime_root, "scripts")
        self._playlists_dir = os.path.join(self._runtime_root, "playlists")
        self._logs_dir = os.path.join(self._runtime_root, "logs")
        self._backend_log_file = os.path.join(self._logs_dir, "radio-backend.log")
        self._backend_access_log_file = os.path.join(self._logs_dir, "icecast-access.log")
        self._backend_error_log_file = os.path.join(self._logs_dir, "icecast-error.log")
        self._backend_playlist_log_file = os.path.join(self._logs_dir, "playlist.log")
        self._backend_pid_file = os.path.join(self._runtime_root, "radio-backend.pid")
        self._icecast_config_file = os.path.join(self._config_dir, "icecast.xml")
        self._backend_unit_file = os.path.join("/etc", "systemd", "system", "%s.service" % self._backend_service_name)
        self._station_unit_template_file = os.path.join("/etc", "systemd", "system", "%s.service" % self._station_service_template_name)
        self._metadata_scheduler_lock = threading.Lock()
        self._metadata_scheduler_started = False
        self._package_scheduler_lock = threading.Lock()
        self._package_scheduler_started = False
        self._log_maintenance_lock = threading.Lock()
        self._package_check_hour = 4

    @staticmethod
    def _lookup_posix_user(username):
        if os.name == "nt":
            return None
        try:
            import pwd

            return pwd.getpwnam(str(username or "").strip())
        except Exception:
            return None

    @staticmethod
    def _lookup_posix_group(group_name):
        if os.name == "nt":
            return None
        try:
            import grp

            return grp.getgrnam(str(group_name or "").strip())
        except Exception:
            return None

    @staticmethod
    def _lookup_posix_group_by_gid(group_id):
        if os.name == "nt":
            return None
        try:
            import grp

            return grp.getgrgid(int(group_id))
        except Exception:
            return None

    @classmethod
    def _get_current_process_user_name(cls):
        if os.name == "nt":
            return ""
        try:
            import pwd

            return pwd.getpwuid(os.geteuid()).pw_name
        except Exception:
            return ""

    @classmethod
    def _get_current_process_group_name(cls):
        if os.name == "nt":
            return ""
        try:
            import grp

            return grp.getgrgid(os.getegid()).gr_name
        except Exception:
            return ""

    @classmethod
    def _resolve_runtime_identity(cls, *, app_service_user, app_service_group):
        resolved_user = str(app_service_user or "").strip() or "flaskdl"
        resolved_group = str(app_service_group or "").strip() or resolved_user
        if os.name == "nt":
            return resolved_user, resolved_group

        if cls._lookup_posix_user(resolved_user) is None:
            fallback_user = cls._get_current_process_user_name()
            if fallback_user:
                resolved_user = fallback_user

        if cls._lookup_posix_group(resolved_group) is None:
            fallback_group = cls._get_current_process_group_name()
            if fallback_group:
                resolved_group = fallback_group
            elif cls._lookup_posix_group(resolved_user) is not None:
                resolved_group = resolved_user

        return resolved_user, resolved_group

    @classmethod
    def _resolve_backend_identity(cls, *, fallback_user, fallback_group):
        if os.name == "nt":
            return fallback_user, fallback_group
        preferred_backend = cls._lookup_posix_user("icecast2") or cls._lookup_posix_user("icecast")
        if preferred_backend is None:
            return fallback_user, fallback_group
        backend_group = cls._lookup_posix_group_by_gid(preferred_backend.pw_gid)
        return preferred_backend.pw_name, str((backend_group.gr_name if backend_group else fallback_group) or fallback_group)

    @classmethod
    def _resolve_runtime_root(cls, *, runtime_root, app_root, backend_service_name, backend_service_user):
        requested_root = os.path.abspath(str(runtime_root or "").strip() or os.path.join(app_root, "data", "runtime", "radio"))
        if os.name == "nt":
            return requested_root
        normalized = requested_root.replace("\\", "/")
        if str(backend_service_user or "").strip() != "root" and (normalized == "/root" or normalized.startswith("/root/")):
            return os.path.join("/var", "lib", str(backend_service_name or "flask-downloader-radio").strip() or "flask-downloader-radio")
        return requested_root

    @staticmethod
    def _default_backend_update_state():
        return {
            "checked_at": 0.0,
            "check_error": "",
            "package_versions": {},
        }

    @staticmethod
    def _format_bytes_text(size):
        try:
            value = float(size)
        except Exception:
            return "0 B"
        if value <= 0:
            return "0 B"
        units = ("B", "KB", "MB", "GB", "TB")
        unit_index = 0
        while value >= 1024.0 and unit_index < len(units) - 1:
            value /= 1024.0
            unit_index += 1
        return ("%d %s" if unit_index == 0 else "%.2f %s") % (value, units[unit_index])

    @staticmethod
    def _escape_xml(value):
        text = str(value or "")
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    @staticmethod
    def _normalize_mount_name(value):
        text = str(value or "").strip().lstrip("/")
        if not text:
            return ""
        return text

    @staticmethod
    def _normalize_playlist_mode(value):
        return "random" if str(value or "").strip().lower() == "random" else "normal"

    @staticmethod
    def _normalize_repeat_guard_percent(value, default=100):
        try:
            parsed = int(str(value or "").strip())
        except Exception:
            parsed = int(default or 100)
        return max(0, min(100, parsed))

    @staticmethod
    def _normalize_number(value, default=0, minimum=0, maximum=99999):
        try:
            parsed = int(str(value or "").strip())
        except Exception:
            return default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _build_apt_query_env():
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        env["LANGUAGE"] = "C"
        return env

    def _ensure_runtime_dirs(self):
        for path in (
            self._runtime_root,
            self._config_dir,
            self._scripts_dir,
            self._playlists_dir,
            self._logs_dir,
        ):
            os.makedirs(path, exist_ok=True)
        self._apply_runtime_permissions()

    def _apply_runtime_permissions(self):
        if os.name == "nt":
            return
        user_entry = self._lookup_posix_user(self._backend_service_user)
        group_entry = self._lookup_posix_group(self._backend_service_group)
        if user_entry is None or group_entry is None:
            return
        uid = int(user_entry.pw_uid)
        gid = int(group_entry.gr_gid)
        for root_dir, dir_names, file_names in os.walk(self._runtime_root):
            try:
                os.chown(root_dir, uid, gid)
                os.chmod(root_dir, 0o775)
            except Exception:
                pass
            for dir_name in dir_names:
                path = os.path.join(root_dir, dir_name)
                try:
                    os.chown(path, uid, gid)
                    os.chmod(path, 0o775)
                except Exception:
                    pass
            for file_name in file_names:
                path = os.path.join(root_dir, file_name)
                try:
                    os.chown(path, uid, gid)
                    os.chmod(path, 0o664)
                except Exception:
                    pass

    def _get_backend_update_state_locked(self):
        raw = (self._radios_store or {}).get("backend_update_state") or {}
        state = self._default_backend_update_state()
        if isinstance(raw, dict):
            try:
                state["checked_at"] = float(raw.get("checked_at") or 0.0)
            except Exception:
                state["checked_at"] = 0.0
            state["check_error"] = str(raw.get("check_error") or "").strip()
            package_versions = {}
            for package_name, value in ((raw.get("package_versions") or {}) if isinstance(raw.get("package_versions"), dict) else {}).items():
                package_versions[str(package_name or "").strip().lower()] = {
                    "installed": str((value or {}).get("installed") or "").strip(),
                    "candidate": str((value or {}).get("candidate") or "").strip(),
                }
            state["package_versions"] = package_versions
        return state

    def _save_backend_update_state(self, package_versions=None, check_error="", checked_at=None):
        with self._radios_lock:
            state = self._get_backend_update_state_locked()
            state["checked_at"] = float(checked_at if checked_at is not None else time.time())
            state["check_error"] = str(check_error or "").strip()
            if package_versions is not None:
                normalized_versions = {}
                for package_name, value in (package_versions or {}).items():
                    normalized_versions[str(package_name or "").strip().lower()] = {
                        "installed": str((value or {}).get("installed") or "").strip(),
                        "candidate": str((value or {}).get("candidate") or "").strip(),
                    }
                state["package_versions"] = normalized_versions
            self._radios_store["backend_update_state"] = state
            self._write_radio_store_locked()
        return copy.deepcopy(state)

    def _get_last_due_check_ts(self, now_ts=None):
        current = time.localtime(now_ts or time.time())
        due_tuple = (
            current.tm_year,
            current.tm_mon,
            current.tm_mday,
            self._package_check_hour,
            0,
            0,
            current.tm_wday,
            current.tm_yday,
            current.tm_isdst,
        )
        due_ts = time.mktime(due_tuple)
        if (now_ts or time.time()) < due_ts:
            due_ts -= 86400
        return due_ts

    def _needs_scheduled_check(self, last_checked_at, now_ts=None):
        try:
            checked_at = float(last_checked_at or 0.0)
        except Exception:
            checked_at = 0.0
        return checked_at < self._get_last_due_check_ts(now_ts=now_ts)

    def _read_dpkg_installed_version(self, package_name):
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}|${Version}", package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
            env=self._build_apt_query_env(),
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
        if "install ok installed" not in status_text:
            return ""
        return version_text

    def _get_apt_package_policy(self, package_name):
        result = subprocess.run(
            ["apt-cache", "policy", package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
            env=self._build_apt_query_env(),
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Nie udało się odczytać stanu pakietu.").strip()
            raise RuntimeError(detail[-1200:])

        installed = self._read_dpkg_installed_version(package_name)
        candidate = ""
        for raw_line in (result.stdout or "").splitlines():
            line = str(raw_line or "").strip()
            lowered = line.lower()
            if lowered.startswith("installed:"):
                installed = line.split(":", 1)[1].strip()
            elif lowered.startswith("candidate:"):
                candidate = line.split(":", 1)[1].strip()
        if installed == "(none)":
            installed = ""
        if candidate == "(none)":
            candidate = ""
        return {
            "installed": installed,
            "candidate": candidate,
        }

    def get_backend_package_state_snapshot(self):
        snapshot = self._get_radio_store_snapshot()
        raw = (snapshot or {}).get("backend_update_state") or {}
        checked_at = float(raw.get("checked_at") or 0.0) if isinstance(raw, dict) else 0.0
        check_error = str((raw or {}).get("check_error") or "").strip() if isinstance(raw, dict) else ""
        raw_versions = (raw or {}).get("package_versions") or {}
        packages = []
        installed_all = True
        update_available = False

        for package_name in self.PACKAGE_NAMES:
            version_info = dict(raw_versions.get(package_name) or {})
            installed_version = str(version_info.get("installed") or "").strip()
            candidate_version = str(version_info.get("candidate") or "").strip()
            installed = bool(installed_version)
            package_update_available = bool(installed and candidate_version and candidate_version != installed_version)
            packages.append({
                "name": package_name,
                "current_version": installed_version or "brak",
                "latest_version": candidate_version or "brak danych",
                "installed": installed,
                "update_available": package_update_available,
            })
            installed_all = installed_all and installed
            update_available = update_available or package_update_available or not installed

        if not self._is_linux_runtime():
            status_pill_kind = "muted"
            status_pill_label = "Runtime radia wymaga Linuxa"
            action_needed = False
            action_button_label = "Linux wymagany"
        elif check_error:
            status_pill_kind = "error"
            status_pill_label = "Błąd sprawdzania backendu radia"
            action_needed = True
            action_button_label = "Sprawdź ponownie"
        elif not raw_versions:
            status_pill_kind = "muted"
            status_pill_label = "Backend radia nie był jeszcze sprawdzany"
            action_needed = True
            action_button_label = "Przygotuj backend"
        elif update_available:
            status_pill_kind = "queued"
            status_pill_label = "Backend radia wymaga instalacji lub aktualizacji"
            action_needed = True
            action_button_label = "Instaluj / aktualizuj"
        else:
            status_pill_kind = "success"
            status_pill_label = "Backend radia jest gotowy"
            action_needed = False
            action_button_label = "Backend gotowy"

        return {
            "checked_at": checked_at,
            "checked_at_text": self._format_ts(checked_at) if checked_at else "jeszcze nie sprawdzano",
            "check_error": check_error,
            "packages": packages,
            "installed": installed_all and bool(raw_versions),
            "update_available": update_available,
            "action_needed": action_needed,
            "action_button_label": action_button_label,
            "status_pill_kind": status_pill_kind,
            "status_pill_label": status_pill_label,
            "linux_supported": bool(self._is_linux_runtime()),
        }

    def refresh_backend_package_state(self, force=False):
        state = self.get_backend_package_state_snapshot()
        if not self._is_linux_runtime():
            return state
        if not force and state["packages"] and not self._needs_scheduled_check(state["checked_at"]):
            return state

        package_versions = {}
        check_error = ""
        for package_name in self.PACKAGE_NAMES:
            try:
                package_versions[package_name] = self._get_apt_package_policy(package_name)
            except Exception as exc:
                check_error = str(exc)
                break

        if check_error:
            self._save_backend_update_state(package_versions=package_versions or None, check_error=check_error)
        else:
            self._save_backend_update_state(package_versions=package_versions, check_error="")
        return self.get_backend_package_state_snapshot()

    def start_package_scheduler_once(self):
        if not self._is_linux_runtime():
            return
        with self._package_scheduler_lock:
            if self._package_scheduler_started:
                return

            def runner():
                while True:
                    try:
                        self.refresh_backend_package_state(force=False)
                        sleep_for = 3600
                    except Exception:
                        sleep_for = 900
                    time.sleep(sleep_for)

            thread = threading.Thread(target=runner, name="radio-package-scheduler", daemon=True)
            thread.start()
            self._package_scheduler_started = True

    @staticmethod
    def _classify_apt_progress(output_line, stage):
        line = str(output_line or "").strip().lower()
        if stage == "update":
            if line.startswith("hit:") or line.startswith("get:") or line.startswith("ign:"):
                return 12.0, "Odświeżanie repozytoriów apt"
            if "reading package lists" in line:
                return 20.0, "Budowanie listy pakietów"
            return 10.0, "Sprawdzanie repozytoriów apt"

        if "already the newest version" in line:
            return 90.0, "Pakiet jest już aktualny"
        if "the following new packages will be installed" in line:
            return 50.0, "Przygotowanie instalacji"
        if "the following packages will be upgraded" in line:
            return 54.0, "Przygotowanie aktualizacji"
        if "need to get" in line or line.startswith("get:") or line.startswith("fetch:"):
            return 62.0, "Pobieranie pakietów"
        if "unpacking" in line:
            return 78.0, "Rozpakowywanie pakietów"
        if "setting up " in line:
            return 90.0, "Konfigurowanie pakietów"
        if "processing triggers for" in line:
            return 95.0, "Finalizacja instalacji"
        if "reading package lists" in line or "building dependency tree" in line or "reading state information" in line:
            return 44.0, "Analiza zależności"
        return 48.0, "Przetwarzanie przez apt"

    def _run_streamed_command(self, command, *, env=None, timeout=1800, progress_callback=None, stage="install"):
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
                    if len(output_lines) > 30:
                        del output_lines[:-30]
                if progress_callback:
                    progress_percent, status_label = self._classify_apt_progress(line, stage)
                    progress_callback(
                        status="running",
                        status_label=status_label,
                        progress_percent=progress_percent,
                        detail=line,
                    )

        output_thread = threading.Thread(target=consume_output, name="radio-apt-output", daemon=True)
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

    def install_or_update_backend(self, progress_callback=None):
        if not self._is_linux_runtime():
            return False, "Automatyczna instalacja backendu radia wymaga Linuxa z apt i systemd."

        env = self._build_apt_query_env()
        env["DEBIAN_FRONTEND"] = "noninteractive"

        try:
            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Przygotowanie",
                    progress_percent=6.0,
                    detail="Sprawdzam stan pakietów Icecast i Liquidsoap.",
                )

            self._run_streamed_command(
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
                    progress_percent=34.0,
                    detail="Uruchamiam apt-get install dla pakietów icecast2 i liquidsoap.",
                )

            self._run_streamed_command(
                ["apt-get", "install", "-y", *self.PACKAGE_NAMES],
                env=env,
                timeout=2400,
                progress_callback=progress_callback,
                stage="install",
            )

            self.refresh_backend_package_state(force=True)
            self.sync_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
            message = "Backend radia został przygotowany. Pakiety Icecast i Liquidsoap są dostępne dla panelu."
            if progress_callback:
                progress_callback(
                    status="running",
                    status_label="Gotowe",
                    progress_percent=100.0,
                    detail=message,
                )
            return True, message
        except Exception as exc:
            self.refresh_backend_package_state(force=True)
            return False, "Instalacja backendu radia nie powiodła się: %s" % (str(exc).strip() or "nieznany błąd")

    def _resolve_icecast_binary_path(self):
        for candidate in ("icecast2", "icecast"):
            path = shutil.which(candidate)
            if path:
                return path
        for candidate in (os.path.join("/usr", "bin", "icecast2"), os.path.join("/usr", "bin", "icecast")):
            if os.path.isfile(candidate):
                return candidate
        return ""

    def _resolve_liquidsoap_binary_path(self):
        path = shutil.which("liquidsoap")
        if path:
            return path
        fallback = os.path.join("/usr", "bin", "liquidsoap")
        return fallback if os.path.isfile(fallback) else ""

    def _resolve_icecast_webroot(self):
        for path in (
            os.path.join("/usr", "share", "icecast2", "web"),
            os.path.join("/usr", "share", "icecast", "web"),
        ):
            if os.path.isdir(path):
                return path
        path = os.path.join(self._runtime_root, "web")
        os.makedirs(path, exist_ok=True)
        return path

    def _resolve_icecast_adminroot(self):
        for path in (
            os.path.join("/usr", "share", "icecast2", "admin"),
            os.path.join("/usr", "share", "icecast", "admin"),
        ):
            if os.path.isdir(path):
                return path
        path = os.path.join(self._runtime_root, "admin")
        os.makedirs(path, exist_ok=True)
        return path

    def _local_admin_base_url(self, global_config):
        bind_ip = str((global_config or {}).get("bind_ip") or "").strip()
        if bind_ip in ("", "0.0.0.0", "::", "::0"):
            host = "127.0.0.1"
        else:
            host = bind_ip
        port = self._normalize_number((global_config or {}).get("port"), default=8000, minimum=1, maximum=65535)
        return "http://%s:%s" % (host, port)

    def make_public_stream_url(self, global_config, station):
        mount_name = self._normalize_mount_name((station or {}).get("mount_name"))
        if not mount_name:
            return ""
        base_url = str((global_config or {}).get("public_base_url") or "").strip().rstrip("/")
        if base_url:
            return "%s/%s" % (base_url, mount_name)
        bind_ip = str((global_config or {}).get("bind_ip") or "").strip() or "localhost"
        port = self._normalize_number((global_config or {}).get("port"), default=8000, minimum=1, maximum=65535)
        return "http://%s:%s/%s" % (bind_ip, port, mount_name)

    def _build_icecast_config_text(self, global_config, stations):
        hostname = str(global_config.get("hostname") or "").strip()
        public_base_url = str(global_config.get("public_base_url") or "").strip()
        if not hostname and public_base_url:
            hostname = re.sub(r"^https?://", "", public_base_url).split("/", 1)[0].strip()
        if not hostname:
            hostname = str(global_config.get("bind_ip") or "").strip() or "localhost"

        bind_ip = str(global_config.get("bind_ip") or "").strip()
        source_password = str(global_config.get("source_password") or "radio-source").strip() or "radio-source"
        admin_username = str(global_config.get("admin_username") or "admin").strip() or "admin"
        admin_password = str(global_config.get("admin_password") or "radio-admin").strip() or "radio-admin"
        port = self._normalize_number(global_config.get("port"), default=8000, minimum=1, maximum=65535)
        max_listeners = self._normalize_number(global_config.get("max_listeners"), default=200, minimum=1, maximum=50000)
        active_station_count = max(1, len([station for station in stations if station]))
        webroot = self._resolve_icecast_webroot()
        adminroot = self._resolve_icecast_adminroot()

        listen_socket_lines = [
            "    <listen-socket>",
            "        <port>%s</port>" % port,
        ]
        if bind_ip:
            listen_socket_lines.append("        <bind-address>%s</bind-address>" % self._escape_xml(bind_ip))
        listen_socket_lines.append("    </listen-socket>")

        mount_section_lines = []
        for station in stations or []:
            mount_name = self._normalize_mount_name((station or {}).get("mount_name"))
            if not mount_name:
                continue
            source_auth = self._station_source_auth((station or {}).get("owner_username") or mount_name, station, global_config)
            mount_section_lines.extend([
                "    <mount type=\"normal\">",
                "        <mount-name>/%s</mount-name>" % self._escape_xml(mount_name),
                "        <username>%s</username>" % self._escape_xml(source_auth["username"]),
                "        <password>%s</password>" % self._escape_xml(source_auth["password"]),
                "    </mount>",
                "",
            ])
        mount_sections = "\n".join(mount_section_lines).rstrip()

        return """<icecast>
    <location>{location}</location>
    <admin>{admin_contact}</admin>
    <hostname>{hostname}</hostname>
    <fileserve>1</fileserve>

    <limits>
        <clients>{clients}</clients>
        <sources>{sources}</sources>
        <queue-size>524288</queue-size>
        <client-timeout>30</client-timeout>
        <header-timeout>15</header-timeout>
        <source-timeout>10</source-timeout>
        <burst-on-connect>1</burst-on-connect>
        <burst-size>65536</burst-size>
    </limits>

    <authentication>
        <source-password>{source_password}</source-password>
        <relay-password>{source_password}</relay-password>
        <admin-user>{admin_username}</admin-user>
        <admin-password>{admin_password}</admin-password>
    </authentication>

{listen_socket}

{mount_sections}

    <paths>
        <basedir>{basedir}</basedir>
        <logdir>{logdir}</logdir>
        <webroot>{webroot}</webroot>
        <adminroot>{adminroot}</adminroot>
        <pidfile>{pidfile}</pidfile>
        <alias source="/" dest="/status.xsl"/>
    </paths>

    <logging>
        <accesslog>{accesslog}</accesslog>
        <errorlog>{errorlog}</errorlog>
        <playlistlog>playlist.log</playlistlog>
        <loglevel>3</loglevel>
        <logsize>{logsize_kbytes}</logsize>
        <logarchive>0</logarchive>
    </logging>
</icecast>
""".format(
            location=self._escape_xml(str(global_config.get("location") or "Polska").strip() or "Polska"),
            admin_contact=self._escape_xml(str(global_config.get("admin_contact") or "admin@example.invalid").strip() or "admin@example.invalid"),
            hostname=self._escape_xml(hostname),
            clients=max_listeners,
            sources=max(4, active_station_count + 2),
            source_password=self._escape_xml(source_password),
            admin_username=self._escape_xml(admin_username),
            admin_password=self._escape_xml(admin_password),
            listen_socket="\n".join(listen_socket_lines),
            mount_sections=mount_sections,
            basedir=self._escape_xml(self._runtime_root),
            logdir=self._escape_xml(self._logs_dir),
            webroot=self._escape_xml(webroot),
            adminroot=self._escape_xml(adminroot),
            pidfile=self._escape_xml(self._backend_pid_file),
            accesslog=self._escape_xml(os.path.basename(self._backend_access_log_file)),
            errorlog=self._escape_xml(os.path.basename(self._backend_error_log_file)),
            logsize_kbytes=self.ICECAST_LOG_MAX_KBYTES,
        )

    def _escape_playlist_metadata(self, value):
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"')

    def _build_playlist_line(self, file_path, display_title=""):
        normalized_path = str(file_path or "").strip()
        if not normalized_path:
            return ""
        title = str(display_title or "").strip()
        if not title:
            return normalized_path
        return 'annotate:title="%s":%s' % (
            self._escape_playlist_metadata(title),
            normalized_path,
        )

    def _iter_station_role_entries(self, owner_username, station, role_names):
        entries = []
        role_set = {str(item).strip().lower() for item in (role_names or [])}
        effective_rows = []
        try:
            effective_rows = list(self._build_library_table_rows(owner_username, station) or [])
        except Exception:
            effective_rows = []

        for item in effective_rows:
            if not bool(item.get("included")):
                continue
            if str(item.get("role") or "music").strip().lower() not in role_set:
                continue
            relative_path = str(item.get("relative_path") or "").strip()
            path = self._resolve_download_path(relative_path, "audio", owner_username=owner_username)
            if not path or not os.path.isfile(path):
                continue
            entries.append({
                "path": path,
                "display_title": str(item.get("display_title") or "").strip() or os.path.splitext(os.path.basename(path))[0],
            })
        return entries

    def _write_playlist_file(self, target_path, entries):
        lines = []
        for entry in entries or []:
            line = self._build_playlist_line(entry.get("path"), entry.get("display_title"))
            if line:
                lines.append(line)
        with open(target_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
            fh.write("\n")

    @staticmethod
    def _normalize_track_compare_value(value):
        return str(value or "").strip().casefold()

    def _build_station_manual_queue_entries(self, owner_username, station, queue_mode):
        queue_key = "play_now" if str(queue_mode or "").strip().lower() == "play_now" else "queue_next"
        entries = []
        manual_queue = dict((station or {}).get("manual_queue") or {})
        for item in manual_queue.get(queue_key) or []:
            relative_path = str(item.get("relative_path") or "").strip()
            if not relative_path:
                continue
            path = self._resolve_download_path(relative_path, "audio", owner_username=owner_username)
            if not path or not os.path.isfile(path):
                continue
            display_title = str(item.get("display_title") or "").strip() or os.path.splitext(os.path.basename(path))[0]
            entries.append({
                "path": path,
                "display_title": display_title,
            })
        return entries

    @staticmethod
    def _entry_identity(entry):
        return str((entry or {}).get("path") or "").strip()

    @staticmethod
    def _entry_display_title(entry):
        title = str((entry or {}).get("display_title") or "").strip()
        if title:
            return title
        path = RadioRuntimeService._entry_identity(entry)
        if not path:
            return ""
        return os.path.splitext(os.path.basename(path))[0]

    def _build_random_guard_playlist_entries(self, entries, repeat_guard_percent=100, avoid_first_titles=None):
        normalized_entries = [dict(item or {}) for item in (entries or []) if self._entry_identity(item)]
        entry_count = len(normalized_entries)
        if entry_count <= 1:
            return normalized_entries

        guard_percent = self._normalize_repeat_guard_percent(repeat_guard_percent, default=100)
        if guard_percent <= 0:
            return list(normalized_entries)

        recent_window = max(1, min(entry_count - 1, int((entry_count * guard_percent + 99) // 100)))
        sequence_length = max(entry_count * 6, recent_window + entry_count * 3)
        sequence_length = min(max(sequence_length, entry_count), 5000)
        rng = random.SystemRandom()
        identity_to_entry = {self._entry_identity(item): item for item in normalized_entries}
        all_keys = list(identity_to_entry.keys())
        blocked_first_titles = {
            str(title or "").strip().casefold()
            for title in (avoid_first_titles or [])
            if str(title or "").strip()
        }
        blocked_first_keys = {
            key
            for key, item in identity_to_entry.items()
            if self._entry_display_title(item).casefold() in blocked_first_titles
        }

        best_sequence = []
        for _ in range(24):
            sequence_keys = []
            recent_keys = []
            for _index in range(sequence_length):
                blocked = set(recent_keys[-recent_window:]) if recent_window > 0 else set()
                if _index == 0 and blocked_first_keys:
                    blocked.update(blocked_first_keys)
                candidates = [key for key in all_keys if key not in blocked]
                if not candidates and sequence_keys:
                    last_key = sequence_keys[-1]
                    candidates = [key for key in all_keys if key != last_key]
                if not candidates:
                    candidates = list(all_keys)
                next_key = rng.choice(candidates)
                sequence_keys.append(next_key)
                recent_keys.append(next_key)
            if recent_window > 0 and sequence_keys:
                head_key = sequence_keys[0]
                if head_key in set(sequence_keys[-recent_window:]):
                    if len(sequence_keys) > len(set(sequence_keys[-recent_window:])):
                        continue
            best_sequence = sequence_keys
            break

        if not best_sequence:
            fallback = list(normalized_entries)
            random.shuffle(fallback)
            return fallback
        return [dict(identity_to_entry[key]) for key in best_sequence if key in identity_to_entry]

    def _station_playlist_paths(self, owner_username):
        owner = self._normalize_username(owner_username)
        return {
            "music": os.path.join(self._playlists_dir, "%s_music.m3u" % owner),
            "inserts": os.path.join(self._playlists_dir, "%s_inserts.m3u" % owner),
            "manual_now": os.path.join(self._playlists_dir, "%s_manual_now.m3u" % owner),
            "manual_next": os.path.join(self._playlists_dir, "%s_manual_next.m3u" % owner),
        }

    def _station_script_path(self, owner_username):
        owner = self._normalize_username(owner_username)
        return os.path.join(self._scripts_dir, "%s.liq" % owner)

    def _station_log_file(self, owner_username):
        owner = self._normalize_username(owner_username)
        return os.path.join(self._logs_dir, "%s.log" % owner)

    def _station_track_title_file(self, owner_username):
        owner = self._normalize_username(owner_username)
        return os.path.join(self._logs_dir, "%s.track.txt" % owner)

    def _sync_station_queue_files(self, owner_username):
        owner = self._normalize_username(owner_username)
        snapshot = self._get_radio_store_snapshot()
        station = copy.deepcopy((snapshot.get("stations") or {}).get(owner))
        if not station:
            return False
        playlists = self._station_playlist_paths(owner)
        self._write_playlist_file(playlists["manual_now"], self._build_station_manual_queue_entries(owner, station, "play_now"))
        self._write_playlist_file(playlists["manual_next"], self._build_station_manual_queue_entries(owner, station, "queue_next"))
        return True

    def _resolve_relative_path_for_title(self, owner_username, station, display_title):
        normalized_title = self._normalize_track_compare_value(display_title)
        if not normalized_title:
            return ""
        try:
            effective_rows = list(self._build_library_table_rows(owner_username, station) or [])
        except Exception:
            effective_rows = []
        for item in effective_rows:
            if not bool(item.get("included")):
                continue
            row_title = str(item.get("display_title") or item.get("default_display_title") or item.get("name") or "").strip()
            if self._normalize_track_compare_value(row_title) == normalized_title:
                return str(item.get("relative_path") or "").strip()
        return ""

    def _track_station_playback_history(self, owner_username, station_state, station):
        owner = self._normalize_username(owner_username)
        if not station:
            return False

        live_connected = bool((station_state or {}).get("live_connected"))
        current_program_name = str((station_state or {}).get("current_program_name") or "").strip()
        current_dj_name = str((station_state or {}).get("current_dj_name") or "").strip()
        current_track_title = str((station_state or {}).get("current_track_title") or "").strip()

        if live_connected:
            display_title = current_program_name or current_dj_name or "Wejście live"
            source_mode = "live"
            queue_mode = ""
            relative_path = ""
        else:
            display_title = current_track_title
            source_mode = "autodj"
            queue_mode = ""
            relative_path = ""

        normalized_display_title = self._normalize_track_compare_value(display_title)
        if not normalized_display_title:
            return False

        signature = "|".join((
            source_mode,
            normalized_display_title,
            self._normalize_track_compare_value(current_program_name),
            self._normalize_track_compare_value(current_dj_name),
        ))

        queue_changed = False
        with self._radios_lock:
            live_station = (self._radios_store.get("stations") or {}).get(owner)
            if not isinstance(live_station, dict):
                return False

            history_payload = live_station.setdefault("history", {})
            previous_signature = str(history_payload.get("last_signature") or "").strip()
            if previous_signature == signature:
                return False

            if not live_connected:
                manual_queue = live_station.setdefault("manual_queue", {})
                for queue_key in ("play_now", "queue_next"):
                    queue_items = list(manual_queue.get(queue_key) or [])
                    if not queue_items:
                        continue
                    first_item = dict(queue_items[0] or {})
                    first_title = self._normalize_track_compare_value(first_item.get("display_title"))
                    if first_title and first_title == normalized_display_title:
                        queue_mode = queue_key
                        relative_path = str(first_item.get("relative_path") or "").strip()
                        manual_queue[queue_key] = queue_items[1:]
                        queue_changed = True
                        break

            if not relative_path and not live_connected:
                relative_path = self._resolve_relative_path_for_title(owner, live_station, display_title)

            history_items = list(history_payload.get("items") or [])
            history_entry = {
                "id": "hist_" + uuid.uuid4().hex[:12],
                "display_title": display_title,
                "relative_path": relative_path,
                "source_mode": source_mode,
                "queue_mode": queue_mode,
                "program_name": current_program_name,
                "dj_name": current_dj_name,
                "played_at": time.time(),
            }
            history_payload["items"] = [history_entry] + history_items[:39]
            history_payload["last_signature"] = signature
            self._write_radio_store_locked()

        if queue_changed:
            try:
                self._sync_station_queue_files(owner)
            except Exception:
                return True
        return True

    def _iter_known_radio_log_files(self):
        log_files = {
            self._backend_log_file,
            self._backend_access_log_file,
            self._backend_error_log_file,
            self._backend_playlist_log_file,
        }
        snapshot = self._get_radio_store_snapshot()
        for owner_username in (snapshot.get("stations") or {}):
            log_files.add(self._station_log_file(owner_username))
        return [path for path in log_files if str(path or "").strip()]

    @staticmethod
    def _trim_file_in_place(path, max_bytes):
        normalized_path = str(path or "").strip()
        if not normalized_path or not os.path.isfile(normalized_path):
            return False
        limit = max(1024, int(max_bytes or 0))
        try:
            file_size = max(0, int(os.path.getsize(normalized_path) or 0))
        except Exception:
            return False
        if file_size <= limit:
            return False
        try:
            with open(normalized_path, "rb+") as fh:
                fh.seek(-limit, os.SEEK_END)
                tail = fh.read(limit)
                newline_index = tail.find(b"\n")
                if newline_index >= 0 and newline_index < (len(tail) - 1):
                    tail = tail[newline_index + 1:]
                fh.seek(0)
                fh.write(tail)
                fh.truncate()
            return True
        except Exception:
            return False

    def trim_all_logs_to_max_bytes(self, max_bytes=None):
        limit = max(1024, int(max_bytes or self.RADIO_LOG_MAX_BYTES))
        trimmed_any = False
        with self._log_maintenance_lock:
            for path in self._iter_known_radio_log_files():
                trimmed_any = self._trim_file_in_place(path, limit) or trimmed_any
        return trimmed_any

    def _station_service_name(self, owner_username):
        owner = self._normalize_username(owner_username)
        return "%s%s.service" % (self._station_service_template_name, owner)

    def _station_control_port(self, owner_username):
        owner = self._normalize_username(owner_username)
        digest = hashlib.md5(owner.encode("utf-8", errors="ignore")).hexdigest()
        return 22000 + (int(digest[:4], 16) % 20000)

    def _default_live_port(self, owner_username):
        owner = self._normalize_username(owner_username)
        digest = hashlib.md5(owner.encode("utf-8", errors="ignore")).hexdigest()
        return 12000 + (int(digest[:4], 16) % 8000)

    def _normalize_live_mount_name(self, value):
        mount = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip().strip("/")).strip("-.")
        return mount[:64] or "live"

    def _station_source_auth(self, owner_username, station, global_config=None):
        owner = self._normalize_username(owner_username)
        source_config = (station or {}).get("source") or {}
        default_username = "source-%s" % (re.sub(r"[^a-z0-9]+", "-", owner.lower()).strip("-") or "radio")
        username = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(source_config.get("username") or "").strip().lower()).strip("-.") or default_username
        password = str(source_config.get("password") or "").strip() or str(((global_config or {}).get("source_password")) or "radio-source").strip() or "radio-source"
        return {
            "username": username[:64],
            "password": password[:160],
        }

    def _station_live_input_config(self, owner_username, station):
        owner = self._normalize_username(owner_username)
        live_config = (station or {}).get("live") or {}
        return {
            "enabled": bool(live_config.get("enabled", True)),
            "port": self._normalize_number(live_config.get("port"), default=self._default_live_port(owner), minimum=1024, maximum=65535),
            "mount_name": self._normalize_live_mount_name(live_config.get("mount_name") or "live"),
        }

    def _station_live_host(self, global_config):
        public_base_url = str((global_config or {}).get("public_base_url") or "").strip()
        if public_base_url:
            host = re.sub(r"^https?://", "", public_base_url).split("/", 1)[0].strip()
            if host.startswith("[") and "]" in host:
                return host[1:].split("]", 1)[0].strip() or "localhost"
            if host.count(":") == 1:
                return host.rsplit(":", 1)[0].strip() or "localhost"
            if host:
                return host
        hostname = str((global_config or {}).get("hostname") or "").strip()
        if hostname:
            return hostname
        bind_ip = str((global_config or {}).get("bind_ip") or "").strip()
        if bind_ip in ("", "0.0.0.0", "::", "::0"):
            return "localhost"
        return bind_ip

    def _live_input_has_established_client(self, port):
        if not self._is_linux_runtime():
            return False
        try:
            result = subprocess.run(
                ["ss", "-tnH", "state", "established", "( sport = :%s )" % int(port or 0)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
        except Exception:
            return False
        return bool(str(result.stdout or "").strip())

    def _build_liquidsoap_script_text(self, owner_username, station, global_config, playlists):
        owner = self._normalize_username(owner_username)
        music_entries = self._iter_station_role_entries(owner, station, ("music",))
        insert_entries = self._iter_station_role_entries(owner, station, ("jingle", "promo"))
        music_count = len(music_entries)
        insert_count = len(insert_entries)
        mount_name = self._normalize_mount_name((station or {}).get("mount_name"))
        stream_format = str((((station or {}).get("stream") or {}).get("format") or "mp3")).strip().lower() or "mp3"
        bitrate = self._normalize_number(((station or {}).get("stream") or {}).get("bitrate_kbps"), default=192, minimum=64, maximum=320)
        play_mode = self._normalize_playlist_mode(((station or {}).get("autopilot") or {}).get("play_mode"))
        repeat_guard_percent = self._normalize_repeat_guard_percent(((station or {}).get("autopilot") or {}).get("repeat_guard_percent"), default=100)
        crossfade_seconds = float(self._normalize_number(((station or {}).get("autopilot") or {}).get("crossfade_seconds"), default=0, minimum=0, maximum=12))
        scan_interval = self._normalize_number(((station or {}).get("autopilot") or {}).get("scan_interval_seconds"), default=30, minimum=5, maximum=3600)
        jingle_every_tracks = self._normalize_number(((station or {}).get("autopilot") or {}).get("jingle_every_tracks"), default=0, minimum=0, maximum=100)
        public_url = self.make_public_stream_url(global_config, station)
        description = str((station or {}).get("description") or "").strip()
        genre = str((station or {}).get("genre") or "").strip()
        station_name = str((station or {}).get("name") or ("Radio %s" % owner)).strip()
        erds_config = (station or {}).get("erds") or {}
        erds_mode = str(erds_config.get("mode") or "").strip().lower() or "rotation"
        suppress_track_titles = bool(erds_config.get("suppress_track_titles")) and erds_mode != "titles"
        control_port = self._station_control_port(owner)
        source_auth = self._station_source_auth(owner, station, global_config)
        live_input = self._station_live_input_config(owner, station)
        host = "127.0.0.1" if str((global_config or {}).get("bind_ip") or "").strip() in ("", "0.0.0.0", "::", "::0") else str((global_config or {}).get("bind_ip")).strip()
        port = self._normalize_number((global_config or {}).get("port"), default=8000, minimum=1, maximum=65535)
        log_file = self._station_log_file(owner)
        output_encoder = '%%mp3(bitrate=%s)' % bitrate
        output_format_line = ""
        if stream_format == "aac":
            output_encoder = '%%ffmpeg(format="adts",codec="aac",ar=44100,channels=2,b="%sk")' % bitrate
            output_format_line = '  format="audio/aac",'

        # Guarded random needs a stable round; periodic reloads would reset it and allow
        # the same title to reappear right after the current track.
        guarded_random_mode = play_mode == "random" and repeat_guard_percent > 0
        music_playlist_mode = "normal" if guarded_random_mode else play_mode

        music_source_expr = 'blank()'
        if music_count:
            if guarded_random_mode:
                music_source_expr = 'playlist(mode="%s",reload_mode="watch","%s")' % (
                    music_playlist_mode,
                    playlists["music"].replace("\\", "/"),
                )
            else:
                music_source_expr = 'playlist(mode="%s",reload=%s,"%s")' % (
                    music_playlist_mode,
                    scan_interval,
                    playlists["music"].replace("\\", "/"),
                )
        insert_source_expr = ""
        if insert_count:
            insert_source_expr = 'playlist(mode="random",reload=%s,"%s")' % (
                scan_interval,
                playlists["inserts"].replace("\\", "/"),
            )

        lines = [
            '# Autogenerated by Flask Downloader. Do not edit manually.',
            'set("init.allow_root",true)',
            'set("log.file.path","%s")' % log_file.replace("\\", "/"),
            'set("log.stdout",true)',
            'set("log.file",true)',
            'set("log.level",3)',
            'set("server.telnet",true)',
            'set("server.telnet.bind_addr","127.0.0.1")',
            'set("server.telnet.port",%s)' % control_port,
            'set("server.telnet.revdns",false)',
            '',
            'manual_now = playlist(mode="normal",reload_mode="watch","%s")' % playlists["manual_now"].replace("\\", "/"),
            'manual_next = playlist(mode="normal",reload_mode="watch","%s")' % playlists["manual_next"].replace("\\", "/"),
            'music = %s' % music_source_expr,
        ]
        if music_count:
            lines.append('music = mksafe(music)')
            if crossfade_seconds > 0:
                lines.append('music = crossfade(music)')
        if insert_source_expr:
            lines.extend([
                'inserts = %s' % insert_source_expr,
                'inserts = mksafe(inserts)',
            ])

        if music_count and insert_count and jingle_every_tracks > 0:
            lines.append('autodj = random(weights=[1,%s],[inserts,music])' % max(1, jingle_every_tracks))
        elif music_count:
            lines.append('autodj = music')
        elif insert_count:
            lines.append('autodj = inserts')
        else:
            lines.append('autodj = blank()')

        lines.extend([
            'def update_current_track(meta) =',
            '  _ = file.write(data=meta["title"], "%s")' % self._station_track_title_file(owner).replace("\\", "/"),
            'end',
            'autodj = on_track(update_current_track,autodj)',
            'autodj = on_metadata(update_current_track,autodj)',
        ])

        if live_input["enabled"]:
            lines.extend([
                'live = input.harbor("/%s",port=%s,user="%s",password="%s",replay_metadata=true)' % (
                    live_input["mount_name"],
                    live_input["port"],
                    self._escape_playlist_metadata(source_auth["username"]),
                    self._escape_playlist_metadata(source_auth["password"]),
                ),
                'server.register(namespace="radio",description="Live takeover status","live_status",(fun (_) -> if source.is_up(live) then "online" else "offline" end))',
                'program = fallback(track_sensitive=false,[live,manual_now,manual_next,autodj])',
            ])
        else:
            lines.extend([
                'server.register(namespace="radio",description="Live takeover status","live_status",(fun (_) -> "disabled"))',
                'program = fallback(track_sensitive=false,[manual_now,manual_next,autodj])',
            ])

        lines.append('program = fallback(track_sensitive=false,[program,blank()])')
        if suppress_track_titles:
            lines.append('program = map_metadata(update=false,strip=true,(fun (_) -> []),program)')

        lines.append('server.register(namespace="radio",description="Skip current track","skip",(fun (_) -> begin source.skip(program); "OK" end))')

        lines.extend([
            '',
            'output.icecast(',
            '  %s,' % output_encoder,
            '  host="%s",' % host,
            '  port=%s,' % port,
            '  user="%s",' % self._escape_playlist_metadata(source_auth["username"]),
            '  password="%s",' % self._escape_playlist_metadata(source_auth["password"]),
            '  mount="%s",' % mount_name,
            '  name="%s",' % self._escape_playlist_metadata(station_name),
            '  description="%s",' % self._escape_playlist_metadata(description),
            '  genre="%s",' % self._escape_playlist_metadata(genre),
            '  url="%s",' % self._escape_playlist_metadata(public_url),
        ])
        if suppress_track_titles:
            lines.append('  icy_metadata="false",')
        if output_format_line:
            lines.append(output_format_line)
        lines.extend([
            '  program',
            ')',
            '',
        ])
        return "\n".join(lines)

    def _write_backend_unit_file(self):
        if not self._is_linux_runtime():
            return
        icecast_binary = self._resolve_icecast_binary_path()
        if not icecast_binary:
            return
        command = "%s -c %s >> %s 2>&1" % (
            self._systemd_quote_arg(icecast_binary),
            self._systemd_quote_arg(self._icecast_config_file),
            self._systemd_quote_arg(self._backend_log_file),
        )
        unit_text = """[Unit]
Description=Flask Downloader Radio Backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={group}
WorkingDirectory={workdir}
ExecStart=/bin/sh -c {command}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
""".format(
            user=self._backend_service_user,
            group=self._backend_service_group,
            workdir=self._runtime_root,
            command=self._systemd_quote_arg(command),
        )
        try:
            if os.path.isfile(self._backend_unit_file):
                with open(self._backend_unit_file, "r", encoding="utf-8", errors="replace") as fh:
                    existing_text = str(fh.read() or "")
                if existing_text == unit_text:
                    return
        except Exception:
            pass
        self._write_text_file_maybe_privileged(self._backend_unit_file, unit_text)

    def _write_station_unit_template(self):
        if not self._is_linux_runtime():
            return
        liquidsoap_binary = self._resolve_liquidsoap_binary_path()
        if not liquidsoap_binary:
            return
        script_pattern = os.path.join(self._scripts_dir, "%i.liq").replace("\\", "/")
        log_pattern = os.path.join(self._logs_dir, "%i.log").replace("\\", "/")
        command = "%s %s >> %s 2>&1" % (
            self._systemd_quote_arg(liquidsoap_binary),
            self._systemd_quote_arg(script_pattern),
            self._systemd_quote_arg(log_pattern),
        )
        unit_text = """[Unit]
Description=Flask Downloader Radio Station %i
After=network-online.target {backend}.service
Wants=network-online.target {backend}.service
Requires={backend}.service

[Service]
Type=simple
User={user}
Group={group}
WorkingDirectory={workdir}
ExecStart=/bin/sh -c {command}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
""".format(
            backend=self._backend_service_name,
            user=self._app_service_user,
            group=self._app_service_group,
            workdir=self._app_root,
            command=self._systemd_quote_arg(command),
        )
        try:
            if os.path.isfile(self._station_unit_template_file):
                with open(self._station_unit_template_file, "r", encoding="utf-8", errors="replace") as fh:
                    existing_text = str(fh.read() or "")
                if existing_text == unit_text:
                    return
        except Exception:
            pass
        self._write_text_file_maybe_privileged(self._station_unit_template_file, unit_text)

    def _write_text_file_maybe_privileged(self, path, text, *, encoding="utf-8", timeout=60):
        normalized_path = os.path.abspath(str(path or "").strip())
        if not normalized_path:
            raise RuntimeError("Brak ścieżki docelowej do zapisu pliku systemowego.")

        if self._is_linux_runtime():
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
                            detail or "Nie udało się zapisać pliku systemowego %s." % normalized_path
                        )
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    "Nie udało się zapisać pliku systemowego %s: %s" % (normalized_path, exc)
                ) from exc

        with open(normalized_path, "w", encoding=encoding) as fh:
            fh.write(str(text or ""))

    def _reload_systemd(self):
        if not self._is_linux_runtime():
            return
        self._run_systemctl_command("daemon-reload", timeout=60)

    def sync_runtime(self, *, restart_backend_if_active=False, restart_active_stations=False):
        self._ensure_runtime_dirs()
        self.trim_all_logs_to_max_bytes()
        snapshot = self._get_radio_store_snapshot()
        global_config = dict(snapshot.get("global") or {})
        stations_map = dict(snapshot.get("stations") or {})

        with open(self._icecast_config_file, "w", encoding="utf-8") as fh:
            fh.write(self._build_icecast_config_text(global_config, list(stations_map.values())))

        for owner_username, station in stations_map.items():
            playlists = self._station_playlist_paths(owner_username)
            music_entries = self._iter_station_role_entries(owner_username, station, ("music",))
            insert_entries = self._iter_station_role_entries(owner_username, station, ("jingle", "promo"))
            repeat_guard_percent = self._normalize_repeat_guard_percent((((station or {}).get("autopilot") or {}).get("repeat_guard_percent")), default=100)
            play_mode = self._normalize_playlist_mode(((station or {}).get("autopilot") or {}).get("play_mode"))
            effective_music_entries = list(music_entries)
            if play_mode == "random" and music_entries:
                current_track_title = self._get_station_autodj_track_title(owner_username)
                effective_music_entries = self._build_random_guard_playlist_entries(
                    music_entries,
                    repeat_guard_percent=repeat_guard_percent,
                    avoid_first_titles=[current_track_title] if current_track_title else None,
                )
            self._write_playlist_file(playlists["music"], effective_music_entries)
            self._write_playlist_file(playlists["inserts"], insert_entries)
            self._write_playlist_file(playlists["manual_now"], self._build_station_manual_queue_entries(owner_username, station, "play_now"))
            self._write_playlist_file(playlists["manual_next"], self._build_station_manual_queue_entries(owner_username, station, "queue_next"))
            with open(self._station_script_path(owner_username), "w", encoding="utf-8") as fh:
                fh.write(self._build_liquidsoap_script_text(owner_username, station, global_config, playlists))

        self._apply_runtime_permissions()

        if self._is_linux_runtime():
            self._write_backend_unit_file()
            self._write_station_unit_template()
            self._reload_systemd()

            backend_state = self.get_backend_service_state()
            active_station_services = []
            if restart_active_stations:
                for owner_username in stations_map:
                    station_state = self.get_station_runtime_state(owner_username)
                    if station_state.get("service_active"):
                        active_station_services.append(owner_username)

            if global_config.get("autostart_backend"):
                self._run_systemctl_command_result("enable", "%s.service" % self._backend_service_name, timeout=60)
            else:
                self._run_systemctl_command_result("disable", "%s.service" % self._backend_service_name, timeout=60)

            for owner_username, station in stations_map.items():
                service_name = self._station_service_name(owner_username)
                wants_enabled = bool(station.get("enabled")) and bool(station.get("autostart"))
                if wants_enabled:
                    self._run_systemctl_command_result("enable", service_name, timeout=60)
                else:
                    self._run_systemctl_command_result("disable", service_name, timeout=60)

            if restart_backend_if_active and backend_state.get("service_active"):
                self.restart_backend_service_now(start_linked_stations=False)
            for owner_username in active_station_services:
                self.control_station(owner_username, "restart")

        return {
            "ok": True,
            "config_file": self._icecast_config_file,
            "runtime_root": self._runtime_root,
        }

    def sync_runtime_safe(self, *, restart_backend_if_active=False, restart_active_stations=False):
        try:
            return self.sync_runtime(
                restart_backend_if_active=restart_backend_if_active,
                restart_active_stations=restart_active_stations,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    def get_backend_service_state(self):
        self.trim_all_logs_to_max_bytes()
        state = {
            "linux_supported": bool(self._is_linux_runtime()),
            "service_name": self._backend_service_name,
            "service_active": False,
            "status_label": "Niedostępny",
            "status_kind": "muted",
            "unit_file_label": "nieznany",
            "toggle_button_label": "Start backendu",
            "runtime_root": self._runtime_root,
            "config_file": self._icecast_config_file,
            "log_file": self._backend_log_file,
            "binary_path": self._resolve_icecast_binary_path(),
            "error": "",
        }
        if not self._is_linux_runtime():
            state["error"] = "Runtime radia wymaga Linuxa z systemd."
            return state
        generic_state = self._get_generic_service_state(self._backend_service_name)
        state.update(generic_state)
        state["service_active"] = str(generic_state.get("active_state") or "") == "active"
        state["toggle_button_label"] = "Stop backendu" if state["service_active"] else "Start backendu"
        return state

    def _read_status_json_sources(self, global_config):
        url = self._local_admin_base_url(global_config) + "/status-json.xsl"
        response = self._requests.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()
        icestats = payload.get("icestats") or {}
        source = icestats.get("source")
        if not source:
            return []
        if isinstance(source, list):
            return [dict(item or {}) for item in source]
        if isinstance(source, dict):
            return [dict(source)]
        return []

    def _read_admin_stats_sources(self, global_config):
        url = self._local_admin_base_url(global_config) + "/admin/stats"
        auth = (
            str(global_config.get("admin_username") or "admin").strip() or "admin",
            str(global_config.get("admin_password") or "radio-admin").strip() or "radio-admin",
        )
        response = self._requests.get(url, auth=auth, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        sources = []
        for source_el in root.findall("source"):
            item = {
                "listenurl": source_el.findtext("listenurl", default=""),
                "server_name": source_el.findtext("server_name", default=""),
                "server_description": source_el.findtext("server_description", default=""),
                "genre": source_el.findtext("genre", default=""),
                "listeners": source_el.findtext("listeners", default="0"),
                "listener_peak": source_el.findtext("listener_peak", default="0"),
                "title": source_el.findtext("title", default=""),
                "artist": source_el.findtext("artist", default=""),
            }
            mount = source_el.attrib.get("mount") or ""
            if mount:
                item["mount"] = mount
            sources.append(item)
        return sources

    def _get_sources_stats(self, global_config):
        if not self._is_linux_runtime():
            return []
        try:
            sources = self._read_status_json_sources(global_config)
            if sources:
                return sources
        except Exception:
            pass
        try:
            return self._read_admin_stats_sources(global_config)
        except Exception:
            return []

    def _find_source_stats_for_mount(self, global_config, mount_name):
        normalized_mount = "/" + self._normalize_mount_name(mount_name)
        for item in self._get_sources_stats(global_config):
            mount = str(item.get("mount") or "").strip()
            if not mount:
                listen_url = str(item.get("listenurl") or "").strip()
                if listen_url:
                    mount = "/" + listen_url.rstrip("/").rsplit("/", 1)[-1]
            if mount == normalized_mount:
                return dict(item)
        return {}

    def _compute_runtime_erds_text(self, station, listener_count=0, now_ts=None, runtime_context=None, global_config=None):
        mode = str((((station or {}).get("erds") or {}).get("mode") or "rotation")).strip().lower()
        if mode == "titles":
            return ""
        preview_lines = self._build_erds_preview_lines(
            station,
            listener_count=listener_count,
            now_ts=now_ts,
            runtime_context=runtime_context,
            global_config=global_config,
            skip_track_templates_when_live=bool((runtime_context or {}).get("live_connected")),
        )
        if not preview_lines:
            return ""
        if mode == "fixed":
            return str(preview_lines[0] or "").strip()
        interval = self._normalize_number(((station or {}).get("erds") or {}).get("rotation_interval_seconds"), default=20, minimum=5, maximum=3600)
        index = 0
        if interval > 0 and len(preview_lines) > 1:
            index = int((now_ts or time.time()) // interval) % len(preview_lines)
        return str(preview_lines[index] or "").strip()

    def _count_role_entries(self, owner_username, station, role_names):
        return len(self._iter_station_role_entries(owner_username, station, role_names))

    def _get_station_listener_record(self, owner_username):
        snapshot = self._get_radio_store_snapshot()
        station = copy.deepcopy((snapshot.get("stations") or {}).get(self._normalize_username(owner_username)) or {})
        return self._normalize_number(((station.get("stats") or {}).get("listener_record")), default=0, minimum=0, maximum=50000)

    def _update_station_listener_record(self, owner_username, listeners=0, listener_peak=0):
        owner = self._normalize_username(owner_username)
        candidate = max(
            self._normalize_number(listeners, default=0, minimum=0, maximum=50000),
            self._normalize_number(listener_peak, default=0, minimum=0, maximum=50000),
        )
        if candidate <= 0:
            return self._get_station_listener_record(owner)
        with self._radios_lock:
            stations = self._radios_store.setdefault("stations", {})
            station = stations.get(owner)
            if not isinstance(station, dict):
                return 0
            stats = station.setdefault("stats", {})
            current_record = self._normalize_number(stats.get("listener_record"), default=0, minimum=0, maximum=50000)
            if candidate > current_record:
                stats["listener_record"] = candidate
                self._write_radio_store_locked()
                return candidate
            return current_record

    @staticmethod
    def _resolve_live_program_name(station_state, station):
        live_config = dict((station or {}).get("live") or {})
        live_show_name = str(live_config.get("show_name") or "").strip()
        if live_show_name:
            return live_show_name
        if station_state.get("live_connected"):
            return str((station or {}).get("name") or "").strip()
        return ""

    @staticmethod
    def _resolve_current_dj_name(station_state, station):
        live_config = dict((station or {}).get("live") or {})
        live_dj_name = str(live_config.get("dj_name") or "").strip()
        if live_dj_name:
            return live_dj_name
        if station_state.get("live_connected"):
            return "DJ live"
        return "AutoDJ"

    def get_station_runtime_state(self, owner_username):
        self.trim_all_logs_to_max_bytes()
        owner = self._normalize_username(owner_username)
        snapshot = self._get_radio_store_snapshot()
        global_config = dict(snapshot.get("global") or {})
        station = copy.deepcopy((snapshot.get("stations") or {}).get(owner))
        service_name = self._station_service_name(owner)
        station_state = {
            "owner_username": owner,
            "service_name": service_name,
            "service_active": False,
            "status_label": "Brak radia",
            "status_kind": "muted",
            "listeners": 0,
            "listener_peak": 0,
            "mount_connected": False,
            "mount_status_label": "Brak źródła",
            "mount_status_kind": "muted",
            "public_stream_url": self.make_public_stream_url(global_config, station or {}),
            "control_port": self._station_control_port(owner),
            "source_username": "",
            "current_track_title": "",
            "current_song": "",
            "current_erds_text": "",
            "current_program_name": "",
            "current_dj_name": "",
            "log_file": self._station_log_file(owner),
            "playable_music_count": 0,
            "playable_insert_count": 0,
            "live_enabled": False,
            "live_port": 0,
            "live_mount_name": "live",
            "live_mount_path": "/live",
            "live_host": self._station_live_host(global_config),
            "live_endpoint": "",
            "live_connected": False,
            "live_status_label": "Wyłączony",
            "live_status_kind": "muted",
            "listener_record": self._normalize_number((((station or {}).get("stats") or {}).get("listener_record")), default=0, minimum=0, maximum=50000),
            "max_listeners": self._normalize_number(global_config.get("max_listeners"), default=0, minimum=0, maximum=50000),
            "error": "",
        }
        if not station:
            return station_state

        source_auth = self._station_source_auth(owner, station, global_config)
        live_input = self._station_live_input_config(owner, station)
        station_state["source_username"] = source_auth["username"]
        station_state["live_enabled"] = live_input["enabled"]
        station_state["live_port"] = live_input["port"]
        station_state["live_mount_name"] = live_input["mount_name"]
        station_state["live_mount_path"] = "/" + live_input["mount_name"]
        station_state["live_endpoint"] = "%s:%s%s" % (station_state["live_host"], live_input["port"], station_state["live_mount_path"])
        if live_input["enabled"]:
            station_state["live_status_label"] = "Gotowy na wejście live"
            station_state["live_status_kind"] = "queued"

        station_state["playable_music_count"] = self._count_role_entries(owner, station, ("music",))
        station_state["playable_insert_count"] = self._count_role_entries(owner, station, ("jingle", "promo"))

        if self._is_linux_runtime():
            generic_state = self._get_generic_service_state(service_name)
            station_state.update({
                "status_label": generic_state.get("status_label") or station_state["status_label"],
                "status_kind": generic_state.get("status_kind") or station_state["status_kind"],
                "service_active": str(generic_state.get("active_state") or "") == "active",
                "error": str(generic_state.get("error") or ""),
                "service_state": generic_state,
            })

        mount_name = self._normalize_mount_name((station or {}).get("mount_name"))
        mount_stats = self._find_source_stats_for_mount(global_config, mount_name)
        if mount_stats:
            listeners = self._normalize_number(mount_stats.get("listeners"), default=0, minimum=0, maximum=50000)
            station_state["listeners"] = listeners
            station_state["listener_peak"] = self._normalize_number(mount_stats.get("listener_peak"), default=0, minimum=0, maximum=50000)
            station_state["mount_connected"] = True
            station_state["mount_status_label"] = "Stream podłączony"
            station_state["mount_status_kind"] = "success"
            station_state["current_track_title"] = str(mount_stats.get("title") or mount_stats.get("song") or "").strip()
            station_state["current_song"] = station_state["current_track_title"]
            station_state["listener_record"] = self._update_station_listener_record(owner, listeners=station_state["listeners"], listener_peak=station_state["listener_peak"])
        elif station_state["service_active"]:
            station_state["mount_status_label"] = "Usługa stacji działa, ale mount nie jest jeszcze widoczny"
            station_state["mount_status_kind"] = "queued"

        if station_state["service_active"] and station_state["live_enabled"]:
            if self._live_input_has_established_client(station_state["live_port"]):
                station_state["live_connected"] = True
                station_state["live_status_label"] = "DJ live przejął antenę"
                station_state["live_status_kind"] = "success"

        autodj_track_title = self._get_station_autodj_track_title(owner) if station_state["service_active"] else ""
        if autodj_track_title:
            station_state["current_track_title"] = autodj_track_title
            if not station_state["live_connected"]:
                station_state["current_song"] = autodj_track_title

        station_state["current_program_name"] = self._resolve_live_program_name(station_state, station)
        station_state["current_dj_name"] = self._resolve_current_dj_name(station_state, station)
        try:
            self._track_station_playback_history(owner, station_state, station)
        except Exception:
            pass
        station_state["current_erds_text"] = self._compute_runtime_erds_text(
            station,
            listener_count=station_state["listeners"],
            now_ts=time.time(),
            runtime_context=station_state,
            global_config=global_config,
        )
        if str((((station or {}).get("erds") or {}).get("mode") or "rotation")).strip().lower() != "titles" and station_state["current_erds_text"]:
            station_state["current_song"] = station_state["current_erds_text"]
        return station_state

    def _update_mount_metadata(self, global_config, station, metadata_text):
        mount_name = "/" + self._normalize_mount_name((station or {}).get("mount_name"))
        url = self._local_admin_base_url(global_config) + "/admin/metadata"
        auth = (
            str(global_config.get("admin_username") or "admin").strip() or "admin",
            str(global_config.get("admin_password") or "radio-admin").strip() or "radio-admin",
        )
        response = self._requests.get(
            url,
            params={
                "mount": mount_name,
                "mode": "updinfo",
                "song": metadata_text,
            },
            auth=auth,
            timeout=10,
        )
        response.raise_for_status()
        return True

    def _send_station_server_command(self, owner_username, command, timeout=5):
        owner = self._normalize_username(owner_username)
        control_port = self._station_control_port(owner)
        payload = ("%s\nquit\n" % str(command or "").strip()).encode("utf-8")
        chunks = []
        sock = socket.create_connection(("127.0.0.1", control_port), timeout=timeout)
        try:
            sock.settimeout(timeout)
            sock.sendall(payload)
            while True:
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    break
                if not data:
                    break
                chunks.append(data)
        finally:
            try:
                sock.close()
            except Exception:
                pass
        response_text = b"".join(chunks).decode("utf-8", errors="replace").strip()
        if "ERROR:" in response_text:
            raise RuntimeError(response_text.split("ERROR:", 1)[1].strip() or "Liquidsoap odrzucił polecenie sterujące.")
        return response_text

    def _get_station_autodj_track_title(self, owner_username):
        path = self._station_track_title_file(owner_username)
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return str(fh.read() or "").strip()
        except Exception:
            return ""

    def metadata_tick(self):
        self.trim_all_logs_to_max_bytes()
        snapshot = self._get_radio_store_snapshot()
        global_config = dict(snapshot.get("global") or {})
        if not bool(global_config.get("enabled", True)):
            return
        backend_state = self.get_backend_service_state()
        if not backend_state.get("service_active"):
            return

        sources_cache = {}
        for owner_username, station in (snapshot.get("stations") or {}).items():
            if not bool((station or {}).get("enabled", False)):
                continue
            mode = str((((station or {}).get("erds") or {}).get("mode") or "rotation")).strip().lower()
            if mode == "titles":
                continue
            if owner_username not in sources_cache:
                station_state = self.get_station_runtime_state(owner_username)
                sources_cache[owner_username] = station_state
            else:
                station_state = sources_cache[owner_username]
            if not station_state.get("mount_connected"):
                continue
            metadata_text = self._compute_runtime_erds_text(
                station,
                listener_count=station_state.get("listeners") or 0,
                now_ts=time.time(),
                runtime_context=station_state,
                global_config=global_config,
            )
            if not metadata_text:
                continue
            try:
                self._update_mount_metadata(global_config, station, metadata_text)
            except Exception:
                continue

    def start_metadata_scheduler_once(self):
        if not self._is_linux_runtime():
            return
        with self._metadata_scheduler_lock:
            if self._metadata_scheduler_started:
                return

            def runner():
                while True:
                    try:
                        snapshot = self._get_radio_store_snapshot()
                        global_config = dict(snapshot.get("global") or {})
                        interval = self._normalize_number(global_config.get("metadata_refresh_seconds"), default=20, minimum=5, maximum=3600)
                        self.metadata_tick()
                    except Exception:
                        interval = 20
                    time.sleep(max(5, interval))

            thread = threading.Thread(target=runner, name="radio-metadata-scheduler", daemon=True)
            thread.start()
            self._metadata_scheduler_started = True

    def _start_backend_if_needed(self):
        backend_state = self.get_backend_service_state()
        if backend_state.get("service_active"):
            return
        self.set_backend_enabled(True)

    def set_backend_enabled(self, enabled):
        if not self._is_linux_runtime():
            raise RuntimeError("Sterowanie backendem radia wymaga Linuxa z systemd.")
        self.sync_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
        service_name = "%s.service" % self._backend_service_name
        if enabled:
            self._run_systemctl_command_result("reset-failed", service_name, timeout=30)
            self._run_systemctl_command("start", service_name, timeout=90)
        else:
            self._run_systemctl_command_result("stop", service_name, timeout=90)
        return self.get_backend_service_state()

    def restart_backend_service_now(self, *, start_linked_stations=True):
        if not self._is_linux_runtime():
            raise RuntimeError("Restart backendu radia wymaga Linuxa z systemd.")
        service_name = "%s.service" % self._backend_service_name
        self._run_systemctl_command_result("stop", service_name, timeout=90)
        self._run_systemctl_command_result("reset-failed", service_name, timeout=30)
        self._run_systemctl_command("start", service_name, timeout=90)
        if start_linked_stations:
            snapshot = self._get_radio_store_snapshot()
            for owner_username, station in (snapshot.get("stations") or {}).items():
                if bool((station or {}).get("enabled")) and bool((station or {}).get("autostart")):
                    try:
                        self._run_systemctl_command_result("start", self._station_service_name(owner_username), timeout=90)
                    except Exception:
                        pass
        return self.get_backend_service_state()

    def control_station(self, owner_username, action):
        if not self._is_linux_runtime():
            raise RuntimeError("Sterowanie stacją radiową wymaga Linuxa z systemd.")
        owner = self._normalize_username(owner_username)
        snapshot = self._get_radio_store_snapshot()
        station = copy.deepcopy((snapshot.get("stations") or {}).get(owner))
        if not station:
            raise ValueError("To radio nie istnieje jeszcze.")
        if not bool(station.get("enabled", False)) and action in ("start", "restart"):
            raise ValueError("Najpierw włącz logicznie tę stację w ustawieniach radia.")
        music_count = self._count_role_entries(owner, station, ("music",))
        insert_count = self._count_role_entries(owner, station, ("jingle", "promo"))
        if (music_count + insert_count) <= 0 and action in ("start", "restart"):
            raise ValueError("Biblioteka radia jest pusta. Dodaj przynajmniej jeden aktywny plik audio.")

        self.sync_runtime_safe(restart_backend_if_active=False, restart_active_stations=False)
        service_name = self._station_service_name(owner)
        normalized_action = str(action or "").strip().lower()
        if normalized_action == "start":
            self._start_backend_if_needed()
            self._run_systemctl_command_result("reset-failed", service_name, timeout=30)
            self._run_systemctl_command("start", service_name, timeout=90)
        elif normalized_action == "stop":
            self._run_systemctl_command_result("stop", service_name, timeout=90)
        elif normalized_action == "restart":
            self._start_backend_if_needed()
            self._run_systemctl_command_result("stop", service_name, timeout=90)
            self._run_systemctl_command_result("reset-failed", service_name, timeout=30)
            self._run_systemctl_command("start", service_name, timeout=90)
        elif normalized_action == "next":
            station_state = self.get_station_runtime_state(owner)
            if not station_state.get("service_active"):
                raise ValueError("Autopilot stacji nie działa. Najpierw go uruchom.")
            if station_state.get("live_connected"):
                raise ValueError("Na antenie działa wejście live DJ. Przeskakiwanie AutoDJ jest chwilowo zablokowane.")
            try:
                self._send_station_server_command(owner, "radio.skip", timeout=5)
            except Exception as exc:
                raise RuntimeError("Nie udało się przeskoczyć do następnego utworu: %s" % exc)
            time.sleep(0.4)
        else:
            raise ValueError("Nieobsługiwana akcja stacji radiowej.")
        return self.get_station_runtime_state(owner)

    def refresh_station_queue_files(self, owner_username):
        return self._sync_station_queue_files(owner_username)

    def skip_station_track(self, owner_username):
        owner = self._normalize_username(owner_username)
        station_state = self.get_station_runtime_state(owner)
        if not station_state.get("service_active"):
            raise ValueError("Autopilot stacji nie działa. Najpierw go uruchom.")
        if station_state.get("live_connected"):
            raise ValueError("Na antenie działa wejście live DJ. Ręczna ingerencja w AutoDJ jest chwilowo zablokowana.")
        try:
            self._send_station_server_command(owner, "radio.skip", timeout=5)
        except Exception as exc:
            raise RuntimeError("Nie udało się przełączyć aktualnego utworu: %s" % exc)
        time.sleep(0.4)
        return self.get_station_runtime_state(owner)

    def stop_and_disable_station(self, owner_username):
        if not self._is_linux_runtime():
            return False
        owner = self._normalize_username(owner_username)
        service_name = self._station_service_name(owner)
        try:
            self._run_systemctl_command_result("stop", service_name, timeout=90)
        except Exception:
            pass
        try:
            self._run_systemctl_command_result("disable", service_name, timeout=60)
        except Exception:
            pass
        return True

    def read_text_log_file_for_browser(self, path, max_bytes=512 * 1024):
        normalized_path = str(path or "").strip()
        if not normalized_path:
            return "Brak ścieżki logu.\n"
        self._trim_file_in_place(normalized_path, self.RADIO_LOG_MAX_BYTES)
        if not os.path.isfile(normalized_path):
            return "Log nie istnieje jeszcze. Uruchom backend albo stację, aby zacząć zbierać wpisy.\n"
        file_size = 0
        try:
            file_size = max(0, int(os.path.getsize(normalized_path) or 0))
        except Exception:
            file_size = 0
        try:
            with open(normalized_path, "rb") as fh:
                if file_size > max_bytes > 0:
                    fh.seek(-max_bytes, os.SEEK_END)
                    raw_data = fh.read()
                else:
                    raw_data = fh.read()
        except Exception as exc:
            return "Nie udało się odczytać logu: %s\n" % exc
        text = raw_data.decode("utf-8", errors="replace")
        if file_size > max_bytes > 0:
            newline_index = text.find("\n")
            if newline_index >= 0:
                text = text[newline_index + 1:]
            text = "[Log jest większy niż %s B, więc pokazuję końcówkę pliku z %s]\n\n%s" % (
                max_bytes,
                normalized_path,
                text,
            )
        return text if text.endswith("\n") else (text + "\n")

    def get_backend_log_file(self):
        return self._backend_log_file

    def get_station_log_file(self, owner_username):
        return self._station_log_file(owner_username)
