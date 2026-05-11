from flask import redirect, request, url_for


def register_auth_routes(app, deps):
    verify_user_credentials = deps["verify_user_credentials"]
    set_session_user = deps["set_session_user"]
    clear_session_user = deps["clear_session_user"]
    set_ui_flash = deps["set_ui_flash"]
    safe_next_url = deps["safe_next_url"]
    is_authenticated = deps["is_authenticated"]
    get_current_username = deps["get_current_username"]
    update_user_password = deps["update_user_password"]
    get_user_by_username = deps["get_user_by_username"]

    @app.route("/admin/login", methods=["POST"])
    def admin_login():
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        next_url = safe_next_url(request.form.get("next"))

        user = verify_user_credentials(username, password)
        if user:
            set_session_user(user)
            role_label = "administrator" if user.get("role") == "admin" else "użytkownik"
            set_ui_flash("Zalogowano jako %s %s." % (role_label, user.get("username")), "success")
        else:
            clear_session_user()
            set_ui_flash("Nieprawidłowy login lub hasło.", "error")

        return redirect(next_url)

    @app.route("/admin/logout", methods=["POST"])
    def admin_logout():
        next_url = safe_next_url(request.form.get("next"))
        clear_session_user()
        set_ui_flash("Wylogowano użytkownika.", "success")
        return redirect(next_url)

    @app.route("/account/change-password", methods=["POST"])
    def account_change_password():
        next_url = safe_next_url(request.form.get("next"))
        if not is_authenticated():
            set_ui_flash("Zaloguj się, aby zmienić własne hasło.", "error")
            return redirect(url_for("index"))

        current_username = get_current_username()
        current_password = str(request.form.get("current_password") or "")
        new_password = str(request.form.get("new_password") or "")
        confirm_new_password = str(request.form.get("confirm_new_password") or "")

        try:
            if not verify_user_credentials(current_username, current_password):
                raise ValueError("Aktualne hasło jest nieprawidłowe.")
            if new_password != confirm_new_password:
                raise ValueError("Nowe hasło i jego powtórzenie muszą być identyczne.")

            user = update_user_password(current_username, new_password)
            refreshed_user = get_user_by_username(user["username"]) or user
            set_session_user(refreshed_user)
            set_ui_flash("Hasło zostało zmienione.", "success")
        except Exception as exc:
            set_ui_flash(str(exc), "error")

        return redirect(next_url)
