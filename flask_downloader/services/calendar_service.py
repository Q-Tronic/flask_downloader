import json
import os
import threading
import time
from datetime import date, datetime, timedelta

from flask_downloader.paths import DATA_DIR


class CalendarService:
    API_TIMEOUT_SECONDS = 8
    NAMEDAY_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
    PUBLIC_HOLIDAY_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

    def __init__(self, *, data_dir=DATA_DIR, requests_module=None):
        self._data_dir = os.path.abspath(str(data_dir or DATA_DIR))
        self._requests = requests_module
        self._cache_lock = threading.Lock()
        self._cache_file = os.path.join(self._data_dir, "calendar_cache.json")
        self._name_days_file = os.path.join(self._data_dir, "name_days_pl.json")
        self._name_days_example_file = os.path.join(self._data_dir, "name_days_pl.example.json")
        self._unusual_holidays_file = os.path.join(self._data_dir, "unusual_holidays_pl.json")
        self._unusual_holidays_example_file = os.path.join(self._data_dir, "unusual_holidays_pl.example.json")
        os.makedirs(self._data_dir, exist_ok=True)

    @staticmethod
    def _safe_int(value, default=0):
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _safe_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _normalize_name_list(value):
        if isinstance(value, list):
            names = [str(item or "").strip() for item in value if str(item or "").strip()]
            return names
        if isinstance(value, str):
            text = str(value or "").strip()
            if not text:
                return []
            return [part.strip() for part in text.split(",") if part.strip()]
        return []

    @staticmethod
    def _join_names(names):
        values = [str(item or "").strip() for item in (names or []) if str(item or "").strip()]
        if not values:
            return ""
        return ", ".join(values)

    @staticmethod
    def _normalize_holiday_names(raw_value):
        if isinstance(raw_value, dict):
            if raw_value.get("name"):
                return [str(raw_value.get("name") or "").strip()]
            return CalendarService._normalize_name_list(raw_value.get("names"))
        return CalendarService._normalize_name_list(raw_value)

    @staticmethod
    def _days_until_phrase(days_until):
        value = max(0, int(days_until or 0))
        if value == 0:
            return "dzisiaj"
        if value == 1:
            return "za 1 dzień"
        return "za %s dni" % value

    @staticmethod
    def _local_date(now_ts=None):
        local_struct = time.localtime(now_ts or time.time())
        return date(local_struct.tm_year, local_struct.tm_mon, local_struct.tm_mday)

    @staticmethod
    def _parse_iso_date(value):
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except Exception:
            return None

    @staticmethod
    def _calculate_easter(year):
        """Meeus/Jones/Butcher Gregorian algorithm."""
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        return date(year, month, day)

    def _read_json_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _read_primary_or_example_json(self, primary_path, example_path):
        payload = self._read_json_file(primary_path)
        if payload:
            return payload
        return self._read_json_file(example_path)

    def _load_cache_locked(self):
        payload = self._read_json_file(self._cache_file)
        return {
            "namedays": dict(payload.get("namedays") or {}),
            "public_holidays": dict(payload.get("public_holidays") or {}),
        }

    def _write_cache_locked(self, cache_payload):
        temp_path = self._cache_file + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as fh:
            json.dump(cache_payload, fh, ensure_ascii=False, indent=2)
        os.replace(temp_path, self._cache_file)

    def _get_nameday_overrides(self):
        raw_payload = self._read_primary_or_example_json(self._name_days_file, self._name_days_example_file)
        normalized = {}
        for raw_key, raw_value in (raw_payload or {}).items():
            key = str(raw_key or "").strip()
            if len(key) != 5 or key[2] != "-":
                continue
            if not isinstance(raw_value, dict):
                continue
            names = self._normalize_name_list(raw_value.get("names"))
            names_inflected = self._normalize_name_list(raw_value.get("names_inflected"))
            if not names and not names_inflected:
                continue
            normalized[key] = {
                "names": names,
                "names_inflected": names_inflected,
            }
        return normalized

    def _get_unusual_holidays_data(self):
        raw_payload = self._read_primary_or_example_json(self._unusual_holidays_file, self._unusual_holidays_example_file)
        normalized = {}
        for raw_key, raw_value in (raw_payload or {}).items():
            key = str(raw_key or "").strip()
            if len(key) not in (5, 10):
                continue
            if len(key) == 5 and key[2] != "-":
                continue
            if len(key) == 10 and (key[4] != "-" or key[7] != "-"):
                continue
            names = self._normalize_holiday_names(raw_value)
            if not names:
                continue
            normalized[key] = names
        return normalized

    def _fetch_nameday_names(self, month, day):
        if self._requests is None:
            return []
        url = "https://nameday.abalin.net/api/V2/date"
        response = self._requests.get(
            url,
            params={"day": int(day), "month": int(month), "country": "pl"},
            timeout=self.API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = json.loads(response.content.decode("utf-8", errors="replace"))
        names_blob = str((((payload or {}).get("data") or {}).get("pl")) or "").strip()
        if not names_blob or names_blob.lower() == "n/a":
            return []
        return [part.strip() for part in names_blob.split(",") if part.strip()]

    def _get_nameday_payload(self, target_date):
        cache_key = target_date.isoformat()
        month_day_key = target_date.strftime("%m-%d")
        overrides = self._get_nameday_overrides()
        override_entry = dict(overrides.get(month_day_key) or {})
        override_names = self._normalize_name_list(override_entry.get("names"))
        override_inflected = self._normalize_name_list(override_entry.get("names_inflected"))
        now_ts = time.time()

        with self._cache_lock:
            cache = self._load_cache_locked()
            cached_entry = dict((cache.get("namedays") or {}).get(cache_key) or {})
            cached_names = self._normalize_name_list(cached_entry.get("names"))
            cached_inflected = self._normalize_name_list(cached_entry.get("names_inflected"))
            cached_updated_at = self._safe_float(cached_entry.get("updated_at"), 0.0)
            cache_is_fresh = bool(cached_names) and (now_ts - cached_updated_at) < self.NAMEDAY_CACHE_TTL_SECONDS

            if cache_is_fresh:
                names = override_names or cached_names
                inflected = override_inflected or cached_inflected or names
                return {
                    "names": names,
                    "names_text": self._join_names(names),
                    "names_inflected": inflected,
                    "names_inflected_text": self._join_names(inflected),
                }

            fetched_names = []
            try:
                fetched_names = self._fetch_nameday_names(target_date.month, target_date.day)
            except Exception:
                fetched_names = []

            names = override_names or fetched_names or cached_names
            inflected = override_inflected or cached_inflected or names
            if names:
                cache.setdefault("namedays", {})[cache_key] = {
                    "names": names,
                    "names_inflected": inflected,
                    "updated_at": now_ts,
                }
                try:
                    self._write_cache_locked(cache)
                except Exception:
                    pass
            return {
                "names": names,
                "names_text": self._join_names(names),
                "names_inflected": inflected,
                "names_inflected_text": self._join_names(inflected),
            }

    def _fetch_public_holidays(self, year):
        if self._requests is None:
            return []
        url = "https://date.nager.at/api/v3/PublicHolidays/%s/PL" % int(year)
        response = self._requests.get(url, timeout=self.API_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = json.loads(response.content.decode("utf-8", errors="replace"))
        items = []
        for item in payload or []:
            if not isinstance(item, dict):
                continue
            holiday_date = self._parse_iso_date(item.get("date"))
            if holiday_date is None:
                continue
            name = str(item.get("localName") or item.get("name") or "").strip()
            if not name:
                continue
            types = item.get("types") or []
            if types and "Public" not in [str(entry or "").strip() for entry in types]:
                continue
            items.append({
                "date": holiday_date.isoformat(),
                "name": name,
            })
        items.sort(key=lambda entry: str(entry.get("date") or ""))
        return items

    def _build_public_holiday_fallback(self, year):
        easter = self._calculate_easter(int(year))
        holidays = [
            (date(year, 1, 1), "Nowy Rok"),
            (date(year, 1, 6), "Święto Trzech Króli"),
            (easter, "Wielkanoc"),
            (easter + timedelta(days=1), "Drugi Dzień Wielkanocy"),
            (date(year, 5, 1), "Święto Pracy"),
            (date(year, 5, 3), "Święto Narodowe Trzeciego Maja"),
            (easter + timedelta(days=49), "Zielone Świątki"),
            (easter + timedelta(days=60), "Boże Ciało"),
            (date(year, 8, 15), "Wniebowzięcie Najświętszej Maryi Panny"),
            (date(year, 11, 1), "Wszystkich Świętych"),
            (date(year, 11, 11), "Narodowe Święto Niepodległości"),
            (date(year, 12, 25), "Boże Narodzenie"),
            (date(year, 12, 26), "Drugi Dzień Bożego Narodzenia"),
        ]
        if int(year) >= 2025:
            holidays.append((date(year, 12, 24), "Wolna Wigilia"))
        return [
            {"date": holiday_date.isoformat(), "name": name}
            for holiday_date, name in sorted(holidays, key=lambda entry: entry[0])
        ]

    def _get_public_holidays_for_year(self, year):
        year_key = str(int(year))
        now_ts = time.time()
        with self._cache_lock:
            cache = self._load_cache_locked()
            cached_entry = dict((cache.get("public_holidays") or {}).get(year_key) or {})
            cached_items = list(cached_entry.get("items") or [])
            cached_updated_at = self._safe_float(cached_entry.get("updated_at"), 0.0)
            if cached_items and (now_ts - cached_updated_at) < self.PUBLIC_HOLIDAY_CACHE_TTL_SECONDS:
                return cached_items

            fetched_items = []
            try:
                fetched_items = self._fetch_public_holidays(year)
            except Exception:
                fetched_items = []

            items = fetched_items or cached_items or self._build_public_holiday_fallback(year)
            cache.setdefault("public_holidays", {})[year_key] = {
                "items": items,
                "updated_at": now_ts,
            }
            try:
                self._write_cache_locked(cache)
            except Exception:
                pass
            return items

    def _find_next_public_holiday(self, target_date):
        for year in (target_date.year, target_date.year + 1):
            for item in self._get_public_holidays_for_year(year):
                holiday_date = self._parse_iso_date(item.get("date"))
                if holiday_date is None or holiday_date < target_date:
                    continue
                days_until = (holiday_date - target_date).days
                return {
                    "name": str(item.get("name") or "").strip(),
                    "date": holiday_date.isoformat(),
                    "days_until": days_until,
                    "days_phrase": self._days_until_phrase(days_until),
                }
        return {"name": "", "date": "", "days_until": 0, "days_phrase": "brak danych"}

    def _find_next_unusual_holiday(self, target_date):
        holiday_map = self._get_unusual_holidays_data()
        for offset in range(0, 370):
            current_date = target_date + timedelta(days=offset)
            exact_key = current_date.isoformat()
            recurring_key = current_date.strftime("%m-%d")
            names = []
            for key in (exact_key, recurring_key):
                for name in holiday_map.get(key) or []:
                    normalized_name = str(name or "").strip()
                    if normalized_name and normalized_name not in names:
                        names.append(normalized_name)
            if names:
                return {
                    "name": self._join_names(names),
                    "date": current_date.isoformat(),
                    "days_until": offset,
                    "days_phrase": self._days_until_phrase(offset),
                }
        return {"name": "", "date": "", "days_until": 0, "days_phrase": "brak danych"}

    def build_erds_placeholder_values(self, now_ts=None):
        target_date = self._local_date(now_ts=now_ts)
        nameday = self._get_nameday_payload(target_date)
        public_holiday = self._find_next_public_holiday(target_date)
        unusual_holiday = self._find_next_unusual_holiday(target_date)
        nominative_text = str(nameday.get("names_text") or "").strip()
        inflected_text = str(nameday.get("names_inflected_text") or "").strip() or nominative_text
        return {
            "imieniny": nominative_text or "brak danych",
            "imieniny_odmiana": inflected_text or "brak danych",
            "swieta": str(public_holiday.get("name") or "").strip() or "brak danych",
            "dni_do_swiat": str(public_holiday.get("days_phrase") or "").strip() or "brak danych",
            "swieta_nietypowe": str(unusual_holiday.get("name") or "").strip() or "brak danych",
            "dni_do_swiat_nietypowych": str(unusual_holiday.get("days_phrase") or "").strip() or "brak danych",
        }
