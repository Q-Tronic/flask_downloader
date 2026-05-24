from flask import Response, jsonify, request


def register_radio_routes(app, deps):
    require_authenticated_page = deps["require_authenticated_page"]
    require_authenticated_json = deps["require_authenticated_json"]
    is_admin_authenticated = deps["is_admin_authenticated"]
    create_sse_json_response = deps["create_sse_json_response"]
    render_page = deps["render_page"]
    start_maintenance_task = deps["start_maintenance_task"]
    resolve_view_scope_username = deps["resolve_view_scope_username"]
    get_current_username = deps["get_current_username"]
    RADIO_CONTENT_TEMPLATE = deps["RADIO_CONTENT_TEMPLATE"]
    get_radio_page_state = deps["get_radio_page_state"]
    create_radio_station = deps["create_radio_station"]
    update_radio_station = deps["update_radio_station"]
    delete_radio_station = deps["delete_radio_station"]
    update_radio_global_settings = deps["update_radio_global_settings"]
    add_radio_library_paths = deps["add_radio_library_paths"]
    bulk_save_radio_library = deps["bulk_save_radio_library"]
    update_radio_library_item = deps["update_radio_library_item"]
    remove_radio_library_item = deps["remove_radio_library_item"]
    store_uploaded_radio_audio = deps["store_uploaded_radio_audio"]
    store_uploaded_radio_audio_batch = deps["store_uploaded_radio_audio_batch"]
    refresh_radio_backend_package_state = deps["refresh_radio_backend_package_state"]
    install_or_update_radio_backend = deps["install_or_update_radio_backend"]
    set_radio_backend_enabled = deps["set_radio_backend_enabled"]
    restart_radio_backend_now = deps["restart_radio_backend_now"]
    control_radio_station = deps["control_radio_station"]
    queue_radio_station_track = deps["queue_radio_station_track"]
    read_radio_log_file_for_browser = deps["read_radio_log_file_for_browser"]
    get_radio_backend_log_file = deps["get_radio_backend_log_file"]
    get_radio_station_log_file = deps["get_radio_station_log_file"]
    RADIO_LOG_BROWSER_MAX_BYTES = deps["RADIO_LOG_BROWSER_MAX_BYTES"]

    def resolve_radio_scope(raw_owner_username=""):
        return resolve_view_scope_username(raw_owner_username, "radio_view_scope")

    def radio_state_response(*, owner_username="", ok=True, message="", kind="success", status_code=200, **extra):
        payload = {
            "ok": bool(ok),
            "message": str(message or ""),
            "kind": str(kind or ("success" if ok else "error")),
            "radio_state": get_radio_page_state(owner_username=owner_username),
        }
        payload.update(extra)
        response = jsonify(payload)
        if status_code and status_code != 200:
            return response, status_code
        return response

    @app.route("/radio", methods=["GET"])
    def radio_page():
        auth_error = require_authenticated_page("Zaloguj się, aby korzystać z własnego radia.")
        if auth_error:
            return auth_error

        scope_username = resolve_radio_scope(request.args.get("user"))
        return render_page(
            "Moje radio",
            "radio",
            RADIO_CONTENT_TEMPLATE,
            radio_initial_state=get_radio_page_state(owner_username=scope_username),
        )

    @app.route("/api/radio/state", methods=["GET"])
    def api_radio_state():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        scope_username = resolve_radio_scope(request.args.get("user"))
        return radio_state_response(owner_username=scope_username)

    @app.route("/api/radio/stream", methods=["GET"])
    def api_radio_stream():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        scope_username = resolve_radio_scope(request.args.get("user"))
        return create_sse_json_response(
            lambda: {
                "ok": True,
                "message": "",
                "kind": "success",
                "radio_state": get_radio_page_state(owner_username=scope_username),
            },
            interval_seconds=2.0,
            retry_ms=2500,
        )

    @app.route("/logs-radio-backend", methods=["GET"])
    def radio_backend_logs_page():
        auth_error = require_authenticated_page("Zaloguj się, aby podejrzeć log backendu radia.")
        if auth_error:
            return auth_error
        if not is_admin_authenticated():
            response = Response("Tylko administrator może podejrzeć pełny log backendu radia.\n", content_type="text/plain; charset=utf-8")
            response.status_code = 403
            return response
        body = read_radio_log_file_for_browser(get_radio_backend_log_file(), max_bytes=RADIO_LOG_BROWSER_MAX_BYTES)
        response = Response(body, content_type="text/plain; charset=utf-8")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/logs-radio-station", methods=["GET"])
    def radio_station_logs_page():
        auth_error = require_authenticated_page("Zaloguj się, aby podejrzeć log własnej stacji radiowej.")
        if auth_error:
            return auth_error
        scope_username = resolve_radio_scope(request.args.get("user") or get_current_username())
        body = read_radio_log_file_for_browser(get_radio_station_log_file(scope_username), max_bytes=RADIO_LOG_BROWSER_MAX_BYTES)
        response = Response(body, content_type="text/plain; charset=utf-8")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/radio/station", methods=["POST"])
    def api_radio_station():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "update").strip().lower()
        scope_username = resolve_radio_scope(payload.get("owner_username") or request.args.get("user") or get_current_username())

        try:
            if action == "create":
                created, _ = create_radio_station(scope_username)
                return radio_state_response(
                    owner_username=scope_username,
                    message="Utworzono nowe radio użytkownika." if created else "To radio już istniało.",
                    kind="success",
                    created=created,
                )
            if action == "update":
                update_radio_station(scope_username, payload)
                return radio_state_response(
                    owner_username=scope_username,
                    message="Ustawienia radia zostały zapisane.",
                    kind="success",
                )
            if action == "delete":
                delete_radio_station(scope_username)
                return radio_state_response(
                    owner_username=scope_username,
                    message="Radio zostało usunięte.",
                    kind="success",
                )
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message="Nieobsługiwana akcja radia.",
                kind="error",
                status_code=400,
            )
        except Exception as exc:
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message=str(exc),
                kind="error",
                status_code=400,
            )

    @app.route("/api/radio/backend/check", methods=["POST"])
    def api_radio_backend_check():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error
        if not is_admin_authenticated():
            return radio_state_response(
                owner_username=resolve_radio_scope(request.args.get("user") or get_current_username()),
                ok=False,
                message="Tylko administrator może sprawdzać backend radia.",
                kind="error",
                status_code=403,
            )

        scope_username = resolve_radio_scope(request.args.get("user") or get_current_username())
        state = refresh_radio_backend_package_state(force=True)
        if not state.get("linux_supported", True):
            return radio_state_response(
                owner_username=scope_username,
                message="Runtime radia wymaga Linuxa z apt i systemd. W tym środowisku możesz konfigurować radio, ale nie uruchomisz backendu.",
                kind="success",
            )
        if state["check_error"]:
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message="Nie udało się sprawdzić pakietów backendu radia: %s" % state["check_error"],
                kind="error",
                status_code=500,
            )
        if not state["installed"]:
            return radio_state_response(
                owner_username=scope_username,
                message="Backend radia nie jest jeszcze gotowy. Sprawdzone pakiety: Icecast i Liquidsoap.",
                kind="success",
            )
        if state["update_available"]:
            return radio_state_response(
                owner_username=scope_username,
                message="Backend radia wymaga instalacji lub aktualizacji pakietów Icecast / Liquidsoap.",
                kind="success",
            )
        return radio_state_response(
            owner_username=scope_username,
            message="Backend radia jest już gotowy.",
            kind="success",
        )

    @app.route("/api/radio/backend/install", methods=["POST"])
    def api_radio_backend_install():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error
        if not is_admin_authenticated():
            return radio_state_response(
                owner_username=resolve_radio_scope(request.args.get("user") or get_current_username()),
                ok=False,
                message="Tylko administrator może instalować backend radia.",
                kind="error",
                status_code=403,
            )

        scope_username = resolve_radio_scope(request.args.get("user") or get_current_username())
        started, task = start_maintenance_task(
            "radio_backend_install",
            "Instalacja backendu radia",
            lambda progress_callback: install_or_update_radio_backend(progress_callback=progress_callback),
        )
        message = "Rozpoczęto instalację lub aktualizację backendu radia." if started else "Instalacja lub aktualizacja backendu radia już trwa."
        return radio_state_response(
            owner_username=scope_username,
            message=message,
            kind="success",
            started=started,
            task=task,
        )

    @app.route("/api/radio/backend/control", methods=["POST"])
    def api_radio_backend_control():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error
        if not is_admin_authenticated():
            return radio_state_response(
                owner_username=resolve_radio_scope(request.args.get("user") or get_current_username()),
                ok=False,
                message="Tylko administrator może sterować backendem radia.",
                kind="error",
                status_code=403,
            )

        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "").strip().lower()
        scope_username = resolve_radio_scope(payload.get("owner_username") or request.args.get("user") or get_current_username())
        try:
            if action == "start":
                set_radio_backend_enabled(True)
                return radio_state_response(owner_username=scope_username, message="Backend radia został uruchomiony.", kind="success")
            if action == "stop":
                set_radio_backend_enabled(False)
                return radio_state_response(owner_username=scope_username, message="Backend radia został zatrzymany.", kind="success")
            if action == "restart":
                restart_radio_backend_now()
                return radio_state_response(owner_username=scope_username, message="Backend radia został zrestartowany.", kind="success")
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message="Nieobsługiwana akcja backendu radia.",
                kind="error",
                status_code=400,
            )
        except Exception as exc:
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message=str(exc),
                kind="error",
                status_code=400,
            )

    @app.route("/api/radio/station/control", methods=["POST"])
    def api_radio_station_control():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "").strip().lower()
        scope_username = resolve_radio_scope(payload.get("owner_username") or request.args.get("user") or get_current_username())
        try:
            if action in ("play_now", "queue_next"):
                relative_path = payload.get("relative_path")
                queue_result = queue_radio_station_track(
                    scope_username,
                    relative_path,
                    queue_mode=action,
                )
                message = "Dodano do ręcznej kolejki: %s (%s)." % (
                    queue_result.get("display_title") or "utwór",
                    "zagraj teraz" if action == "play_now" else "zagraj jako następne",
                )
                return radio_state_response(
                    owner_username=scope_username,
                    message=message,
                    kind="success",
                    queue_result=queue_result,
                )
            control_radio_station(scope_username, action)
            if action == "start":
                message = "Stacja radiowa została uruchomiona."
            elif action == "stop":
                message = "Stacja radiowa została zatrzymana."
            elif action == "restart":
                message = "Stacja radiowa została zrestartowana."
            elif action == "next":
                message = "Przełączono autopilota na następny utwór."
            else:
                message = "Zapisano zmianę stanu stacji radiowej."
            return radio_state_response(owner_username=scope_username, message=message, kind="success")
        except Exception as exc:
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message=str(exc),
                kind="error",
                status_code=400,
            )

    @app.route("/api/radio/global", methods=["POST"])
    def api_radio_global():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error
        if not is_admin_authenticated():
            return radio_state_response(
                owner_username=resolve_radio_scope(request.args.get("user") or get_current_username()),
                ok=False,
                message="Tylko administrator może zmieniać globalne ustawienia backendu radia.",
                kind="error",
                status_code=403,
            )

        payload = request.get_json(silent=True) or {}
        scope_username = resolve_radio_scope(payload.get("owner_username") or request.args.get("user") or get_current_username())
        try:
            update_radio_global_settings(payload)
            return radio_state_response(
                owner_username=scope_username,
                message="Zapisano globalne ustawienia backendu radia.",
                kind="success",
            )
        except Exception as exc:
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message=str(exc),
                kind="error",
                status_code=400,
            )

    @app.route("/api/radio/library", methods=["POST"])
    def api_radio_library():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "add").strip().lower()
        scope_username = resolve_radio_scope(payload.get("owner_username") or request.args.get("user") or get_current_username())

        try:
            if action == "add":
                raw_paths = payload.get("relative_paths")
                if isinstance(raw_paths, list):
                    relative_paths = raw_paths
                else:
                    relative_paths = [payload.get("relative_path")]
                summary = add_radio_library_paths(
                    scope_username,
                    relative_paths,
                    source_type=str(payload.get("source_type") or "download"),
                )
                message = "Dodano %s pozycji do biblioteki radia." % summary.get("added") if summary.get("added") else "Nie dodano żadnych nowych pozycji do biblioteki radia."
                return radio_state_response(
                    owner_username=scope_username,
                    message=message,
                    kind="success",
                    library_summary=summary,
                )
            if action == "update":
                update_radio_library_item(
                    scope_username,
                    payload.get("item_id"),
                    display_title=payload.get("display_title") or "",
                    role=payload.get("role") or "music",
                    enabled=payload.get("enabled", True),
                )
                return radio_state_response(
                    owner_username=scope_username,
                    message="Zapisano wpis biblioteki radia.",
                    kind="success",
                )
            if action == "delete":
                remove_radio_library_item(scope_username, payload.get("item_id"))
                return radio_state_response(
                    owner_username=scope_username,
                    message="Usunięto wpis z biblioteki radia.",
                    kind="success",
                )
            if action == "bulk_save":
                summary = bulk_save_radio_library(
                    scope_username,
                    mode=payload.get("mode") or "manual",
                    rows=payload.get("rows") or [],
                )
                mode_label = "całej biblioteki użytkownika" if str(summary.get("mode") or "") == "all_user_audio" else "ręcznego wyboru"
                return radio_state_response(
                    owner_username=scope_username,
                    message="Zapisano bibliotekę radia w trybie %s." % mode_label,
                    kind="success",
                    library_summary=summary,
                )
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message="Nieobsługiwana akcja biblioteki radia.",
                kind="error",
                status_code=400,
            )
        except Exception as exc:
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message=str(exc),
                kind="error",
                status_code=400,
            )

    @app.route("/api/radio/upload", methods=["POST"])
    def api_radio_upload():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        scope_username = resolve_radio_scope(request.form.get("owner_username") or request.args.get("user") or get_current_username())
        try:
            file_storages = [item for item in request.files.getlist("files") if item is not None]
            if not file_storages:
                single_file = request.files.get("file")
                if single_file is not None:
                    file_storages = [single_file]
            if len(file_storages) > 1:
                batch_result = store_uploaded_radio_audio_batch(scope_username, file_storages)
                uploaded_count = int(batch_result.get("uploaded_count") or 0)
                failed_count = int(batch_result.get("failed_count") or 0)
                if uploaded_count and failed_count:
                    message = "Wgrano %s plików audio, a %s zakończyło się błędem." % (uploaded_count, failed_count)
                elif uploaded_count:
                    message = "Wgrano %s plików audio i dodano je do biblioteki radia." % uploaded_count
                else:
                    message = "Nie udało się wgrać żadnego pliku audio."
                return radio_state_response(
                    owner_username=scope_username,
                    ok=uploaded_count > 0,
                    message=message,
                    kind="success" if uploaded_count > 0 else "error",
                    upload_summary=batch_result,
                    status_code=200 if uploaded_count > 0 else 400,
                )
            relative_path = store_uploaded_radio_audio(scope_username, file_storages[0] if file_storages else None)
            return radio_state_response(
                owner_username=scope_username,
                message="Wgrano plik audio i dodano go do biblioteki radia.",
                kind="success",
                uploaded_relative_path=relative_path,
            )
        except Exception as exc:
            return radio_state_response(
                owner_username=scope_username,
                ok=False,
                message=str(exc),
                kind="error",
                status_code=400,
            )
