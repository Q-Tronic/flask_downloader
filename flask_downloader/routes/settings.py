from flask import jsonify, redirect, request, url_for


def register_settings_routes(app, deps):
    is_admin_authenticated = deps["is_admin_authenticated"]
    wants_json_response = deps["wants_json_response"]
    require_admin_json = deps["require_admin_json"]
    set_ui_flash = deps["set_ui_flash"]
    render_page = deps["render_page"]
    SETTINGS_CONTENT_TEMPLATE = deps["SETTINGS_CONTENT_TEMPLATE"]
    get_settings_page_state = deps["get_settings_page_state"]
    save_app_config = deps["save_app_config"]
    ensure_share_ready = deps["ensure_share_ready"]
    sync_dlna_runtime_safe = deps["sync_dlna_runtime_safe"]
    refresh_ffmpeg_update_state = deps["refresh_ffmpeg_update_state"]
    start_maintenance_task = deps["start_maintenance_task"]
    install_or_update_ffmpeg = deps["install_or_update_ffmpeg"]
    refresh_yt_dlp_update_state = deps["refresh_yt_dlp_update_state"]
    update_yt_dlp_package = deps["update_yt_dlp_package"]
    refresh_dlna_package_state = deps["refresh_dlna_package_state"]
    build_dlna_json_response = deps["build_dlna_json_response"]
    install_or_update_dlna_server = deps["install_or_update_dlna_server"]
    parse_boolean_flag = deps["parse_boolean_flag"]
    set_dlna_service_enabled = deps["set_dlna_service_enabled"]
    restart_dlna_service_now = deps["restart_dlna_service_now"]
    schedule_flask_service_restart = deps["schedule_flask_service_restart"]
    SYSTEMD_SERVICE_NAME = deps["SYSTEMD_SERVICE_NAME"]

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby wejść do konfiguracji.", "error")
            return redirect(url_for("index"))

        if request.method == "POST":
            try:
                save_app_config(
                    download_root=request.form.get("user_storage_root") or request.form.get("download_root"),
                    audio_download_root=request.form.get("audio_download_root"),
                    job_retention_days=request.form.get("job_retention_days"),
                )
                ensure_share_ready(auto_remount=True)
                sync_dlna_runtime_safe(restart_service_if_active=False)
                message = "Konfiguracja została zapisana."
                if wants_json_response():
                    return jsonify({
                        "ok": True,
                        "message": message,
                        "kind": "success",
                        "state": get_settings_page_state(include_user_rows=True),
                    })
                set_ui_flash(message, "success")
            except Exception as exc:
                if wants_json_response():
                    return jsonify({
                        "ok": False,
                        "error": str(exc),
                        "kind": "error",
                        "state": get_settings_page_state(include_user_rows=True),
                    }), 400
                set_ui_flash(str(exc), "error")

            return redirect(url_for("settings_page"))

        return render_page(
            "Konfiguracja",
            "settings",
            SETTINGS_CONTENT_TEMPLATE,
            **get_settings_page_state(include_user_rows=True)
        )

    @app.route("/settings/ffmpeg-check", methods=["POST"])
    def settings_check_ffmpeg():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby sprawdzać wersję ffmpeg.", "error")
            return redirect(url_for("index"))

        state = refresh_ffmpeg_update_state(force=True)
        if state["check_error"]:
            message = "Nie udało się sprawdzić najnowszego buildu ffmpeg: %s" % state["check_error"]
            kind = "error"
        elif not state["installed"]:
            message = "ffmpeg nie jest jeszcze zainstalowany. Dostępny build: %s." % state["latest_version"]
            kind = "success"
        elif state["update_available"]:
            message = "Dostępny jest nowszy build ffmpeg: %s (na serwerze: %s)." % (
                state["latest_version"],
                state["current_version"],
            )
            kind = "success"
        elif state["managed"]:
            message = "Masz już najnowszy dostępny build ffmpeg (%s)." % state["current_version"]
            kind = "success"
        else:
            message = "Wykryto systemowy ffmpeg (%s). Jeśli chcesz nim zarządzać z panelu, użyj instalacji lokalnego buildu." % (
                state["current_version"],
            )
            kind = "success"

        if wants_json_response():
            return jsonify({
                "ok": kind == "success",
                "message": message,
                "kind": kind,
                "state": get_settings_page_state(),
            })

        set_ui_flash(message, "error" if state["check_error"] else "success")
        return redirect(url_for("settings_page"))

    @app.route("/settings/ffmpeg-install", methods=["POST"])
    def settings_install_ffmpeg():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby instalować ffmpeg.", "error")
            return redirect(url_for("index"))

        started, task = start_maintenance_task(
            "ffmpeg_install",
            "Instalacja ffmpeg",
            lambda progress_callback: install_or_update_ffmpeg(progress_callback=progress_callback),
        )
        message = "Rozpoczęto instalację lub aktualizację ffmpeg." if started else "Instalacja lub aktualizacja ffmpeg już trwa."

        if wants_json_response():
            return jsonify({
                "ok": True,
                "started": started,
                "message": message,
                "task": task,
                "state": get_settings_page_state(),
            })

        set_ui_flash(message, "success")
        return redirect(url_for("settings_page"))

    @app.route("/settings/yt-dlp-check", methods=["POST"])
    def settings_check_ytdlp():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby sprawdzać wersję yt-dlp.", "error")
            return redirect(url_for("index"))

        state = refresh_yt_dlp_update_state(force=True)
        if state["update_available"]:
            message = "Dostępna jest nowsza wersja yt-dlp: %s (na serwerze: %s)." % (
                state["latest_version"],
                state["current_version"],
            )
            kind = "success"
        elif state["check_error"]:
            message = "Nie udało się sprawdzić najnowszej wersji yt-dlp: %s" % state["check_error"]
            kind = "error"
        else:
            message = "Masz już najnowszą dostępną wersję yt-dlp (%s)." % state["current_version"]
            kind = "success"

        if wants_json_response():
            return jsonify({
                "ok": kind == "success",
                "message": message,
                "kind": kind,
                "state": get_settings_page_state(),
            })

        if state["check_error"]:
            set_ui_flash(message, "error")
        else:
            set_ui_flash(message, "success")
        return redirect(url_for("settings_page"))

    @app.route("/settings/yt-dlp-update", methods=["POST"])
    def settings_update_ytdlp():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby aktualizować yt-dlp.", "error")
            return redirect(url_for("index"))

        started, task = start_maintenance_task(
            "yt_dlp_update",
            "Aktualizacja yt-dlp",
            lambda progress_callback: update_yt_dlp_package(progress_callback=progress_callback),
        )
        message = "Rozpoczęto aktualizację yt-dlp." if started else "Aktualizacja yt-dlp już trwa."

        if wants_json_response():
            return jsonify({
                "ok": True,
                "started": started,
                "message": message,
                "task": task,
                "state": get_settings_page_state(),
            })

        set_ui_flash(message, "success")
        return redirect(url_for("settings_page"))

    @app.route("/settings/dlna-check", methods=["POST"])
    def settings_check_dlna():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby sprawdzać pakiet DLNA.", "error")
            return redirect(url_for("index"))

        state = refresh_dlna_package_state(force=True)
        if state["installed"]:
            sync_dlna_runtime_safe(restart_service_if_active=False)
            state = refresh_dlna_package_state(force=False)
        if state["check_error"]:
            message = "Nie udało się sprawdzić pakietu DLNA: %s" % state["check_error"]
            kind = "error"
        elif not state["installed"]:
            message = "Pakiet Gerbera nie jest jeszcze zainstalowany. Dostępna wersja: %s." % state["latest_version"]
            kind = "success"
        elif state["update_available"]:
            message = "Dostępna jest nowsza wersja pakietu Gerbera: %s (na serwerze: %s)." % (state["latest_version"], state["current_version"])
            kind = "success"
        else:
            message = "Pakiet Gerbera jest już aktualny (%s)." % state["current_version"]
            kind = "success"

        if wants_json_response():
            status_code = 500 if kind == "error" else 200
            return build_dlna_json_response(ok=kind == "success", message=message, kind=kind, status_code=status_code)

        set_ui_flash(message, kind)
        return redirect(url_for("settings_page"))

    @app.route("/settings/dlna-install", methods=["POST"])
    def settings_install_dlna():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby instalować serwer DLNA.", "error")
            return redirect(url_for("index"))

        started, task = start_maintenance_task(
            "dlna_install",
            "Instalacja serwera DLNA",
            lambda progress_callback: install_or_update_dlna_server(progress_callback=progress_callback),
        )
        message = "Rozpoczęto instalację lub aktualizację serwera DLNA." if started else "Instalacja lub aktualizacja serwera DLNA już trwa."

        if wants_json_response():
            return build_dlna_json_response(message=message, kind="success", started=started, task=task)

        set_ui_flash(message, "success")
        return redirect(url_for("settings_page"))

    @app.route("/settings/dlna-toggle-service", methods=["POST"])
    def settings_toggle_dlna_service():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby przełączać usługę DLNA.", "error")
            return redirect(url_for("index"))

        enabled = parse_boolean_flag(request.form.get("enabled"), default=False)
        try:
            set_dlna_service_enabled(enabled)
            message = "Serwer DLNA został %s." % ("włączony" if enabled else "wyłączony")
            if wants_json_response():
                return build_dlna_json_response(message=message, kind="success")
            set_ui_flash(message, "success")
        except Exception as exc:
            if wants_json_response():
                return build_dlna_json_response(ok=False, message=str(exc), kind="error", status_code=400)
            set_ui_flash(str(exc), "error")

        return redirect(url_for("settings_page"))

    @app.route("/settings/dlna-restart-service", methods=["POST"])
    def settings_restart_dlna_service():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby restartować usługę DLNA.", "error")
            return redirect(url_for("index"))

        try:
            restart_dlna_service_now()
            message = "Usługa DLNA została zrestartowana."
            if wants_json_response():
                return build_dlna_json_response(message=message, kind="success")
            set_ui_flash(message, "success")
        except Exception as exc:
            if wants_json_response():
                return build_dlna_json_response(ok=False, message=str(exc), kind="error", status_code=400)
            set_ui_flash(str(exc), "error")

        return redirect(url_for("settings_page"))

    @app.route("/api/settings/state", methods=["GET"])
    @app.route("/api/settings/maintenance", methods=["GET"])
    def api_settings_state():
        auth_error = require_admin_json()
        if auth_error:
            return auth_error

        return jsonify({
            "ok": True,
            "state": get_settings_page_state(include_user_rows=True),
        })

    @app.route("/settings/restart-service", methods=["POST"])
    def settings_restart_service():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby restartować usługę Flask.", "error")
            return redirect(url_for("index"))

        try:
            schedule_flask_service_restart()
            message = "Wysłano polecenie restartu usługi %s. Panel będzie odświeżał status automatycznie." % (
                SYSTEMD_SERVICE_NAME,
            )
            if wants_json_response():
                return jsonify({
                    "ok": True,
                    "message": message,
                    "kind": "success",
                    "state": get_settings_page_state(),
                })
            set_ui_flash(message, "success")
        except Exception as exc:
            if wants_json_response():
                return jsonify({
                    "ok": False,
                    "error": "Nie udało się zrestartować usługi Flask: %s" % exc,
                    "kind": "error",
                    "state": get_settings_page_state(),
                }), 500
            set_ui_flash("Nie udało się zrestartować usługi Flask: %s" % exc, "error")

        return redirect(url_for("settings_page"))
