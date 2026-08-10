import base64
import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from xml.etree import ElementTree as ET

import requests
from flask import Flask, Response, jsonify, request, send_file, stream_with_context
from werkzeug.security import check_password_hash

from flask_downloader.paths import CONFIG_FILE, IPTV_FILE, IPTV_RUNTIME_DIR, PROJECT_ROOT
from flask_downloader.services.iptv_catalog_service import IptvCatalogRepository, is_stable_video_file
from flask_downloader.services.iptv_openwebif import OpenWebifClient
from flask_downloader.stores.iptv_store import load_iptv_store


GATEWAY_STARTED_AT = time.time()


def _to_int(value, default=0):
    try:
        return int(str(value or default).strip())
    except Exception:
        return int(default)


def _base64_text(value):
    return base64.b64encode(str(value or "").encode("utf-8")).decode("ascii")


def _xmltv_time(timestamp):
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y%m%d%H%M%S +0000")


class ConnectionRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._connections = {}

    def acquire(self, user, profile, remote_addr=""):
        username = str(user.get("username") or "")
        profile_id = str(profile.get("id") or "")
        with self._lock:
            user_count = sum(1 for item in self._connections.values() if item["username"] == username)
            profile_count = sum(1 for item in self._connections.values() if item["profile_id"] == profile_id)
            if user_count >= max(1, _to_int(user.get("max_connections"), 1)):
                return "", "Przekroczono limit jednoczesnych połączeń dla konta."
            if profile_count >= max(1, _to_int(profile.get("max_streams"), 2)):
                return "", "Wszystkie dostępne sesje tunera tego profilu są obecnie zajęte."
            token = uuid.uuid4().hex
            self._connections[token] = {
                "username": username,
                "profile_id": profile_id,
                "remote_addr": str(remote_addr or ""),
                "started_at": time.time(),
            }
            return token, ""

    def release(self, token):
        with self._lock:
            self._connections.pop(str(token or ""), None)

    def count(self, username="", profile_id=""):
        with self._lock:
            return sum(
                1 for item in self._connections.values()
                if (not username or item["username"] == username)
                and (not profile_id or item["profile_id"] == profile_id)
            )

    def total(self):
        return self.count()


class GatewayContext:
    def __init__(self, store_file=IPTV_FILE, runtime_dir=IPTV_RUNTIME_DIR):
        self.store_file = os.path.abspath(store_file)
        self.runtime_dir = os.path.abspath(runtime_dir)
        self.catalogs = IptvCatalogRepository(self.runtime_dir)
        self.credentials_dir = os.path.join(self.runtime_dir, "credentials")
        self.connections = ConnectionRegistry()

    def store(self):
        return load_iptv_store(self.store_file)

    @staticmethod
    def find_profile(store, profile_id):
        for profile in store.get("profiles") or []:
            if str(profile.get("id") or "") == str(profile_id or ""):
                return profile
        return None

    def authenticate(self, username, password):
        store = self.store()
        if not (store.get("settings") or {}).get("enabled", True):
            return store, None, None
        requested = str(username or "").strip().casefold()
        for user in store.get("users") or []:
            if str(user.get("username") or "").casefold() != requested:
                continue
            if not user.get("enabled", True):
                return store, None, None
            expires_at = float(user.get("expires_at") or 0.0)
            if expires_at and expires_at <= time.time():
                return store, None, None
            if not check_password_hash(str(user.get("password_hash") or ""), str(password or "")):
                return store, None, None
            profile = self.find_profile(store, user.get("profile_id"))
            if not profile or not profile.get("enabled", True):
                return store, None, None
            return store, user, profile
        return store, None, None

    def read_profile_password(self, profile_id):
        path = os.path.join(self.credentials_dir, str(profile_id) + ".json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return str((json.load(handle) or {}).get("password") or "")
        except Exception:
            return ""

    def openwebif_client(self, profile):
        password = self.read_profile_password(profile.get("id"))
        if not password:
            raise RuntimeError("Brakuje poświadczeń OpenWebif dla profilu.")
        return OpenWebifClient(
            profile.get("host"),
            web_port=profile.get("web_port") or 1234,
            stream_port=profile.get("stream_port") or 8001,
            username=profile.get("username") or "root",
            password=password,
            timeout=30,
        )


def create_gateway_app(store_file=IPTV_FILE, runtime_dir=IPTV_RUNTIME_DIR):
    app = Flask("flask_downloader_iptv")
    context = GatewayContext(store_file=store_file, runtime_dir=runtime_dir)

    def public_base_url(store):
        configured = str((store.get("settings") or {}).get("public_base_url") or "").strip().rstrip("/")
        return configured or request.url_root.rstrip("/")

    def auth_payload():
        return request.args.get("username") or "", request.args.get("password") or ""

    def invalid_auth_response():
        return jsonify({"user_info": {"auth": 0, "status": "Disabled"}, "server_info": {}})

    def filtered_categories(catalog, user):
        allowed = {str(item) for item in user.get("allowed_category_ids") or []}
        categories = list(catalog.get("categories") or [])
        if allowed:
            categories = [item for item in categories if str(item.get("category_id")) in allowed]
        return categories

    def filtered_channels(catalog, user):
        allowed = {str(item) for item in user.get("allowed_category_ids") or []}
        channels = list(catalog.get("channels") or [])
        if allowed:
            channels = [item for item in channels if str(item.get("category_id")) in allowed]
        return channels

    def build_user_info(store, user, password):
        settings = store.get("settings") or {}
        base = public_base_url(store)
        parsed = urlparse(base)
        default_port = 443 if parsed.scheme == "https" else 80
        return {
            "user_info": {
                "username": user.get("username"),
                "password": str(password or ""),
                "message": "VLC Stream Extractor IPTV",
                "auth": 1,
                "status": "Active",
                "exp_date": str(int(float(user.get("expires_at") or 0.0))) if user.get("expires_at") else None,
                "is_trial": "0",
                "active_cons": str(context.connections.count(username=user.get("username"))),
                "created_at": str(int(float(user.get("created_at") or time.time()))),
                "max_connections": str(max(1, _to_int(user.get("max_connections"), 1))),
                "allowed_output_formats": ["ts"],
            },
            "server_info": {
                "url": parsed.hostname or request.host.split(":", 1)[0],
                "port": str(parsed.port or settings.get("port") or default_port),
                "https_port": "443",
                "server_protocol": parsed.scheme or "http",
                "rtmp_port": "0",
                "timezone": "Europe/Warsaw",
                "timestamp_now": int(time.time()),
                "time_now": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            },
        }

    def build_live_stream_rows(catalog, user):
        rows = []
        for channel in filtered_channels(catalog, user):
            rows.append({
                "num": _to_int(channel.get("num")),
                "name": channel.get("name") or "Kanał",
                "stream_type": "live",
                "stream_id": _to_int(channel.get("stream_id")),
                "stream_icon": channel.get("stream_icon") or "",
                "epg_channel_id": channel.get("tvg_id") or "",
                "added": str(_to_int(channel.get("added"), int(time.time()))),
                "category_id": str(channel.get("category_id") or ""),
                "custom_sid": "",
                "tv_archive": 0,
                "direct_source": "",
                "tv_archive_duration": 0,
            })
        return rows

    def build_vod_rows(catalog, user):
        if not user.get("vod_enabled", True):
            return []
        rows = []
        for index, movie in enumerate(catalog.get("vod") or [], start=1):
            rows.append({
                "num": index,
                "name": movie.get("name") or "Film",
                "stream_type": "movie",
                "stream_id": _to_int(movie.get("stream_id")),
                "stream_icon": "",
                "rating": "",
                "rating_5based": 0,
                "added": str(_to_int(movie.get("added"))),
                "category_id": str(movie.get("category_id") or ""),
                "container_extension": movie.get("container_extension") or "mp4",
                "custom_sid": "",
                "direct_source": "",
            })
        return rows

    def build_epg_listings(catalog, stream_id):
        channel = next((item for item in catalog.get("channels") or [] if _to_int(item.get("stream_id")) == _to_int(stream_id)), None)
        if not channel:
            return []
        listings = []
        now = int(time.time())
        for event in (catalog.get("epg") or {}).get(channel.get("tvg_id")) or []:
            start = _to_int(event.get("start"))
            stop = _to_int(event.get("stop"))
            listings.append({
                "id": str(event.get("event_id") or stable_epg_id(channel.get("tvg_id"), start)),
                "epg_id": channel.get("tvg_id"),
                "title": _base64_text(event.get("title")),
                "lang": "pl",
                "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start)),
                "end": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stop)),
                "description": _base64_text(event.get("description_extended") or event.get("description")),
                "channel_id": channel.get("tvg_id"),
                "start_timestamp": str(start),
                "stop_timestamp": str(stop),
                "now_playing": 1 if start <= now < stop else 0,
                "has_archive": 0,
            })
        return listings

    def stable_epg_id(tvg_id, start):
        raw = (str(tvg_id) + ":" + str(start)).encode("utf-8")
        return str(int.from_bytes(hashlib.sha256(raw).digest()[:8], "big"))

    @app.after_request
    def add_gateway_headers(response):
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        response.headers.setdefault("Access-Control-Allow-Headers", "*")
        response.headers.setdefault("Cache-Control", "no-cache, no-store, must-revalidate")
        return response

    @app.route("/healthz", methods=["GET"])
    def healthz():
        store = context.store()
        return jsonify({
            "ok": True,
            "enabled": bool((store.get("settings") or {}).get("enabled", True)),
            "started_at": GATEWAY_STARTED_AT,
            "active_connections": context.connections.total(),
            "profiles": len(store.get("profiles") or []),
        })

    @app.route("/player_api.php", methods=["GET"])
    @app.route("/panel_api.php", methods=["GET"])
    def player_api():
        username, password = auth_payload()
        store, user, profile = context.authenticate(username, password)
        if not user or not profile:
            return invalid_auth_response()
        catalog = context.catalogs.read(profile.get("id"))
        action = str(request.args.get("action") or "").strip().lower()
        if not action:
            return jsonify(build_user_info(store, user, password))
        if action == "get_live_categories":
            return jsonify(filtered_categories(catalog, user))
        if action == "get_live_streams":
            rows = build_live_stream_rows(catalog, user)
            category_id = str(request.args.get("category_id") or "").strip()
            if category_id:
                rows = [item for item in rows if str(item.get("category_id")) == category_id]
            return jsonify(rows)
        if action in ("get_short_epg", "get_simple_data_table"):
            listings = build_epg_listings(catalog, request.args.get("stream_id"))
            limit = max(0, _to_int(request.args.get("limit"), 0))
            if limit:
                listings = listings[:limit]
            return jsonify({"epg_listings": listings})
        if action == "get_vod_categories":
            return jsonify((catalog.get("vod_categories") or []) if user.get("vod_enabled", True) else [])
        if action == "get_vod_streams":
            rows = build_vod_rows(catalog, user)
            category_id = str(request.args.get("category_id") or "").strip()
            if category_id:
                rows = [item for item in rows if str(item.get("category_id")) == category_id]
            return jsonify(rows)
        if action == "get_vod_info":
            stream_id = _to_int(request.args.get("vod_id"))
            movie = next((item for item in catalog.get("vod") or [] if _to_int(item.get("stream_id")) == stream_id), None)
            if not movie or not user.get("vod_enabled", True):
                return jsonify({})
            return jsonify({
                "info": {"name": movie.get("name"), "plot": "", "duration": "", "rating": ""},
                "movie_data": {
                    "stream_id": stream_id,
                    "name": movie.get("name"),
                    "container_extension": movie.get("container_extension") or "mp4",
                },
            })
        if action in ("get_series_categories", "get_series", "get_series_info"):
            return jsonify([] if action != "get_series_info" else {})
        return jsonify([])

    @app.route("/get.php", methods=["GET"])
    def get_playlist():
        username, password = auth_payload()
        store, user, profile = context.authenticate(username, password)
        if not user or not profile:
            return Response("Błędny login lub hasło.\n", status=401, mimetype="text/plain")
        catalog = context.catalogs.read(profile.get("id"))
        base = public_base_url(store)
        xmltv_url = "%s/xmltv.php?username=%s&password=%s" % (base, quote(username), quote(password))
        lines = ['#EXTM3U x-tvg-url="%s" url-tvg="%s"' % (xmltv_url, xmltv_url)]
        for channel in filtered_channels(catalog, user):
            lines.append(
                '#EXTINF:-1 tvg-id="%s" tvg-name="%s" tvg-logo="%s" group-title="%s",%s' % (
                    str(channel.get("tvg_id") or "").replace('"', ""),
                    str(channel.get("name") or "").replace('"', ""),
                    str(channel.get("stream_icon") or "").replace('"', ""),
                    str(channel.get("category_name") or "Inne").replace('"', ""),
                    str(channel.get("name") or "Kanał"),
                )
            )
            lines.append("%s/live/%s/%s/%s.ts" % (base, quote(username), quote(password), channel.get("stream_id")))
        if user.get("vod_enabled", True):
            for movie in catalog.get("vod") or []:
                lines.append(
                    '#EXTINF:-1 tvg-id="" tvg-name="%s" group-title="VOD - %s",%s' % (
                        str(movie.get("name") or "").replace('"', ""),
                        str(movie.get("category_name") or "Filmy").replace('"', ""),
                        str(movie.get("name") or "Film"),
                    )
                )
                lines.append("%s/movie/%s/%s/%s.%s" % (
                    base,
                    quote(username),
                    quote(password),
                    movie.get("stream_id"),
                    movie.get("container_extension") or "mp4",
                ))
        response = Response("\n".join(lines) + "\n", mimetype="audio/x-mpegurl")
        response.headers["Content-Disposition"] = 'inline; filename="%s.m3u"' % profile.get("id")
        return response

    @app.route("/xmltv.php", methods=["GET"])
    def xmltv():
        username, password = auth_payload()
        _, user, profile = context.authenticate(username, password)
        if not user or not profile:
            return Response("Błędny login lub hasło.\n", status=401, mimetype="text/plain")
        catalog = context.catalogs.read(profile.get("id"))
        channels = filtered_channels(catalog, user)
        root = ET.Element("tv", {"generator-info-name": "VLC Stream Extractor"})
        allowed_tvg_ids = set()
        for channel in channels:
            tvg_id = str(channel.get("tvg_id") or "")
            allowed_tvg_ids.add(tvg_id)
            node = ET.SubElement(root, "channel", {"id": tvg_id})
            ET.SubElement(node, "display-name", {"lang": "pl"}).text = str(channel.get("name") or "Kanał")
            if channel.get("stream_icon"):
                ET.SubElement(node, "icon", {"src": str(channel.get("stream_icon"))})
        for tvg_id, events in (catalog.get("epg") or {}).items():
            if tvg_id not in allowed_tvg_ids:
                continue
            for event in events or []:
                programme = ET.SubElement(root, "programme", {
                    "start": _xmltv_time(event.get("start")),
                    "stop": _xmltv_time(event.get("stop")),
                    "channel": str(tvg_id),
                })
                ET.SubElement(programme, "title", {"lang": "pl"}).text = str(event.get("title") or "Brak tytułu")
                description = str(event.get("description_extended") or event.get("description") or "").strip()
                if description:
                    ET.SubElement(programme, "desc", {"lang": "pl"}).text = description
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return Response(payload, mimetype="application/xml")

    def stream_live_response(username, password, stream_token):
        _, user, profile = context.authenticate(username, password)
        if not user or not profile:
            return Response("Błędny login lub hasło.\n", status=401, mimetype="text/plain")
        stream_id = _to_int(str(stream_token).split(".", 1)[0])
        catalog = context.catalogs.read(profile.get("id"))
        channel = next((item for item in filtered_channels(catalog, user) if _to_int(item.get("stream_id")) == stream_id), None)
        if not channel:
            return Response("Nie znaleziono kanału.\n", status=404, mimetype="text/plain")
        connection_token, error = context.connections.acquire(user, profile, request.remote_addr)
        if not connection_token:
            return Response(error + "\n", status=429, mimetype="text/plain")
        try:
            client = context.openwebif_client(profile)
            upstream = requests.get(
                client.stream_url(channel.get("service_reference")),
                headers={
                    "Authorization": client.authorization_header(),
                    "User-Agent": "VLC-Stream-Extractor-IPTV/1.0",
                    "Accept-Encoding": "identity",
                },
                stream=True,
                timeout=(10, 60),
            )
            if upstream.status_code < 200 or upstream.status_code >= 300:
                detail = "Dekoder zwrócił HTTP %s." % upstream.status_code
                upstream.close()
                context.connections.release(connection_token)
                return Response(detail + "\n", status=502, mimetype="text/plain")
        except Exception as exc:
            context.connections.release(connection_token)
            return Response("Nie udało się uruchomić kanału: %s\n" % exc, status=502, mimetype="text/plain")

        @stream_with_context
        def generate():
            try:
                for chunk in upstream.iter_content(chunk_size=188 * 512):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()
                context.connections.release(connection_token)

        response = Response(generate(), mimetype="video/mp2t", direct_passthrough=True)
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
        return response

    @app.route("/live/<username>/<password>/<stream_token>", methods=["GET"])
    def live_stream(username, password, stream_token):
        return stream_live_response(username, password, stream_token)

    @app.route("/<username>/<password>/<stream_token>", methods=["GET"])
    def legacy_live_stream(username, password, stream_token):
        return stream_live_response(username, password, stream_token)

    @app.route("/movie/<username>/<password>/<stream_token>", methods=["GET"])
    def movie_stream(username, password, stream_token):
        _, user, profile = context.authenticate(username, password)
        if not user or not profile or not user.get("vod_enabled", True):
            return Response("Błędny login lub brak dostępu do VOD.\n", status=401, mimetype="text/plain")
        stream_id = _to_int(str(stream_token).split(".", 1)[0])
        catalog = context.catalogs.read(profile.get("id"))
        movie = next((item for item in catalog.get("vod") or [] if _to_int(item.get("stream_id")) == stream_id), None)
        path = os.path.abspath(str((movie or {}).get("path") or ""))
        if not movie or not os.path.isfile(path) or not is_stable_video_file(path):
            return Response("Nie znaleziono pliku VOD.\n", status=404, mimetype="text/plain")
        connection_token, error = context.connections.acquire(user, profile, request.remote_addr)
        if not connection_token:
            return Response(error + "\n", status=429, mimetype="text/plain")
        response = send_file(path, conditional=True, download_name=os.path.basename(path))
        response.call_on_close(lambda: context.connections.release(connection_token))
        return response

    return app


def main():
    app = create_gateway_app()
    store = load_iptv_store(IPTV_FILE)
    settings = store.get("settings") or {}
    host = str(os.environ.get("FLASK_DOWNLOADER_IPTV_HOST") or settings.get("bind_host") or "0.0.0.0")
    port = _to_int(os.environ.get("FLASK_DOWNLOADER_IPTV_PORT") or settings.get("port"), 9988)
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
