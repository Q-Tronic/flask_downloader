import json
import os


def load_app_config(
    config_file,
    default_factory,
    normalize_user_storage_root,
    normalize_download_root,
    normalize_audio_download_root,
    normalize_storage_config,
    normalize_retention_days,
    normalize_yt_dlp_update_state,
    normalize_ffmpeg_update_state,
    normalize_app_update_state,
    normalize_dlna_update_state,
    normalize_dlna_config,
):
    data = default_factory()

    try:
        if os.path.isfile(config_file):
            with open(config_file, "r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}

            data["user_storage_root"] = normalize_user_storage_root(raw.get("user_storage_root", data["user_storage_root"]))
            try:
                data["user_storage_layout_version"] = max(1, int(raw.get("user_storage_layout_version") or 1))
            except Exception:
                data["user_storage_layout_version"] = 1
            data["storage"] = normalize_storage_config(raw.get("storage", data.get("storage")))
            data["download_root"] = normalize_download_root(raw.get("download_root", data["download_root"]))
            data["audio_download_root"] = normalize_audio_download_root(raw.get("audio_download_root", data["audio_download_root"]))
            data["job_retention_days"] = normalize_retention_days(raw.get("job_retention_days", data["job_retention_days"]))
            data["yt_dlp_update_state"] = normalize_yt_dlp_update_state(raw.get("yt_dlp_update_state", data["yt_dlp_update_state"]))
            data["ffmpeg_update_state"] = normalize_ffmpeg_update_state(raw.get("ffmpeg_update_state", data["ffmpeg_update_state"]))
            data["app_update_state"] = normalize_app_update_state(raw.get("app_update_state", data["app_update_state"]))
            data["dlna_update_state"] = normalize_dlna_update_state(raw.get("dlna_update_state", data["dlna_update_state"]))
            data["dlna"] = normalize_dlna_config(raw.get("dlna", data["dlna"]))
    except Exception:
        data = default_factory()

    return data


def write_app_config(config_file, payload):
    with open(config_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
