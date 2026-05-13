import re
import time


_NATURAL_NUMBER_RE = re.compile(r"(\d+)")


def format_ts(ts):
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def format_duration(seconds):
    try:
        total = int(max(0, float(seconds or 0)))
    except Exception:
        return "nieznany"

    days, rem = divmod(total, 24 * 60 * 60)
    hours, rem = divmod(rem, 60 * 60)
    minutes, secs = divmod(rem, 60)
    parts = []

    if days:
        parts.append("%sd" % days)
    if hours:
        parts.append("%sg" % hours)
    if minutes:
        parts.append("%smin" % minutes)
    if secs or not parts:
        parts.append("%ss" % secs)

    return " ".join(parts[:3])


def build_natural_sort_key(value):
    normalized_text = str(value or "").casefold()
    parts = _NATURAL_NUMBER_RE.split(normalized_text)
    key = []

    for index, part in enumerate(parts):
        if not part:
            continue
        if index % 2 == 1 and part.isdigit():
            key.append((1, int(part)))
            continue
        key.append((0, part))

    if not key:
        key.append((0, ""))
    key.append((2, normalized_text))
    return tuple(key)


__all__ = [
    "build_natural_sort_key",
    "format_duration",
    "format_ts",
]
