import json
import time

from flask import Response, stream_with_context


def encode_sse_message(*, data=None, event_name="message", retry_ms=None, comment=""):
    lines = []
    if retry_ms is not None:
        lines.append("retry: %s" % int(retry_ms))
    if comment:
        lines.append(": %s" % str(comment))
    if event_name:
        lines.append("event: %s" % str(event_name))
    if data is not None:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        for line in payload.splitlines() or ("",):
            lines.append("data: %s" % line)
    return "\n".join(lines) + "\n\n"


def create_sse_json_response(
    payload_builder,
    *,
    event_name="state",
    interval_seconds=1.5,
    retry_ms=3000,
    keepalive_seconds=15.0,
):
    def generate():
        last_serialized = None
        last_keepalive_at = time.time()
        yield encode_sse_message(retry_ms=retry_ms, comment="flask-downloader-live")

        while True:
            try:
                payload = payload_builder()
                serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if serialized != last_serialized:
                    last_serialized = serialized
                    last_keepalive_at = time.time()
                    yield encode_sse_message(event_name=event_name, data=payload)
                elif (time.time() - last_keepalive_at) >= keepalive_seconds:
                    last_keepalive_at = time.time()
                    yield encode_sse_message(comment="keepalive")
            except GeneratorExit:
                raise
            except Exception as exc:
                last_keepalive_at = time.time()
                yield encode_sse_message(
                    event_name="error",
                    data={
                        "ok": False,
                        "error": str(exc),
                    },
                )

            time.sleep(max(0.5, float(interval_seconds or 1.5)))

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    return response


__all__ = ["create_sse_json_response", "encode_sse_message"]
