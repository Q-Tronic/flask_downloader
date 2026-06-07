import os
import re

from flask import Response, jsonify, request, send_file


def register_download_routes(app, deps):
    require_authenticated_json = deps["require_authenticated_json"]
    create_sse_json_response = deps["create_sse_json_response"]
    resolve_view_scope_username = deps["resolve_view_scope_username"]
    get_users_snapshot = deps["get_users_snapshot"]
    is_admin_authenticated = deps["is_admin_authenticated"]
    get_current_username = deps["get_current_username"]
    get_mount_info = deps["get_mount_info"]
    get_server_files = deps["get_server_files"]
    filter_jobs_for_viewer = deps["filter_jobs_for_viewer"]
    get_jobs_snapshot = deps["get_jobs_snapshot"]
    get_dlna_manual_sync_notice_state = deps["get_dlna_manual_sync_notice_state"]
    is_valid_http_url = deps["is_valid_http_url"]
    extract_http_urls = deps["extract_http_urls"]
    extract_video_data = deps["extract_video_data"]
    build_result_with_proxy_urls = deps["build_result_with_proxy_urls"]
    find_format = deps["find_format"]
    choose_best_source = deps["choose_best_source"]
    public_source_download_match_state = deps["public_source_download_match_state"]
    get_source_download_match_state = deps["get_source_download_match_state"]
    get_assignable_dlna_collections_for_current_user = deps["get_assignable_dlna_collections_for_current_user"]
    ensure_share_ready = deps["ensure_share_ready"]
    normalize_storage_kind = deps["normalize_storage_kind"]
    create_job = deps["create_job"]
    build_download_filename = deps["build_download_filename"]
    normalize_requested_download_filename = deps["normalize_requested_download_filename"]
    mark_job_cancel_requested = deps["mark_job_cancel_requested"]
    mark_job_pause_requested = deps["mark_job_pause_requested"]
    resume_job_download = deps["resume_job_download"]
    retry_job_download = deps["retry_job_download"]
    delete_job = deps["delete_job"]
    delete_managed_file = deps["delete_managed_file"]
    build_m3u = deps["build_m3u"]
    stream_upstream_response = deps["stream_upstream_response"]
    build_intermediate_download_filename = deps["build_intermediate_download_filename"]
    is_authenticated = deps["is_authenticated"]
    build_managed_relative_path = deps["build_managed_relative_path"]
    parse_managed_relative_path = deps["parse_managed_relative_path"]
    safe_relative_download_path = deps["safe_relative_download_path"]
    resolve_download_path = deps["resolve_download_path"]
    normalize_username = deps["normalize_username"]
    DEFAULT_ADMIN_USERNAME = deps["DEFAULT_ADMIN_USERNAME"]
    can_access_owner = deps["can_access_owner"]

    def get_allowed_dlna_collection_map():
        return {
            str(item.get("id") or "").strip(): item
            for item in (get_assignable_dlna_collections_for_current_user() or [])
            if str(item.get("id") or "").strip()
        }

    def normalize_requested_auto_dlna_collection_id(raw_value):
        collection_id = str(raw_value or "").strip()
        if not collection_id:
            return ""

        allowed_map = get_allowed_dlna_collection_map()
        if collection_id not in allowed_map:
            raise ValueError("Nie masz dostępu do wybranego bukietu DLNA.")
        return collection_id

    def build_files_payload(scope_username):
        available_users = [item["username"] for item in get_users_snapshot()] if is_admin_authenticated() else []
        filtered_jobs = filter_jobs_for_viewer(get_jobs_snapshot(), scope_username=scope_username)
        return {
            "logged_in": True,
            "current_user": get_current_username(),
            "admin_logged_in": is_admin_authenticated(),
            "available_users": available_users,
            "scope_username": scope_username,
            "mount": get_mount_info(auto_remount=True, viewer_username=scope_username or get_current_username(), is_admin=is_admin_authenticated()),
            "files": get_server_files(scope_username=scope_username),
            "jobs": filtered_jobs,
            "dlna_manual_sync_notice": get_dlna_manual_sync_notice_state() if is_admin_authenticated() else {"pending": False},
        }

    def build_jobs_payload(scope_username):
        available_users = [item["username"] for item in get_users_snapshot()] if is_admin_authenticated() else []
        return {
            "logged_in": True,
            "current_user": get_current_username(),
            "admin_logged_in": is_admin_authenticated(),
            "available_users": available_users,
            "scope_username": scope_username,
            "mount": get_mount_info(auto_remount=True, viewer_username=scope_username or get_current_username(), is_admin=is_admin_authenticated()),
            "jobs": filter_jobs_for_viewer(get_jobs_snapshot(), scope_username=scope_username),
            "dlna_manual_sync_notice": get_dlna_manual_sync_notice_state() if is_admin_authenticated() else {"pending": False},
        }

    def enqueue_download_job(*, page_url, result, fmt, owner_username, overwrite_existing=False, auto_dlna_collection_id="", custom_filename=""):
        storage_kind = normalize_storage_kind(fmt.get("media_kind") or "video")
        is_live_capture = bool(result.get("is_live_stream") and result.get("supports_live_from_start"))
        download_title = result.get("download_title") or result["title"]
        filename = normalize_requested_download_filename(custom_filename, download_title, fmt)
        duplicate_state = get_source_download_match_state(
            result,
            fmt.get("format_id"),
            owner_username=owner_username,
            target_filename_override=filename,
        )
        if duplicate_state["same_quality_count"] and not overwrite_existing:
            return None, duplicate_state

        job = create_job(
            page_url,
            str(fmt.get("format_id") or ""),
            selection_signature={
                "media_kind": str(fmt.get("media_kind") or "").strip().lower(),
                "label": str(fmt.get("label") or "").strip(),
                "height": int(fmt.get("height") or 0),
                "width": int(fmt.get("width") or 0),
                "ext": str(fmt.get("ext") or "").strip().lower(),
            },
            owner_username=owner_username,
            storage_kind=storage_kind,
            title=result["title"],
            label=fmt.get("label") or fmt.get("format_id") or "",
            filename=filename,
            planned_filename=filename,
            overwrite_existing=overwrite_existing,
            replace_paths=[entry["path"] for entry in duplicate_state["same_quality"]],
            auto_dlna_collection_id=auto_dlna_collection_id,
            is_live_capture=is_live_capture,
            live_status=str(result.get("live_status") or ""),
        )
        return job, duplicate_state

    @app.route("/api/files", methods=["GET"])
    def api_files():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        scope_username = resolve_view_scope_username(request.args.get("user"), "files_view_scope")
        return jsonify(build_files_payload(scope_username))

    @app.route("/api/files/stream", methods=["GET"])
    def api_files_stream():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        scope_username = resolve_view_scope_username(request.args.get("user"), "files_view_scope")
        return create_sse_json_response(
            lambda: build_files_payload(scope_username),
            interval_seconds=3.0,
            retry_ms=3000,
        )

    @app.route("/api/jobs", methods=["GET"])
    def api_jobs():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        scope_username = resolve_view_scope_username(request.args.get("user"), "jobs_view_scope")
        return jsonify(build_jobs_payload(scope_username))

    @app.route("/api/jobs/stream", methods=["GET"])
    def api_jobs_stream():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        scope_username = resolve_view_scope_username(request.args.get("user"), "jobs_view_scope")
        return create_sse_json_response(
            lambda: build_jobs_payload(scope_username),
            interval_seconds=2.0,
            retry_ms=3000,
        )

    @app.route("/api/source-detail", methods=["GET"])
    def api_source_detail():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        page_url = str(request.args.get("page_url") or "").strip()
        format_id = str(request.args.get("format_id") or "").strip()

        if not is_valid_http_url(page_url):
            return jsonify({"ok": False, "error": "Nieprawidłowy page_url."}), 400

        if not format_id:
            return jsonify({"ok": False, "error": "Brak format_id."}), 400

        try:
            parsed = extract_video_data(page_url, force_refresh=False)
            result = build_result_with_proxy_urls(parsed, request.url_root)
            item = find_format(result, format_id)

            if not item:
                return jsonify({"ok": False, "error": "Nie znaleziono wybranego źródła."}), 404

            item = dict(item)
            item["target_filename"] = build_download_filename(result.get("download_title") or result["title"], item)
            item["existing_downloads"] = public_source_download_match_state(
                get_source_download_match_state(result, format_id, owner_username=get_current_username())
            )

            return jsonify({
                "ok": True,
                "title": result["title"],
                "page_url": result["page_url"],
                "item": item,
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/api/downloads", methods=["GET"])
    def api_downloads():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        scope_username = resolve_view_scope_username(request.args.get("user"), "files_view_scope")
        available_users = [item["username"] for item in get_users_snapshot()] if is_admin_authenticated() else []
        return jsonify({
            "logged_in": True,
            "current_user": get_current_username(),
            "admin_logged_in": is_admin_authenticated(),
            "available_users": available_users,
            "scope_username": scope_username,
            "mount": get_mount_info(auto_remount=True, viewer_username=scope_username or get_current_username(), is_admin=is_admin_authenticated()),
            "jobs": filter_jobs_for_viewer(get_jobs_snapshot(), scope_username=scope_username),
            "files": get_server_files(scope_username=scope_username),
        })

    @app.route("/enqueue-download", methods=["POST"])
    def enqueue_download():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        if not request.is_json:
            return jsonify({"ok": False, "error": "Wymagany JSON."}), 400

        payload = request.get_json(silent=True) or {}
        page_url = str(payload.get("page_url") or "").strip()
        format_id = str(payload.get("format_id") or "").strip()
        custom_filename = str(payload.get("custom_filename") or "").strip()
        overwrite_existing = bool(payload.get("overwrite_existing"))
        try:
            auto_dlna_collection_id = normalize_requested_auto_dlna_collection_id(payload.get("auto_dlna_collection_id"))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        if not is_valid_http_url(page_url):
            return jsonify({"ok": False, "error": "Nieprawidłowy page_url."}), 400

        if not format_id:
            return jsonify({"ok": False, "error": "Brak format_id."}), 400

        ok, message = ensure_share_ready(auto_remount=True)
        if not ok:
            return jsonify({
                "ok": False,
                "error": "Udział sieciowy offline. %s" % message
            }), 503

        try:
            owner_username = get_current_username()
            result = extract_video_data(page_url, force_refresh=False)
            fmt = find_format(result, format_id)
            if not fmt:
                return jsonify({"ok": False, "error": "Nie znaleziono wskazanego formatu."}), 404

            job, duplicate_state = enqueue_download_job(
                page_url=page_url,
                result=result,
                fmt=fmt,
                owner_username=owner_username,
                overwrite_existing=overwrite_existing,
                auto_dlna_collection_id=auto_dlna_collection_id,
                custom_filename=custom_filename,
            )
            if duplicate_state["same_quality_count"] and not overwrite_existing:
                return jsonify({
                    "ok": False,
                    "requires_confirmation": True,
                    "error": "Na serwerze istnieje już plik w tej samej jakości.",
                    "existing_downloads": public_source_download_match_state(duplicate_state),
                }), 409
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

        return jsonify({
            "ok": True,
            "job_id": job["job_id"],
            "status": job["status"],
            "is_live_capture": bool(job.get("is_live_capture")),
        }), 202

    @app.route("/api/quick-downloads", methods=["POST"])
    def api_quick_downloads():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        if not request.is_json:
            return jsonify({"ok": False, "error": "Wymagany JSON."}), 400

        payload = request.get_json(silent=True) or {}
        raw_urls = payload.get("urls_text")
        media_kind = normalize_storage_kind(payload.get("media_kind") or "video")

        try:
            auto_dlna_collection_id = normalize_requested_auto_dlna_collection_id(payload.get("auto_dlna_collection_id"))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        urls = extract_http_urls(raw_urls)
        if not urls:
            return jsonify({"ok": False, "error": "Nie znaleziono żadnych poprawnych linków http/https."}), 400

        if len(urls) > 50:
            return jsonify({"ok": False, "error": "Jednorazowo możesz dodać maksymalnie 50 linków."}), 400

        ok, message = ensure_share_ready(auto_remount=True)
        if not ok:
            return jsonify({
                "ok": False,
                "error": "Udział sieciowy offline. %s" % message
            }), 503

        owner_username = get_current_username()
        queued_jobs = []
        failed_items = []

        for page_url in urls:
            try:
                result = extract_video_data(page_url, force_refresh=False)
                sources = list(result.get("sources") or [])
                if not sources:
                    failed_items.append({
                        "url": page_url,
                        "error": "yt-dlp nie zwrócił żadnych źródeł dla tego linku.",
                    })
                    continue

                best_source = choose_best_source(
                    sources,
                    preferred_media_kind=media_kind,
                    extractor_name=result.get("extractor") or "",
                )
                if not best_source:
                    failed_items.append({
                        "url": page_url,
                        "error": "Nie znaleziono odpowiedniego źródła do szybkiego pobrania.",
                    })
                    continue

                job_source = dict(best_source)
                if media_kind == "audio":
                    job_source["media_kind"] = "audio"
                    job_source["has_audio"] = True

                job, duplicate_state = enqueue_download_job(
                    page_url=page_url,
                    result=result,
                    fmt=job_source,
                    owner_username=owner_username,
                    overwrite_existing=False,
                    auto_dlna_collection_id=auto_dlna_collection_id,
                )
                if duplicate_state["same_quality_count"]:
                    failed_items.append({
                        "url": page_url,
                        "error": "Ta sama jakość jest już na serwerze.",
                    })
                    continue

                queued_jobs.append({
                    "job_id": job["job_id"],
                    "url": page_url,
                    "title": job.get("title") or "",
                    "label": job.get("label") or "",
                    "is_live_capture": bool(job.get("is_live_capture")),
                })
            except Exception as exc:
                failed_items.append({
                    "url": page_url,
                    "error": str(exc),
                })

        return jsonify({
            "ok": bool(queued_jobs),
            "queued_count": len(queued_jobs),
            "live_queued_count": sum(1 for item in queued_jobs if item.get("is_live_capture")),
            "failed_count": len(failed_items),
            "queued_jobs": queued_jobs,
            "failed_items": failed_items,
            "remaining_urls_text": "\n".join(item["url"] for item in failed_items if item.get("url")),
            "media_kind": media_kind,
        }), (202 if queued_jobs else 400)

    @app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
    def api_cancel_job(job_id):
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        ok, message = mark_job_cancel_requested(job_id)
        if not ok:
            status_code = 404 if "Nie znaleziono zadania" in message else 403 if "Nie masz dostępu" in message else 409
            return jsonify({"ok": False, "error": message}), status_code

        return jsonify({"ok": True, "message": message})

    @app.route("/api/jobs/<job_id>/pause", methods=["POST"])
    def api_pause_job(job_id):
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        ok, message = mark_job_pause_requested(job_id)
        if not ok:
            status_code = 404 if "Nie znaleziono zadania" in message else 403 if "Nie masz dostępu" in message else 409
            return jsonify({"ok": False, "error": message}), status_code

        return jsonify({"ok": True, "message": message})

    @app.route("/api/jobs/<job_id>/resume", methods=["POST"])
    def api_resume_job(job_id):
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        ok, message = resume_job_download(job_id)
        if not ok:
            status_code = 404 if "Nie znaleziono zadania" in message else 403 if "Nie masz dostępu" in message else 409
            return jsonify({"ok": False, "error": message}), status_code

        return jsonify({"ok": True, "message": message})

    @app.route("/api/jobs/<job_id>/retry", methods=["POST"])
    def api_retry_job(job_id):
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        ok, message = ensure_share_ready(auto_remount=True)
        if not ok:
            return jsonify({
                "ok": False,
                "error": "Udział sieciowy offline. %s" % message
            }), 503

        ok, message, job = retry_job_download(job_id)
        if not ok:
            status_code = 404 if "Nie znaleziono zadania" in message else 403 if "Nie masz dostępu" in message else 409
            return jsonify({"ok": False, "error": message}), status_code

        return jsonify({
            "ok": True,
            "message": message,
            "job_id": str((job or {}).get("job_id") or ""),
        }), 202

    @app.route("/api/jobs/<job_id>/delete", methods=["POST"])
    def api_delete_job(job_id):
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        ok, message, status_code = delete_job(job_id)
        if not ok:
            return jsonify({"ok": False, "error": message}), status_code

        return jsonify({"ok": True})

    @app.route("/api/files/delete", methods=["POST"])
    def api_delete_file():
        auth_error = require_authenticated_json()
        if auth_error:
            return auth_error

        if not request.is_json:
            return jsonify({"ok": False, "error": "Wymagany JSON."}), 400

        payload = request.get_json(silent=True) or {}
        ok, message, status_code = delete_managed_file(
            payload.get("relative_path") or payload.get("filename") or "",
            storage_kind=payload.get("storage_kind") or "video",
            owner_username=payload.get("owner_username") or get_current_username(),
        )
        if not ok:
            return jsonify({"ok": False, "error": message}), status_code
        return jsonify({"ok": True})

    @app.route("/playlist", methods=["GET"])
    def playlist():
        if not is_authenticated():
            return Response("Zaloguj się, aby pobierać playlisty.\n", status=403, mimetype="text/plain; charset=utf-8")

        page_url = request.args.get("page_url", "").strip()

        if not is_valid_http_url(page_url):
            return Response("Nieprawidłowy page_url.\\n", status=400, mimetype="text/plain; charset=utf-8")

        try:
            result = extract_video_data(page_url, force_refresh=True)
            if not result["sources"]:
                return Response("Nie znaleziono źródeł wideo.\\n", status=404, mimetype="text/plain; charset=utf-8")

            content = deps["build_m3u"](
                title=result["title"],
                page_url=result["page_url"],
                base_url=request.url_root,
                sources=result["sources"],
            )
            filename = re.sub(r"[^a-zA-Z0-9._-]+", "_", result["title"])[:80] or "playlist"

            return Response(
                content,
                mimetype="audio/x-mpegurl",
                headers={"Content-Disposition": 'attachment; filename="%s.m3u"' % filename},
            )
        except Exception as exc:
            return Response(
                "Błąd generowania playlisty:\\n%s\\n" % exc,
                status=500,
                mimetype="text/plain; charset=utf-8",
            )

    @app.route("/single-playlist", methods=["GET"])
    def single_playlist():
        if not is_authenticated():
            return Response("Zaloguj się, aby pobierać playlisty.\n", status=403, mimetype="text/plain; charset=utf-8")

        page_url = request.args.get("page_url", "").strip()
        format_id = request.args.get("format_id", "").strip()

        if not is_valid_http_url(page_url):
            return Response("Nieprawidłowy page_url.\\n", status=400, mimetype="text/plain; charset=utf-8")

        if not format_id:
            return Response("Brak format_id.\\n", status=400, mimetype="text/plain; charset=utf-8")

        try:
            result = extract_video_data(page_url, force_refresh=True)
            fmt = find_format(result, format_id)
            if not fmt:
                return Response("Nie znaleziono format_id.\\n", status=404, mimetype="text/plain; charset=utf-8")

            content = deps["build_m3u"](
                title=result["title"],
                page_url=result["page_url"],
                base_url=request.url_root,
                sources=result["sources"],
                only_format_id=format_id,
            )

            suffix = fmt.get("label") or fmt.get("format_id") or "source"
            filename = re.sub(r"[^a-zA-Z0-9._-]+", "_", "%s_%s" % (result["title"], suffix))[:80] or "single_playlist"

            return Response(
                content,
                mimetype="audio/x-mpegurl",
                headers={"Content-Disposition": 'attachment; filename="%s.m3u"' % filename},
            )
        except Exception as exc:
            return Response(
                "Błąd generowania playlisty:\\n%s\\n" % exc,
                status=500,
                mimetype="text/plain; charset=utf-8",
            )

    @app.route("/proxy", methods=["GET"])
    def proxy():
        if not is_authenticated():
            return Response("Zaloguj się, aby korzystać z proxy strumieni.\n", status=403, mimetype="text/plain; charset=utf-8")

        page_url = request.args.get("page_url", "").strip()
        format_id = request.args.get("format_id", "").strip()

        if not is_valid_http_url(page_url):
            return Response("Nieprawidłowy page_url.\\n", status=400, mimetype="text/plain; charset=utf-8")

        if not format_id:
            return Response("Brak format_id.\\n", status=400, mimetype="text/plain; charset=utf-8")

        try:
            result = extract_video_data(page_url, force_refresh=True)
            fmt = find_format(result, format_id)
            if not fmt:
                return Response("Nie znaleziono wskazanego formatu.\\n", status=404, mimetype="text/plain; charset=utf-8")

            return stream_upstream_response(
                stream_url=fmt["url"],
                page_url=result["page_url"],
                fmt=fmt,
                download=False,
            )

        except Exception as exc:
            return Response(
                "Błąd proxy:\\n%s\\n" % exc,
                status=500,
                mimetype="text/plain; charset=utf-8",
            )

    @app.route("/download", methods=["GET"])
    def download():
        if not is_authenticated():
            return Response("Zaloguj się, aby pobierać pliki.\n", status=403, mimetype="text/plain; charset=utf-8")

        page_url = request.args.get("page_url", "").strip()
        format_id = request.args.get("format_id", "").strip()

        if not is_valid_http_url(page_url):
            return Response("Nieprawidłowy page_url.\\n", status=400, mimetype="text/plain; charset=utf-8")

        if not format_id:
            return Response("Brak format_id.\\n", status=400, mimetype="text/plain; charset=utf-8")

        try:
            result = extract_video_data(page_url, force_refresh=True)
            fmt = find_format(result, format_id)
            if not fmt:
                return Response("Nie znaleziono wskazanego formatu.\\n", status=404, mimetype="text/plain; charset=utf-8")

            filename = build_intermediate_download_filename(result.get("download_title") or result["title"], fmt)

            return stream_upstream_response(
                stream_url=fmt["url"],
                page_url=result["page_url"],
                fmt=fmt,
                download=True,
                download_filename=filename,
            )

        except Exception as exc:
            return Response(
                "Błąd pobierania:\\n%s\\n" % exc,
                status=500,
                mimetype="text/plain; charset=utf-8",
            )

    def serve_managed_file(storage_kind, filename, owner_username=None):
        if not is_authenticated():
            return Response(
                "Zaloguj się, aby otwierać pliki.\n",
                status=403,
                mimetype="text/plain; charset=utf-8",
            )

        requested_storage_id = str(request.args.get("storage") or "").strip().lower()
        parsed_relative = parse_managed_relative_path(filename)
        owner = normalize_username((parsed_relative or {}).get("owner_username") or owner_username or get_current_username() or DEFAULT_ADMIN_USERNAME)
        storage_kind = normalize_storage_kind((parsed_relative or {}).get("storage_kind") or storage_kind)
        user_relative_path = safe_relative_download_path((parsed_relative or {}).get("user_relative_path") or filename)
        storage_id = requested_storage_id or str((parsed_relative or {}).get("storage_id") or "").strip().lower()
        relative_path = build_managed_relative_path(owner, storage_kind, user_relative_path, storage_id=storage_id or None)
        path = resolve_download_path(relative_path, storage_kind, owner_username=owner, storage_id=storage_id or None)
        effective_path_info = parse_managed_relative_path(relative_path) or {}
        effective_storage_id = str(effective_path_info.get("storage_id") or storage_id or "").strip().lower()

        if effective_storage_id == "network":
            ok, message = ensure_share_ready(auto_remount=True)
            if not ok:
                return Response(
                    "Udział sieciowy offline.\\n%s\\n" % message,
                    status=503,
                    mimetype="text/plain; charset=utf-8",
                )

        if not path or not os.path.isfile(path):
            return Response(
                "Plik nie istnieje.\\n",
                status=404,
                mimetype="text/plain; charset=utf-8",
            )

        if not can_access_owner(owner):
            return Response(
                "Nie masz dostępu do tego pliku.\n",
                status=403,
                mimetype="text/plain; charset=utf-8",
            )

        return send_file(path, as_attachment=False, conditional=True)

    @app.route("/server-files/<owner_username>/<storage_kind>/<path:filename>", methods=["GET"])
    def server_file_with_owner_and_kind(owner_username, storage_kind, filename):
        return serve_managed_file(storage_kind, filename, owner_username=owner_username)

    @app.route("/server-files/<storage_kind>/<path:filename>", methods=["GET"])
    def server_file_with_kind(storage_kind, filename):
        return serve_managed_file(storage_kind, filename)

    @app.route("/server-files/<path:filename>", methods=["GET"])
    def server_file(filename):
        return serve_managed_file("video", filename)
