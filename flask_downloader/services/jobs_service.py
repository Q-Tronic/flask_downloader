import os
import threading
import time
import uuid


class JobViewService:
    def __init__(self, *, get_current_username, is_admin_authenticated, normalize_username, default_admin_username):
        self._get_current_username = get_current_username
        self._is_admin_authenticated = is_admin_authenticated
        self._normalize_username = normalize_username
        self._default_admin_username = default_admin_username

    def filter_jobs_for_viewer(self, jobs, scope_username=""):
        viewer_username = self._get_current_username()
        admin_view = self._is_admin_authenticated()
        selected_owner = ""
        if admin_view and scope_username:
            try:
                selected_owner = self._normalize_username(scope_username)
            except Exception:
                selected_owner = ""

        visible_jobs = []
        for job in jobs:
            owner_username = self._normalize_username(job.get("owner_username") or self._default_admin_username)
            if admin_view:
                if selected_owner and owner_username != selected_owner:
                    continue
            elif owner_username != viewer_username:
                continue
            visible_jobs.append(job)
        return visible_jobs


class DownloadJobsService:
    def __init__(
        self,
        *,
        jobs_store,
        cancel_events_store,
        jobs_lock,
        default_admin_username,
        normalize_username,
        normalize_storage_kind,
        get_current_username,
        is_admin_authenticated,
        get_completed_job_retention_seconds,
        write_download_jobs_locked,
        download_worker,
        can_access_owner,
        safe_relative_download_path,
        parse_managed_relative_path,
        resolve_download_path,
        cleanup_empty_download_dirs,
        ensure_share_ready,
        sync_dlna_runtime_safe,
        get_relative_download_path,
        build_managed_file_url,
        format_relative_path_for_user,
    ):
        self._jobs_store = jobs_store
        self._cancel_events_store = cancel_events_store
        self._jobs_lock = jobs_lock
        self._default_admin_username = default_admin_username
        self._normalize_username = normalize_username
        self._normalize_storage_kind = normalize_storage_kind
        self._get_current_username = get_current_username
        self._is_admin_authenticated = is_admin_authenticated
        self._get_completed_job_retention_seconds = get_completed_job_retention_seconds
        self._write_download_jobs_locked = write_download_jobs_locked
        self._download_worker = download_worker
        self._can_access_owner = can_access_owner
        self._safe_relative_download_path = safe_relative_download_path
        self._parse_managed_relative_path = parse_managed_relative_path
        self._resolve_download_path = resolve_download_path
        self._cleanup_empty_download_dirs = cleanup_empty_download_dirs
        self._ensure_share_ready = ensure_share_ready
        self._sync_dlna_runtime_safe = sync_dlna_runtime_safe
        self._get_relative_download_path = get_relative_download_path
        self._build_managed_file_url = build_managed_file_url
        self._format_relative_path_for_user = format_relative_path_for_user

    def update_job(self, job_id, **kwargs):
        with self._jobs_lock:
            job = self._jobs_store.get(job_id)
            if not job:
                return
            persist = bool(kwargs.pop("persist", False))
            job.update(kwargs)
            if persist:
                self._write_download_jobs_locked()

    def create_job(self, page_url, format_id, **kwargs):
        self.purge_expired_jobs()

        job_id = uuid.uuid4().hex
        cancel_event = threading.Event()
        now_ts = time.time()
        owner_username = self._normalize_username(
            kwargs.get("owner_username") or self._get_current_username() or self._default_admin_username
        )

        job = {
            "job_id": job_id,
            "owner_username": owner_username,
            "page_url": page_url,
            "format_id": format_id,
            "storage_kind": self._normalize_storage_kind(kwargs.get("storage_kind") or "video"),
            "status": "queued",
            "status_label": "W kolejce",
            "title": str(kwargs.get("title") or ""),
            "label": str(kwargs.get("label") or ""),
            "filename": str(kwargs.get("filename") or ""),
            "filepath": "",
            "relative_path": "",
            "downloaded_bytes": 0,
            "total_bytes": None,
            "progress_percent": 0.0,
            "error": "",
            "created_at": now_ts,
            "started_at": None,
            "finished_at": None,
            "planned_filename": str(kwargs.get("planned_filename") or ""),
            "overwrite_existing": bool(kwargs.get("overwrite_existing")),
            "replace_paths": [str(path) for path in (kwargs.get("replace_paths") or []) if path],
        }

        with self._jobs_lock:
            self._jobs_store[job_id] = job
            self._cancel_events_store[job_id] = cancel_event
            self._write_download_jobs_locked()

        thread = threading.Thread(
            target=self._download_worker,
            args=(job_id,),
            daemon=True,
        )
        thread.start()

        return job

    def mark_job_cancel_requested(self, job_id):
        with self._jobs_lock:
            event = self._cancel_events_store.get(job_id)
            job = self._jobs_store.get(job_id)
            if not job:
                return False, "Nie znaleziono zadania."

            if not self._can_access_owner(job.get("owner_username") or self._default_admin_username):
                return False, "Nie masz dostępu do tego zadania."

            if job.get("status") in ("completed", "failed", "canceled"):
                return False, "Tego zadania nie można już przerwać."

            if event is None:
                return False, "Brak uchwytu anulowania dla zadania."

            event.set()
            job["status_label"] = "Anulowanie..."
            self._write_download_jobs_locked()
            return True, "Wysłano żądanie anulowania."

    def cleanup_job_cancel_handle(self, job_id):
        with self._jobs_lock:
            if job_id in self._cancel_events_store:
                del self._cancel_events_store[job_id]

    def purge_expired_jobs(self, now_ts=None):
        now_ts = now_ts or time.time()
        cutoff_ts = now_ts - self._get_completed_job_retention_seconds()
        changed = False

        with self._jobs_lock:
            for job_id, job in list(self._jobs_store.items()):
                if job.get("status") not in ("completed", "failed", "canceled"):
                    continue

                finished_at = job.get("finished_at")
                if not finished_at or finished_at > cutoff_ts:
                    continue

                self._jobs_store.pop(job_id, None)
                self._cancel_events_store.pop(job_id, None)
                changed = True

            if changed:
                self._write_download_jobs_locked()

    def get_jobs_snapshot(self):
        self.purge_expired_jobs()

        with self._jobs_lock:
            jobs = [dict(job) for job in self._jobs_store.values()]

        jobs.sort(key=lambda item: item.get("created_at") or 0, reverse=True)

        for job in jobs:
            owner_username = self._normalize_username(job.get("owner_username") or self._default_admin_username)
            job["owner_username"] = owner_username
            storage_kind = self._normalize_storage_kind(job.get("storage_kind") or "video")
            job["storage_kind"] = storage_kind
            if job.get("status") == "completed":
                job["progress_percent"] = 100.0
            elif job.get("status") == "canceled":
                if job.get("total_bytes") and job.get("downloaded_bytes") is not None:
                    try:
                        job["progress_percent"] = round(
                            (float(job["downloaded_bytes"]) * 100.0) / float(job["total_bytes"]),
                            1,
                        )
                    except Exception:
                        job["progress_percent"] = 0.0
                else:
                    job["progress_percent"] = 0.0
            elif job.get("total_bytes") and job.get("downloaded_bytes") is not None:
                try:
                    job["progress_percent"] = round(
                        (float(job["downloaded_bytes"]) * 100.0) / float(job["total_bytes"]),
                        1,
                    )
                except Exception:
                    job["progress_percent"] = None
            elif job.get("status") == "downloading":
                job["progress_percent"] = None

            resolved_path = job.get("filepath") or self._resolve_download_path(
                job.get("relative_path"),
                storage_kind,
                owner_username=owner_username,
            )
            relative_path = self._safe_relative_download_path(
                job.get("relative_path") or self._get_relative_download_path(resolved_path, storage_kind, owner_username)
            )
            if relative_path and resolved_path and os.path.exists(resolved_path):
                job["relative_path"] = relative_path
                job["file_url"] = self._build_managed_file_url(owner_username, storage_kind, relative_path)
                job["file_display_name"] = self._format_relative_path_for_user(
                    relative_path,
                    viewer_username=self._get_current_username(),
                    is_admin=self._is_admin_authenticated(),
                )
            else:
                job["file_url"] = None
                job["file_display_name"] = job.get("filename") or ""

            job["can_delete_from_list"] = job.get("status") in ("completed", "failed", "canceled")
            job["can_cancel"] = job.get("status") in ("queued", "downloading")

        return jobs

    def delete_job(self, job_id):
        with self._jobs_lock:
            job = self._jobs_store.get(job_id)
            if not job:
                return False, "Nie znaleziono zadania.", 404

            if not self._can_access_owner(job.get("owner_username") or self._default_admin_username):
                return False, "Nie masz dostępu do tego zadania.", 403

            if job.get("status") in ("queued", "downloading"):
                return False, "Najpierw przerwij aktywne pobieranie.", 409

            del self._jobs_store[job_id]
            self._cancel_events_store.pop(job_id, None)
            self._write_download_jobs_locked()

        return True, "", 200

    def delete_managed_file(self, relative_path, *, storage_kind="video", owner_username=None):
        safe_relative_path = self._safe_relative_download_path(relative_path)
        parsed_relative = self._parse_managed_relative_path(safe_relative_path)
        owner = self._normalize_username(
            (parsed_relative or {}).get("owner_username")
            or owner_username
            or self._get_current_username()
            or self._default_admin_username
        )
        kind = self._normalize_storage_kind((parsed_relative or {}).get("storage_kind") or storage_kind or "video")

        ok, message = self._sync_or_share_ready()
        if not ok:
            return False, "Udział sieciowy offline. %s" % message, 503

        if not safe_relative_path:
            return False, "Brak ścieżki pliku.", 400

        if not self._can_access_owner(owner):
            return False, "Nie masz dostępu do tego pliku.", 403

        path = self._resolve_download_path(safe_relative_path, kind, owner_username=owner)
        if not path:
            return False, "Nieprawidłowa ścieżka pliku.", 400

        if not os.path.isfile(path):
            return False, "Plik nie istnieje.", 404

        try:
            os.remove(path)
            self._cleanup_empty_download_dirs(path)

            with self._jobs_lock:
                for job in self._jobs_store.values():
                    if self._normalize_storage_kind(job.get("storage_kind") or "video") != kind:
                        continue
                    if self._normalize_username(job.get("owner_username") or self._default_admin_username) != owner:
                        continue
                    if job.get("filepath") == path or self._safe_relative_download_path(job.get("relative_path")) == safe_relative_path:
                        job["filepath"] = ""
                        job["relative_path"] = ""
                self._write_download_jobs_locked()

            self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
            return True, "", 200
        except Exception as exc:
            return False, str(exc), 500

    def _sync_or_share_ready(self):
        return self._ensure_share_ready(auto_remount=True)
