class PageStateService:
    def __init__(
        self,
        *,
        get_mount_info,
        get_config_snapshot,
        get_daily_download_dir,
        get_all_maintenance_task_snapshots,
        get_storage_disk_state,
        refresh_ffmpeg_update_state,
        refresh_yt_dlp_update_state,
        refresh_app_update_state,
        refresh_dlna_package_state,
        refresh_radio_backend_package_state,
        get_dlna_service_state,
        get_radio_backend_service_state,
        get_flask_service_state,
        build_user_management_rows,
        get_dlna_page_state,
        get_authenticated_user,
        is_admin_authenticated,
        pop_ui_flash,
        render_template,
        base_page_template,
        request_path_getter,
    ):
        self._get_mount_info = get_mount_info
        self._get_config_snapshot = get_config_snapshot
        self._get_daily_download_dir = get_daily_download_dir
        self._get_all_maintenance_task_snapshots = get_all_maintenance_task_snapshots
        self._get_storage_disk_state = get_storage_disk_state
        self._refresh_ffmpeg_update_state = refresh_ffmpeg_update_state
        self._refresh_yt_dlp_update_state = refresh_yt_dlp_update_state
        self._refresh_app_update_state = refresh_app_update_state
        self._refresh_dlna_package_state = refresh_dlna_package_state
        self._refresh_radio_backend_package_state = refresh_radio_backend_package_state
        self._get_dlna_service_state = get_dlna_service_state
        self._get_radio_backend_service_state = get_radio_backend_service_state
        self._get_flask_service_state = get_flask_service_state
        self._build_user_management_rows = build_user_management_rows
        self._get_dlna_page_state = get_dlna_page_state
        self._get_authenticated_user = get_authenticated_user
        self._is_admin_authenticated = is_admin_authenticated
        self._pop_ui_flash = pop_ui_flash
        self._render_template = render_template
        self._base_page_template = base_page_template
        self._request_path_getter = request_path_getter

    def get_settings_page_state(self, include_user_rows=False):
        state = {
            "mount": self._get_mount_info(auto_remount=False),
            "config": self._get_config_snapshot(),
            "today_download_dir": self._get_daily_download_dir(),
            "today_audio_download_dir": self._get_daily_download_dir(media_kind="audio"),
            "storage_disk_state": self._get_storage_disk_state(),
            "maintenance_tasks": self._get_all_maintenance_task_snapshots(),
            "ffmpeg_state": self._refresh_ffmpeg_update_state(force=False),
            "yt_dlp_state": self._refresh_yt_dlp_update_state(force=False),
            "app_update_state": self._refresh_app_update_state(force=False),
            "dlna_package_state": self._refresh_dlna_package_state(force=False),
            "radio_backend_package_state": self._refresh_radio_backend_package_state(force=False),
            "dlna_service_state": self._get_dlna_service_state(),
            "radio_backend_service_state": self._get_radio_backend_service_state(),
            "service_state": self._get_flask_service_state(),
        }
        if include_user_rows:
            state["user_rows"] = self._build_user_management_rows()
        return state

    def get_dlna_page_state(self):
        return self._get_dlna_page_state()

    def render_page(self, page_title, active_page, content_template, **context):
        auth_user = self._get_authenticated_user()
        admin_logged_in = self._is_admin_authenticated()
        current_user = auth_user or {}
        template_context = dict(context)
        return self._render_template(
            self._base_page_template,
            page_template=content_template,
            page_title=page_title,
            active_page=active_page,
            current_path=self._request_path_getter(),
            admin_logged_in=admin_logged_in,
            logged_in=bool(auth_user),
            current_user=current_user,
            current_role=str(current_user.get("role") or ""),
            flash=self._pop_ui_flash(),
            **template_context
        )


__all__ = ["PageStateService"]
