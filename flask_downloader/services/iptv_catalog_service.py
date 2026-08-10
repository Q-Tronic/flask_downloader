import hashlib
import json
import os
import re
import tempfile
import time


IPTV_VIDEO_EXTENSIONS = {
    ".3gp", ".avi", ".flv", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4",
    ".mpeg", ".mpg", ".mts", ".ogv", ".ts", ".webm", ".wmv",
}
IPTV_TEMP_MARKERS = (".part", ".ytdl", ".temp.")


def stable_numeric_id(namespace, value):
    digest = hashlib.sha256((str(namespace) + "\x00" + str(value)).encode("utf-8")).digest()
    return 1000 + (int.from_bytes(digest[:7], "big") % 2000000000)


def stable_text_id(namespace, value):
    return hashlib.sha1((str(namespace) + "\x00" + str(value)).encode("utf-8")).hexdigest()[:20]


def natural_sort_key(value):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(value or ""))]


def is_stable_video_file(path):
    name = os.path.basename(str(path or "")).lower()
    if not name or any(marker in name for marker in IPTV_TEMP_MARKERS):
        return False
    if re.search(r"\.f\d+\.[^.]+$", name):
        return False
    return os.path.splitext(name)[1].lower() in IPTV_VIDEO_EXTENSIONS


def _atomic_write_json(path, payload):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".catalog.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


class IptvCatalogRepository:
    def __init__(self, runtime_dir):
        self.runtime_dir = os.path.abspath(runtime_dir)

    def profile_dir(self, profile_id):
        return os.path.join(self.runtime_dir, "profiles", str(profile_id))

    def catalog_path(self, profile_id):
        return os.path.join(self.profile_dir(profile_id), "catalog.json")

    def write(self, profile_id, payload):
        normalized = dict(payload or {})
        normalized["schema_version"] = 1
        normalized["profile_id"] = str(profile_id)
        normalized.setdefault("generated_at", time.time())
        _atomic_write_json(self.catalog_path(profile_id), normalized)
        return normalized

    def read(self, profile_id):
        path = self.catalog_path(profile_id)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {
            "schema_version": 1,
            "profile_id": str(profile_id),
            "generated_at": 0.0,
            "categories": [],
            "channels": [],
            "epg": {},
            "vod_categories": [],
            "vod": [],
        }

    def remove(self, profile_id):
        path = self.catalog_path(profile_id)
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except Exception:
            pass


class IptvVodScanner:
    def __init__(self, config_file):
        self.config_file = os.path.abspath(config_file)

    def _read_app_config(self):
        try:
            with open(self.config_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _storage_roots(self):
        config = self._read_app_config()
        storage = config.get("storage") if isinstance(config.get("storage"), dict) else {}
        local = storage.get("local") if isinstance(storage.get("local"), dict) else {}
        network = storage.get("network") if isinstance(storage.get("network"), dict) else {}
        candidates = {
            "local": str(local.get("root") or "").strip(),
            "network": str(network.get("mount_dir") or "").strip(),
        }
        return {key: os.path.abspath(value) for key, value in candidates.items() if value}

    def discover_sources(self):
        result = []
        for storage_id, root in self._storage_roots().items():
            user_root = os.path.join(root, "flask_downloader_users")
            if os.path.isdir(user_root):
                try:
                    owners = sorted(os.listdir(user_root), key=natural_sort_key)
                except OSError:
                    owners = []
                for owner in owners:
                    video_root = os.path.join(user_root, owner, "video")
                    if os.path.isdir(video_root):
                        result.append({
                            "id": "%s:user:%s" % (storage_id, owner),
                            "label": "%s / pliki użytkownika %s" % (
                                "Lokalny storage" if storage_id == "local" else "Udział sieciowy",
                                owner,
                            ),
                            "root": video_root,
                            "category": "Pliki %s" % owner,
                            "storage_id": storage_id,
                            "kind": "user",
                        })
            dlna_root = os.path.join(root, "flask_downloader_dlna")
            if os.path.isdir(dlna_root):
                try:
                    collections = sorted(os.listdir(dlna_root), key=natural_sort_key)
                except OSError:
                    collections = []
                for collection in collections:
                    collection_root = os.path.join(dlna_root, collection)
                    if os.path.isdir(collection_root):
                        result.append({
                            "id": "%s:dlna:%s" % (storage_id, collection),
                            "label": "%s / bukiet DLNA %s" % (
                                "Lokalny storage" if storage_id == "local" else "Udział sieciowy",
                                collection,
                            ),
                            "root": collection_root,
                            "category": collection,
                            "storage_id": storage_id,
                            "kind": "dlna",
                        })
        return result

    def scan(self, profile_id, selected_source_ids, previous_movies=None):
        selected = {str(item or "").strip() for item in (selected_source_ids or []) if str(item or "").strip()}
        available_sources = {item["id"]: item for item in self.discover_sources()}
        previous_by_source = {}
        for movie in previous_movies or []:
            previous_by_source.setdefault(str(movie.get("source_id") or ""), []).append(movie)

        movies = []
        errors = []
        category_map = {}
        for source_id in sorted(selected, key=natural_sort_key):
            source = available_sources.get(source_id)
            if not source:
                errors.append("Źródło VOD %s jest chwilowo niedostępne; zachowano poprzedni indeks." % source_id)
                movies.extend(previous_by_source.get(source_id) or [])
                continue
            category_id = str(stable_numeric_id(profile_id + ":vod-category", source_id))
            category_map[category_id] = source["category"]
            try:
                paths = []
                for current_root, _, file_names in os.walk(source["root"]):
                    for file_name in file_names:
                        path = os.path.join(current_root, file_name)
                        if is_stable_video_file(path):
                            paths.append(path)
                paths.sort(key=lambda item: natural_sort_key(os.path.relpath(item, source["root"])))
                for path in paths[:20000]:
                    relative = os.path.relpath(path, source["root"]).replace("\\", "/")
                    extension = os.path.splitext(path)[1].lower().lstrip(".") or "mp4"
                    movie_id = stable_numeric_id(profile_id + ":vod", source_id + ":" + relative.casefold())
                    try:
                        size = max(0, int(os.path.getsize(path)))
                    except OSError:
                        size = 0
                    movies.append({
                        "stream_id": movie_id,
                        "name": os.path.splitext(os.path.basename(path))[0],
                        "category_id": category_id,
                        "category_name": source["category"],
                        "container_extension": extension,
                        "path": os.path.abspath(path),
                        "relative_path": relative,
                        "source_id": source_id,
                        "size": size,
                        "added": int(os.path.getmtime(path)) if os.path.exists(path) else 0,
                    })
            except OSError as exc:
                errors.append("Nie udało się odczytać VOD %s: %s" % (source["label"], exc))
                movies.extend(previous_by_source.get(source_id) or [])

        movies.sort(key=lambda item: (natural_sort_key(item.get("category_name")), natural_sort_key(item.get("name"))))
        categories = [
            {"category_id": category_id, "category_name": name, "parent_id": 0}
            for category_id, name in sorted(category_map.items(), key=lambda item: natural_sort_key(item[1]))
        ]
        return {
            "sources": list(available_sources.values()),
            "categories": categories,
            "movies": movies,
            "errors": errors,
        }


__all__ = [
    "IPTV_VIDEO_EXTENSIONS",
    "IptvCatalogRepository",
    "IptvVodScanner",
    "is_stable_video_file",
    "natural_sort_key",
    "stable_numeric_id",
    "stable_text_id",
]
