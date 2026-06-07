import time


class DlnaRuntimeService:
    def __init__(
        self,
        *,
        sync_lock,
        ensure_dlna_runtime_dirs,
        ensure_share_ready,
        get_server_files,
        prune_missing_dlna_media_rules,
        get_dlna_config_snapshot,
        normalize_dlna_config,
        set_dlna_config,
        filter_dlna_export_files,
        clear_dlna_manual_sync_needed,
        get_dlna_package_state_snapshot,
        get_generic_service_state,
        ensure_dlna_service_started_impl,
        ensure_dlna_service_stopped_impl,
        clear_dlna_database_files,
        write_dlna_gerbera_config,
        validate_dlna_gerbera_config,
        write_dlna_service_unit,
        run_systemctl_command,
        save_dlna_runtime_status,
        get_dlna_feature_support,
        format_dlna_service_error,
        run_systemctl_command_result,
        ensure_no_conflicting_dlna_listener,
        wait_for_dlna_service_stable,
        wait_for_dlna_service_stopped,
        dlna_virtual_layout_version,
        dlna_service_name,
        dlna_system_service_name,
        dlna_config_xml_file,
        dlna_export_root,
        dlna_service_unit_file,
    ):
        self._sync_lock = sync_lock
        self._ensure_dlna_runtime_dirs = ensure_dlna_runtime_dirs
        self._ensure_share_ready = ensure_share_ready
        self._get_server_files = get_server_files
        self._prune_missing_dlna_media_rules = prune_missing_dlna_media_rules
        self._get_dlna_config_snapshot = get_dlna_config_snapshot
        self._normalize_dlna_config = normalize_dlna_config
        self._set_dlna_config = set_dlna_config
        self._filter_dlna_export_files = filter_dlna_export_files
        self._clear_dlna_manual_sync_needed = clear_dlna_manual_sync_needed
        self._get_dlna_package_state_snapshot = get_dlna_package_state_snapshot
        self._get_generic_service_state = get_generic_service_state
        self._ensure_dlna_service_started_impl = ensure_dlna_service_started_impl
        self._ensure_dlna_service_stopped_impl = ensure_dlna_service_stopped_impl
        self._clear_dlna_database_files = clear_dlna_database_files
        self._write_dlna_gerbera_config = write_dlna_gerbera_config
        self._validate_dlna_gerbera_config = validate_dlna_gerbera_config
        self._write_dlna_service_unit = write_dlna_service_unit
        self._run_systemctl_command = run_systemctl_command
        self._save_dlna_runtime_status = save_dlna_runtime_status
        self._get_dlna_feature_support = get_dlna_feature_support
        self._format_dlna_service_error = format_dlna_service_error
        self._run_systemctl_command_result = run_systemctl_command_result
        self._ensure_no_conflicting_dlna_listener = ensure_no_conflicting_dlna_listener
        self._wait_for_dlna_service_stable = wait_for_dlna_service_stable
        self._wait_for_dlna_service_stopped = wait_for_dlna_service_stopped
        self._dlna_virtual_layout_version = dlna_virtual_layout_version
        self._dlna_service_name = dlna_service_name
        self._dlna_system_service_name = dlna_system_service_name
        self._dlna_config_xml_file = dlna_config_xml_file
        self._dlna_export_root = dlna_export_root
        self._dlna_service_unit_file = dlna_service_unit_file

    def build_service_failure_detail(self, state, fallback_detail=""):
        parts = []
        fallback_text = str(fallback_detail or "").strip()
        if fallback_text:
            parts.append(fallback_text)
        formatted_state_error = self._format_dlna_service_error(state)
        if formatted_state_error and formatted_state_error not in parts:
            parts.append(formatted_state_error)
        return " | ".join(parts)

    def ensure_service_started(self, enable_unit=False, timeout=90, failure_label="startu"):
        return self._ensure_dlna_service_started_impl(
            enable_unit=enable_unit,
            timeout=timeout,
            failure_label=failure_label,
        )

    def ensure_service_stopped(self, timeout=90, reset_failed_after_stop=True):
        return self._ensure_dlna_service_stopped_impl(
            timeout=timeout,
            reset_failed_after_stop=reset_failed_after_stop,
        )

    def sync_runtime(
        self,
        restart_service_if_active=False,
        force_full_rescan=False,
        include_pending_downloads=True,
    ):
        with self._sync_lock:
            self._ensure_dlna_runtime_dirs()
            try:
                self._ensure_share_ready(auto_remount=True)
            except Exception:
                pass
            files = self._get_server_files()
            prune_result = self._prune_missing_dlna_media_rules(
                files=files,
                sync_runtime=False,
                restart_service_if_active=restart_service_if_active,
            )
            dlna_config = self._normalize_dlna_config(prune_result.get("config"))
            layout_upgraded = int(dlna_config.get("layout_version") or 0) < self._dlna_virtual_layout_version
            if layout_upgraded:
                dlna_config["layout_version"] = self._dlna_virtual_layout_version
                self._set_dlna_config(dlna_config)
                dlna_config = self._normalize_dlna_config(dlna_config)

            package_state = self._get_dlna_package_state_snapshot()
            current_service_state = (
                self._get_generic_service_state(self._dlna_service_name)
                if package_state["installed"]
                else {}
            )
            service_was_active = current_service_state.get("active_state") == "active"
            should_restart_after_sync = bool(restart_service_if_active) and service_was_active

            if force_full_rescan and service_was_active:
                self.ensure_service_stopped(timeout=90)
                should_restart_after_sync = True

            if layout_upgraded and service_was_active:
                self.ensure_service_stopped(timeout=90)
                should_restart_after_sync = True

            if layout_upgraded or force_full_rescan:
                self._clear_dlna_database_files()

            export_files = self._filter_dlna_export_files(
                files,
                dlna_config=dlna_config,
                include_pending_downloads=include_pending_downloads,
            )
            export_state = self._write_dlna_gerbera_config(dlna_config, files=export_files)

            if package_state["installed"]:
                allow_runtime_probe = not should_restart_after_sync
                self._validate_dlna_gerbera_config(allow_runtime_probe=allow_runtime_probe)
                self._write_dlna_service_unit()
                self._run_systemctl_command("daemon-reload")
                if should_restart_after_sync:
                    self.ensure_service_started(enable_unit=False, timeout=90, failure_label="restartu")

            if include_pending_downloads:
                self._clear_dlna_manual_sync_needed()
            self._save_dlna_runtime_status(last_sync_at=time.time(), last_sync_error="")
            return export_state

    def sync_runtime_safe(
        self,
        restart_service_if_active=False,
        force_full_rescan=False,
        include_pending_downloads=True,
    ):
        try:
            self.sync_runtime(
                restart_service_if_active=restart_service_if_active,
                force_full_rescan=force_full_rescan,
                include_pending_downloads=include_pending_downloads,
            )
        except Exception as exc:
            self._save_dlna_runtime_status(last_sync_error=str(exc))

    def get_service_state(self):
        dlna_config = self._get_dlna_config_snapshot()
        package_state = self._get_dlna_package_state_snapshot()
        feature_support = self._get_dlna_feature_support(package_state.get("current_version_raw"))
        state = self._get_generic_service_state(self._dlna_service_name)
        state["desired_enabled"] = bool(dlna_config.get("enabled"))
        state["package_installed"] = bool(package_state["installed"])
        state["package_version"] = package_state["current_version"]
        state["toggle_button_label"] = "Wyłącz serwer DLNA" if dlna_config.get("enabled") else "Włącz serwer DLNA"
        state["restart_button_label"] = "Uruchom ponownie serwer DLNA"
        state["config_file"] = self._dlna_config_xml_file
        state["export_root"] = self._dlna_export_root
        state["service_unit_file"] = self._dlna_service_unit_file
        state["feature_support"] = feature_support
        return state

    def set_service_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled:
            package_state = self._get_dlna_package_state_snapshot()
            if not package_state["installed"]:
                raise RuntimeError("Najpierw zainstaluj pakiet Gerbera z poziomu konfiguracji.")
            dlna_config = self._get_dlna_config_snapshot()
            dlna_config["enabled"] = True
            self._set_dlna_config(dlna_config)
            self.sync_runtime(restart_service_if_active=False)
            self.ensure_service_started(enable_unit=True, timeout=90, failure_label="startu")
        else:
            dlna_config = self._get_dlna_config_snapshot()
            dlna_config["enabled"] = False
            self._set_dlna_config(dlna_config)
            package_state = self._get_dlna_package_state_snapshot()
            if package_state["installed"]:
                disable_result = self._run_systemctl_command_result("disable", self._dlna_service_name, timeout=90)
                self.ensure_service_stopped(timeout=90)
                if disable_result["returncode"] != 0:
                    raise RuntimeError(
                        disable_result.get("detail")
                        or "Nie udało się wyłączyć autostartu serwera DLNA."
                    )

        return self.get_service_state()

    def restart_service_now(self):
        package_state = self._get_dlna_package_state_snapshot()
        if not package_state["installed"]:
            raise RuntimeError("Serwer DLNA nie jest jeszcze zainstalowany.")
        self.sync_runtime(restart_service_if_active=False)
        service_state = self.get_service_state()
        if service_state.get("active_state") == "active" or str(service_state.get("main_pid") or "").strip() not in ("", "0"):
            self.ensure_service_stopped(timeout=90)
        self.ensure_service_started(enable_unit=False, timeout=90, failure_label="restartu")
        return self.get_service_state()
