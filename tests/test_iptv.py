import json
import os
import tempfile
import unittest
from unittest import mock

from flask_downloader.iptv_gateway import ConnectionRegistry, create_gateway_app
from flask_downloader.services.iptv_catalog_service import IptvCatalogRepository, IptvVodScanner
from flask_downloader.services.iptv_openwebif import (
    OpenWebifClient,
    is_dvb_service_reference,
    is_network_service_reference,
)
from flask_downloader.services.system_service import SystemServiceHelper
from flask_downloader.stores.iptv_store import (
    default_iptv_store,
    hash_iptv_password,
    load_iptv_store,
    write_iptv_store,
)


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.content = text.encode("utf-8")
        self.encoding = "iso-8859-1"
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)


class IptvStoreTests(unittest.TestCase):
    def test_store_recovers_from_atomic_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "iptv.json")
            first = default_iptv_store()
            first["settings"]["port"] = 9988
            write_iptv_store(path, first)
            second = default_iptv_store()
            second["settings"]["port"] = 9990
            write_iptv_store(path, second)

            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{uszkodzony")

            restored = load_iptv_store(path)
            self.assertEqual(9988, restored["settings"]["port"])
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(9988, json.load(handle)["settings"]["port"])

    def test_user_password_is_hashed_and_never_stored_as_plain_text(self):
        password_hash = hash_iptv_password("Haslo-test_123")
        self.assertNotIn("Haslo-test_123", password_hash)


class OpenWebifTests(unittest.TestCase):
    def test_reference_filters_keep_tv_and_reject_radio_or_network(self):
        self.assertTrue(is_dvb_service_reference("1:0:19:1234:1:1:C00000:0:0:0:"))
        self.assertFalse(is_dvb_service_reference("1:0:2:1234:1:1:C00000:0:0:0:"))
        self.assertFalse(is_dvb_service_reference("1:64:0:0:0:0:0:0:0:0:"))
        self.assertFalse(is_dvb_service_reference("4097:0:1:0:0:0:0:0:0:0:http%3a//example"))
        self.assertTrue(is_network_service_reference("4097:0:1:0:0:0:0:0:0:0:http%3a//example"))

    def test_openwebif_xml_parsing(self):
        about_xml = """<e2abouts><e2about><e2model>TestBox</e2model><e2lanip>192.0.2.10</e2lanip><e2tunerinfo><e2nim><name>Tuner A</name><type>DVB-S2</type></e2nim></e2tunerinfo></e2about></e2abouts>"""
        bouquet_xml = """<e2servicelist><e2service><e2servicereference>1:7:1:0:0:0:0:0:0:0:</e2servicereference><e2servicename>Polskie kanały</e2servicename></e2service></e2servicelist>"""
        services_xml = """<e2servicelist>
        <e2service><e2servicereference>1:0:19:1:2:3:4:0:0:0:</e2servicereference><e2servicename>TV Test</e2servicename></e2service>
        <e2service><e2servicereference>1:0:2:2:2:3:4:0:0:0:</e2servicereference><e2servicename>Radio Test</e2servicename></e2service>
        </e2servicelist>"""

        def fake_get(url, params=None, timeout=None):
            if url.endswith("/web/about"):
                return FakeResponse(about_xml)
            if url.endswith("/web/getservices") and params and params.get("sRef"):
                return FakeResponse(services_xml)
            return FakeResponse(bouquet_xml)

        client = OpenWebifClient("192.0.2.10", password="secret")
        client.session.get = mock.Mock(side_effect=fake_get)
        self.assertEqual("TestBox", client.about()["model"])
        self.assertEqual("Polskie kanały", client.list_bouquets()[0]["name"])
        services = client.list_services("bouquet")
        self.assertTrue(services[0]["is_dvb"])
        self.assertFalse(services[1]["is_dvb"])


class CatalogTests(unittest.TestCase):
    def test_vod_scanner_indexes_only_finished_video_files(self):
        with tempfile.TemporaryDirectory() as directory:
            storage_root = os.path.join(directory, "storage")
            video_root = os.path.join(storage_root, "flask_downloader_users", "admin", "video")
            os.makedirs(video_root)
            movie_path = os.path.join(video_root, "Film 2.mp4")
            with open(movie_path, "wb") as handle:
                handle.write(b"movie")
            with open(os.path.join(video_root, "Film 3.mp4.part"), "wb") as handle:
                handle.write(b"partial")
            with open(os.path.join(video_root, "Muzyka.mp3"), "wb") as handle:
                handle.write(b"audio")
            config_path = os.path.join(directory, "config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump({"storage": {"local": {"root": storage_root}, "network": {}}}, handle)

            scanner = IptvVodScanner(config_path)
            sources = scanner.discover_sources()
            result = scanner.scan("salon", [sources[0]["id"]])
            self.assertEqual(["Film 2"], [item["name"] for item in result["movies"]])
            self.assertEqual(os.path.abspath(movie_path), result["movies"][0]["path"])


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store_path = os.path.join(self.temp.name, "iptv.json")
        self.runtime_dir = os.path.join(self.temp.name, "runtime")
        self.movie_path = os.path.join(self.temp.name, "Film Test.mp4")
        with open(self.movie_path, "wb") as handle:
            handle.write(b"0123456789")

        store = default_iptv_store()
        store["settings"]["public_base_url"] = "http://iptv.test:9988"
        store["profiles"] = [{
            "id": "salon",
            "name": "Salon",
            "host": "192.0.2.10",
            "web_port": 1234,
            "stream_port": 8001,
            "username": "root",
            "password_saved": True,
            "enabled": True,
            "dvb_only": True,
            "max_streams": 2,
            "selected_bouquets": [{"reference": "bouquet", "name": "Polskie"}],
            "vod_enabled": True,
            "vod_source_ids": [],
        }]
        store["users"] = [{
            "id": "user-1",
            "username": "salon-user",
            "profile_id": "salon",
            "password_hash": hash_iptv_password("Test-pass_123"),
            "enabled": True,
            "expires_at": 0,
            "max_connections": 1,
            "vod_enabled": True,
            "allowed_category_ids": [],
        }]
        write_iptv_store(self.store_path, store)

        repository = IptvCatalogRepository(self.runtime_dir)
        repository.write("salon", {
            "categories": [{"category_id": "10", "category_name": "Polskie", "parent_id": 0}],
            "channels": [{
                "stream_id": 1001,
                "num": 1,
                "name": "Kanał Test",
                "service_reference": "1:0:19:1:2:3:4:0:0:0:",
                "category_id": "10",
                "category_name": "Polskie",
                "tvg_id": "salon.test.vlc",
                "stream_icon": "",
                "stream_type": "live",
                "added": 1700000000,
            }],
            "epg": {"salon.test.vlc": [
                {"event_id": "", "start": 1700000000, "stop": 1700003600, "title": "Program 1", "description": "Opis 1"},
                {"event_id": "", "start": 1700003600, "stop": 1700007200, "title": "Program 2", "description": "Opis 2"},
            ]},
            "vod_categories": [{"category_id": "20", "category_name": "Filmy", "parent_id": 0}],
            "vod": [{
                "stream_id": 2001,
                "name": "Film Test",
                "category_id": "20",
                "category_name": "Filmy",
                "container_extension": "mp4",
                "path": self.movie_path,
                "added": 1700000000,
            }],
        })
        app = create_gateway_app(store_file=self.store_path, runtime_dir=self.runtime_dir)
        app.testing = True
        self.client = app.test_client()
        self.auth = {"username": "salon-user", "password": "Test-pass_123"}

    def tearDown(self):
        self.temp.cleanup()

    def test_xtream_login_categories_streams_and_epg(self):
        login = self.client.get("/player_api.php", query_string=self.auth)
        self.assertEqual(200, login.status_code)
        payload = login.get_json()
        self.assertEqual(1, payload["user_info"]["auth"])
        self.assertEqual("iptv.test", payload["server_info"]["url"])
        self.assertEqual("9988", payload["server_info"]["port"])

        categories = self.client.get("/player_api.php", query_string={**self.auth, "action": "get_live_categories"}).get_json()
        streams = self.client.get("/player_api.php", query_string={**self.auth, "action": "get_live_streams"}).get_json()
        epg = self.client.get("/player_api.php", query_string={**self.auth, "action": "get_short_epg", "stream_id": 1001}).get_json()
        self.assertEqual("Polskie", categories[0]["category_name"])
        self.assertEqual("Kanał Test", streams[0]["name"])
        epg_ids = [item["id"] for item in epg["epg_listings"]]
        self.assertEqual(2, len(set(epg_ids)))

    def test_m3u_xmltv_and_vod_range(self):
        playlist = self.client.get("/get.php", query_string={**self.auth, "type": "m3u_plus", "output": "ts"})
        self.assertEqual(200, playlist.status_code)
        self.assertIn(b"#EXTM3U", playlist.data)
        self.assertIn(b"/live/salon-user/Test-pass_123/1001.ts", playlist.data)

        xmltv = self.client.get("/xmltv.php", query_string=self.auth)
        self.assertEqual(200, xmltv.status_code)
        self.assertIn(b'<channel id="salon.test.vlc">', xmltv.data)
        self.assertIn("Program 1".encode("utf-8"), xmltv.data)

        movie = self.client.get(
            "/movie/salon-user/Test-pass_123/2001.mp4",
            headers={"Range": "bytes=2-5"},
        )
        self.assertEqual(206, movie.status_code)
        self.assertEqual(b"2345", movie.data)
        movie.close()

    def test_invalid_password_is_rejected(self):
        response = self.client.get("/player_api.php", query_string={"username": "salon-user", "password": "wrong"})
        self.assertEqual(0, response.get_json()["user_info"]["auth"])

    def test_connection_registry_enforces_user_and_profile_limits(self):
        registry = ConnectionRegistry()
        user = {"username": "test", "max_connections": 1}
        profile = {"id": "salon", "max_streams": 2}
        token, error = registry.acquire(user, profile)
        self.assertTrue(token)
        self.assertFalse(error)
        second, error = registry.acquire(user, profile)
        self.assertFalse(second)
        self.assertIn("limit", error.lower())
        registry.release(token)
        self.assertEqual(0, registry.total())


class UpdateFinalizeTests(unittest.TestCase):
    def test_finalize_script_restarts_iptv_before_main_service(self):
        fake_process = mock.Mock(pid=123)
        script_path = ""
        with mock.patch("flask_downloader.services.system_service.os.name", "posix"), mock.patch(
            "flask_downloader.services.system_service.subprocess.Popen",
            return_value=fake_process,
        ):
            result = SystemServiceHelper.schedule_systemd_service_update_finalize(
                "flask-downloader",
                additional_service_names=["flask-downloader-iptv"],
                delay_seconds=0.5,
            )
            script_path = result["script_path"]
        try:
            with open(script_path, "r", encoding="utf-8") as handle:
                script = handle.read()
            restart_position = script.index("restart flask-downloader-iptv")
            start_position = script.index("start flask-downloader")
            self.assertLess(restart_position, start_position)
        finally:
            if script_path and os.path.exists(script_path):
                os.unlink(script_path)


if __name__ == "__main__":
    unittest.main()
