import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

import requests


class YtDlpMaintenanceService:
    def __init__(
        self,
        *,
        importlib_metadata_module,
        ytdlp_module,
        version_class,
        invalid_version_exceptions,
        user_agent,
        pip_package_spec,
        read_update_state,
        save_update_state,
        is_version_newer,
        needs_scheduled_check,
        get_next_check_dt,
        format_ts,
        services_cache,
        services_lock,
        scheduler_lock,
        is_scheduler_started,
        set_scheduler_started,
    ):
        self._importlib_metadata = importlib_metadata_module
        self._ytdlp_module = ytdlp_module
        self._version_class = version_class
        self._invalid_version_exceptions = invalid_version_exceptions
        self._user_agent = user_agent
        self._pip_package_spec = pip_package_spec
        self._read_update_state = read_update_state
        self._save_update_state = save_update_state
        self._is_version_newer = is_version_newer
        self._needs_scheduled_check = needs_scheduled_check
        self._get_next_check_dt = get_next_check_dt
        self._format_ts = format_ts
        self._services_cache = services_cache
        self._services_lock = services_lock
        self._scheduler_lock = scheduler_lock
        self._is_scheduler_started = is_scheduler_started
        self._set_scheduler_started = set_scheduler_started

    def get_installed_version(self):
        try:
            return self._importlib_metadata.version("yt-dlp")
        except Exception:
            try:
                return self._ytdlp_module.version.__version__
            except Exception:
                return "nieznana"

    def fetch_latest_version(self):
        response = requests.get(
            "https://pypi.org/pypi/yt-dlp/json",
            headers={
                "Accept": "application/json",
                "User-Agent": self._user_agent,
            },
            timeout=(5, 20),
        )
        response.raise_for_status()
        payload = response.json() or {}
        releases = payload.get("releases") or {}
        candidates = []

        for raw_version, files in releases.items():
            version_text = str(raw_version or "").strip()
            if not version_text:
                continue

            file_entries = files or []
            if file_entries and all(bool(entry.get("yanked")) for entry in file_entries):
                continue

            if self._version_class is not None:
                try:
                    parsed_version = self._version_class(version_text)
                except self._invalid_version_exceptions:
                    continue
                candidates.append((parsed_version, version_text))
            else:
                candidates.append((version_text, version_text))

        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[-1][1]

        latest_version = str(((payload.get("info") or {}).get("version")) or "").strip()
        if not latest_version:
            raise RuntimeError("Nie udało się ustalić najnowszej wersji yt-dlp.")
        return latest_version

    def fetch_supported_services(self):
        script = (
            "import json\n"
            "from yt_dlp.extractor import gen_extractors\n"
            "services = sorted({\n"
            "    str(getattr(ie, 'IE_NAME', '') or '').strip()\n"
            "    for ie in gen_extractors()\n"
            "    if str(getattr(ie, 'IE_NAME', '') or '').strip() and str(getattr(ie, 'IE_NAME', '') or '').strip().lower() != 'generic'\n"
            "})\n"
            "print(json.dumps(services, ensure_ascii=False))\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Nieznany błąd pobierania listy serwisów.").strip()
            raise RuntimeError(detail[-1200:])

        try:
            services = json.loads(result.stdout or "[]")
        except Exception as exc:
            raise RuntimeError("Nie udało się odczytać listy serwisów z yt-dlp.") from exc

        return [str(item).strip() for item in services if str(item).strip()]

    def get_services_state(self, force=False):
        current_version = self.get_installed_version()

        with self._services_lock:
            cached = dict(self._services_cache)
            if (
                not force
                and cached.get("version") == current_version
                and (cached.get("services") or cached.get("error"))
            ):
                generated_at = float(cached.get("generated_at") or 0.0)
                return {
                    "version": current_version,
                    "services": list(cached.get("services") or []),
                    "count": len(cached.get("services") or []),
                    "generated_at": generated_at,
                    "generated_at_text": self._format_ts(generated_at) if generated_at else "jeszcze nie wygenerowano",
                    "error": str(cached.get("error") or ""),
                }

        generated_at = time.time()
        services = []
        error = ""

        try:
            services = self.fetch_supported_services()
        except Exception as exc:
            error = str(exc)

        state = {
            "version": current_version,
            "services": services,
            "generated_at": generated_at,
            "error": error,
        }

        with self._services_lock:
            self._services_cache.update(state)

        return {
            "version": current_version,
            "services": services,
            "count": len(services),
            "generated_at": generated_at,
            "generated_at_text": self._format_ts(generated_at) if generated_at else "jeszcze nie wygenerowano",
            "error": error,
        }

    def get_update_state_snapshot(self):
        current_version = self.get_installed_version()
        raw_state = self._read_update_state()
        latest_version = raw_state["latest_version"]
        checked_at = raw_state["checked_at"]
        check_error = raw_state["check_error"]
        update_available = bool(latest_version) and self._is_version_newer(latest_version, current_version)
        if check_error:
            status_pill_kind = "error"
            status_pill_label = "Błąd sprawdzania wersji"
        elif update_available:
            status_pill_kind = "queued"
            status_pill_label = "Dostępna jest aktualizacja"
        else:
            status_pill_kind = "success"
            status_pill_label = "Wersja jest aktualna"

        return {
            "current_version": current_version,
            "latest_version": latest_version or "jeszcze nie sprawdzono",
            "latest_version_raw": latest_version,
            "checked_at": checked_at,
            "checked_at_text": self._format_ts(checked_at) if checked_at else "jeszcze nie sprawdzono",
            "check_error": check_error,
            "update_available": update_available,
            "action_needed": update_available,
            "action_button_label": "Zaktualizuj yt-dlp",
            "status_pill_kind": status_pill_kind,
            "status_pill_label": status_pill_label,
        }

    def refresh_update_state(self, force=False):
        snapshot = self.get_update_state_snapshot()
        should_check = force or not snapshot["latest_version_raw"] or self._needs_scheduled_check(snapshot["checked_at"])

        if not should_check:
            return snapshot

        latest_version = snapshot["latest_version_raw"]
        check_error = ""
        checked_at = time.time()

        try:
            latest_version = self.fetch_latest_version()
        except Exception as exc:
            check_error = str(exc)

        self._save_update_state(latest_version, checked_at, check_error)
        return self.get_update_state_snapshot()

    @staticmethod
    def classify_pip_progress(output_line):
        line = str(output_line or "").strip().lower()
        if not line:
            return 18.0, "Uruchamianie pip"
        if "collecting" in line:
            return 30.0, "Pobieranie metadanych"
        if "downloading" in line:
            return 50.0, "Pobieranie pakietu"
        if "installing collected packages" in line:
            return 76.0, "Instalowanie pakietu"
        if "successfully installed" in line:
            return 92.0, "Finalizacja instalacji"
        if "requirement already satisfied" in line:
            return 90.0, "Pakiet jest już obecny"
        if "uninstalling" in line:
            return 72.0, "Zastępowanie poprzedniej wersji"
        return 18.0, "Przetwarzanie przez pip"

    def start_scheduler_once(self):
        with self._scheduler_lock:
            if self._is_scheduler_started():
                return

            def runner():
                while True:
                    try:
                        self.refresh_update_state(force=False)
                        next_check_dt = self._get_next_check_dt()
                        sleep_for = max(60.0, min((next_check_dt - datetime.now()).total_seconds(), 3600.0))
                    except Exception:
                        sleep_for = 300.0
                    time.sleep(sleep_for)

            thread = threading.Thread(target=runner, name="yt-dlp-check-scheduler", daemon=True)
            thread.start()
            self._set_scheduler_started(True)

    def update_package(self, progress_callback=None):
        if progress_callback:
            progress_callback(
                status="running",
                status_label="Przygotowanie",
                progress_percent=6.0,
                detail="Sprawdzam obecną wersję yt-dlp i uruchamiam pip.",
            )

        before_version = self.get_installed_version()
        env = dict(os.environ)
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env["PIP_PROGRESS_BAR"] = "off"
        env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "-U", "--pre", self._pip_package_spec],
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
                    if len(output_lines) > 12:
                        del output_lines[:-12]

                if progress_callback:
                    progress_percent, status_label = self.classify_pip_progress(line)
                    progress_callback(
                        status="running",
                        status_label=status_label,
                        progress_percent=progress_percent,
                        detail=line,
                    )

        output_thread = threading.Thread(target=consume_output, name="yt-dlp-pip-output", daemon=True)
        output_thread.start()

        try:
            return_code = process.wait(timeout=600)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=10)
            except Exception:
                pass
            return False, "Aktualizacja yt-dlp została przerwana po przekroczeniu limitu czasu."
        finally:
            if process.stdout:
                try:
                    process.stdout.close()
                except Exception:
                    pass
            output_thread.join(timeout=2)

        after_version = self.get_installed_version()
        with output_lock:
            output = "\n".join(output_lines).strip()

        if return_code != 0:
            detail = output or "Nieznany błąd aktualizacji."
            return False, "Aktualizacja yt-dlp nie powiodła się: %s" % detail[-1200:]

        if progress_callback:
            progress_callback(
                status="running",
                status_label="Weryfikacja",
                progress_percent=97.0,
                detail="Sprawdzam wersję po zakończeniu instalacji.",
            )

        try:
            latest_version = self.fetch_latest_version()
            self._save_update_state(latest_version, time.time(), "")
        except Exception:
            self._save_update_state(after_version, time.time(), "")

        message = "yt-dlp zaktualizowano z %s do %s." % (before_version, after_version)
        message += " Jeśli aplikacja nadal używa starej wersji, uruchom ponownie usługę Flask."
        if progress_callback:
            progress_callback(
                status="running",
                status_label="Gotowe",
                progress_percent=100.0,
                detail=message,
            )
        return True, message
