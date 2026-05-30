import os
import re
import time
from urllib.parse import quote, urlparse


class SourceMediaService:
    URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

    def __init__(
        self,
        *,
        cache,
        cache_ttl,
        ytdlp_module,
        ydl_opts_factory,
        normalize_storage_kind,
        audio_download_target_codec,
        safe_filename,
        get_current_username,
        is_admin_authenticated,
        default_admin_username,
        normalize_username,
        get_user_storage_root,
        is_temporary_download_artifact_name,
        get_relative_download_path,
        format_relative_path_for_user,
    ):
        self._cache = cache
        self._cache_ttl = cache_ttl
        self._ytdlp_module = ytdlp_module
        self._ydl_opts_factory = ydl_opts_factory
        self._normalize_storage_kind = normalize_storage_kind
        self._audio_download_target_codec = audio_download_target_codec
        self._safe_filename = safe_filename
        self._get_current_username = get_current_username
        self._is_admin_authenticated = is_admin_authenticated
        self._default_admin_username = default_admin_username
        self._normalize_username = normalize_username
        self._get_user_storage_root = get_user_storage_root
        self._is_temporary_download_artifact_name = is_temporary_download_artifact_name
        self._get_relative_download_path = get_relative_download_path
        self._format_relative_path_for_user = format_relative_path_for_user

    @staticmethod
    def is_valid_http_url(url):
        try:
            parsed = urlparse(url)
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    @classmethod
    def extract_http_urls(cls, raw_text):
        text = str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
        seen = set()
        results = []

        for match in cls.URL_PATTERN.findall(text):
            candidate = str(match or "").strip().rstrip("),.;")
            if not candidate:
                continue
            if not cls.is_valid_http_url(candidate):
                continue
            dedupe_key = candidate.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(candidate)

        return results

    def get_download_output_ext(self, item):
        media_kind = self._normalize_storage_kind((item or {}).get("media_kind") or "video")
        source_ext = (str((item or {}).get("ext") or "").strip().lower() or "bin")
        if media_kind == "audio":
            return self._audio_download_target_codec
        return source_ext

    def build_live_download_format(self, item):
        media_kind = self._normalize_storage_kind((item or {}).get("media_kind") or "video")
        if media_kind == "audio":
            return "bestaudio/best"

        try:
            height = int((item or {}).get("height") or 0)
        except Exception:
            height = 0

        height_filter = "[height<=%d]" % height if height > 0 else ""
        best_video = "bestvideo%s+bestaudio" % height_filter
        best_muxed = "best%s" % height_filter
        return "%s/%s/best" % (best_video, best_muxed)

    @staticmethod
    def _merge_format_candidates(target_item, incoming_item):
        existing = list(target_item.get("_format_candidates") or [])
        seen = {
            (
                str(candidate.get("format_id") or "").strip(),
                bool(candidate.get("has_audio")),
            )
            for candidate in existing
        }

        for candidate in incoming_item.get("_format_candidates") or []:
            format_id = str(candidate.get("format_id") or "").strip()
            has_audio = bool(candidate.get("has_audio"))
            if not format_id:
                continue
            key = (format_id, has_audio)
            if key in seen:
                continue
            seen.add(key)
            existing.append({
                "format_id": format_id,
                "has_audio": has_audio,
            })

        target_item["_format_candidates"] = existing

    @staticmethod
    def _build_download_selector(item):
        candidates = []
        seen_ids = set()

        for candidate in item.get("_format_candidates") or []:
            format_id = str(candidate.get("format_id") or "").strip()
            if not format_id or format_id in seen_ids:
                continue
            seen_ids.add(format_id)
            candidates.append({
                "format_id": format_id,
                "has_audio": bool(candidate.get("has_audio")),
            })

        if not candidates:
            fallback_format_id = str(item.get("format_id") or "").strip()
            if fallback_format_id:
                candidates.append({
                    "format_id": fallback_format_id,
                    "has_audio": bool(item.get("has_audio")),
                })

        if item.get("media_kind") != "video":
            return str(item.get("format_id") or "best")

        preferred_id = str(item.get("format_id") or "").strip()
        preferred_has_audio = bool(item.get("has_audio"))
        audio_candidates = [candidate for candidate in candidates if candidate["has_audio"]]
        video_only_candidates = [candidate for candidate in candidates if not candidate["has_audio"]]

        selectors = []
        if preferred_id:
            if preferred_has_audio:
                selectors.append(preferred_id)
            else:
                selectors.append("%s+bestaudio/best" % preferred_id)

        selectors.extend(
            candidate["format_id"]
            for candidate in audio_candidates
            if candidate["format_id"] != preferred_id
        )
        selectors.extend(
            "%s+bestaudio/best" % candidate["format_id"]
            for candidate in video_only_candidates
            if candidate["format_id"] != preferred_id
        )
        if audio_candidates:
            selectors.append("best")
        else:
            selectors.append("bestvideo+bestaudio/best")

        deduped = []
        seen = set()
        for selector in selectors:
            if not selector or selector in seen:
                continue
            seen.add(selector)
            deduped.append(selector)

        return "/".join(deduped) or "best"

    @staticmethod
    def build_selection_signature(item):
        return {
            "media_kind": str((item or {}).get("media_kind") or "").strip().lower(),
            "label": str((item or {}).get("label") or "").strip(),
            "height": int((item or {}).get("height") or 0),
            "width": int((item or {}).get("width") or 0),
            "ext": str((item or {}).get("ext") or "").strip().lower(),
        }

    @staticmethod
    def get_download_intermediate_ext(item):
        source_ext = (str((item or {}).get("ext") or "").strip().lower() or "bin")
        return source_ext

    @staticmethod
    def replace_filename_extension(filename, ext):
        base = os.path.splitext(str(filename or ""))[0]
        normalized_ext = str(ext or "").strip().lstrip(".") or "bin"
        return "%s.%s" % (base, normalized_ext)

    @staticmethod
    def make_quality_label(fmt):
        try:
            height = int(fmt.get("height") or 0)
        except Exception:
            height = 0
        try:
            width = int(fmt.get("width") or 0)
        except Exception:
            width = 0

        if height >= 4320 or width >= 7680:
            return "8K"
        if height >= 2160 or width >= 3840:
            return "4K"
        if height >= 1440 or width >= 2560:
            return "2K"
        if height > 0:
            return "%sp" % height

        note = str(fmt.get("format_note") or fmt.get("resolution") or "").strip()
        if note:
            return note
        return str(fmt.get("format_id") or "Źródło")

    @staticmethod
    def _normalize_title_text(value):
        return " ".join(str(value or "").strip().split())

    @classmethod
    def _title_compare_key(cls, value):
        text = cls._normalize_title_text(value).casefold()
        for source, target in (
            ("–", "-"),
            ("—", "-"),
            ("−", "-"),
            (":", "-"),
            ("_", "-"),
        ):
            text = text.replace(source, target)
        return " ".join(text.split())

    @classmethod
    def build_download_title(cls, info):
        base_title = cls._normalize_title_text((info or {}).get("title") or "Nieznany tytuł")
        if not base_title:
            return "Nieznany tytuł"

        prefix = ""
        for candidate in (
            (info or {}).get("series"),
            (info or {}).get("playlist_title"),
            (info or {}).get("album"),
        ):
            candidate_text = cls._normalize_title_text(candidate)
            if candidate_text:
                prefix = candidate_text
                break

        if not prefix:
            return base_title

        base_key = cls._title_compare_key(base_title)
        prefix_key = cls._title_compare_key(prefix)
        if not prefix_key or base_key.startswith(prefix_key):
            return base_title

        return "%s - %s" % (prefix, base_title)

    def build_download_basename(self, title, item):
        media_kind = str((item or {}).get("media_kind") or "").strip().lower()
        if media_kind == "audio":
            return self._safe_filename(title, default="audio")
        label = item.get("label") or item.get("format_id") or "source"
        return self._safe_filename("%s_%s" % (title, label), default="video")

    def build_download_filename(self, title, item):
        ext = self.get_download_output_ext(item)
        base = self.build_download_basename(title, item)
        return "%s.%s" % (base, ext)

    def normalize_requested_download_filename(self, requested_filename, title, item):
        default_filename = self.build_download_filename(title, item)
        requested_text = str(requested_filename or "").strip()
        if not requested_text:
            return default_filename

        requested_root = os.path.splitext(requested_text)[0].strip()
        default_root = os.path.splitext(default_filename)[0].strip() or "file"
        normalized_root = self._safe_filename(requested_root or default_root, default=default_root)
        return self.replace_filename_extension(normalized_root, self.get_download_output_ext(item))

    def build_intermediate_download_filename(self, title, item):
        final_filename = self.build_download_filename(title, item)
        return self.replace_filename_extension(final_filename, self.get_download_intermediate_ext(item))

    @staticmethod
    def make_label(fmt):
        parts = []

        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        ext = fmt.get("ext")
        tbr = fmt.get("tbr")
        abr = fmt.get("abr")

        if vcodec == "none" and acodec != "none":
            return "Audio"

        quality_label = SourceMediaService.make_quality_label(fmt)
        if quality_label:
            parts.append(str(quality_label))

        if not parts and ext:
            parts.append(str(ext))

        if not parts:
            parts.append(str(fmt.get("format_id", "unknown")))

        return " | ".join(parts)

    @staticmethod
    def normalize_info(info):
        if info.get("_type") == "playlist" and info.get("entries"):
            for entry in info["entries"]:
                if entry:
                    return entry
        return info

    @staticmethod
    def get_live_status_value(info):
        return str((info or {}).get("live_status") or "").strip().lower()

    @classmethod
    def is_active_live_stream(cls, info):
        if bool((info or {}).get("is_live")):
            return True
        return cls.get_live_status_value(info) == "is_live"

    @staticmethod
    def supports_live_from_start(extractor_name):
        text = str(extractor_name or "").strip().lower()
        return any(marker in text for marker in ("youtube", "twitch", "tver"))

    @classmethod
    def describe_live_state(cls, info, extractor_name=""):
        live_status = cls.get_live_status_value(info)
        is_live_stream = cls.is_active_live_stream(info)
        supports_from_start = bool(is_live_stream and cls.supports_live_from_start(extractor_name))

        if is_live_stream:
            live_status_label = "Transmisja na żywo"
        elif live_status == "is_upcoming":
            live_status_label = "Zaplanowana transmisja"
        elif live_status in ("post_live", "was_live"):
            live_status_label = "Zakończona transmisja"
        else:
            live_status_label = ""

        return {
            "is_live_stream": is_live_stream,
            "live_status": live_status,
            "live_status_label": live_status_label,
            "supports_live_from_start": supports_from_start,
        }

    def filter_formats(self, info):
        extractor_name = str(info.get("extractor_key") or info.get("extractor") or "").strip().lower()
        allow_audio_only = extractor_name.startswith("youtube")
        grouped_video = {}
        audio_results = []
        seen_audio_keys = set()

        formats = info.get("formats") or []
        if not formats and info.get("url"):
            formats = [info]

        for fmt in formats:
            url = fmt.get("url")
            if not url:
                continue

            vcodec = fmt.get("vcodec")
            acodec = fmt.get("acodec")
            ext = (fmt.get("ext") or "").lower()
            protocol = str(fmt.get("protocol") or "").lower()
            format_id = str(fmt.get("format_id") or "")
            media_kind = "audio" if vcodec == "none" and acodec != "none" else "video"

            if media_kind == "video" and vcodec == "none":
                continue

            if media_kind == "video":
                if ext not in ("mp4", "m3u8", "webm", "mkv") and "m3u8" not in protocol and "http" not in protocol:
                    continue

                label = self.make_label(fmt)
                item = {
                    "format_id": format_id or "default",
                    "label": label,
                    "height": fmt.get("height") or 0,
                    "width": fmt.get("width") or 0,
                    "ext": fmt.get("ext") or "",
                    "protocol": fmt.get("protocol") or "",
                    "url": url,
                    "http_headers": fmt.get("http_headers") or info.get("http_headers") or {},
                    "media_kind": "video",
                    "has_audio": acodec not in (None, "", "none"),
                    "download_format": format_id or "best",
                    "merge_ext": (fmt.get("ext") or "mp4").lower(),
                    "bitrate_kbps": float(fmt.get("tbr") or 0) if fmt.get("tbr") not in (None, "", False) else 0.0,
                    "_format_candidates": [{
                        "format_id": format_id or "default",
                        "has_audio": acodec not in (None, "", "none"),
                    }],
                }
                item["live_download_format"] = self.build_live_download_format(item)

                if not item["has_audio"]:
                    item["download_format"] = "%s+bestaudio/best" % (format_id or "bestvideo")

                group_key = (
                    item["media_kind"],
                    label,
                    item["ext"],
                    item["height"],
                    item["width"],
                )
                existing = grouped_video.get(group_key)
                if existing is None:
                    grouped_video[group_key] = item
                    continue

                self._merge_format_candidates(existing, item)

                existing_score = (
                    float(existing.get("bitrate_kbps") or 0.0),
                    1 if existing.get("has_audio") else 0,
                    1 if "m3u8" in str(existing.get("protocol") or "").lower() else 0,
                    1 if str(existing.get("protocol") or "").lower().startswith("http") else 0,
                    len(str(existing.get("format_id") or "")),
                )
                item_score = (
                    float(item.get("bitrate_kbps") or 0.0),
                    1 if item.get("has_audio") else 0,
                    1 if "m3u8" in protocol else 0,
                    1 if protocol.startswith("http") else 0,
                    len(str(item.get("format_id") or "")),
                )
                if item_score > existing_score:
                    self._merge_format_candidates(item, existing)
                    grouped_video[group_key] = item
                continue

            if not allow_audio_only:
                continue

            if ext not in ("m4a", "mp3", "opus", "webm", "aac", "mp4", "ogg") and "http" not in protocol:
                continue

            audio_key = (format_id, ext, protocol)
            if audio_key in seen_audio_keys:
                continue
            seen_audio_keys.add(audio_key)

            audio_results.append({
                "format_id": format_id or "bestaudio",
                "label": "Audio",
                "height": 0,
                "width": 0,
                "ext": fmt.get("ext") or "",
                "protocol": fmt.get("protocol") or "",
                "url": url,
                "http_headers": fmt.get("http_headers") or info.get("http_headers") or {},
                "media_kind": "audio",
                "has_audio": True,
                "download_format": format_id or "bestaudio",
                "live_download_format": self.build_live_download_format({"media_kind": "audio"}),
                "merge_ext": (fmt.get("ext") or "m4a").lower(),
                "bitrate_kbps": float((fmt.get("abr") or fmt.get("tbr") or 0) or 0),
            })

        def sort_key(item):
            media_rank = 0 if item.get("media_kind") == "video" else 1
            height = item.get("height") or 0
            width = item.get("width") or 0
            return (media_rank, height, width, str(item.get("label", "")), str(item.get("format_id", "")))

        video_results = []
        for item in grouped_video.values():
            item["download_format"] = self._build_download_selector(item)
            item.pop("_format_candidates", None)
            video_results.append(item)

        results = video_results + audio_results
        results.sort(key=sort_key)
        return results

    def extract_video_data(self, page_url, force_refresh=False):
        now = time.time()

        if not force_refresh and page_url in self._cache:
            cached = self._cache[page_url]
            if now - cached["ts"] < self._cache_ttl:
                return cached["data"]

        with self._ytdlp_module.YoutubeDL(self._ydl_opts_factory()) as ydl:
            info = ydl.extract_info(page_url, download=False)

        info = self.normalize_info(info)
        extractor_name = info.get("extractor_key") or info.get("extractor") or "unknown"
        live_state = self.describe_live_state(info, extractor_name=extractor_name)

        data = {
            "title": info.get("title") or "Nieznany tytuł",
            "download_title": self.build_download_title(info),
            "page_url": info.get("webpage_url") or page_url,
            "extractor": extractor_name,
            "sources": self.filter_formats(info),
            **live_state,
        }

        self._cache[page_url] = {
            "ts": now,
            "data": data,
        }
        return data

    @staticmethod
    def build_proxy_url(page_url, format_id):
        return "/proxy?page_url=%s&format_id=%s" % (
            quote(page_url, safe=""),
            quote(format_id, safe=""),
        )

    @staticmethod
    def build_download_url(page_url, format_id):
        return "/download?page_url=%s&format_id=%s" % (
            quote(page_url, safe=""),
            quote(format_id, safe=""),
        )

    def build_result_with_proxy_urls(self, result, request_root):
        output = {
            "title": result["title"],
            "download_title": result.get("download_title") or result["title"],
            "page_url": result["page_url"],
            "extractor": result["extractor"],
            "is_live_stream": bool(result.get("is_live_stream")),
            "live_status": str(result.get("live_status") or ""),
            "live_status_label": str(result.get("live_status_label") or ""),
            "supports_live_from_start": bool(result.get("supports_live_from_start")),
            "sources": [],
        }

        base_url = request_root.rstrip("/")

        for item in result["sources"]:
            proxy_path = self.build_proxy_url(result["page_url"], item["format_id"])
            proxy_url = "%s%s" % (base_url, proxy_path)

            download_path = self.build_download_url(result["page_url"], item["format_id"])
            download_url = "%s%s" % (base_url, download_path)

            output["sources"].append({
                **item,
                "proxy_url": proxy_url,
                "download_url": download_url,
                "download_filename": self.build_intermediate_download_filename(
                    result.get("download_title") or result["title"],
                    item,
                ),
                "live_download_format": str(item.get("live_download_format") or ""),
                "vlc_command": 'vlc "%s"' % proxy_url,
                "is_live_stream": bool(result.get("is_live_stream")),
                "live_status": str(result.get("live_status") or ""),
                "live_status_label": str(result.get("live_status_label") or ""),
                "supports_live_from_start": bool(result.get("supports_live_from_start")),
            })

        return output

    @staticmethod
    def find_format(result, format_id):
        for item in result["sources"]:
            if str(item["format_id"]) == str(format_id):
                return item
        return None

    @classmethod
    def find_format_by_signature(cls, result, signature):
        requested = {
            "media_kind": str((signature or {}).get("media_kind") or "").strip().lower(),
            "label": str((signature or {}).get("label") or "").strip(),
            "height": int((signature or {}).get("height") or 0),
            "width": int((signature or {}).get("width") or 0),
            "ext": str((signature or {}).get("ext") or "").strip().lower(),
        }
        if not any(requested.values()):
            return None

        for item in result.get("sources", []):
            candidate = cls.build_selection_signature(item)
            if candidate == requested:
                return item
        return None

    @staticmethod
    def format_bytes_text(num_bytes):
        try:
            value = float(num_bytes or 0)
        except Exception:
            return "nieznany"

        if value <= 0:
            return "0 B"

        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        while value >= 1024.0 and unit_index < len(units) - 1:
            value /= 1024.0
            unit_index += 1

        precision = 0 if unit_index == 0 else 2
        return ("%0.*f %s" % (precision, value, units[unit_index])).replace(".00 ", " ")

    @staticmethod
    def get_source_bitrate(item):
        try:
            value = float((item or {}).get("bitrate_kbps") or 0)
        except Exception:
            value = 0
        if value > 0:
            return value

        label = str((item or {}).get("label") or "")
        match = re.search(r"(\d+(?:\.\d+)?)k\b", label, re.IGNORECASE)
        if not match:
            return 0.0
        try:
            return float(match.group(1))
        except Exception:
            return 0.0

    def get_source_quality_rank(self, item):
        return (
            int((item or {}).get("height") or 0),
            int((item or {}).get("width") or 0),
            self.get_source_bitrate(item),
            1 if (item or {}).get("has_audio") else 0,
        )

    @staticmethod
    def get_source_container_preference(item, preferred_media_kind="video"):
        ext = str((item or {}).get("ext") or "").lower()
        if str(preferred_media_kind or "video").lower() == "audio":
            if ext == "mp3":
                return 4
            if ext == "m4a":
                return 3
            if ext in ("aac", "opus"):
                return 2
            if ext in ("webm", "ogg"):
                return 1
            return 0

        if ext == "mp4":
            return 3
        if ext == "mkv":
            return 2
        if ext == "webm":
            return 1
        return 0

    @staticmethod
    def compare_rank_desc(left, right):
        max_length = max(len(left), len(right))
        for index in range(max_length):
            left_value = float(left[index] if index < len(left) else 0)
            right_value = float(right[index] if index < len(right) else 0)
            if left_value > right_value:
                return -1
            if left_value < right_value:
                return 1
        return 0

    @staticmethod
    def is_youtube_extractor(extractor_name):
        return "youtube" in str(extractor_name or "").strip().lower()

    def choose_best_source(self, items, preferred_media_kind="video", extractor_name=""):
        candidates = list(items or [])
        if not candidates:
            return None

        preferred_kind = str(preferred_media_kind or "video").strip().lower()
        if preferred_kind == "audio":
            audio_candidates = [
                item for item in candidates
                if str((item or {}).get("media_kind") or "video").strip().lower() == "audio"
            ]
            if audio_candidates:
                candidates = audio_candidates
            else:
                av_candidates = [
                    item for item in candidates
                    if str((item or {}).get("media_kind") or "video").strip().lower() == "video"
                    and bool((item or {}).get("has_audio"))
                ]
                if av_candidates:
                    candidates = av_candidates
        else:
            video_candidates = [
                item for item in candidates
                if str((item or {}).get("media_kind") or "video").strip().lower() == "video"
            ]
            if video_candidates:
                candidates = video_candidates

        youtube_extractor = self.is_youtube_extractor(extractor_name)

        def sort_key(item):
            media_kind = str((item or {}).get("media_kind") or "video").strip().lower()
            media_rank = 0 if media_kind == preferred_kind else 1

            if preferred_kind == "audio":
                quality_rank = (
                    self.get_source_bitrate(item),
                    1 if (item or {}).get("has_audio") else 0,
                    int((item or {}).get("height") or 0),
                    int((item or {}).get("width") or 0),
                )
            else:
                quality_rank = self.get_source_quality_rank(item)

            container_rank = self.get_source_container_preference(item, preferred_media_kind=preferred_kind)
            youtube_audio_rank = 1 if (youtube_extractor and (item or {}).get("has_audio")) else 0

            return (
                media_rank,
                tuple(-float(value) for value in quality_rank),
                -container_rank,
                -youtube_audio_rank,
                str((item or {}).get("format_id") or ""),
            )

        candidates.sort(key=sort_key)
        return candidates[0]

    def get_source_download_match_state(self, result, format_id, owner_username=None, target_filename_override=""):
        target_item = self.find_format(result, format_id)
        download_title = result.get("download_title") or result["title"]
        target_filename = str(target_filename_override or "").strip()
        if not target_filename:
            target_filename = self.build_download_filename(download_title, target_item) if target_item else ""
        media_kind = self._normalize_storage_kind((target_item or {}).get("media_kind") or "video")
        owner = self._normalize_username(
            owner_username or self._get_current_username() or self._default_admin_username
        )

        filename_map = {}
        for item in result.get("sources") or []:
            if self._normalize_storage_kind(item.get("media_kind") or "video") != media_kind:
                continue
            filename = self.build_download_filename(download_title, item)
            descriptor = {
                "format_id": str(item.get("format_id") or ""),
                "label": str(item.get("label") or item.get("format_id") or filename),
                "filename": filename,
            }
            filename_map.setdefault(filename, []).append(descriptor)

        state = {
            "target_filename": target_filename,
            "same_quality": [],
            "other_qualities": [],
            "same_quality_count": 0,
            "other_qualities_count": 0,
        }

        if not filename_map:
            return state

        root = self._get_user_storage_root(owner, media_kind)
        if not os.path.isdir(root):
            return state

        for current_root, _, filenames in os.walk(root):
            for name in filenames:
                if self._is_temporary_download_artifact_name(name) or name not in filename_map:
                    continue

                path = os.path.join(current_root, name)

                try:
                    st = os.stat(path)
                except Exception:
                    continue

                related_descriptors = filename_map.get(name) or []
                related_labels = sorted({entry["label"] for entry in related_descriptors if entry.get("label")})
                relative_path = self._get_relative_download_path(path, media_kind, owner)
                entry = {
                    "path": os.path.abspath(path),
                    "filename": name,
                    "owner_username": owner,
                    "relative_path": relative_path,
                    "size": int(st.st_size),
                    "size_text": self.format_bytes_text(st.st_size),
                    "mtime": float(st.st_mtime),
                    "mtime_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                    "matched_label": ", ".join(related_labels),
                }

                if name == target_filename:
                    state["same_quality"].append(entry)
                else:
                    state["other_qualities"].append(entry)

        state["same_quality"].sort(key=lambda item: item.get("mtime") or 0, reverse=True)
        state["other_qualities"].sort(key=lambda item: item.get("mtime") or 0, reverse=True)
        state["same_quality_count"] = len(state["same_quality"])
        state["other_qualities_count"] = len(state["other_qualities"])
        return state

    def public_source_download_match_state(self, state):
        def sanitize(items):
            output = []
            for item in items:
                relative_path = item.get("relative_path") or ""
                output.append({
                    "filename": item.get("filename") or "",
                    "relative_path": relative_path,
                    "display_path": self._format_relative_path_for_user(
                        relative_path,
                        viewer_username=self._get_current_username(),
                        is_admin=self._is_admin_authenticated(),
                    ),
                    "size": item.get("size") or 0,
                    "size_text": item.get("size_text") or "0 B",
                    "mtime_text": item.get("mtime_text") or "",
                    "matched_label": item.get("matched_label") or "",
                })
            return output

        return {
            "target_filename": state.get("target_filename") or "",
            "same_quality": sanitize(state.get("same_quality") or []),
            "other_qualities": sanitize(state.get("other_qualities") or []),
            "same_quality_count": int(state.get("same_quality_count") or 0),
            "other_qualities_count": int(state.get("other_qualities_count") or 0),
        }

    @staticmethod
    def build_m3u(title, page_url, base_url, sources, only_format_id=None):
        lines = ["#EXTM3U"]

        for item in sources:
            if only_format_id is not None and str(item["format_id"]) != str(only_format_id):
                continue

            proxy_url = "%s/proxy?page_url=%s&format_id=%s" % (
                base_url.rstrip("/"),
                quote(page_url, safe=""),
                quote(str(item["format_id"]), safe=""),
            )

            display_name = "%s [%s]" % (title, item.get("label", item.get("format_id", "source")))
            lines.append("#EXTINF:-1,%s" % display_name)
            lines.append(proxy_url)

        return "\n".join(lines) + "\n"
