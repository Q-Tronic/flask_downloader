import os
import time
from urllib.parse import quote, urlparse


class SourceMediaService:
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

    def get_download_output_ext(self, item):
        media_kind = self._normalize_storage_kind((item or {}).get("media_kind") or "video")
        source_ext = (str((item or {}).get("ext") or "").strip().lower() or "bin")
        if media_kind == "audio":
            return self._audio_download_target_codec
        return source_ext

    @staticmethod
    def get_download_intermediate_ext(item):
        source_ext = (str((item or {}).get("ext") or "").strip().lower() or "bin")
        return source_ext

    @staticmethod
    def replace_filename_extension(filename, ext):
        base = os.path.splitext(str(filename or ""))[0]
        normalized_ext = str(ext or "").strip().lstrip(".") or "bin"
        return "%s.%s" % (base, normalized_ext)

    def build_download_basename(self, title, item):
        label = item.get("label") or item.get("format_id") or "source"
        return self._safe_filename("%s_%s" % (title, label), default="video")

    def build_download_filename(self, title, item):
        ext = self.get_download_output_ext(item)
        base = self.build_download_basename(title, item)
        return "%s.%s" % (base, ext)

    def build_intermediate_download_filename(self, title, item):
        final_filename = self.build_download_filename(title, item)
        return self.replace_filename_extension(final_filename, self.get_download_intermediate_ext(item))

    @staticmethod
    def make_label(fmt):
        parts = []

        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        height = fmt.get("height")
        width = fmt.get("width")
        ext = fmt.get("ext")
        note = fmt.get("format_note") or fmt.get("resolution")
        tbr = fmt.get("tbr")
        abr = fmt.get("abr")

        if vcodec == "none" and acodec != "none":
            parts.append("Audio")

            if abr:
                try:
                    parts.append("%dk" % int(float(abr)))
                except Exception:
                    pass
            elif tbr:
                try:
                    parts.append("%dk" % int(float(tbr)))
                except Exception:
                    pass

            if ext:
                parts.append(str(ext))

            return " | ".join(parts)

        if height:
            parts.append("%sp" % height)
        elif note:
            parts.append(str(note))

        if width and height:
            parts.append("%sx%s" % (width, height))

        if tbr:
            try:
                parts.append("%dk" % int(float(tbr)))
            except Exception:
                pass

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
                }

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

                existing_score = (
                    1 if existing.get("has_audio") else 0,
                    1 if "m3u8" in str(existing.get("protocol") or "").lower() else 0,
                    1 if str(existing.get("protocol") or "").lower().startswith("http") else 0,
                    len(str(existing.get("format_id") or "")),
                )
                item_score = (
                    1 if item.get("has_audio") else 0,
                    1 if "m3u8" in protocol else 0,
                    1 if protocol.startswith("http") else 0,
                    len(str(item.get("format_id") or "")),
                )
                if item_score > existing_score:
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
                "label": self.make_label(fmt),
                "height": 0,
                "width": 0,
                "ext": fmt.get("ext") or "",
                "protocol": fmt.get("protocol") or "",
                "url": url,
                "http_headers": fmt.get("http_headers") or info.get("http_headers") or {},
                "media_kind": "audio",
                "has_audio": True,
                "download_format": format_id or "bestaudio",
                "merge_ext": (fmt.get("ext") or "m4a").lower(),
            })

        def sort_key(item):
            media_rank = 0 if item.get("media_kind") == "video" else 1
            height = item.get("height") or 0
            width = item.get("width") or 0
            return (media_rank, height, width, str(item.get("label", "")), str(item.get("format_id", "")))

        results = list(grouped_video.values()) + audio_results
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

        data = {
            "title": info.get("title") or "Nieznany tytuł",
            "page_url": info.get("webpage_url") or page_url,
            "extractor": info.get("extractor_key") or info.get("extractor") or "unknown",
            "sources": self.filter_formats(info),
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
            "page_url": result["page_url"],
            "extractor": result["extractor"],
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
                "download_filename": self.build_intermediate_download_filename(result["title"], item),
                "vlc_command": 'vlc "%s"' % proxy_url,
            })

        return output

    @staticmethod
    def find_format(result, format_id):
        for item in result["sources"]:
            if str(item["format_id"]) == str(format_id):
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

    def get_source_download_match_state(self, result, format_id, owner_username=None):
        target_item = self.find_format(result, format_id)
        target_filename = self.build_download_filename(result["title"], target_item) if target_item else ""
        media_kind = self._normalize_storage_kind((target_item or {}).get("media_kind") or "video")
        owner = self._normalize_username(
            owner_username or self._get_current_username() or self._default_admin_username
        )

        filename_map = {}
        for item in result.get("sources") or []:
            if self._normalize_storage_kind(item.get("media_kind") or "video") != media_kind:
                continue
            filename = self.build_download_filename(result["title"], item)
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
