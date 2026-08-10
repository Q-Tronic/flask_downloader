import base64
import re
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests


CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
NETWORK_SERVICE_TYPES = {"4097", "5001", "5002", "8193"}
DVB_NON_TV_SERVICE_TYPES = {"0", "2", "64"}


def _node_text(node, name, default=""):
    child = node.find(name) if node is not None else None
    return str(child.text or default).strip() if child is not None else str(default)


def _parse_number(value, default=0):
    try:
        return int(float(str(value or "0").strip()))
    except Exception:
        return int(default)


def is_dvb_service_reference(reference):
    parts = str(reference or "").strip().split(":")
    if len(parts) < 3:
        return False
    return parts[0] == "1" and parts[1] == "0" and parts[2] not in DVB_NON_TV_SERVICE_TYPES


def is_network_service_reference(reference):
    service_type = (str(reference or "").strip().split(":") or [""])[0]
    return service_type in NETWORK_SERVICE_TYPES


class OpenWebifClient:
    def __init__(self, host, web_port=1234, stream_port=8001, username="root", password="", timeout=15):
        self.host = str(host or "").strip()
        self.web_port = int(web_port)
        self.stream_port = int(stream_port)
        self.username = str(username or "root").strip() or "root"
        self.password = str(password or "")
        self.timeout = max(3, int(timeout or 15))
        self.session = requests.Session()
        self.session.auth = (self.username, self.password)
        self.session.headers.update({"User-Agent": "VLC-Stream-Extractor-IPTV/1.0"})

    @property
    def base_url(self):
        return "http://%s:%s" % (self.host, self.web_port)

    def _get_xml(self, endpoint, params=None):
        response = self.session.get(
            self.base_url + endpoint,
            params=params or {},
            timeout=(5, self.timeout),
        )
        response.raise_for_status()
        raw_content = getattr(response, "content", b"") or b""
        if raw_content:
            try:
                text = raw_content.decode("utf-8")
            except UnicodeDecodeError:
                text = raw_content.decode(getattr(response, "encoding", None) or "utf-8", errors="replace")
        else:
            text = response.text or ""
        text = CONTROL_CHAR_RE.sub("", text)
        try:
            return ET.fromstring(text)
        except ET.ParseError as exc:
            raise RuntimeError("OpenWebif zwrócił nieprawidłowy XML: %s" % exc) from exc

    def about(self):
        root = self._get_xml("/web/about")
        node = root.find("e2about")
        if node is None:
            raise RuntimeError("OpenWebif nie zwrócił informacji o dekoderze.")
        tuners = []
        tuner_root = node.find("e2tunerinfo")
        for tuner in tuner_root.findall("e2nim") if tuner_root is not None else []:
            tuners.append({
                "name": _node_text(tuner, "name"),
                "type": _node_text(tuner, "type"),
                "live": _node_text(tuner, "live"),
                "recording": _node_text(tuner, "rec"),
            })
        return {
            "model": _node_text(node, "e2model"),
            "image_version": _node_text(node, "e2imageversion"),
            "enigma_version": _node_text(node, "e2enigmaversion"),
            "openwebif_version": _node_text(node, "e2webifversion"),
            "ip": _node_text(node, "e2lanip"),
            "mask": _node_text(node, "e2lanmask"),
            "current_service": _node_text(node, "e2servicename"),
            "tuners": tuners,
        }

    def list_bouquets(self, include_counts=False):
        root = self._get_xml("/web/getservices")
        bouquets = []
        for node in root.findall("e2service"):
            reference = _node_text(node, "e2servicereference")
            name = _node_text(node, "e2servicename")
            if not reference:
                continue
            bouquet = {"reference": reference, "name": name or "Bez nazwy"}
            if include_counts:
                services = self.list_services(reference)
                bouquet["channel_count"] = sum(1 for item in services if is_dvb_service_reference(item["reference"]))
                bouquet["network_count"] = sum(1 for item in services if is_network_service_reference(item["reference"]))
                bouquet["total_count"] = len(services)
            bouquets.append(bouquet)
        return bouquets

    def list_services(self, bouquet_reference):
        root = self._get_xml("/web/getservices", params={"sRef": str(bouquet_reference or "")})
        services = []
        for node in root.findall("e2service"):
            reference = _node_text(node, "e2servicereference")
            name = _node_text(node, "e2servicename")
            if not reference:
                continue
            services.append({
                "reference": reference,
                "name": name or "Kanał bez nazwy",
                "is_dvb": is_dvb_service_reference(reference),
                "is_network": is_network_service_reference(reference),
            })
        return services

    def get_epg(self, service_reference):
        root = self._get_xml("/web/epgservice", params={"sRef": str(service_reference or "")})
        events = []
        for node in root.findall("e2event"):
            start = _parse_number(_node_text(node, "e2eventstart"))
            duration = max(0, _parse_number(_node_text(node, "e2eventduration")))
            if start <= 0:
                continue
            events.append({
                "event_id": _node_text(node, "e2eventid"),
                "start": start,
                "stop": start + duration,
                "duration": duration,
                "title": _node_text(node, "e2eventtitle") or "Brak tytułu",
                "description": _node_text(node, "e2eventdescription"),
                "description_extended": _node_text(node, "e2eventdescriptionextended"),
            })
        events.sort(key=lambda item: item["start"])
        return events

    def stream_url(self, service_reference):
        encoded = quote(str(service_reference or "").strip(), safe="")
        return "http://%s:%s/%s" % (self.host, self.stream_port, encoded)

    def authorization_header(self):
        raw = (self.username + ":" + self.password).encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")


__all__ = [
    "OpenWebifClient",
    "is_dvb_service_reference",
    "is_network_service_reference",
]
