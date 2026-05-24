import os
import shutil
import subprocess
import time


class SystemServiceHelper:
    def __init__(
        self,
        *,
        dlna_log_file,
        dlna_log_max_bytes,
        dlna_log_tail_read_bytes,
        dlna_log_browser_max_bytes,
        dlna_service_name,
        format_ts,
        format_duration,
    ):
        self._dlna_log_file = dlna_log_file
        self._dlna_log_max_bytes = dlna_log_max_bytes
        self._dlna_log_tail_read_bytes = dlna_log_tail_read_bytes
        self._dlna_log_browser_max_bytes = dlna_log_browser_max_bytes
        self._dlna_service_name = dlna_service_name
        self._format_ts = format_ts
        self._format_duration = format_duration

    @staticmethod
    def get_system_uptime_seconds():
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as fh:
                return float((fh.read().strip().split() or ["0"])[0])
        except Exception:
            return None

    @staticmethod
    def read_systemctl_service_info(service_name):
        result = subprocess.run(
            [
                "systemctl",
                "show",
                service_name,
                "--property=Id",
                "--property=Description",
                "--property=LoadState",
                "--property=ActiveState",
                "--property=SubState",
                "--property=MainPID",
                "--property=UnitFileState",
                "--property=ExecMainStartTimestamp",
                "--property=ExecMainStartTimestampMonotonic",
                "--property=ActiveEnterTimestamp",
                "--property=ActiveEnterTimestampMonotonic",
                "--property=ExecMainStatus",
                "--property=Result",
                "--property=NRestarts",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Nie udało się odczytać statusu usługi.").strip()
            raise RuntimeError(detail[-1200:])

        info = {}
        for line in (result.stdout or "").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
        return info

    @staticmethod
    def read_recent_service_journal_lines(service_name, lines=12):
        try:
            result = subprocess.run(
                [
                    "journalctl",
                    "-u",
                    service_name,
                    "-n",
                    str(max(1, int(lines))),
                    "--no-pager",
                    "-o",
                    "cat",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception:
            return []

        if result.returncode != 0:
            return []

        journal_lines = []
        for raw_line in (result.stdout or "").splitlines():
            line = str(raw_line or "").strip()
            if line:
                journal_lines.append(line)
        return journal_lines[-max(1, int(lines)):]

    def read_recent_log_file_lines(self, path, lines=12):
        try:
            if not os.path.isfile(path):
                return []
            self.trim_text_log_file(path, max_bytes=self._dlna_log_max_bytes)
            file_size = max(0, int(os.path.getsize(path) or 0))
            bytes_to_read = max(4096, min(file_size, self._dlna_log_tail_read_bytes))
            with open(path, "rb") as fh:
                if file_size > bytes_to_read:
                    fh.seek(-bytes_to_read, os.SEEK_END)
                raw_data = fh.read()
        except Exception:
            return []

        text = raw_data.decode("utf-8", errors="replace")
        if file_size > bytes_to_read:
            newline_index = text.find("\n")
            if newline_index >= 0:
                text = text[newline_index + 1:]

        result = []
        for line in text.splitlines()[-max(1, int(lines)):]:
            cleaned = str(line or "").strip()
            if cleaned:
                result.append(cleaned)
        return result

    def trim_text_log_file(self, path, max_bytes=None):
        max_bytes = self._dlna_log_max_bytes if max_bytes is None else max_bytes
        normalized_path = str(path or "").strip()
        if not normalized_path or not os.path.isfile(normalized_path):
            return False

        try:
            file_size = max(0, int(os.path.getsize(normalized_path) or 0))
        except Exception:
            return False

        if file_size <= max(1024, int(max_bytes or 0)):
            return False

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        header_text = (
            "[%s] PANEL DLNA: Przycięto log Gerbera do limitu %s MB. Zachowano najnowszą część pliku.\n"
            % (timestamp, int(max_bytes // (1024 * 1024)))
        )
        header_bytes = header_text.encode("utf-8")
        keep_bytes = max(1024, int(max_bytes) - len(header_bytes))

        try:
            with open(normalized_path, "rb") as fh:
                fh.seek(-keep_bytes, os.SEEK_END)
                tail = fh.read()
        except Exception:
            return False

        newline_index = tail.find(b"\n")
        if newline_index >= 0 and newline_index < len(tail) - 1:
            tail = tail[newline_index + 1:]

        payload = header_bytes + tail[-keep_bytes:]
        if len(payload) > int(max_bytes):
            payload = payload[-int(max_bytes):]

        try:
            with open(normalized_path, "wb") as fh:
                fh.write(payload)
        except Exception:
            return False

        return True

    def read_text_log_file_for_browser(self, path, max_bytes=None):
        max_bytes = self._dlna_log_browser_max_bytes if max_bytes is None else max_bytes
        if not os.path.isfile(path):
            return "Log DLNA nie istnieje jeszcze. Uruchom serwer DLNA, aby zacząć zbierać wpisy.\n"

        self.trim_text_log_file(path, max_bytes=self._dlna_log_max_bytes)
        file_size = 0
        try:
            file_size = max(0, int(os.path.getsize(path) or 0))
        except Exception:
            file_size = 0

        try:
            with open(path, "rb") as fh:
                if file_size > max_bytes > 0:
                    fh.seek(-max_bytes, os.SEEK_END)
                    raw_data = fh.read()
                else:
                    raw_data = fh.read()
        except Exception as exc:
            return "Nie udało się odczytać logu DLNA: %s\n" % exc

        text = raw_data.decode("utf-8", errors="replace")
        if file_size > max_bytes > 0:
            newline_index = text.find("\n")
            if newline_index >= 0:
                text = text[newline_index + 1:]
            text = "[Log DLNA jest większy niż %s B, więc pokazuję końcówkę pliku z %s]\n\n%s" % (
                max_bytes,
                path,
                text,
            )
        return text if text.endswith("\n") else (text + "\n")

    @staticmethod
    def select_service_log_excerpt(journal_lines):
        noise_markers = (
            "scheduled restart job",
            "start request repeated too quickly",
            "failed with result",
            "stopped ",
            "started ",
            "shutdown():",
            "shutting down",
            "shutdowndriver():",
            "subscriber destroyed",
            "upnp_cleanup: upnpunregisterrootdevice failed",
            "destroying storage",
            "destroying server",
            "signalling...",
            "waiting for thread",
            "exiting thread",
        )
        for line in reversed(journal_lines or []):
            lowered = str(line or "").strip().lower()
            if not lowered:
                continue
            if any(marker in lowered for marker in noise_markers):
                continue
            return str(line).strip()
        return ""

    def get_generic_service_state(self, service_name):
        state = {
            "service_name": service_name,
            "available": False,
            "load_state": "unknown",
            "active_state": "unknown",
            "sub_state": "",
            "status_label": "Nieznany",
            "status_kind": "muted",
            "main_pid": "",
            "service_uptime_seconds": None,
            "service_uptime_text": "nieznany",
            "last_restart_ts": 0.0,
            "last_restart_text": "nieznany",
            "unit_file_state": "unknown",
            "unit_file_label": "nieznany",
            "enabled": False,
            "result": "",
            "exec_main_status": "",
            "restart_count": 0,
            "recent_log_lines": [],
            "recent_log_excerpt": "",
            "diagnostic_text": "",
            "error": "",
        }

        try:
            info = self.read_systemctl_service_info(service_name)
            load_state = str(info.get("LoadState") or "unknown")
            active_state = str(info.get("ActiveState") or "unknown")
            unit_file_state = str(info.get("UnitFileState") or "unknown")
            sub_state = str(info.get("SubState") or "")

            state.update({
                "available": load_state != "not-found",
                "load_state": load_state,
                "active_state": active_state,
                "sub_state": sub_state,
                "main_pid": str(info.get("MainPID") or ""),
                "unit_file_state": unit_file_state,
                "enabled": unit_file_state in ("enabled", "enabled-runtime", "linked", "linked-runtime"),
                "result": str(info.get("Result") or ""),
                "exec_main_status": str(info.get("ExecMainStatus") or ""),
            })
            try:
                state["restart_count"] = max(0, int(str(info.get("NRestarts") or "0").strip() or "0"))
            except Exception:
                state["restart_count"] = 0

            unit_label_map = {
                "enabled": "autostart włączony",
                "enabled-runtime": "autostart tymczasowy",
                "disabled": "autostart wyłączony",
                "masked": "zamaskowana",
                "static": "statyczna",
                "linked": "podlinkowana",
                "linked-runtime": "podlinkowana tymczasowo",
                "indirect": "pośrednia",
            }
            state["unit_file_label"] = unit_label_map.get(unit_file_state, unit_file_state or "nieznany")

            if load_state == "not-found":
                state["status_label"] = "Brak jednostki"
                state["status_kind"] = "error"
            elif active_state == "active":
                state["status_label"] = "Aktywna"
                state["status_kind"] = "success"
            elif active_state in ("activating", "reloading"):
                state["status_label"] = "Uruchamianie"
                state["status_kind"] = "queued"
            elif active_state in ("inactive", "failed", "deactivating"):
                state["status_label"] = "Nieaktywna"
                state["status_kind"] = "error"
            else:
                state["status_label"] = active_state or "Nieznany"
                state["status_kind"] = "muted"

            monotonic_usec = info.get("ExecMainStartTimestampMonotonic") or info.get("ActiveEnterTimestampMonotonic") or "0"
            try:
                start_mono_seconds = float(monotonic_usec) / 1000000.0
            except Exception:
                start_mono_seconds = 0.0

            system_uptime_seconds = self.get_system_uptime_seconds()
            if system_uptime_seconds and start_mono_seconds and system_uptime_seconds >= start_mono_seconds:
                service_uptime_seconds = max(0.0, system_uptime_seconds - start_mono_seconds)
                state["service_uptime_seconds"] = service_uptime_seconds
                state["service_uptime_text"] = self._format_duration(service_uptime_seconds)
                last_restart_ts = time.time() - service_uptime_seconds
                state["last_restart_ts"] = last_restart_ts
                state["last_restart_text"] = self._format_ts(last_restart_ts)
            else:
                state["last_restart_text"] = str(info.get("ExecMainStartTimestamp") or info.get("ActiveEnterTimestamp") or "nieznany")

            state["recent_log_lines"] = self.read_recent_service_journal_lines(service_name, lines=10)
            file_log_lines = self.read_recent_log_file_lines(self._dlna_log_file, lines=12) if service_name == self._dlna_service_name else []
            if file_log_lines:
                state["recent_log_lines"] = file_log_lines
            if state["recent_log_lines"]:
                state["recent_log_excerpt"] = self.select_service_log_excerpt(state["recent_log_lines"])

            diagnostic_parts = []
            if state["restart_count"]:
                diagnostic_parts.append("Restarty: %s" % state["restart_count"])
            if state["result"]:
                diagnostic_parts.append("Wynik: %s" % state["result"])
            if state["exec_main_status"] and state["exec_main_status"] != "0":
                diagnostic_parts.append("Kod wyjścia: %s" % state["exec_main_status"])
            state["diagnostic_text"] = " | ".join(diagnostic_parts)
        except Exception as exc:
            state["error"] = str(exc)

        return state

    def get_flask_service_state(self, service_name, app_started_at_ts):
        app_uptime_seconds = max(0.0, time.time() - app_started_at_ts)
        state = self.get_generic_service_state(service_name)
        state["app_uptime_seconds"] = app_uptime_seconds
        state["app_uptime_text"] = self._format_duration(app_uptime_seconds)
        return state

    @staticmethod
    def schedule_systemd_service_restart(service_name):
        systemctl_binary = shutil.which("systemctl") or "/bin/systemctl"
        command = [systemctl_binary, "restart", service_name]
        if os.name != "nt":
            try:
                if os.geteuid() != 0:
                    sudo_binary = shutil.which("sudo")
                    if sudo_binary:
                        command = [sudo_binary, "-n", systemctl_binary, "restart", service_name]
            except Exception:
                pass
        return subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
