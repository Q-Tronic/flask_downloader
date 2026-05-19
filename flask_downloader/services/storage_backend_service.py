import json
import os
import shutil
import subprocess


class StorageBackendService:
    def __init__(
        self,
        *,
        helper_path,
        app_service_user,
        app_service_group,
    ):
        self._helper_path = str(helper_path or "").strip()
        self._app_service_user = str(app_service_user or "").strip()
        self._app_service_group = str(app_service_group or "").strip()

    def helper_available(self):
        path = self._helper_path
        return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)

    def build_helper_payload(self, storage_config, *, password="", keep_existing_password=True, mount_now=False):
        config = dict(storage_config or {})
        network = dict(config.get("network") or {})
        payload = {
            "app_user": self._app_service_user,
            "app_group": self._app_service_group,
            "storage": {
                "active_backend": str(config.get("active_backend") or "local").strip().lower(),
                "local": dict(config.get("local") or {}),
                "network": {
                    **network,
                    "password": str(password or ""),
                    "keep_existing_password": bool(keep_existing_password),
                },
            },
            "mount_now": bool(mount_now),
        }
        return payload

    def _build_command(self, action):
        helper_path = self._helper_path
        if not helper_path:
            raise RuntimeError("Brakuje ścieżki helpera storage-control.")
        if not os.path.isfile(helper_path):
            raise RuntimeError(
                "Brakuje helpera storage-control w systemie. Uruchom ponownie instalator, aby doinstalować obsługę udziału sieciowego."
            )

        command = [helper_path, str(action or "").strip()]
        if os.name != "nt":
            try:
                if os.geteuid() != 0:
                    sudo_binary = shutil.which("sudo")
                    if sudo_binary:
                        command = [sudo_binary, "-n", helper_path, str(action or "").strip()]
            except Exception:
                pass
        return command

    def run_helper(self, action, payload=None, *, timeout=120):
        completed_process = subprocess.run(
            self._build_command(action),
            input=json.dumps(payload or {}, ensure_ascii=False),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )

        stdout_text = str(completed_process.stdout or "").strip()
        stderr_text = str(completed_process.stderr or "").strip()
        response_data = {}
        if stdout_text:
            try:
                response_data = json.loads(stdout_text)
            except Exception:
                response_data = {}

        if completed_process.returncode != 0:
            detail = str(response_data.get("message") or stderr_text or stdout_text or "").strip()
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
                    "Brakuje uprawnień do obsługi udziału sieciowego z poziomu panelu WWW. Uruchom ponownie instalator albo sprawdź regułę sudoers dla użytkownika usługi."
                )
            raise RuntimeError(detail or "Helper storage-control zakończył się błędem.")

        return response_data if isinstance(response_data, dict) else {}

    def test_network_config(self, storage_config, *, password="", keep_existing_password=True):
        payload = self.build_helper_payload(
            storage_config,
            password=password,
            keep_existing_password=keep_existing_password,
            mount_now=False,
        )
        return self.run_helper("test-cifs", payload, timeout=90)

    def configure_network_storage(self, storage_config, *, password="", keep_existing_password=True, mount_now=False):
        payload = self.build_helper_payload(
            storage_config,
            password=password,
            keep_existing_password=keep_existing_password,
            mount_now=mount_now,
        )
        return self.run_helper("configure-cifs", payload, timeout=120)

    def mount_network_storage(self, storage_config):
        payload = self.build_helper_payload(storage_config, mount_now=True)
        return self.run_helper("mount-cifs", payload, timeout=90)

    def unmount_network_storage(self, storage_config):
        payload = self.build_helper_payload(storage_config, mount_now=False)
        return self.run_helper("unmount-cifs", payload, timeout=90)


__all__ = ["StorageBackendService"]
