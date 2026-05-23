from flask import Response, jsonify, redirect, request, url_for


def register_dlna_routes(app, deps):
    is_admin_authenticated = deps["is_admin_authenticated"]
    wants_json_response = deps["wants_json_response"]
    require_admin_json = deps["require_admin_json"]
    create_sse_json_response = deps["create_sse_json_response"]
    set_ui_flash = deps["set_ui_flash"]
    render_page = deps["render_page"]
    DLNA_CONTENT_TEMPLATE = deps["DLNA_CONTENT_TEMPLATE"]
    get_dlna_page_state = deps["get_dlna_page_state"]
    DLNA_SERVICE_NAME = deps["DLNA_SERVICE_NAME"]
    DLNA_ALL_COLLECTION_NAME = deps["DLNA_ALL_COLLECTION_NAME"]
    read_text_log_file_for_browser = deps["read_text_log_file_for_browser"]
    DLNA_LOG_FILE = deps["DLNA_LOG_FILE"]
    DLNA_LOG_BROWSER_MAX_BYTES = deps["DLNA_LOG_BROWSER_MAX_BYTES"]
    build_dlna_collection_library_results = deps["build_dlna_collection_library_results"]
    update_dlna_general_settings = deps["update_dlna_general_settings"]
    build_dlna_json_response = deps["build_dlna_json_response"]
    refresh_dlna_package_state = deps["refresh_dlna_package_state"]
    sync_dlna_runtime_safe = deps["sync_dlna_runtime_safe"]
    start_maintenance_task = deps["start_maintenance_task"]
    install_or_update_dlna_server = deps["install_or_update_dlna_server"]
    parse_boolean_flag = deps["parse_boolean_flag"]
    set_dlna_service_enabled = deps["set_dlna_service_enabled"]
    restart_dlna_service_now = deps["restart_dlna_service_now"]
    sync_dlna_runtime = deps["sync_dlna_runtime"]
    create_dlna_collection = deps["create_dlna_collection"]
    update_dlna_collection = deps["update_dlna_collection"]
    delete_dlna_collection = deps["delete_dlna_collection"]
    create_dlna_client = deps["create_dlna_client"]
    update_dlna_client = deps["update_dlna_client"]
    delete_dlna_client = deps["delete_dlna_client"]
    create_dlna_media_rule = deps["create_dlna_media_rule"]
    update_dlna_media_rule = deps["update_dlna_media_rule"]
    bulk_assign_dlna_collection_items = deps["bulk_assign_dlna_collection_items"]
    delete_dlna_media_rule = deps["delete_dlna_media_rule"]

    @app.route("/dlna", methods=["GET"])
    def dlna_page():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby wejść do konfiguracji DLNA.", "error")
            return redirect(url_for("index"))

        return render_page(
            "DLNA",
            "dlna",
            DLNA_CONTENT_TEMPLATE,
            dlna_initial_state=get_dlna_page_state(),
            dlna_service_name=DLNA_SERVICE_NAME,
            dlna_all_collection_name=DLNA_ALL_COLLECTION_NAME,
        )

    @app.route("/logs-dlna", methods=["GET"])
    def dlna_logs_page():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby podejrzeć log DLNA.", "error")
            return redirect(url_for("index"))

        body = read_text_log_file_for_browser(DLNA_LOG_FILE, max_bytes=DLNA_LOG_BROWSER_MAX_BYTES)
        response = Response(body, content_type="text/plain; charset=utf-8")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/dlna/state", methods=["GET"])
    def api_dlna_state():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        return jsonify({
            "ok": True,
            "state": get_dlna_page_state(),
        })

    @app.route("/api/dlna/stream", methods=["GET"])
    def api_dlna_stream():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        return create_sse_json_response(
            lambda: {
                "ok": True,
                "state": get_dlna_page_state(),
            },
            interval_seconds=1.5,
            retry_ms=2500,
        )

    @app.route("/api/dlna/library", methods=["GET"])
    def api_dlna_library():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        query = str(request.args.get("query") or "").strip()
        collection_id = str(request.args.get("collection_id") or "").strip()
        mode = str(request.args.get("mode") or "").strip()
        try:
            limit = max(20, min(500, int(str(request.args.get("limit") or "200").strip())))
        except Exception:
            limit = 200
        results = build_dlna_collection_library_results(
            collection_id=collection_id,
            query=query,
            mode=mode,
            limit=limit,
        )

        return jsonify({
            "ok": True,
            "results": results,
        })

    @app.route("/api/dlna/settings", methods=["POST"])
    def api_dlna_settings():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        payload = request.get_json(silent=True) or {}
        try:
            update_dlna_general_settings(
                server_name=payload.get("server_name"),
                bind_ip=payload.get("bind_ip"),
                port=payload.get("port"),
            )
            return build_dlna_json_response(message="Ustawienia serwera DLNA zostały zapisane.", kind="success")
        except Exception as exc:
            return build_dlna_json_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/dlna/package-check", methods=["POST"])
    def api_dlna_package_check():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        state = refresh_dlna_package_state(force=True)
        if state["installed"]:
            sync_dlna_runtime_safe(restart_service_if_active=False)
            state = refresh_dlna_package_state(force=False)
        if state["check_error"]:
            return build_dlna_json_response(ok=False, message="Nie udało się sprawdzić pakietu DLNA: %s" % state["check_error"], kind="error", status_code=500)
        if not state["installed"]:
            return build_dlna_json_response(message="Pakiet Gerbera nie jest jeszcze zainstalowany. Dostępna wersja: %s." % state["latest_version"], kind="success")
        if state["update_available"]:
            return build_dlna_json_response(message="Dostępna jest nowsza wersja pakietu Gerbera: %s (na serwerze: %s)." % (state["latest_version"], state["current_version"]), kind="success")
        return build_dlna_json_response(message="Pakiet Gerbera jest już aktualny (%s)." % state["current_version"], kind="success")

    @app.route("/api/dlna/package-install", methods=["POST"])
    def api_dlna_package_install():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        started, task = start_maintenance_task(
            "dlna_install",
            "Instalacja serwera DLNA",
            lambda progress_callback: install_or_update_dlna_server(progress_callback=progress_callback),
        )
        message = "Rozpoczęto instalację lub aktualizację serwera DLNA." if started else "Instalacja lub aktualizacja serwera DLNA już trwa."
        return build_dlna_json_response(message=message, kind="success", started=started, task=task)

    @app.route("/api/dlna/service-toggle", methods=["POST"])
    def api_dlna_service_toggle():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        payload = request.get_json(silent=True) or {}
        try:
            enabled = parse_boolean_flag(payload.get("enabled"))
            set_dlna_service_enabled(enabled)
            return build_dlna_json_response(message="Serwer DLNA został %s." % ("włączony" if enabled else "wyłączony"), kind="success")
        except Exception as exc:
            return build_dlna_json_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/dlna/service-restart", methods=["POST"])
    def api_dlna_service_restart():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        try:
            restart_dlna_service_now()
            return build_dlna_json_response(message="Usługa DLNA została zrestartowana.", kind="success")
        except Exception as exc:
            return build_dlna_json_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/dlna/resync", methods=["POST"])
    def api_dlna_resync():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        try:
            sync_dlna_runtime(restart_service_if_active=True, force_full_rescan=True)
            return build_dlna_json_response(message="Biblioteka DLNA została zsynchronizowana.", kind="success")
        except Exception as exc:
            return build_dlna_json_response(ok=False, message=str(exc), kind="error", status_code=500)

    @app.route("/api/dlna/collections", methods=["POST"])
    def api_dlna_collections():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "").strip().lower()

        try:
            if action == "create":
                create_dlna_collection(payload.get("name"), payload.get("description"))
                return build_dlna_json_response(message="Dodano kolekcję DLNA.", kind="success")
            if action == "update":
                update_dlna_collection(payload.get("collection_id"), payload.get("name"), payload.get("description"))
                return build_dlna_json_response(message="Zapisano kolekcję DLNA.", kind="success")
            if action == "delete":
                delete_dlna_collection(payload.get("collection_id"))
                return build_dlna_json_response(message="Usunięto kolekcję DLNA.", kind="success")
            return build_dlna_json_response(ok=False, message="Nieobsługiwana akcja dla kolekcji DLNA.", kind="error", status_code=400)
        except Exception as exc:
            return build_dlna_json_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/dlna/clients", methods=["POST"])
    def api_dlna_clients():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "").strip().lower()

        try:
            if action == "create":
                create_dlna_client(
                    ip=payload.get("ip"),
                    description=payload.get("description"),
                    enabled=parse_boolean_flag(payload.get("enabled"), default=True),
                    collection_ids=payload.get("collection_ids") or [],
                    usernames=payload.get("usernames") or [],
                )
                return build_dlna_json_response(message="Dodano klienta DLNA do whitelisty.", kind="success")
            if action == "update":
                update_dlna_client(
                    client_id=payload.get("client_id"),
                    ip=payload.get("ip"),
                    description=payload.get("description"),
                    enabled=parse_boolean_flag(payload.get("enabled"), default=True),
                    collection_ids=payload.get("collection_ids") or [],
                    usernames=payload.get("usernames") or [],
                )
                return build_dlna_json_response(message="Zapisano klienta DLNA.", kind="success")
            if action == "delete":
                delete_dlna_client(payload.get("client_id"))
                return build_dlna_json_response(message="Usunięto klienta DLNA.", kind="success")
            return build_dlna_json_response(ok=False, message="Nieobsługiwana akcja dla klienta DLNA.", kind="error", status_code=400)
        except Exception as exc:
            return build_dlna_json_response(ok=False, message=str(exc), kind="error", status_code=400)

    @app.route("/api/dlna/media", methods=["POST"])
    def api_dlna_media():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "").strip().lower()

        try:
            if action == "create":
                create_dlna_media_rule(
                    kind=payload.get("kind"),
                    storage_kind=payload.get("storage_kind"),
                    relative_path=payload.get("relative_path"),
                    collection_ids=payload.get("collection_ids") or [],
                    enabled=True,
                )
                return build_dlna_json_response(message="Dodano medium do aktywnej biblioteki DLNA.", kind="success")
            if action == "update":
                update_dlna_media_rule(
                    rule_id=payload.get("rule_id"),
                    collection_ids=payload.get("collection_ids") or [],
                    enabled=parse_boolean_flag(payload.get("enabled"), default=True),
                )
                return build_dlna_json_response(message="Zapisano wpis DLNA.", kind="success")
            if action == "bulk_assign_collection":
                summary = bulk_assign_dlna_collection_items(
                    collection_id=payload.get("collection_id"),
                    items=payload.get("items") or [],
                )
                return build_dlna_json_response(
                    message="Zapisano zmiany widocznych pozycji w bukiecie DLNA." if summary.get("changed") else "Brak zmian do zapisania w tym bukiecie.",
                    kind="success",
                    bulk_summary=summary,
                )
            if action == "delete":
                delete_dlna_media_rule(payload.get("rule_id"))
                return build_dlna_json_response(message="Usunięto wpis DLNA.", kind="success")
            return build_dlna_json_response(ok=False, message="Nieobsługiwana akcja dla mediów DLNA.", kind="error", status_code=400)
        except Exception as exc:
            return build_dlna_json_response(ok=False, message=str(exc), kind="error", status_code=400)
