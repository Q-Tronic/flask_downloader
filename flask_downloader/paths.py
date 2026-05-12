import os
import shutil


PACKAGE_ROOT = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(PACKAGE_ROOT, os.pardir))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

LEGACY_CONFIG_FILE = os.path.join(PROJECT_ROOT, "flask_downloader_config.json")
LEGACY_JOBS_FILE = os.path.join(PROJECT_ROOT, "flask_downloader_jobs.json")
LEGACY_USERS_FILE = os.path.join(PROJECT_ROOT, "flask_downloader_users.json")

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")


def ensure_data_layout():
    os.makedirs(DATA_DIR, exist_ok=True)

    file_pairs = (
        (LEGACY_CONFIG_FILE, CONFIG_FILE),
        (LEGACY_JOBS_FILE, JOBS_FILE),
        (LEGACY_USERS_FILE, USERS_FILE),
    )

    for legacy_path, current_path in file_pairs:
        if os.path.exists(current_path):
            continue
        if not os.path.exists(legacy_path):
            continue
        shutil.move(legacy_path, current_path)


__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "LEGACY_CONFIG_FILE",
    "LEGACY_JOBS_FILE",
    "LEGACY_USERS_FILE",
    "CONFIG_FILE",
    "JOBS_FILE",
    "USERS_FILE",
    "ensure_data_layout",
]
