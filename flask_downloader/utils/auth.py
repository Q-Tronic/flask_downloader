from flask import jsonify, redirect, request, session, url_for


def set_session_user(user):
    session["auth_username"] = str((user or {}).get("username") or "").strip()
    session["auth_role"] = str((user or {}).get("role") or "").strip()


def clear_session_user():
    session.pop("auth_username", None)
    session.pop("auth_role", None)
    session.pop("files_view_scope", None)
    session.pop("jobs_view_scope", None)


def get_current_session_username():
    return str(session.get("auth_username") or "").strip()


def get_current_session_role():
    return str(session.get("auth_role") or "").strip().lower()


def get_authenticated_user(get_user_by_username):
    username = get_current_session_username()
    if not username:
        return None
    user = get_user_by_username(username)
    if not user or not user.get("enabled", True):
        clear_session_user()
        return None
    if get_current_session_role() != str(user.get("role") or "").strip().lower():
        set_session_user(user)
    return user


def safe_next_url(value, fallback_endpoint="index"):
    candidate = str(value or "").strip()
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return url_for(fallback_endpoint)


def set_ui_flash(message, kind="success"):
    session["ui_flash"] = {
        "message": str(message),
        "kind": str(kind),
    }


def pop_ui_flash():
    return session.pop("ui_flash", None)


def wants_json_response():
    accept = str(request.headers.get("Accept") or "").lower()
    requested_with = str(request.headers.get("X-Requested-With") or "").lower()
    return "application/json" in accept or requested_with in ("fetch", "xmlhttprequest")


def require_admin_json(check_admin):
    if check_admin():
        return None
    return jsonify({"ok": False, "error": "Zaloguj się jako administrator."}), 403


def require_authenticated_json(check_authenticated):
    if check_authenticated():
        return None
    return jsonify({"ok": False, "error": "Zaloguj się, aby korzystać z aplikacji."}), 403


def require_authenticated_page(
    check_authenticated,
    wants_json_response_fn,
    require_authenticated_json_fn,
    set_ui_flash_fn,
    message="Zaloguj się, aby korzystać z aplikacji.",
    fallback_endpoint="index",
):
    if check_authenticated():
        return None
    if wants_json_response_fn():
        return require_authenticated_json_fn()
    set_ui_flash_fn(message, "error")
    return redirect(url_for(fallback_endpoint))
