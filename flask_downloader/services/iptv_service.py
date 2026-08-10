import copy
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

import requests
from werkzeug.security import check_password_hash

from flask_downloader.services.iptv_catalog_service import (
    IptvCatalogRepository,
    IptvVodScanner,
    natural_sort_key,
    stable_numeric_id,
    stable_text_id,
)
from flask_downloader.services.iptv_openwebif import OpenWebifClient, is_dvb_service_reference
from flask_downloader.stores.iptv_store import (
    default_profile_runtime,
    hash_iptv_password,
    load_iptv_store,
    normalize_iptv_store,
    normalize_iptv_username,
    normalize_profile,
    normalize_profile_id,
    write_iptv_store,
)


HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9.-]{1,253}$")


def _atomic_write_secret(path, payload):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".credential.", suffix=".tmp", dir=directory)
    try:
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _validate_host(value):
    host = str(value or "").strip()
    if not host or "://" in host or "/" in host or "\\" in host or not HOSTNAME_RE.fullmatch(host):
        raise ValueError("Podaj poprawny adres IP albo nazwę hosta dekodera.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
            raise ValueError("Podaj poprawny adres IP albo nazwę hosta dekodera.")
    return host


def _normalize_port(value, label, default):
    try:
        port = int(str(value if value is not None else default).strip())
    except Exception as exc:
        raise ValueError("%s musi być liczbą." % label) from exc
    if port < 1 or port > 65535:
        raise ValueError("%s musi mieścić się w zakresie 1-65535." % label)
    return port


def _normalize_public_base_url(value):
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path not in ("", "/"):
        raise ValueError("Publiczny adres bramki musi mieć postać http://host:port albo https://host.")
    return text


def _format_timestamp(value):
    try:
        timestamp = float(value or 0.0)
    except Exception:
        return "nigdy"
    if timestamp <= 0:
        return "nigdy"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


class IptvService:
    def __init__(self, *, store_file, runtime_dir, app_config_file, service_name="flask-downloader-iptv"):
        self.store_file = os.path.abspath(store_file)
        self.runtime_dir = os.path.abspath(runtime_dir)
        self.credentials_dir = os.path.join(self.runtime_dir, "credentials")
        self.catalogs = IptvCatalogRepository(self.runtime_dir)
        self.vod_scanner = IptvVodScanner(app_config_file)
        self.service_name = str(service_name or "flask-downloader-iptv").strip()
        self._lock = threading.RLock()
        self._refresh_locks = {}
        self._refresh_registry_lock = threading.Lock()
        self._scheduler_lock = threading.Lock()
        self._scheduler_started = False
        self._state_cache_lock = threading.Lock()
        self._service_state_cache = (0.0, None)
        self._gateway_health_cache = (0.0, None)
        self._vod_sources_cache = (0.0, None)
        os.makedirs(self.credentials_dir, exist_ok=True)
        with self._lock:
            store = load_iptv_store(self.store_file)
            write_iptv_store(self.store_file, store)

    def _credential_path(self, profile_id):
        return os.path.join(self.credentials_dir, normalize_profile_id(profile_id) + ".json")

    def _read_profile_password(self, profile_id):
        try:
            with open(self._credential_path(profile_id), "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
            return str(payload.get("password") or "")
        except Exception:
            return ""

    def _write_profile_password(self, profile_id, password):
        text = str(password or "")
        if not text:
            raise ValueError("Podaj hasło OpenWebif dla dekodera.")
        _atomic_write_secret(self._credential_path(profile_id), {"password": text, "updated_at": time.time()})

    def _load(self):
        return load_iptv_store(self.store_file)

    def _write(self, store):
        return write_iptv_store(self.store_file, store)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._load())

    def _find_profile(self, store, profile_id):
        normalized_id = normalize_profile_id(profile_id)
        for profile in store.get("profiles") or []:
            if profile.get("id") == normalized_id:
                return profile
        return None

    def _find_user(self, store, user_id=None, username=None):
        normalized_username = str(username or "").strip().casefold()
        for item in store.get("users") or []:
            if user_id and str(item.get("id") or "") == str(user_id):
                return item
            if normalized_username and str(item.get("username") or "").casefold() == normalized_username:
                return item
        return None

    def _client_for_profile(self, profile, password=None, timeout=15):
        effective_password = self._read_profile_password(profile.get("id")) if password is None else str(password)
        if not effective_password:
            raise ValueError("Brakuje zapisanego hasła OpenWebif dla profilu %s." % (profile.get("name") or profile.get("id")))
        return OpenWebifClient(
            host=profile.get("host"),
            web_port=profile.get("web_port"),
            stream_port=profile.get("stream_port"),
            username=profile.get("username") or "root",
            password=effective_password,
            timeout=timeout,
        )

    def test_profile(self, payload, *, password="", existing_profile_id=""):
        raw = dict(payload or {})
        profile_id = normalize_profile_id(raw.get("id") or existing_profile_id or raw.get("name"))
        raw["id"] = profile_id
        raw["host"] = _validate_host(raw.get("host"))
        raw["web_port"] = _normalize_port(raw.get("web_port"), "Port OpenWebif", 1234)
        raw["stream_port"] = _normalize_port(raw.get("stream_port"), "Port streamingu", 8001)
        profile = normalize_profile(raw)
        if not profile:
            raise ValueError("Nie udało się przygotować konfiguracji źródła.")
        effective_password = str(password or "") or self._read_profile_password(profile_id)
        client = self._client_for_profile(profile, password=effective_password, timeout=12)
        about = client.about()
        bouquets = client.list_bouquets(include_counts=False)

        def load_counts(bouquet):
            try:
                worker_client = self._client_for_profile(profile, password=effective_password, timeout=12)
                services = worker_client.list_services(bouquet["reference"])
                return {
                    **bouquet,
                    "channel_count": sum(1 for item in services if item.get("is_dvb")),
                    "network_count": sum(1 for item in services if item.get("is_network")),
                    "total_count": len(services),
                }
            except Exception as exc:
                return {**bouquet, "channel_count": 0, "network_count": 0, "total_count": 0, "error": str(exc)}

        counted = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(load_counts, bouquet) for bouquet in bouquets]
            for future in as_completed(futures):
                counted.append(future.result())
        counted.sort(key=lambda item: natural_sort_key(item.get("name")))
        return {
            "profile_id": profile_id,
            "about": about,
            "bouquets": counted,
            "bouquet_count": len(counted),
            "dvb_channel_count": sum(int(item.get("channel_count") or 0) for item in counted),
            "network_channel_count": sum(int(item.get("network_count") or 0) for item in counted),
        }

    def save_profile(self, payload, *, password=""):
        raw = dict(payload or {})
        profile_id = normalize_profile_id(raw.get("id") or raw.get("name"))
        raw["id"] = profile_id
        raw["host"] = _validate_host(raw.get("host"))
        raw["web_port"] = _normalize_port(raw.get("web_port"), "Port OpenWebif", 1234)
        raw["stream_port"] = _normalize_port(raw.get("stream_port"), "Port streamingu", 8001)

        with self._lock:
            store = self._load()
            existing = self._find_profile(store, profile_id)
            effective_password = str(password or "") or self._read_profile_password(profile_id)
            if not effective_password:
                raise ValueError("Najpierw podaj i sprawdź hasło OpenWebif.")
            raw["password_saved"] = True
            raw["created_at"] = (existing or {}).get("created_at") or time.time()
            raw["updated_at"] = time.time()
            raw["runtime"] = copy.deepcopy((existing or {}).get("runtime") or default_profile_runtime())
            normalized = normalize_profile(raw)
            if not normalized:
                raise ValueError("Nie udało się zapisać profilu dekodera.")

            client = self._client_for_profile(normalized, password=effective_password, timeout=12)
            client.about()
            available_bouquets = {
                str(item.get("reference") or "").strip(): str(item.get("name") or "").strip()
                for item in client.list_bouquets(include_counts=False)
                if str(item.get("reference") or "").strip()
            }
            selected_bouquets = list(normalized.get("selected_bouquets") or [])
            if not selected_bouquets:
                raise ValueError("Wybierz przynajmniej jeden bukiet kanałów.")
            missing = [
                item.get("name") or item.get("reference")
                for item in selected_bouquets
                if item.get("reference") not in available_bouquets
            ]
            if missing:
                raise ValueError("Nie znaleziono wybranych bukietów na dekoderze: %s." % ", ".join(missing[:5]))
            normalized["selected_bouquets"] = [
                {
                    "reference": item["reference"],
                    "name": available_bouquets.get(item["reference"]) or item.get("name") or "Bukiet",
                }
                for item in selected_bouquets
            ]
            if existing:
                index = store["profiles"].index(existing)
                store["profiles"][index] = normalized
            else:
                store.setdefault("profiles", []).append(normalized)
            self._write_profile_password(profile_id, effective_password)
            normalized_store = self._write(store)
        return copy.deepcopy(self._find_profile(normalized_store, profile_id))

    def delete_profile(self, profile_id):
        normalized_id = normalize_profile_id(profile_id)
        with self._lock:
            store = self._load()
            users = [item for item in store.get("users") or [] if item.get("profile_id") == normalized_id]
            if users:
                raise ValueError("Najpierw usuń konta IPTV przypisane do tego profilu.")
            previous_count = len(store.get("profiles") or [])
            store["profiles"] = [item for item in store.get("profiles") or [] if item.get("id") != normalized_id]
            if len(store["profiles"]) == previous_count:
                raise ValueError("Nie znaleziono profilu IPTV.")
            self._write(store)
            try:
                os.unlink(self._credential_path(normalized_id))
            except OSError:
                pass
            self.catalogs.remove(normalized_id)

    def save_settings(self, payload):
        raw = dict(payload or {})
        with self._lock:
            store = self._load()
            settings = dict(store.get("settings") or {})
            settings.update({
                "enabled": bool(raw.get("enabled", settings.get("enabled", True))),
                "bind_host": _validate_host(raw.get("bind_host") or settings.get("bind_host") or "0.0.0.0"),
                "port": _normalize_port(raw.get("port"), "Port bramki IPTV", settings.get("port") or 9988),
                "public_base_url": _normalize_public_base_url(raw.get("public_base_url")),
                "refresh_hour": max(0, min(23, int(raw.get("refresh_hour", settings.get("refresh_hour") or 2)))),
                "refresh_minute": max(0, min(59, int(raw.get("refresh_minute", settings.get("refresh_minute") or 0)))),
                "epg_days": max(1, min(14, int(raw.get("epg_days", settings.get("epg_days") or 7)))),
            })
            store["settings"] = settings
            return copy.deepcopy(self._write(store)["settings"])

    def create_user(self, payload):
        raw = dict(payload or {})
        username = normalize_iptv_username(raw.get("username"))
        profile_id = normalize_profile_id(raw.get("profile_id"))
        password = str(raw.get("password") or "")
        password_hash = hash_iptv_password(password)
        with self._lock:
            store = self._load()
            if not self._find_profile(store, profile_id):
                raise ValueError("Wybrany profil IPTV nie istnieje.")
            if self._find_user(store, username=username):
                raise ValueError("Konto IPTV o takim loginie już istnieje.")
            now = time.time()
            user = {
                "id": secrets.token_hex(16),
                "username": username,
                "profile_id": profile_id,
                "password_hash": password_hash,
                "enabled": bool(raw.get("enabled", True)),
                "expires_at": max(0.0, float(raw.get("expires_at") or 0.0)),
                "max_connections": max(1, min(8, int(raw.get("max_connections") or 1))),
                "vod_enabled": bool(raw.get("vod_enabled", True)),
                "allowed_category_ids": [],
                "created_at": now,
                "updated_at": now,
            }
            store.setdefault("users", []).append(user)
            normalized_store = self._write(store)
            return copy.deepcopy(self._find_user(normalized_store, user_id=user["id"]))

    def update_user(self, user_id, payload):
        raw = dict(payload or {})
        with self._lock:
            store = self._load()
            user = self._find_user(store, user_id=user_id)
            if not user:
                raise ValueError("Nie znaleziono konta IPTV.")
            next_username = normalize_iptv_username(raw.get("username") or user.get("username"))
            duplicate = self._find_user(store, username=next_username)
            if duplicate and duplicate.get("id") != user.get("id"):
                raise ValueError("Konto IPTV o takim loginie już istnieje.")
            profile_id = normalize_profile_id(raw.get("profile_id") or user.get("profile_id"))
            if not self._find_profile(store, profile_id):
                raise ValueError("Wybrany profil IPTV nie istnieje.")
            user.update({
                "username": next_username,
                "profile_id": profile_id,
                "enabled": bool(raw.get("enabled", user.get("enabled", True))),
                "expires_at": max(0.0, float(raw.get("expires_at") or 0.0)),
                "max_connections": max(1, min(8, int(raw.get("max_connections") or 1))),
                "vod_enabled": bool(raw.get("vod_enabled", user.get("vod_enabled", True))),
                "updated_at": time.time(),
            })
            password = str(raw.get("password") or "")
            if password:
                user["password_hash"] = hash_iptv_password(password)
            normalized_store = self._write(store)
            return copy.deepcopy(self._find_user(normalized_store, user_id=user_id))

    def delete_user(self, user_id):
        with self._lock:
            store = self._load()
            previous_count = len(store.get("users") or [])
            store["users"] = [item for item in store.get("users") or [] if str(item.get("id")) != str(user_id)]
            if len(store["users"]) == previous_count:
                raise ValueError("Nie znaleziono konta IPTV.")
            self._write(store)

    def verify_user(self, username, password):
        store = self.snapshot()
        user = self._find_user(store, username=username)
        if not user or not user.get("enabled", True):
            return None, None
        if float(user.get("expires_at") or 0.0) > 0 and float(user.get("expires_at")) <= time.time():
            return None, None
        if not check_password_hash(str(user.get("password_hash") or ""), str(password or "")):
            return None, None
        profile = self._find_profile(store, user.get("profile_id"))
        if not profile or not profile.get("enabled", True):
            return None, None
        return user, profile

    def _update_runtime(self, profile_id, **updates):
        with self._lock:
            store = self._load()
            profile = self._find_profile(store, profile_id)
            if not profile:
                return
            runtime = dict(profile.get("runtime") or default_profile_runtime())
            runtime.update(updates)
            profile["runtime"] = runtime
            self._write(store)

    def _build_channel_catalog(self, profile, client, previous_catalog):
        selected = list(profile.get("selected_bouquets") or [])
        if not selected:
            raise ValueError("W profilu nie wybrano żadnego bukietu kanałów.")
        categories = []
        channels = []
        seen_references = set()
        used_stream_ids = set()
        for index, bouquet in enumerate(selected, start=1):
            self._update_runtime(
                profile["id"],
                status="refreshing",
                status_label="Pobieranie kanałów",
                progress_percent=min(30.0, 5.0 + (20.0 * index / max(1, len(selected)))),
                detail="Czytam bukiet: %s" % (bouquet.get("name") or "bez nazwy"),
            )
            services = client.list_services(bouquet.get("reference"))
            if profile.get("dvb_only", True):
                services = [item for item in services if is_dvb_service_reference(item.get("reference"))]
            else:
                services = [item for item in services if item.get("is_dvb") or item.get("is_network")]
            category_id = str(stable_numeric_id(profile["id"] + ":category", bouquet.get("reference")))
            category_channels = []
            for service in services:
                reference = str(service.get("reference") or "").strip()
                if not reference or reference in seen_references:
                    continue
                seen_references.add(reference)
                stream_id = stable_numeric_id(profile["id"] + ":channel", reference)
                while stream_id in used_stream_ids:
                    stream_id += 1
                used_stream_ids.add(stream_id)
                tvg_id = "%s.%s.vlc" % (profile["id"], stable_text_id("epg", reference))
                category_channels.append({
                    "stream_id": stream_id,
                    "num": 0,
                    "name": str(service.get("name") or "Kanał bez nazwy").strip(),
                    "service_reference": reference,
                    "category_id": category_id,
                    "category_name": bouquet.get("name") or "Inne",
                    "tvg_id": tvg_id,
                    "stream_icon": "",
                    "stream_type": "live",
                    "added": int(time.time()),
                })
            if category_channels:
                categories.append({
                    "category_id": category_id,
                    "category_name": bouquet.get("name") or "Inne",
                    "parent_id": 0,
                })
                channels.extend(category_channels)

        channels.sort(key=lambda item: (natural_sort_key(item.get("category_name")), natural_sort_key(item.get("name"))))
        for number, channel in enumerate(channels, start=1):
            channel["num"] = number

        previous_epg = previous_catalog.get("epg") if isinstance(previous_catalog.get("epg"), dict) else {}
        epg = {}
        epg_errors = []
        now = int(time.time())
        max_stop = now + (int(self.snapshot().get("settings", {}).get("epg_days") or 7) * 86400)

        def load_epg(channel):
            worker_client = self._client_for_profile(profile, timeout=20)
            events = worker_client.get_epg(channel["service_reference"])
            return channel, [item for item in events if item.get("stop", 0) >= now - 3600 and item.get("start", 0) <= max_stop]

        completed = 0
        max_workers = min(6, max(1, len(channels)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(load_epg, channel): channel for channel in channels}
            for future in as_completed(future_map):
                channel = future_map[future]
                completed += 1
                try:
                    _, events = future.result()
                    epg[channel["tvg_id"]] = events
                except Exception as exc:
                    epg[channel["tvg_id"]] = list(previous_epg.get(channel["tvg_id"]) or [])
                    epg_errors.append("%s: %s" % (channel.get("name"), exc))
                if completed == len(channels) or completed % 5 == 0:
                    self._update_runtime(
                        profile["id"],
                        status="refreshing",
                        status_label="Aktualizacja EPG",
                        progress_percent=30.0 + (55.0 * completed / max(1, len(channels))),
                        detail="EPG: %s / %s kanałów" % (completed, len(channels)),
                    )
        return categories, channels, epg, epg_errors

    def refresh_profile_now(self, profile_id, _reserved_lock=None):
        normalized_id = normalize_profile_id(profile_id)
        if _reserved_lock is None:
            with self._refresh_registry_lock:
                lock = self._refresh_locks.setdefault(normalized_id, threading.Lock())
            if not lock.acquire(blocking=False):
                raise ValueError("Odświeżanie tego profilu już trwa.")
        else:
            lock = _reserved_lock
        started_at = time.time()
        try:
            self._update_runtime(
                normalized_id,
                status="refreshing",
                status_label="Łączenie z dekoderem",
                progress_percent=2.0,
                detail="Sprawdzam OpenWebif i ostatni poprawny katalog.",
                last_error="",
                refresh_started_at=started_at,
                refresh_finished_at=0.0,
                last_refresh_at=started_at,
            )
            store = self.snapshot()
            profile = self._find_profile(store, normalized_id)
            if not profile:
                raise ValueError("Profil IPTV nie istnieje.")
            if not profile.get("enabled", True):
                raise ValueError("Profil IPTV jest wyłączony.")
            client = self._client_for_profile(profile, timeout=20)
            client.about()
            previous = self.catalogs.read(normalized_id)
            categories, channels, epg, epg_errors = self._build_channel_catalog(profile, client, previous)
            self._update_runtime(
                normalized_id,
                status="refreshing",
                status_label="Indeksowanie VOD",
                progress_percent=90.0,
                detail="Sprawdzam wybrane katalogi VOD bez przenoszenia plików.",
            )
            if profile.get("vod_enabled"):
                vod_result = self.vod_scanner.scan(
                    normalized_id,
                    profile.get("vod_source_ids") or [],
                    previous_movies=previous.get("vod") or [],
                )
            else:
                vod_result = {"categories": [], "movies": [], "errors": []}
            finished_at = time.time()
            catalog = {
                "schema_version": 1,
                "profile_id": normalized_id,
                "profile_name": profile.get("name") or normalized_id,
                "generated_at": finished_at,
                "categories": categories,
                "channels": channels,
                "epg": epg,
                "vod_categories": vod_result.get("categories") or [],
                "vod": vod_result.get("movies") or [],
            }
            self.catalogs.write(normalized_id, catalog)
            warning_parts = []
            if epg_errors:
                warning_parts.append("EPG zachował poprzednie dane dla %s kanałów" % len(epg_errors))
            warning_parts.extend(vod_result.get("errors") or [])
            detail = "Kanały: %s, EPG: %s wpisów, VOD: %s plików." % (
                len(channels),
                sum(len(items) for items in epg.values()),
                len(vod_result.get("movies") or []),
            )
            if warning_parts:
                detail += " Uwagi: " + "; ".join(warning_parts[:3])
            self._update_runtime(
                normalized_id,
                status="ready",
                status_label="Katalog aktualny",
                progress_percent=100.0,
                detail=detail,
                last_refresh_at=finished_at,
                last_success_at=finished_at,
                last_error="",
                channel_count=len(channels),
                category_count=len(categories),
                epg_event_count=sum(len(items) for items in epg.values()),
                vod_count=len(vod_result.get("movies") or []),
                refresh_finished_at=finished_at,
            )
            return catalog
        except Exception as exc:
            finished_at = time.time()
            previous = self.catalogs.read(normalized_id)
            has_last_good = bool(previous.get("generated_at"))
            self._update_runtime(
                normalized_id,
                status="error",
                status_label="Błąd odświeżania",
                progress_percent=0.0,
                detail=("Zachowano ostatni poprawny katalog. " if has_last_good else "Brak wcześniejszego katalogu. ") + str(exc),
                last_refresh_at=finished_at,
                last_error=str(exc),
                refresh_finished_at=finished_at,
            )
            raise
        finally:
            lock.release()

    def start_refresh(self, profile_id=""):
        store = self.snapshot()
        profile_ids = [
            item["id"] for item in store.get("profiles") or []
            if item.get("enabled", True) and (not profile_id or item.get("id") == normalize_profile_id(profile_id))
        ]
        if profile_id and not profile_ids:
            raise ValueError("Nie znaleziono aktywnego profilu IPTV.")
        started = []
        for current_id in profile_ids:
            with self._refresh_registry_lock:
                lock = self._refresh_locks.setdefault(current_id, threading.Lock())
                if lock.locked():
                    continue
                lock.acquire()
            thread = threading.Thread(
                target=self._refresh_worker_safe,
                args=(current_id, lock),
                name="iptv-refresh-%s" % current_id,
                daemon=True,
            )
            try:
                thread.start()
                started.append(current_id)
            except Exception:
                lock.release()
                raise
        return started

    def _refresh_worker_safe(self, profile_id, reserved_lock):
        try:
            self.refresh_profile_now(profile_id, _reserved_lock=reserved_lock)
        except Exception:
            return

    def start_scheduler_once(self):
        with self._scheduler_lock:
            if self._scheduler_started:
                return
            self._scheduler_started = True
        thread = threading.Thread(target=self._scheduler_loop, name="iptv-refresh-scheduler", daemon=True)
        thread.start()

    def _scheduler_loop(self):
        while True:
            try:
                store = self.snapshot()
                settings = store.get("settings") or {}
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                if (
                    settings.get("enabled", True)
                    and now.hour == int(settings.get("refresh_hour") or 0)
                    and now.minute >= int(settings.get("refresh_minute") or 0)
                    and str(settings.get("last_scheduler_run_date") or "") != today
                ):
                    with self._lock:
                        latest = self._load()
                        latest.setdefault("settings", {})["last_scheduler_run_date"] = today
                        self._write(latest)
                    self.start_refresh()
            except Exception:
                pass
            time.sleep(30)

    def _service_state(self):
        state = {
            "service_name": self.service_name,
            "available": os.name != "nt",
            "active": False,
            "enabled": False,
            "status_label": "Niedostępna w tym środowisku" if os.name == "nt" else "Nieaktywna",
            "status_kind": "muted" if os.name == "nt" else "error",
            "main_pid": "",
            "error": "",
        }
        if os.name == "nt":
            return state
        try:
            result = subprocess.run(
                ["systemctl", "show", self.service_name, "--property=LoadState", "--property=ActiveState", "--property=SubState", "--property=MainPID", "--property=UnitFileState"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "Brak usługi IPTV.").strip())
            values = {}
            for line in result.stdout.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key] = value
            state.update({
                "available": values.get("LoadState") != "not-found",
                "active": values.get("ActiveState") == "active",
                "enabled": values.get("UnitFileState") in ("enabled", "enabled-runtime"),
                "status_label": "Aktywna" if values.get("ActiveState") == "active" else "Nieaktywna",
                "status_kind": "success" if values.get("ActiveState") == "active" else "error",
                "main_pid": values.get("MainPID") or "",
                "sub_state": values.get("SubState") or "",
            })
        except Exception as exc:
            state["error"] = str(exc)
        return state

    def _cached_service_state(self):
        now = time.time()
        with self._state_cache_lock:
            cached_at, cached = self._service_state_cache
            if cached is not None and (now - cached_at) < 3.0:
                return copy.deepcopy(cached)
        value = self._service_state()
        with self._state_cache_lock:
            self._service_state_cache = (now, copy.deepcopy(value))
        return value

    def _gateway_health(self, settings):
        port = int(settings.get("port") or 9988)
        try:
            response = requests.get("http://127.0.0.1:%s/healthz" % port, timeout=2)
            payload = response.json() if response.ok else {}
            return {
                "online": bool(response.ok and payload.get("ok")),
                "active_connections": int(payload.get("active_connections") or 0),
                "started_at": float(payload.get("started_at") or 0.0),
                "error": "" if response.ok else "HTTP %s" % response.status_code,
            }
        except Exception as exc:
            return {"online": False, "active_connections": 0, "started_at": 0.0, "error": str(exc)}

    def _cached_gateway_health(self, settings):
        now = time.time()
        with self._state_cache_lock:
            cached_at, cached = self._gateway_health_cache
            if cached is not None and (now - cached_at) < 2.0:
                return copy.deepcopy(cached)
        value = self._gateway_health(settings)
        with self._state_cache_lock:
            self._gateway_health_cache = (now, copy.deepcopy(value))
        return value

    def _cached_vod_sources(self):
        now = time.time()
        with self._state_cache_lock:
            cached_at, cached = self._vod_sources_cache
            if cached is not None and (now - cached_at) < 30.0:
                return copy.deepcopy(cached)
        value = self.vod_scanner.discover_sources()
        with self._state_cache_lock:
            self._vod_sources_cache = (now, copy.deepcopy(value))
        return value

    def invalidate_state_cache(self):
        with self._state_cache_lock:
            self._service_state_cache = (0.0, None)
            self._gateway_health_cache = (0.0, None)
            self._vod_sources_cache = (0.0, None)

    def get_page_state(self):
        store = self.snapshot()
        settings = copy.deepcopy(store.get("settings") or {})
        profiles = []
        for profile in store.get("profiles") or []:
            row = copy.deepcopy(profile)
            row["password_saved"] = bool(self._read_profile_password(profile.get("id")))
            row["last_refresh_text"] = _format_timestamp((profile.get("runtime") or {}).get("last_refresh_at"))
            row["last_success_text"] = _format_timestamp((profile.get("runtime") or {}).get("last_success_at"))
            profiles.append(row)
        users = []
        now = time.time()
        for user in store.get("users") or []:
            row = {key: copy.deepcopy(value) for key, value in user.items() if key != "password_hash"}
            expires_at = float(row.get("expires_at") or 0.0)
            row["expired"] = bool(expires_at and expires_at <= now)
            row["expires_at_text"] = _format_timestamp(expires_at) if expires_at else "bezterminowo"
            users.append(row)
        return {
            "settings": settings,
            "profiles": profiles,
            "users": users,
            "vod_sources": [
                {key: value for key, value in item.items() if key != "root"}
                for item in self._cached_vod_sources()
            ],
            "service": self._cached_service_state(),
            "gateway": self._cached_gateway_health(settings),
            "generated_at": time.time(),
        }

    def control_gateway(self, action):
        normalized = str(action or "").strip().lower()
        if normalized not in ("start", "stop", "restart"):
            raise ValueError("Nieobsługiwana akcja usługi IPTV.")
        if os.name == "nt":
            raise ValueError("Sterowanie usługą IPTV wymaga systemd.")
        systemctl = shutil.which("systemctl") or "/bin/systemctl"
        command = [systemctl, normalized, self.service_name]
        try:
            if os.geteuid() != 0:
                sudo = shutil.which("sudo")
                if sudo:
                    command = [sudo, "-n", systemctl, normalized, self.service_name]
        except Exception:
            pass
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, check=False)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "Nie udało się sterować usługą IPTV.").strip())
        self.invalidate_state_cache()
        return self._service_state()


__all__ = ["IptvService"]
