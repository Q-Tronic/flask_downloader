from flask_downloader.paths import IPTV_FILE
from flask_downloader.stores.iptv_store import load_iptv_store


_settings = load_iptv_store(IPTV_FILE).get("settings") or {}

bind = "%s:%s" % (
    str(_settings.get("bind_host") or "0.0.0.0"),
    int(_settings.get("port") or 9988),
)
worker_class = "gthread"
workers = 1
threads = 32
timeout = 0
graceful_timeout = 20
keepalive = 5
errorlog = "-"
accesslog = None
capture_output = True
