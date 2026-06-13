"""Hotfixy runtime dla yt-dlp używanego przez aplikację."""

from __future__ import annotations

import functools
import re
from urllib.parse import urlparse

import requests


_PORNHUB_AGE_COOKIES = {
    "age_verified": "1",
    "accessAgeDisclaimerPH": "1",
    "accessAgeDisclaimerUK": "1",
    "accessPH": "1",
    "platform": "pc",
}


def _looks_like_pornhub_webpage_error(message):
    text = str(message or "").strip().lower()
    if "unable to download webpage" not in text:
        return False
    return "http error 410" in text or "http error 403" in text


def _parse_bitrate_from_url(url):
    match = re.search(r"_(\d+)[kK]_", str(url or ""))
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except Exception:
        return 0.0


def _unique_page_candidates(page_url, extractor_host, video_id):
    candidates = []
    for candidate in (
        page_url,
        "https://www.%s/view_video.php?viewkey=%s" % (extractor_host, video_id),
    ):
        cleaned = str(candidate or "").strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates


def _build_progressive_format_entry(url, *, height=0, width=0, referer="", origin=""):
    height_value = int(height or 0)
    width_value = int(width or 0)
    suffix = "%sp" % height_value if height_value > 0 else "source"
    return {
        "format_id": "ph-http-%s" % suffix,
        "format_note": suffix,
        "height": height_value,
        "width": width_value,
        "ext": "mp4",
        "protocol": urlparse(str(url or "")).scheme or "https",
        "url": str(url or ""),
        "vcodec": "avc1",
        "acodec": "aac",
        "tbr": _parse_bitrate_from_url(url),
        "http_headers": {
            "Referer": referer,
            "Origin": origin,
        },
    }


def _build_hls_format_entry(url, *, height=0, width=0, referer="", origin=""):
    height_value = int(height or 0)
    width_value = int(width or 0)
    suffix = "%sp" % height_value if height_value > 0 else "source"
    return {
        "format_id": "ph-hls-%s" % suffix,
        "format_note": suffix,
        "height": height_value,
        "width": width_value,
        "ext": "mp4",
        "protocol": "m3u8_native",
        "url": str(url or ""),
        "vcodec": "avc1",
        "acodec": "mp4a.40.2",
        "tbr": _parse_bitrate_from_url(url),
        "http_headers": {
            "Referer": referer,
            "Origin": origin,
        },
    }


def _download_pornhub_progressive_formats(session, media_url, *, headers, page_headers):
    try:
        response = session.get(media_url, headers=headers, timeout=(10, 30), allow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    if not isinstance(payload, list):
        return []

    formats = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        direct_url = item.get("videoUrl")
        if not isinstance(direct_url, str) or not direct_url.strip():
            continue
        formats.append(
            _build_progressive_format_entry(
                direct_url,
                height=item.get("height") or item.get("quality") or 0,
                width=item.get("width") or 0,
                referer=page_headers["Referer"],
                origin=page_headers["Origin"],
            )
        )
    return formats


def _extract_pornhub_with_requests(self, url, *, requests_module, user_agent, original_exc=None):
    from yt_dlp.utils import ExtractorError, int_or_none, merge_dicts, url_or_none

    mobj = self._match_valid_url(url)
    extractor_host = mobj.group("host") or "pornhub.com"
    video_id = mobj.group("id")

    session = requests_module.Session()
    session.cookies.update(_PORNHUB_AGE_COOKIES)
    request_headers = {
        "User-Agent": str(user_agent or "").strip() or "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl,en-US;q=0.9,en;q=0.8",
    }

    webpage = ""
    final_url = ""
    last_error = None

    for candidate_url in _unique_page_candidates(url, extractor_host, video_id):
        try:
            response = session.get(
                candidate_url,
                headers=request_headers,
                timeout=(10, 30),
                allow_redirects=True,
            )
            response.raise_for_status()
            webpage = str(response.text or "")
            final_url = str(response.url or candidate_url)
            if webpage:
                break
        except Exception as exc:
            last_error = exc

    if not webpage:
        if original_exc is not None:
            raise original_exc
        raise ExtractorError("Nie udało się pobrać strony PornHub: %s" % (last_error or "brak odpowiedzi"))

    error_msg = self._html_search_regex(
        (
            r'(?s)<div[^>]+class=(["\'])(?:(?!\1).)*\b(?:removed|userMessageSection)\b(?:(?!\1).)*\1[^>]*>(?P<error>.+?)</div>',
            r'(?s)<section[^>]+class=["\']noVideo["\'][^>]*>(?P<error>.+?)</section>',
        ),
        webpage,
        "error message",
        default=None,
        group="error",
    )
    if error_msg:
        error_msg = re.sub(r"\s+", " ", error_msg)
        raise ExtractorError("PornHub said: %s" % error_msg, expected=True, video_id=video_id)

    if any(
        re.search(pattern, webpage)
        for pattern in (
            r'class=["\']geoBlocked["\']',
            r'>\s*This content is unavailable in your country',
        )
    ):
        self.raise_geo_restricted()

    if self._search_regex(
        r'originPart\s*=\s*["\']([^"\']+)["\']',
        webpage,
        "redirect to homepage",
        default="",
    ) == "homepage":
        raise ExtractorError(
            "Redirected to homepage; the video may be deleted or require logging in.",
            expected=True,
            video_id=video_id,
        )

    title = self._html_search_meta("twitter:title", webpage, default=None) or self._html_search_regex(
        (
            r'(?s)<h1[^>]+class=["\']title["\'][^>]*>(?P<title>.+?)</h1>',
            r'<div[^>]+data-video-title=(["\'])(?P<title>(?:(?!\1).)+)\1',
            r'shareTitle["\']\s*[=:]\s*(["\'])(?P<title>(?:(?!\1).)+)\1',
        ),
        webpage,
        "title",
        group="title",
    )

    flashvars = self._parse_json(
        self._search_regex(
            r"var\s+flashvars_\d+\s*=\s*({.+?});",
            webpage,
            "flashvars",
            default="{}",
        ),
        video_id,
    ) or {}

    subtitle_url = url_or_none(flashvars.get("closedCaptionsFile"))
    subtitles = {}
    if subtitle_url:
        subtitles.setdefault("en", []).append({
            "url": subtitle_url,
            "ext": "srt",
        })

    thumbnail = flashvars.get("image_url")
    duration = int_or_none(flashvars.get("video_duration"))
    json_ld = self._search_json_ld(webpage, video_id, default={}) or {}
    json_ld["description"] = None

    parsed_final = urlparse(final_url or url)
    page_origin = "%s://%s" % (
        parsed_final.scheme or "https",
        parsed_final.netloc or urlparse(url).netloc,
    )
    page_headers = {
        "Referer": final_url or url,
        "Origin": page_origin,
    }

    progressive_formats_by_height = {}
    fallback_hls_formats_by_height = {}

    media_definitions = flashvars.get("mediaDefinitions")
    if isinstance(media_definitions, list):
        for definition in media_definitions:
            if not isinstance(definition, dict):
                continue

            format_url = url_or_none(definition.get("videoUrl"))
            if not format_url:
                continue

            height = int_or_none(definition.get("height") or definition.get("quality")) or 0
            width = int_or_none(definition.get("width")) or 0
            normalized_format = str(definition.get("format") or "").strip().lower()

            if "/video/get_media" in format_url:
                for item in _download_pornhub_progressive_formats(
                    session,
                    format_url,
                    headers=request_headers,
                    page_headers=page_headers,
                ):
                    item_height = int(item.get("height") or 0)
                    if item_height > 0:
                        progressive_formats_by_height[item_height] = item
                continue

            if normalized_format == "hls" or ".m3u8" in format_url:
                if height > 0 and height not in progressive_formats_by_height:
                    fallback_hls_formats_by_height[height] = _build_hls_format_entry(
                        format_url,
                        height=height,
                        width=width,
                        referer=page_headers["Referer"],
                        origin=page_headers["Origin"],
                    )
                continue

            if height > 0 and height not in progressive_formats_by_height:
                progressive_formats_by_height[height] = _build_progressive_format_entry(
                    format_url,
                    height=height,
                    width=width,
                    referer=page_headers["Referer"],
                    origin=page_headers["Origin"],
                )

    formats = list(progressive_formats_by_height.values())
    for height, item in fallback_hls_formats_by_height.items():
        if height not in progressive_formats_by_height:
            formats.append(item)

    if not formats and original_exc is not None:
        raise original_exc
    if not formats:
        raise ExtractorError("Nie znaleziono żadnych wspieranych formatów dla tego filmu.", expected=True)

    formats.sort(
        key=lambda item: (
            int(item.get("height") or 0),
            float(item.get("tbr") or 0.0),
            1 if str(item.get("protocol") or "").startswith("http") else 0,
        )
    )

    return merge_dicts({
        "id": video_id,
        "title": title,
        "thumbnail": thumbnail,
        "duration": duration,
        "formats": formats,
        "subtitles": subtitles,
        "age_limit": 18,
        "extractor": "PornHub",
        "extractor_key": "PornHub",
        "webpage_url": final_url or url,
        "original_url": url,
        "http_headers": dict(page_headers),
    }, json_ld)


def apply_ytdlp_hotfixes(ytdlp_module, *, user_agent=""):
    try:
        pornhub_module = ytdlp_module.extractor.pornhub
    except Exception:
        return

    extractor_cls = getattr(pornhub_module, "PornHubIE", None)
    if extractor_cls is None:
        return
    if getattr(extractor_cls, "_flask_downloader_patched", False):
        return

    original_real_extract = extractor_cls._real_extract

    @functools.wraps(original_real_extract)
    def patched_real_extract(self, url):
        try:
            return original_real_extract(self, url)
        except Exception as exc:
            if not _looks_like_pornhub_webpage_error(exc):
                raise
            return _extract_pornhub_with_requests(
                self,
                url,
                requests_module=requests,
                user_agent=user_agent,
                original_exc=exc,
            )

    extractor_cls._real_extract = patched_real_extract
    extractor_cls._flask_downloader_patched = True
