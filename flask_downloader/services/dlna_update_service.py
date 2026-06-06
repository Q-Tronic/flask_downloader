import ipaddress
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta


class DlnaUpdateService:
    def __init__(
        self,
        *,
        default_update_state_factory,
        default_config_factory,
        normalize_username,
        get_users_snapshot,
        allowed_network,
        all_collection_id,
        preferred_repo_channel,
        official_repo_channels,
        repo_key_url,
        repo_keyring_file,
        repo_list_file,
        user_agent,
        requests_module,
        package_name,
        check_hour,
        is_linux_runtime,
        format_ts,
        read_config_values,
        save_update_state,
    ):
        self._default_update_state_factory = default_update_state_factory
        self._default_config_factory = default_config_factory
        self._normalize_username = normalize_username
        self._get_users_snapshot = get_users_snapshot
        self._allowed_network = allowed_network
        self._all_collection_id = all_collection_id
        self._preferred_repo_channel = preferred_repo_channel
        self._official_repo_channels = official_repo_channels
        self._repo_key_url = repo_key_url
        self._repo_keyring_file = repo_keyring_file
        self._repo_list_file = repo_list_file
        self._user_agent = user_agent
        self._requests = requests_module
        self._package_name = package_name
        self._check_hour = check_hour
        self._is_linux_runtime = is_linux_runtime
        self._format_ts = format_ts
        self._read_config_values = read_config_values
        self._save_update_state = save_update_state

    def normalize_update_state(self, value):
        state = self._default_update_state_factory()

        if not isinstance(value, dict):
            return state

        latest_version = str(value.get("latest_version") or "").strip()
        check_error = str(value.get("check_error") or "").strip()

        try:
            checked_at = float(value.get("checked_at") or 0.0)
        except Exception:
            checked_at = 0.0

        state.update({
            "latest_version": latest_version,
            "checked_at": checked_at,
            "check_error": check_error,
        })
        return state

    @staticmethod
    def normalize_server_name(value):
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if not text:
            raise ValueError("Nazwa serwera DLNA nie może być pusta.")
        return text[:120]

    def normalize_bind_ip(self, value):
        text = str(value or "").strip()
        if not text:
            return ""

        try:
            address = ipaddress.ip_address(text)
        except Exception as exc:
            raise ValueError("Adres IP serwera DLNA jest nieprawidłowy.") from exc

        if address.version != 4 or address not in self._allowed_network:
            raise ValueError("Adres IP serwera DLNA musi należeć do sieci %s." % self._allowed_network)

        return str(address)

    @staticmethod
    def normalize_port(value):
        try:
            port = int(str(value or "").strip())
        except Exception as exc:
            raise ValueError("Port DLNA musi być liczbą całkowitą.") from exc

        if port < 49152 or port > 65535:
            raise ValueError("Port DLNA musi mieścić się w zakresie 49152-65535.")

        return port

    @staticmethod
    def normalize_collection_name(value):
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if not text:
            raise ValueError("Nazwa kolekcji nie może być pusta.")
        return text[:80]

    @staticmethod
    def normalize_description(value, max_len=240):
        return re.sub(r"\s+", " ", str(value or "").strip())[:max_len]

    @staticmethod
    def normalize_collection_id(value, fallback=None):
        text = re.sub(r"[^a-zA-Z0-9_-]+", "", str(value or "").strip())
        if text:
            return text[:48]
        if fallback:
            return fallback[:48]
        return uuid.uuid4().hex

    def normalize_collection_entry(self, raw, existing_ids=None):
        if not isinstance(raw, dict):
            return None

        try:
            name = self.normalize_collection_name(raw.get("name"))
        except Exception:
            return None

        collection_id = self.normalize_collection_id(raw.get("id"))
        if existing_ids is not None:
            while collection_id in existing_ids or collection_id == self._all_collection_id:
                collection_id = uuid.uuid4().hex
            existing_ids.add(collection_id)

        return {
            "id": collection_id,
            "name": name,
            "description": self.normalize_description(raw.get("description"), max_len=320),
        }

    def normalize_client_ip(self, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("Adres IP klienta nie może być pusty.")

        try:
            address = ipaddress.ip_address(text)
        except Exception as exc:
            raise ValueError("Adres IP klienta jest nieprawidłowy.") from exc

        if address.version != 4 or address not in self._allowed_network:
            raise ValueError("Adres IP klienta musi należeć do sieci %s." % self._allowed_network)

        return str(address)

    def normalize_client_entry(self, raw, valid_collection_ids, valid_usernames):
        if not isinstance(raw, dict):
            return None

        try:
            ip = self.normalize_client_ip(raw.get("ip"))
        except Exception:
            return None

        collection_ids = []
        seen = set()
        for item in raw.get("collection_ids") or []:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            if value != self._all_collection_id and value not in valid_collection_ids:
                continue
            seen.add(value)
            collection_ids.append(value)

        usernames = []
        seen_usernames = set()
        for item in raw.get("usernames") or []:
            try:
                value = self._normalize_username(item)
            except Exception:
                continue
            if not value or value in seen_usernames or value not in valid_usernames:
                continue
            seen_usernames.add(value)
            usernames.append(value)

        return {
            "id": self.normalize_collection_id(raw.get("id")),
            "ip": ip,
            "description": self.normalize_description(raw.get("description"), max_len=200),
            "enabled": bool(raw.get("enabled", True)),
            "collection_ids": collection_ids,
            "usernames": usernames,
        }

    @staticmethod
    def normalize_config_storage_kind(value):
        return "audio" if str(value or "").strip().lower() == "audio" else "video"

    @staticmethod
    def normalize_config_relative_path(value):
        path = str(value or "").strip().replace("\\", "/")
        if not path:
            return ""

        normalized = os.path.normpath(path).replace("\\", "/").lstrip("/")
        if normalized in ("", ".", "..") or normalized.startswith("../"):
            return ""

        return normalized

    def normalize_media_rule_entry(self, raw, valid_collection_ids):
        if not isinstance(raw, dict):
            return None

        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in ("file", "folder"):
            return None

        relative_path = self.normalize_config_relative_path(raw.get("relative_path") or raw.get("path") or "")
        if not relative_path:
            return None

        collection_ids = []
        seen = set()
        for item in raw.get("collection_ids") or []:
            value = str(item or "").strip()
            if not value or value in seen or value == self._all_collection_id:
                continue
            if value not in valid_collection_ids:
                continue
            seen.add(value)
            collection_ids.append(value)

        return {
            "id": self.normalize_collection_id(raw.get("id")),
            "kind": kind,
            "storage_kind": self.normalize_config_storage_kind(raw.get("storage_kind") or "video"),
            "relative_path": relative_path,
            "enabled": bool(raw.get("enabled", True)),
            "collection_ids": collection_ids,
        }

    def normalize_config(self, value):
        state = self._default_config_factory()

        if not isinstance(value, dict):
            return state

        try:
            server_name = self.normalize_server_name(value.get("server_name", state["server_name"]))
        except Exception:
            server_name = state["server_name"]

        try:
            bind_ip = self.normalize_bind_ip(value.get("bind_ip", state["bind_ip"]))
        except Exception:
            bind_ip = state["bind_ip"]

        try:
            port = self.normalize_port(value.get("port", state["port"]))
        except Exception:
            port = state["port"]

        icon_mode = "custom" if str(value.get("icon_mode") or state.get("icon_mode") or "").strip().lower() == "custom" else "default"
        icon_source_name = self.normalize_description(value.get("icon_source_name"), max_len=160)
        try:
            icon_updated_at = float(value.get("icon_updated_at") or 0.0)
        except Exception:
            icon_updated_at = 0.0

        collection_items = []
        collection_ids = set()
        for raw in value.get("collections") or []:
            item = self.normalize_collection_entry(raw, existing_ids=collection_ids)
            if item:
                collection_items.append(item)

        valid_collection_ids = {item["id"] for item in collection_items}
        valid_usernames = {
            str(item.get("username") or "").strip()
            for item in (self._get_users_snapshot() or [])
            if str(item.get("username") or "").strip()
        }
        client_items = []
        seen_ips = set()
        for raw in value.get("clients") or []:
            item = self.normalize_client_entry(raw, valid_collection_ids, valid_usernames)
            if not item or item["ip"] in seen_ips:
                continue
            seen_ips.add(item["ip"])
            client_items.append(item)

        rule_items = []
        seen_rules = set()
        for raw in value.get("media_rules") or []:
            item = self.normalize_media_rule_entry(raw, valid_collection_ids)
            if not item:
                continue
            key = (item["kind"], item["storage_kind"], item["relative_path"])
            if key in seen_rules:
                continue
            seen_rules.add(key)
            rule_items.append(item)

        try:
            layout_version = max(0, int(value.get("layout_version") or 0))
        except Exception:
            layout_version = 0

        try:
            last_sync_at = float(value.get("last_sync_at") or 0.0)
        except Exception:
            last_sync_at = 0.0

        return {
            "enabled": bool(value.get("enabled", state["enabled"])),
            "server_name": server_name,
            "bind_ip": bind_ip,
            "port": port,
            "icon_mode": icon_mode,
            "icon_source_name": icon_source_name,
            "icon_updated_at": icon_updated_at,
            "collections": collection_items,
            "clients": client_items,
            "media_rules": rule_items,
            "layout_version": layout_version,
            "last_sync_at": last_sync_at,
            "last_sync_error": str(value.get("last_sync_error") or "").strip(),
        }

    @staticmethod
    def build_apt_query_env():
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        env["LANGUAGE"] = "C"
        return env

    def get_linux_distribution_codename(self):
        os_release_path = os.path.join("/etc", "os-release")
        try:
            with open(os_release_path, "r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = str(raw_line or "").strip()
                    if not line or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key.strip() != "VERSION_CODENAME":
                        continue
                    text = str(value or "").strip().strip("\"' ")
                    if text:
                        return text
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["lsb_release", "-c", "--short"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
                check=False,
                env=self.build_apt_query_env(),
            )
            text = str(result.stdout or "").strip()
            if result.returncode == 0 and text:
                return text
        except Exception:
            pass

        raise RuntimeError("Nie udało się ustalić codename systemu Debian/Ubuntu potrzebnego do repo Gerbera.")

    def get_official_repo_channel(self, channel_key=""):
        key = str(channel_key or self._preferred_repo_channel).strip().lower()
        if key not in self._official_repo_channels:
            key = self._preferred_repo_channel
        data = dict(self._official_repo_channels.get(key) or {})
        data["key"] = key
        return data

    def read_official_repo_line(self):
        try:
            with open(self._repo_list_file, "r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = str(raw_line or "").strip()
                    if line and not line.startswith("#"):
                        return line
        except Exception:
            return ""
        return ""

    def get_repo_source_snapshot(self, policy=None):
        raw_policy = str((policy or {}).get("raw_output") or "")
        repo_line = self.read_official_repo_line()
        source = {
            "channel_key": "system",
            "label": "Pakiet Debian / apt",
            "repo_line": repo_line,
        }

        if "pkg.gerbera.io/debian-git" in repo_line or "pkg.gerbera.io/debian-git" in raw_policy:
            channel = self.get_official_repo_channel("latest")
            source["channel_key"] = channel["key"]
            source["label"] = channel["label"]
            return source

        if "pkg.gerbera.io/debian/" in repo_line or "pkg.gerbera.io/debian/" in raw_policy:
            channel = self.get_official_repo_channel("stable")
            source["channel_key"] = channel["key"]
            source["label"] = channel["label"]
            return source

        return source

    def download_official_repo_key_bytes(self):
        wget_path = shutil.which("wget")
        if wget_path:
            result = subprocess.run(
                [wget_path, "-qO-", self._repo_key_url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
                env=self.build_apt_query_env(),
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout

        response = self._requests.get(self._repo_key_url, headers={"User-Agent": self._user_agent}, timeout=45)
        response.raise_for_status()
        return response.content

    def ensure_official_repo(self, channel_key="", progress_callback=None):
        if not self._is_linux_runtime():
            raise RuntimeError("Oficjalne repo Gerbera można skonfigurować tylko na serwerze Linux z apt.")

        channel = self.get_official_repo_channel(channel_key)
        codename = self.get_linux_distribution_codename()
        repo_line = "deb [signed-by=%s] https://pkg.gerbera.io/%s/ %s main" % (
            self._repo_keyring_file,
            channel["apt_path"],
            codename,
        )

        if progress_callback:
            progress_callback(
                status="running",
                status_label="Repozytorium",
                progress_percent=14.0,
                detail="Konfiguruję %s dla systemu %s." % (channel["label"], codename),
            )

        key_bytes = self.download_official_repo_key_bytes()
        if not key_bytes:
            raise RuntimeError("Nie udało się pobrać klucza GPG oficjalnego repo Gerbera.")

        gpg_binary = shutil.which("gpg")
        if not gpg_binary:
            raise RuntimeError("Brakuje binarki gpg potrzebnej do instalacji oficjalnego repo Gerbera.")

        keyring_dir = os.path.dirname(self._repo_keyring_file)
        repo_list_dir = os.path.dirname(self._repo_list_file)
        os.makedirs(keyring_dir, exist_ok=True)
        os.makedirs(repo_list_dir, exist_ok=True)

        ascii_tmp = ""
        gpg_tmp = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False) as ascii_fh:
                ascii_fh.write(key_bytes)
                ascii_tmp = ascii_fh.name
            # Plik tymczasowy dla końcowego keyringu musi powstać w tym samym
            # katalogu co plik docelowy, żeby końcowy os.replace nie wpadał
            # w EXDEV na systemach z osobnym /tmp (np. Debian 13 / trixie).
            with tempfile.NamedTemporaryFile(
                delete=False,
                dir=keyring_dir,
                prefix=".gerbera-keyring-",
                suffix=".gpg",
            ) as gpg_fh:
                gpg_tmp = gpg_fh.name

            result = subprocess.run(
                [gpg_binary, "--dearmor", "--yes", "--output", gpg_tmp, ascii_tmp],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
                env=self.build_apt_query_env(),
            )
            if result.returncode != 0 or not os.path.isfile(gpg_tmp) or os.path.getsize(gpg_tmp) <= 0:
                detail = (result.stderr or result.stdout or "gpg --dearmor zakończył się błędem.").strip()
                raise RuntimeError(detail[-1200:])

            os.replace(gpg_tmp, self._repo_keyring_file)
            try:
                os.chmod(self._repo_keyring_file, 0o644)
            except Exception:
                pass

            with open(self._repo_list_file, "w", encoding="utf-8") as fh:
                fh.write(repo_line + "\n")
        finally:
            for path in (ascii_tmp, gpg_tmp):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

        return {
            "channel_key": channel["key"],
            "channel_label": channel["label"],
            "codename": codename,
            "repo_line": repo_line,
        }

    def read_dpkg_installed_version(self, package_name):
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}|${Version}", package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
            env=self.build_apt_query_env(),
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
        if "install ok installed" not in status_text or not version_text:
            return ""
        return version_text

    def get_apt_package_policy(self, package_name):
        if not self._is_linux_runtime():
            raise RuntimeError("Automatyczna obsługa pakietów DLNA wymaga Linuxa z apt.")

        result = subprocess.run(
            ["apt-cache", "policy", package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
            env=self.build_apt_query_env(),
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Nie udało się odczytać stanu pakietu.").strip()
            raise RuntimeError(detail[-1200:])

        installed = self.read_dpkg_installed_version(package_name)
        candidate = ""
        for raw_line in (result.stdout or "").splitlines():
            line = raw_line.strip()
            if line.lower().startswith("installed:"):
                installed = line.split(":", 1)[1].strip()
            elif line.lower().startswith("candidate:"):
                candidate = line.split(":", 1)[1].strip()

        if installed == "(none)":
            installed = ""
        if candidate == "(none)":
            candidate = ""

        return {
            "installed": installed,
            "candidate": candidate,
            "raw_output": result.stdout or "",
        }

    def get_last_due_check_dt(self, now=None):
        now = now or datetime.now()
        due = now.replace(hour=self._check_hour, minute=0, second=0, microsecond=0)
        if now < due:
            due -= timedelta(days=1)
        return due

    def get_next_check_dt(self, now=None):
        return self.get_last_due_check_dt(now=now) + timedelta(days=1)

    def needs_scheduled_check(self, last_checked_at, now=None):
        due_dt = self.get_last_due_check_dt(now=now)
        return not last_checked_at or float(last_checked_at or 0.0) < due_dt.timestamp()

    def get_package_state_snapshot(self):
        raw_state, raw_dlna_config = self._read_config_values()
        raw_state = self.normalize_update_state(raw_state)
        dlna_config = self.normalize_config(raw_dlna_config)

        current_version = ""
        latest_version = raw_state["latest_version"]
        check_error = raw_state["check_error"]
        policy = None

        try:
            policy = self.get_apt_package_policy(self._package_name)
            current_version = policy["installed"]
            if policy["candidate"]:
                latest_version = policy["candidate"]
        except Exception as exc:
            if not check_error:
                check_error = str(exc)

        repo_source = self.get_repo_source_snapshot(policy=policy)
        preferred_channel = self.get_official_repo_channel()
        installed = bool(current_version)
        update_available = bool(installed and latest_version and latest_version != current_version)
        needs_repo_switch = repo_source["channel_key"] != preferred_channel["key"]
        action_needed = (not installed) or update_available or needs_repo_switch

        if installed and needs_repo_switch:
            status_pill_label = "Dostępna migracja do nowszego repo Gerbera"
            status_pill_kind = "queued"
        elif update_available:
            status_pill_label = "Dostępna aktualizacja serwera DLNA"
            status_pill_kind = "queued"
        elif installed:
            status_pill_label = "Serwer DLNA jest aktualny"
            status_pill_kind = "success"
        else:
            status_pill_label = "Serwer DLNA nie jest zainstalowany"
            status_pill_kind = "error"

        return {
            "package_name": self._package_name,
            "current_version": current_version or "brak",
            "latest_version": latest_version or "brak danych",
            "current_version_raw": current_version,
            "latest_version_raw": latest_version,
            "checked_at": raw_state["checked_at"],
            "checked_at_text": self._format_ts(raw_state["checked_at"]) if raw_state["checked_at"] else "jeszcze nie sprawdzano",
            "check_error": check_error,
            "installed": installed,
            "update_available": update_available,
            "needs_repo_switch": needs_repo_switch,
            "action_needed": action_needed,
            "status_pill_label": status_pill_label,
            "status_pill_kind": status_pill_kind,
            "action_button_label": (
                "Przełącz na oficjalne repo i zaktualizuj DLNA"
                if installed and needs_repo_switch
                else ("Zaktualizuj serwer DLNA" if update_available else "Zainstaluj serwer DLNA")
            ),
            "source_label": repo_source["label"],
            "source_channel_key": repo_source["channel_key"],
            "enabled_in_app": bool(dlna_config.get("enabled")),
        }

    def refresh_package_state(self, force=False):
        snapshot = self.get_package_state_snapshot()
        should_check = force or not snapshot["latest_version_raw"] or self.needs_scheduled_check(snapshot["checked_at"])

        if not should_check:
            return snapshot

        latest_version = snapshot["latest_version_raw"]
        check_error = ""
        try:
            policy = self.get_apt_package_policy(self._package_name)
            latest_version = policy["candidate"] or policy["installed"] or latest_version
        except Exception as exc:
            check_error = str(exc)

        self._save_update_state(latest_version, time.time(), check_error)
        return self.get_package_state_snapshot()


__all__ = ["DlnaUpdateService"]
