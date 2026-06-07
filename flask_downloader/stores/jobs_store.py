import json
import os
import shutil
import tempfile
from datetime import datetime


MAX_JOBS_BACKUPS = 20


def _get_jobs_backup_dir(jobs_file):
    project_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(jobs_file)), os.pardir))
    return os.path.join(project_root, "backups", "jobs-store")


def _prune_old_backups(backup_dir):
    try:
        entries = sorted(
            (
                os.path.join(backup_dir, name)
                for name in os.listdir(backup_dir)
                if name.startswith("jobs-") and name.endswith(".json")
            ),
            key=lambda path: os.path.getmtime(path),
            reverse=True,
        )
    except Exception:
        return

    for stale_path in entries[MAX_JOBS_BACKUPS:]:
        try:
            os.remove(stale_path)
        except Exception:
            continue


def _write_atomic_json(target_path, payload):
    target_dir = os.path.dirname(os.path.abspath(target_path))
    os.makedirs(target_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".jobs-", suffix=".json", dir=target_dir, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, target_path)
    except Exception:
        try:
            os.remove(temp_path)
        except Exception:
            pass
        raise


def _backup_current_jobs_file(jobs_file):
    if not os.path.isfile(jobs_file):
        return

    backup_dir = _get_jobs_backup_dir(jobs_file)
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(backup_dir, f"jobs-{timestamp}.json")
    shutil.copy2(jobs_file, backup_path)
    _prune_old_backups(backup_dir)


def read_jobs_payload(jobs_file):
    with open(jobs_file, "r", encoding="utf-8") as fh:
        return json.load(fh) or []


def write_jobs_payload(jobs_file, payload):
    _backup_current_jobs_file(jobs_file)
    _write_atomic_json(jobs_file, payload)
