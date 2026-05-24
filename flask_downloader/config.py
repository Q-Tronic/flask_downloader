import os

from flask_downloader.paths import PROJECT_ROOT


ENV_FILE = os.path.join(PROJECT_ROOT, ".env")


def load_dotenv_file(env_file=ENV_FILE):
    if not os.path.isfile(env_file):
        return

    try:
        with open(env_file, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = str(raw_line or "").strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = str(key or "").strip()
                if not key or key in os.environ:
                    continue
                value = str(value or "").strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                os.environ[key] = value
    except Exception:
        return


def read_env(name, default=""):
    value = os.environ.get(name)
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def read_env_int(name, default, min_value=None, max_value=None):
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except Exception:
        return default
    if min_value is not None and value < min_value:
        return default
    if max_value is not None and value > max_value:
        return default
    return value


load_dotenv_file()


APP_HOST = read_env("FLASK_DOWNLOADER_HOST", "0.0.0.0")
APP_PORT = read_env_int("FLASK_DOWNLOADER_PORT", 9999, min_value=1, max_value=65535)
APP_SECRET_KEY = read_env("FLASK_SECRET_KEY", "flask-downloader-admin-session")
APP_SERVICE_USER = read_env("FLASK_DOWNLOADER_SERVICE_USER", "flaskdl")
APP_SERVICE_GROUP = read_env("FLASK_DOWNLOADER_SERVICE_GROUP", APP_SERVICE_USER)
APP_SERVICE_NAME = read_env("FLASK_DOWNLOADER_SERVICE_NAME", "flask-downloader")
DLNA_SERVICE_NAME = read_env("FLASK_DOWNLOADER_DLNA_SERVICE_NAME", "flask-downloader-dlna")
RADIO_SERVICE_NAME = read_env("FLASK_DOWNLOADER_RADIO_SERVICE_NAME", "flask-downloader-radio")
RADIO_STATION_SERVICE_TEMPLATE = read_env("FLASK_DOWNLOADER_RADIO_STATION_SERVICE_TEMPLATE", "flask-downloader-radio-station@")
MOUNT_POINT = read_env("FLASK_DOWNLOADER_MOUNT_POINT", "/srv/flask_downloader/share")
DOWNLOAD_DIR = read_env("FLASK_DOWNLOADER_DOWNLOAD_DIR", os.path.join(MOUNT_POINT, "flask_downloader"))
AUDIO_DOWNLOAD_DIR = read_env("FLASK_DOWNLOADER_AUDIO_DOWNLOAD_DIR", os.path.join(MOUNT_POINT, "flask_downloader_audio"))
USER_STORAGE_ROOT = read_env("FLASK_DOWNLOADER_USER_STORAGE_ROOT", os.path.join(MOUNT_POINT, "flask_downloader_users"))
SMB_SHARE = read_env("FLASK_DOWNLOADER_SMB_SHARE", "")
SMB_CREDENTIALS_FILE = read_env("FLASK_DOWNLOADER_SMB_CREDENTIALS_FILE", "")
LOCAL_STORAGE_ROOT = read_env("FLASK_DOWNLOADER_LOCAL_STORAGE_ROOT", MOUNT_POINT)
NETWORK_STORAGE_MOUNT_DIR = read_env("FLASK_DOWNLOADER_NETWORK_STORAGE_MOUNT_DIR", MOUNT_POINT)
NETWORK_STORAGE_CREDENTIALS_FILE = read_env(
    "FLASK_DOWNLOADER_NETWORK_STORAGE_CREDENTIALS_FILE",
    SMB_CREDENTIALS_FILE or "/etc/flask-downloader/network-share.credentials",
)
NETWORK_STORAGE_HELPER = read_env(
    "FLASK_DOWNLOADER_NETWORK_STORAGE_HELPER",
    "/usr/local/lib/flask-downloader/storage-control",
)
DLNA_DEFAULT_PORT = read_env_int("FLASK_DOWNLOADER_DLNA_PORT", 49152, min_value=1024, max_value=65535)
DLNA_PREFERRED_REPO_CHANNEL = read_env("FLASK_DOWNLOADER_DLNA_CHANNEL", "latest")
REPO_OWNER = read_env("FLASK_DOWNLOADER_REPO_OWNER", "Q-Tronic")
REPO_NAME = read_env("FLASK_DOWNLOADER_REPO_NAME", "flask_downloader")
REPO_BRANCH = read_env("FLASK_DOWNLOADER_REPO_BRANCH", "main")
MAX_PARALLEL_DOWNLOADS_PER_USER = read_env_int(
    "FLASK_DOWNLOADER_MAX_PARALLEL_DOWNLOADS_PER_USER",
    3,
    min_value=1,
    max_value=20,
)


__all__ = [
    "ENV_FILE",
    "load_dotenv_file",
    "read_env",
    "read_env_int",
    "APP_HOST",
    "APP_PORT",
    "APP_SECRET_KEY",
    "APP_SERVICE_USER",
    "APP_SERVICE_GROUP",
    "APP_SERVICE_NAME",
    "DLNA_SERVICE_NAME",
    "RADIO_SERVICE_NAME",
    "RADIO_STATION_SERVICE_TEMPLATE",
    "MOUNT_POINT",
    "DOWNLOAD_DIR",
    "AUDIO_DOWNLOAD_DIR",
    "USER_STORAGE_ROOT",
    "SMB_SHARE",
    "SMB_CREDENTIALS_FILE",
    "LOCAL_STORAGE_ROOT",
    "NETWORK_STORAGE_MOUNT_DIR",
    "NETWORK_STORAGE_CREDENTIALS_FILE",
    "NETWORK_STORAGE_HELPER",
    "DLNA_DEFAULT_PORT",
    "DLNA_PREFERRED_REPO_CHANNEL",
    "REPO_OWNER",
    "REPO_NAME",
    "REPO_BRANCH",
    "MAX_PARALLEL_DOWNLOADS_PER_USER",
]
