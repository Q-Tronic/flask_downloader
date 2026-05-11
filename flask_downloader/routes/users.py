from flask import jsonify, redirect, request, url_for


def register_user_management_routes(app, deps):
    is_admin_authenticated = deps["is_admin_authenticated"]
    wants_json_response = deps["wants_json_response"]
    require_admin_json = deps["require_admin_json"]
    set_ui_flash = deps["set_ui_flash"]
    create_user_account = deps["create_user_account"]
    update_user_password = deps["update_user_password"]
    update_user_account = deps["update_user_account"]
    delete_user_account = deps["delete_user_account"]
    get_settings_page_state = deps["get_settings_page_state"]
    ensure_directory = deps["ensure_directory"]
    get_user_storage_root = deps["get_user_storage_root"]
    normalize_username = deps["normalize_username"]
    get_current_username = deps["get_current_username"]

    @app.route("/settings/users/create", methods=["POST"])
    def settings_create_user():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby tworzyć użytkowników.", "error")
            return redirect(url_for("index"))

        try:
            user = create_user_account(
                username=request.form.get("username"),
                password=request.form.get("password"),
                role=request.form.get("role") or "user",
            )
            ensure_directory(get_user_storage_root(user["username"], "video"))
            ensure_directory(get_user_storage_root(user["username"], "audio"))
            message = "Dodano użytkownika %s." % user["username"]
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

    @app.route("/settings/users/reset-password", methods=["POST"])
    def settings_reset_user_password():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby resetować hasła.", "error")
            return redirect(url_for("index"))

        try:
            user = update_user_password(
                username=request.form.get("username"),
                new_password=request.form.get("new_password"),
            )
            message = "Hasło użytkownika %s zostało zresetowane." % user["username"]
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

    @app.route("/settings/users/update", methods=["POST"])
    def settings_update_user():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby edytować użytkowników.", "error")
            return redirect(url_for("index"))

        try:
            original_username = request.form.get("original_username")
            normalized_original_username = normalize_username(original_username)
            if normalized_original_username == get_current_username():
                raise ValueError("Własnego loginu ani roli nie zmienisz w tym panelu.")

            updated_user = update_user_account(
                username=original_username,
                new_username=request.form.get("username"),
                role=request.form.get("role") or "user",
            )
            if updated_user["username"] != normalized_original_username:
                message = "Zmieniono login użytkownika %s na %s." % (
                    normalized_original_username,
                    updated_user["username"],
                )
            else:
                message = "Zapisano zmiany użytkownika %s." % updated_user["username"]
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

    @app.route("/settings/users/delete", methods=["POST"])
    def settings_delete_user():
        if not is_admin_authenticated():
            if wants_json_response():
                return require_admin_json()
            set_ui_flash("Zaloguj się jako administrator, aby usuwać użytkowników.", "error")
            return redirect(url_for("index"))

        try:
            username = request.form.get("username")
            if normalize_username(username) == get_current_username():
                raise ValueError("Nie możesz usunąć własnego aktualnie zalogowanego konta.")
            user = delete_user_account(username)
            message = "Usunięto użytkownika %s wraz z jego plikami i zadaniami." % user["username"]
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
