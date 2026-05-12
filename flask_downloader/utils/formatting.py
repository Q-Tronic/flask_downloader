import time


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


__all__ = [
    "format_duration",
    "format_ts",
]
