def build_json_response(jsonify_fn, *, ok=True, message="", kind="success", status_code=200, **extra):
    payload = {
        "ok": bool(ok),
        "message": str(message or ""),
        "kind": str(kind or ("success" if ok else "error")),
    }
    payload.update(extra)
    response = jsonify_fn(payload)
    if status_code and status_code != 200:
        return response, status_code
    return response


def build_stateful_json_response(
    jsonify_fn,
    *,
    state_builders=None,
    ok=True,
    message="",
    kind="success",
    status_code=200,
    **extra
):
    payload = {
        "ok": bool(ok),
        "message": str(message or ""),
        "kind": str(kind or ("success" if ok else "error")),
    }

    for key, builder in (state_builders or {}).items():
        payload[key] = builder()

    payload.update(extra)
    response = jsonify_fn(payload)
    if status_code and status_code != 200:
        return response, status_code
    return response


__all__ = [
    "build_json_response",
    "build_stateful_json_response",
]
