import os
import tempfile
import threading
import time
import shutil


class FfmpegMaintenanceService:
    def __init__(
        self,
        *,
        resolve_ffmpeg_binary,
        get_ffmpeg_install_source_label,
        get_installed_ffmpeg_version,
        load_ffmpeg_manifest,
        read_update_state,
        save_update_state,
        needs_scheduled_check,
        get_next_check_dt,
        fetch_latest_release_info,
        ffmpeg_tools_root,
        build_ffmpeg_candidate_dir,
        activate_ffmpeg_candidate_dir,
        format_bytes_text,
        format_ts,
        install_lock,
        scheduler_lock,
        is_scheduler_started,
        set_scheduler_started,
    ):
        self._resolve_ffmpeg_binary = resolve_ffmpeg_binary
        self._get_ffmpeg_install_source_label = get_ffmpeg_install_source_label
        self._get_installed_ffmpeg_version = get_installed_ffmpeg_version
        self._load_ffmpeg_manifest = load_ffmpeg_manifest
        self._read_update_state = read_update_state
        self._save_update_state = save_update_state
        self._needs_scheduled_check = needs_scheduled_check
        self._get_next_check_dt = get_next_check_dt
        self._fetch_latest_release_info = fetch_latest_release_info
        self._ffmpeg_tools_root = ffmpeg_tools_root
        self._build_ffmpeg_candidate_dir = build_ffmpeg_candidate_dir
        self._activate_ffmpeg_candidate_dir = activate_ffmpeg_candidate_dir
        self._format_bytes_text = format_bytes_text
        self._format_ts = format_ts
        self._install_lock = install_lock
        self._scheduler_lock = scheduler_lock
        self._is_scheduler_started = is_scheduler_started
        self._set_scheduler_started = set_scheduler_started

    def apply_ffmpeg_location(self, options):
        location = self.get_ffmpeg_location_for_yt_dlp()
        if location:
            options["ffmpeg_location"] = location
        return options

    def get_ffmpeg_location_for_yt_dlp(self):
        binary_path, _ = self._resolve_ffmpeg_binary()
        if not binary_path:
            return ""
        return os.path.dirname(binary_path)

    def ensure_ffmpeg_available_for_audio_conversion(self):
        binary_path, _ = self._resolve_ffmpeg_binary()
        if binary_path:
            return binary_path

        raise RuntimeError(
            "Pobieranie audio jako MP3 wymaga ffmpeg. Zainstaluj go w Konfiguracji przed rozpoczęciem pobierania audio."
        )

    def get_installed_ffmpeg_version(self, binary_path=None):
        return self._get_installed_ffmpeg_version(binary_path)

    def get_update_state_snapshot(self):
        current_path, source_key = self._resolve_ffmpeg_binary()
        current_version = self._get_installed_ffmpeg_version(current_path)
        manifest = self._load_ffmpeg_manifest() if source_key == "managed" else {}

        raw_state = self._read_update_state()
        latest_version = raw_state["latest_version"]
        latest_build_id = raw_state["latest_build_id"]
        checked_at = raw_state["checked_at"]
        check_error = raw_state["check_error"]
        installed_build_id = str(manifest.get("build_id") or "").strip()
        managed = source_key == "managed"
        installed = bool(current_path)
        can_compare_updates = managed and bool(installed_build_id) and bool(latest_build_id)
        update_available = bool(can_compare_updates and latest_build_id != installed_build_id)
        if check_error:
            status_pill_kind = "error"
            status_pill_label = "Błąd sprawdzania wersji"
        elif not installed:
            status_pill_kind = "error"
            status_pill_label = "ffmpeg nie jest zainstalowany"
        elif update_available:
            status_pill_kind = "queued"
            status_pill_label = "Dostępna jest aktualizacja"
        elif managed:
            status_pill_kind = "success"
            status_pill_label = "Gotowy do łączenia audio i wideo"
        else:
            status_pill_kind = "success"
            status_pill_label = "Wykryto systemowy ffmpeg"

        return {
            "current_version": current_version,
            "current_path": current_path or "nie znaleziono",
            "current_source_label": self._get_ffmpeg_install_source_label(source_key),
            "current_build_label": str(manifest.get("version_label") or "").strip()
            or ("instalacja zewnętrzna" if source_key == "system" else "brak"),
            "installed": installed,
            "managed": managed,
            "latest_version": latest_version or "jeszcze nie sprawdzono",
            "latest_version_raw": latest_version,
            "latest_build_id_raw": latest_build_id,
            "checked_at": checked_at,
            "checked_at_text": self._format_ts(checked_at) if checked_at else "jeszcze nie sprawdzono",
            "check_error": check_error,
            "update_available": update_available,
            "can_compare_updates": can_compare_updates,
            "action_button_label": "Zaktualizuj ffmpeg" if managed and update_available else "Zainstaluj ffmpeg",
            "action_needed": (not installed) or update_available,
            "status_pill_kind": status_pill_kind,
            "status_pill_label": status_pill_label,
        }

    def refresh_update_state(self, force=False):
        snapshot = self.get_update_state_snapshot()
        should_check = force or not snapshot["latest_build_id_raw"] or self._needs_scheduled_check(snapshot["checked_at"])

        if not should_check:
            return snapshot

        latest_version = snapshot["latest_version_raw"]
        latest_build_id = snapshot["latest_build_id_raw"]
        check_error = ""
        checked_at = time.time()

        try:
            latest = self._fetch_latest_release_info()
            latest_version = latest["version_label"]
            latest_build_id = latest["build_id"]
        except Exception as exc:
            check_error = str(exc)

        self._save_update_state(latest_version, latest_build_id, checked_at, check_error)
        return self.get_update_state_snapshot()

    def start_scheduler_once(self):
        with self._scheduler_lock:
            if self._is_scheduler_started():
                return

            def runner():
                while True:
                    try:
                        self.refresh_update_state(force=False)
                        next_check_dt = self._get_next_check_dt()
                        sleep_for = max(60.0, min((next_check_dt - __import__("datetime").datetime.now()).total_seconds(), 3600.0))
                    except Exception:
                        sleep_for = 300.0
                    time.sleep(sleep_for)

            thread = threading.Thread(target=runner, name="ffmpeg-check-scheduler", daemon=True)
            thread.start()
            self._set_scheduler_started(True)

    def install_or_update(self, progress_callback=None):
        with self._install_lock:
            release_info = None
            temp_root = ""

            try:
                if progress_callback:
                    progress_callback(
                        status="running",
                        status_label="Sprawdzanie buildu",
                        progress_percent=6.0,
                        detail="Sprawdzam najnowszy build ffmpeg dla tej platformy.",
                    )

                release_info = self._fetch_latest_release_info()
                os.makedirs(self._ffmpeg_tools_root, exist_ok=True)
                temp_root = tempfile.mkdtemp(prefix="ffmpeg-install-", dir=self._ffmpeg_tools_root)

                if progress_callback:
                    progress_callback(
                        status="running",
                        status_label="Pobieranie paczki",
                        progress_percent=14.0,
                        detail="Przygotowuję pobranie %s (%s)." % (
                            release_info["asset_name"],
                            self._format_bytes_text(release_info.get("asset_size") or 0),
                        ),
                    )

                def report_download_progress(downloaded_bytes=None, total_bytes=None, **event):
                    if not progress_callback:
                        return
                    if event:
                        progress_callback(**event)
                        return

                    stage_start = 14.0
                    stage_end = 76.0
                    if total_bytes and total_bytes > 0:
                        ratio = max(0.0, min(1.0, float(downloaded_bytes) / float(total_bytes)))
                        progress_percent = stage_start + ((stage_end - stage_start) * ratio)
                        detail = "Pobieranie %s / %s." % (
                            self._format_bytes_text(downloaded_bytes),
                            self._format_bytes_text(total_bytes),
                        )
                    else:
                        progress_percent = 45.0
                        detail = "Pobieranie %s." % self._format_bytes_text(downloaded_bytes)

                    progress_callback(
                        status="running",
                        status_label="Pobieranie paczki",
                        progress_percent=progress_percent,
                        detail=detail,
                    )

                candidate_dir, _ = self._build_ffmpeg_candidate_dir(
                    temp_root,
                    release_info,
                    progress_callback=report_download_progress,
                )

                if progress_callback:
                    progress_callback(
                        status="running",
                        status_label="Aktywowanie",
                        progress_percent=96.0,
                        detail="Podmieniam aktywny katalog z ffmpeg używany przez aplikację.",
                    )

                self._activate_ffmpeg_candidate_dir(candidate_dir)
                self._save_update_state(release_info["version_label"], release_info["build_id"], time.time(), "")
            except Exception as exc:
                if release_info:
                    self._save_update_state(
                        release_info["version_label"],
                        release_info["build_id"],
                        time.time(),
                        str(exc),
                    )
                detail = str(exc).strip() or "Nieznany błąd instalacji."
                return False, "Instalacja lub aktualizacja ffmpeg nie powiodła się: %s" % detail[-1200:]
            finally:
                if temp_root and os.path.isdir(temp_root):
                    shutil.rmtree(temp_root, ignore_errors=True)

        state = self.get_update_state_snapshot()
        if state["managed"]:
            message = "ffmpeg jest gotowy (%s, %s)." % (
                state["current_version"],
                state["current_build_label"],
            )
        else:
            message = "ffmpeg zainstalowano, ale aplikacja nie widzi jeszcze nowej binarki."

        message += " Nowe pobrania będą mogły łączyć osobne audio i wideo bez restartu usługi."
        if progress_callback:
            progress_callback(
                status="running",
                status_label="Gotowe",
                progress_percent=100.0,
                detail=message,
            )
        return True, message
