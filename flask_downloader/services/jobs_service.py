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
