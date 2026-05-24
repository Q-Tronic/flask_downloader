import os
import shutil


class StorageStatsService:
    def __init__(
        self,
        *,
        get_storage_config_snapshot,
        read_storage_runtime_access_state,
        format_bytes_text,
    ):
        self._get_storage_config_snapshot = get_storage_config_snapshot
        self._read_storage_runtime_access_state = read_storage_runtime_access_state
        self._format_bytes_text = format_bytes_text

    def _format_bytes(self, value):
        if value is None:
            return "nieznany"
        return self._format_bytes_text(value)

    def _build_entry(self, label, path, *, require_mount=False):
        normalized_path = os.path.abspath(str(path or "").strip() or ".")
        access = self._read_storage_runtime_access_state(normalized_path, require_mount=require_mount)
        online = bool(access.get("read_ok")) and (not require_mount or bool(access.get("is_mount")))
        total_bytes = None
        used_bytes = None
        free_bytes = None
        error = ""

        if online:
            try:
                usage = shutil.disk_usage(normalized_path)
                total_bytes = int(usage.total)
                used_bytes = int(usage.used)
                free_bytes = int(usage.free)
            except Exception as exc:
                error = str(exc or "").strip()
                online = False

        if online:
            headline = "%s wolne" % self._format_bytes_text(free_bytes)
            meta = "Zajęte: %s • Razem: %s" % (
                self._format_bytes_text(used_bytes),
                self._format_bytes_text(total_bytes),
            )
            status_label = "Online"
            status_kind = "success"
        else:
            headline = "offline"
            status_label = "Offline"
            status_kind = "error"
            detail_parts = []
            if access.get("message"):
                detail_parts.append(str(access.get("message")).strip())
            if error:
                detail_parts.append(error)
            meta = " • ".join([part for part in detail_parts if part]) or "Brak dostępu do magazynu."

        return {
            "label": str(label or "").strip(),
            "path": normalized_path,
            "online": online,
            "exists": bool(access.get("exists")),
            "is_mount": bool(access.get("is_mount")),
            "read_ok": bool(access.get("read_ok")),
            "write_ok": bool(access.get("write_ok")),
            "execute_ok": bool(access.get("execute_ok")),
            "status_label": status_label,
            "status_kind": status_kind,
            "headline": headline,
            "meta": meta,
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
            "total_text": self._format_bytes(total_bytes),
            "used_text": self._format_bytes(used_bytes),
            "free_text": self._format_bytes(free_bytes),
            "message": str(access.get("message") or error or "").strip(),
        }

    def get_state(self):
        storage_config = self._get_storage_config_snapshot()
        local_root = ((storage_config or {}).get("local") or {}).get("root")
        network_root = ((storage_config or {}).get("network") or {}).get("mount_dir")
        return {
            "local": self._build_entry("Lokalny storage", local_root, require_mount=False),
            "network": self._build_entry("Udział sieciowy", network_root, require_mount=True),
        }


__all__ = ["StorageStatsService"]
