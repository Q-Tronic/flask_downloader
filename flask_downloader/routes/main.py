from flask import Response, request


def register_main_routes(app, deps):
    FAVICON_SVG = deps["FAVICON_SVG"]
    render_page = deps["render_page"]
    get_mount_info = deps["get_mount_info"]
    require_authenticated_page = deps["require_authenticated_page"]
    is_valid_http_url = deps["is_valid_http_url"]
    extract_http_urls = deps["extract_http_urls"]
    extract_video_data = deps["extract_video_data"]
    extract_browser_data = deps["extract_browser_data"]
    build_result_with_proxy_urls = deps["build_result_with_proxy_urls"]
    get_assignable_dlna_collections_for_current_user = deps["get_assignable_dlna_collections_for_current_user"]
    get_daily_download_dir = deps["get_daily_download_dir"]
    get_yt_dlp_services_state = deps["get_yt_dlp_services_state"]
    INDEX_CONTENT_TEMPLATE = deps["INDEX_CONTENT_TEMPLATE"]
    DOWNLOADS_CONTENT_TEMPLATE = deps["DOWNLOADS_CONTENT_TEMPLATE"]
    JOBS_CONTENT_TEMPLATE = deps["JOBS_CONTENT_TEMPLATE"]
    SERVICES_CONTENT_TEMPLATE = deps["SERVICES_CONTENT_TEMPLATE"]

    @app.template_filter("urlencode")
    def urlencode_filter(value):
        return deps["quote"](str(value), safe="")

    @app.route("/favicon.svg", methods=["GET"])
    @app.route("/favicon.ico", methods=["GET"])
    def favicon():
        return Response(
            FAVICON_SVG,
            mimetype="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.route("/", methods=["GET", "POST"])
    def index():
        error = None
        result = None
        collection_result = None
        input_url = ""
        mount = get_mount_info(auto_remount=False)

        if request.method == "POST":
            auth_error = require_authenticated_page("Zaloguj się, aby pobierać dane źródeł i dodawać zadania.")
            if auth_error:
                return auth_error
            input_url = request.form.get("url", "").strip()
            parsed_urls = extract_http_urls(input_url)

            if not input_url:
                error = "Podaj adres URL."
            elif not parsed_urls:
                error = "Adres musi zaczynać się od http:// albo https://"
            elif len(parsed_urls) > 1:
                error = "Podgląd źródeł działa tylko dla pojedynczego linku. Użyj przycisków BEST, jeśli chcesz dodać wiele adresów naraz."
            else:
                try:
                    input_url = parsed_urls[0]
                    browser_payload = extract_browser_data(input_url, force_refresh=True)
                    if browser_payload.get("kind") == "collection":
                        collection_result = dict(browser_payload.get("collection") or {})
                    else:
                        parsed = dict(browser_payload.get("result") or {})
                        if not parsed.get("sources"):
                            error = "yt-dlp nie zwrócił żadnych formatów wideo dla tej strony."
                        else:
                            result = build_result_with_proxy_urls(parsed, request.url_root)
                except Exception as exc:
                    error = "Błąd ekstrakcji:\\n%s" % exc

        return render_page(
            "VLC Stream Extractor",
            "home",
            INDEX_CONTENT_TEMPLATE,
            error=error,
            result=result,
            collection_result=collection_result,
            input_url=input_url,
            quick_dlna_collections=get_assignable_dlna_collections_for_current_user(),
            mount=mount,
            download_dir=get_daily_download_dir(),
        )

    @app.route("/downloads", methods=["GET"])
    def downloads_page():
        auth_error = require_authenticated_page("Zaloguj się, aby zobaczyć swoje pliki.")
        if auth_error:
            return auth_error
        return render_page(
            "Pobrane pliki",
            "downloads",
            DOWNLOADS_CONTENT_TEMPLATE,
            mount=get_mount_info(auto_remount=False),
        )

    @app.route("/jobs", methods=["GET"])
    def jobs_page():
        auth_error = require_authenticated_page("Zaloguj się, aby zobaczyć swoje zadania pobierania.")
        if auth_error:
            return auth_error
        return render_page(
            "Zadania pobierania",
            "jobs",
            JOBS_CONTENT_TEMPLATE,
            mount=get_mount_info(auto_remount=False),
        )

    @app.route("/services", methods=["GET"])
    def services_page():
        auth_error = require_authenticated_page("Zaloguj się, aby korzystać z listy serwisów.")
        if auth_error:
            return auth_error
        return render_page(
            "Lista Serwisów",
            "services",
            SERVICES_CONTENT_TEMPLATE,
            services_state=get_yt_dlp_services_state(force=False),
        )
