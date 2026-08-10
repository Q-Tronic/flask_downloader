from flask import jsonify, request


def register_iptv_routes(app, deps):
    require_admin_json = deps["require_admin_json"]
    require_authenticated_page = deps["require_authenticated_page"]
    is_admin_authenticated = deps["is_admin_authenticated"]
    create_sse_json_response = deps["create_sse_json_response"]
    render_page = deps["render_page"]
    IPTV_CONTENT_TEMPLATE = deps["IPTV_CONTENT_TEMPLATE"]
    IPTV_SERVICE_NAME = deps["IPTV_SERVICE_NAME"]
    service = deps["IPTV_SERVICE"]

    def state_response(*, ok=True, message="", kind="success", status_code=200, **extra):
        payload = {
            "ok": bool(ok),
            "message": str(message or ""),
            "kind": str(kind or ("success" if ok else "error")),
            "iptv_state": service.get_page_state(),
        }
        payload.update(extra)
        response = jsonify(payload)
        return (response, status_code) if status_code != 200 else response

    def admin_error():
        return require_admin_json()

    @app.route("/iptv", methods=["GET"])
    def iptv_page():
        auth_error = require_authenticated_page("Zaloguj się, aby otworzyć panel IPTV.")
        if auth_error:
            return auth_error
        if not is_admin_authenticated():
            return render_page(
                "IPTV",
                "iptv",
                IPTV_CONTENT_TEMPLATE,
                iptv_initial_state={},
                iptv_service_name=IPTV_SERVICE_NAME,
                iptv_access_denied=True,
            ), 403
        return render_page(
            "IPTV",
            "iptv",
            IPTV_CONTENT_TEMPLATE,
            iptv_initial_state=service.get_page_state(),
            iptv_service_name=IPTV_SERVICE_NAME,
            iptv_access_denied=False,
        )

    @app.route("/api/iptv/state", methods=["GET"])
    def api_iptv_state():
        auth_error = admin_error()
        if auth_error:
            return auth_error
        return state_response()

    @app.route("/api/iptv/stream", methods=["GET"])
    def api_iptv_stream():
        auth_error = admin_error()
        if auth_error:
            return auth_error
        return create_sse_json_response(
            lambda: {"ok": True, "kind": "success", "message": "", "iptv_state": service.get_page_state()},
            interval_seconds=2.0,
            retry_ms=2500,
        )

    @app.route("/api/iptv/settings", methods=["POST"])
    def api_iptv_settings():
        auth_error = admin_error()
        if auth_error:
            return auth_error
        try:
            was_active = bool((service.get_page_state().get("service") or {}).get("active"))
            service.save_settings(request.get_json(silent=True) or {})
            if was_active:
                service.control_gateway("restart")
            return state_response(
                message="Ustawienia bramki IPTV zostały zapisane%s." % (
                    " i usługa została zrestartowana" if was_active else ""
                )
            )
        except Exception as exc:
            return state_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/iptv/profile-test", methods=["POST"])
    def api_iptv_profile_test():
        auth_error = admin_error()
        if auth_error:
            return auth_error
        payload = request.get_json(silent=True) or {}
        try:
            result = service.test_profile(
                payload,
                password=payload.get("password") or "",
                existing_profile_id=payload.get("existing_profile_id") or "",
            )
            return state_response(
                message="Połączenie z dekoderem działa. Wybierz bukiety i zapisz źródło.",
                test_result=result,
            )
        except Exception as exc:
            return state_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/iptv/profiles", methods=["POST"])
    def api_iptv_profiles():
        auth_error = admin_error()
        if auth_error:
            return auth_error
        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "save").strip().lower()
        try:
            if action == "delete":
                service.delete_profile(payload.get("profile_id"))
                return state_response(message="Źródło IPTV zostało usunięte.")
            if action != "save":
                raise ValueError("Nieobsługiwana akcja źródła IPTV.")
            profile = service.save_profile(payload, password=payload.get("password") or "")
            started = service.start_refresh(profile.get("id"))
            return state_response(
                message="Źródło zostało zapisane. Rozpoczęto budowanie listy kanałów i EPG.",
                refresh_started=bool(started),
            )
        except Exception as exc:
            return state_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/iptv/users", methods=["POST"])
    def api_iptv_users():
        auth_error = admin_error()
        if auth_error:
            return auth_error
        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "create").strip().lower()
        try:
            if action == "create":
                service.create_user(payload)
                return state_response(message="Konto IPTV zostało utworzone.")
            if action == "update":
                service.update_user(payload.get("user_id"), payload)
                return state_response(message="Konto IPTV zostało zapisane.")
            if action == "delete":
                service.delete_user(payload.get("user_id"))
                return state_response(message="Konto IPTV zostało usunięte.")
            raise ValueError("Nieobsługiwana akcja konta IPTV.")
        except Exception as exc:
            return state_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/iptv/refresh", methods=["POST"])
    def api_iptv_refresh():
        auth_error = admin_error()
        if auth_error:
            return auth_error
        payload = request.get_json(silent=True) or {}
        try:
            started = service.start_refresh(payload.get("profile_id") or "")
            message = "Rozpoczęto aktualizację list IPTV." if started else "Wybrane listy IPTV są już aktualizowane."
            return state_response(message=message, refresh_started=started)
        except Exception as exc:
            return state_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/iptv/service", methods=["POST"])
    def api_iptv_service():
        auth_error = admin_error()
        if auth_error:
            return auth_error
        payload = request.get_json(silent=True) or {}
        try:
            action = str(payload.get("action") or "").strip().lower()
            service.control_gateway(action)
            labels = {"start": "uruchomiona", "stop": "zatrzymana", "restart": "zrestartowana"}
            return state_response(message="Usługa IPTV została %s." % labels.get(action, "zaktualizowana"))
        except Exception as exc:
            return state_response(ok=False, message=str(exc), kind="error", status_code=400)


__all__ = ["register_iptv_routes"]
