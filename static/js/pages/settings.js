(function() {
    const pageData = window.pageBootstrapData || {};
    const root = document.getElementById("settingsMaintenancePage");
    if (!root) {
        return;
    }

    const pollIntervalMs = 1000;
    let liveSubscription = null;
    const dirtyForms = new Set();

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function setText(id, value) {
        const node = document.getElementById(id);
        if (!node) {
            return;
        }
        node.textContent = String(value ?? "");
    }

    function setValue(id, value) {
        const node = document.getElementById(id);
        if (!node) {
            return;
        }
        node.value = String(value ?? "");
    }

    function setHidden(id, hidden) {
        const node = document.getElementById(id);
        if (!node) {
            return;
        }
        node.hidden = !!hidden;
    }

    function setPill(id, kind, label) {
        const node = document.getElementById(id);
        if (!node) {
            return;
        }
        node.className = "service-status-pill " + String(kind || "muted");
        node.textContent = String(label || "");
    }

    function showToast(message, kind) {
        const host = document.querySelector(".toast-host");
        if (!host) {
            return;
        }

        const toast = document.createElement("div");
        toast.className = "toast " + String(kind || "success");
        toast.setAttribute("role", "status");
        toast.textContent = String(message || "");
        host.appendChild(toast);

        setTimeout(function() {
            toast.classList.add("is-leaving");
            setTimeout(function() {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 600);
        }, 4200);
    }

    function formatPercent(value) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) {
            return "...";
        }
        return Number(value).toFixed(1) + "%";
    }

    function getTaskProgressBarClass(task) {
        if (!task) {
            return "queued";
        }
        if (task.active) {
            return "downloading";
        }
        if (task.status === "success") {
            return "completed";
        }
        if (task.status === "error") {
            return "error";
        }
        return "queued";
    }

    function setFormBusy(form, busy, busyLabel, submitter) {
        const buttons = form ? Array.from(form.querySelectorAll("button")) : [];
        if (!buttons.length) {
            return;
        }

        buttons.forEach(function(button) {
            if (!button.dataset.idleLabel) {
                button.dataset.idleLabel = String(button.textContent || "").trim();
            }
            button.disabled = !!busy;
            if (!busy) {
                button.textContent = button.dataset.idleLabel || button.textContent;
            }
        });

        if (busy) {
            const targetButton = submitter instanceof HTMLButtonElement ? submitter : buttons[0];
            targetButton.textContent = String(busyLabel || "Trwa...");
        }
    }

    function isProtectedFormDirty(formId) {
        return dirtyForms.has(String(formId || ""));
    }

    function markProtectedFormDirty(form) {
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        if (form.dataset.protectState !== "true") {
            return;
        }
        if (!form.id) {
            return;
        }
        dirtyForms.add(form.id);
    }

    function clearProtectedFormDirty(form) {
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        if (!form.id) {
            return;
        }
        dirtyForms.delete(form.id);
    }

    function updateTaskPanel(prefix, task, runningLabelFallback) {
        const panel = document.getElementById(prefix + "TaskPanel");
        const progress = document.getElementById(prefix + "TaskProgress");
        const bar = document.getElementById(prefix + "TaskBar");
        if (!panel || !progress || !bar) {
            return;
        }

        const visible = !!(task && task.visible);
        panel.hidden = !visible;

        if (!visible) {
            return;
        }

        setPill(prefix + "TaskStatusPill", task.status_kind, task.status_label || runningLabelFallback);
        setText(prefix + "TaskLabel", task.title || runningLabelFallback);
        setText(prefix + "TaskPercent", formatPercent(task.progress_percent));
        setText(prefix + "TaskDetail", task.detail || task.message || "Trwa przetwarzanie zadania.");

        let timeText = "";
        if (task.active && task.started_at_text) {
            timeText = "Start: " + task.started_at_text;
        } else if (task.finished_at_text) {
            timeText = "Zakończono: " + task.finished_at_text;
        }
        setText(prefix + "TaskTime", timeText);

        if (task.progress_percent === null || task.progress_percent === undefined) {
            progress.classList.add("is-indeterminate");
            bar.style.width = "38%";
        } else {
            progress.classList.remove("is-indeterminate");
            bar.style.width = Math.max(0, Math.min(100, Number(task.progress_percent) || 0)) + "%";
        }

        bar.className = "progress-bar " + getTaskProgressBarClass(task);
    }

    function setGroupBusy(taskKey, task, busyLabel) {
        const forms = root.querySelectorAll('[data-maintenance-lock="' + taskKey + '"]');
        const active = !!(task && task.active);

        forms.forEach(function(form) {
            if (form.dataset.maintenanceStart) {
                setFormBusy(form, active, busyLabel);
            } else {
                setFormBusy(form, active, "");
            }
        });
    }

    function applyMountState(mount) {
        if (!mount) {
            return;
        }

        const node = document.getElementById("settingsMountStatus");
        if (!node) {
            return;
        }

        const online = !!mount.online;
        node.className = "page-status-inline " + (online ? "is-online" : "is-offline");
        node.title = String(mount.message || "");
        node.innerHTML = `
            <span class="page-status-icon" aria-hidden="true"></span>
            <span class="page-status-text">
                <span class="page-status-icon-dot" aria-hidden="true"></span>
                ${online ? "Serwer danych online" : "Serwer danych offline"}
            </span>
        `;
    }

    function toggleNetworkFields(activeBackend) {
        const node = document.getElementById("settingsNetworkFields");
        if (!node) {
            return;
        }
        node.hidden = String(activeBackend || "local") !== "network";
    }

    function applyStorageSummary(config, mount) {
        if (!config || !mount) {
            return;
        }
        const activeBackendLabel = mount.active_backend_label || (String(mount.active_backend || "") === "network" ? "Udział sieciowy" : "Lokalny serwer");
        const accessLabel = mount.read_ok ? (mount.write_ok ? "OK / OK" : "OK / brak zapisu") : "brak dostępu";
        setText("settingsActiveBackendValue", activeBackendLabel);
        setText("settingsActiveStorageRootValue", mount.active_root || config.user_storage_root || "");
        setText("settingsStorageAccessValue", accessLabel);
        setText("settingsNetworkLastTestValue", mount.network_last_test_at_text || "-");
        setText("settingsNetworkLastTestMessageValue", mount.network_last_test_message || "Brak testu udziału sieciowego.");
    }

    function applyConfigState(config, mount, todayDownloadDir, todayAudioDownloadDir) {
        if (!config) {
            return;
        }

        setText("settingsUserStorageRootValue", config.user_storage_root || "");
        setText("settingsDownloadRootValue", config.download_root || "");
        setText("settingsAudioDownloadRootValue", config.audio_download_root || "");
        setText("settingsTodayDownloadDirValue", todayDownloadDir || "");
        setText("settingsTodayAudioDownloadDirValue", todayAudioDownloadDir || "");
        setText("settingsRetentionDaysValue", String(config.job_retention_days || "") + " dni");

        applyStorageSummary(config, mount || {});

        const storage = config.storage || {};
        const local = storage.local || {};
        const network = storage.network || {};
        const configFormDirty = isProtectedFormDirty("settingsConfigForm");

        if (!configFormDirty) {
            setValue("jobRetentionDays", config.job_retention_days || "");
            setValue("activeStorageBackend", storage.active_backend || "local");
            setValue("localStorageRoot", local.root || "");
            setValue("networkShare", network.share || "");
            setValue("networkSubpath", network.subpath || "");
            setValue("networkMountDir", network.mount_dir || "");
            setValue("networkUsername", network.username || "");
            setValue("networkDomain", network.domain || "");
            setValue("networkCredentialsFile", network.credentials_file || "");
            setValue("networkCifsVersion", network.cifs_version || "3.0");
            setValue("networkIocharset", network.iocharset || "utf8");
            const keepExistingPassword = document.getElementById("keepExistingNetworkPassword");
            if (keepExistingPassword) {
                keepExistingPassword.checked = !!network.password_saved;
            }
            const networkPassword = document.getElementById("networkPassword");
            if (networkPassword) {
                networkPassword.value = "";
            }
        }

        toggleNetworkFields(storage.active_backend || "local");
        setText("settingsLocalUsersRootHint", (local.root || "") + "/flask_downloader_users/login/video/" + String((todayDownloadDir || "").split("/").pop() || "YYYY-MM-DD") + "/plik.mp4");
        setText("settingsNetworkUsersRootHint", (network.mount_dir || "") + "/flask_downloader_users/login/video/" + String((todayDownloadDir || "").split("/").pop() || "YYYY-MM-DD") + "/plik.mp4");
        setText(
            "settingsKeepPasswordLabel",
            "Zachowaj zapisane hasło SMB" + (network.password_saved ? " (plik poświadczeń jest już zapisany)" : "")
        );
    }

    function renderUserRows(rows) {
        const container = document.getElementById("userManagementList");
        if (!container) {
            return;
        }

        if (!Array.isArray(rows) || !rows.length) {
            container.innerHTML = '<div class="empty">Brak użytkowników w systemie.</div>';
            return;
        }

        container.innerHTML = rows.map(function(user) {
            const username = escapeHtml(user.username || "");
            const role = escapeHtml(user.role || "user");
            const createdAtText = escapeHtml(user.created_at_text || "");
            const editHtml = user.can_edit
                ? `
                    <form method="post" action="/settings/users/update" class="dlna-inline-form is-wide" data-settings-async="true" data-busy-label="Zapisywanie użytkownika...">
                        <input type="hidden" name="original_username" value="${username}">
                        <div class="field-group">
                            <label class="field-label">Login</label>
                            <input type="text" name="username" value="${username}" required>
                        </div>
                        <div class="field-group">
                            <label class="field-label">Rola</label>
                            <select name="role">
                                <option value="user"${role === "user" ? " selected" : ""}>Użytkownik</option>
                                <option value="admin"${role === "admin" ? " selected" : ""}>Administrator</option>
                            </select>
                        </div>
                        <div class="field-group">
                            <label class="field-label">&nbsp;</label>
                            <button type="submit" class="btn full-width">Zapisz zmiany</button>
                        </div>
                    </form>
                `
                : "";
            const resetPasswordHtml = user.can_admin_reset_password
                ? `
                    <form method="post" action="/settings/users/reset-password" class="dlna-inline-form is-wide" data-settings-async="true" data-reset-after-success="true" data-busy-label="Resetowanie hasła...">
                        <input type="hidden" name="username" value="${username}">
                        <div class="field-group">
                            <label class="field-label">Nowe hasło</label>
                            <input type="password" name="new_password" placeholder="minimum 4 znaki" required>
                        </div>
                        <div class="field-group">
                            <label class="field-label">&nbsp;</label>
                            <div class="inline-note">Administrator ustawia nowe hasło bez znajomości starego.</div>
                        </div>
                        <div class="field-group">
                            <label class="field-label">&nbsp;</label>
                            <button type="submit" class="btn btn-secondary full-width">Resetuj hasło</button>
                        </div>
                    </form>
                `
                : "";
            const deleteHtml = user.can_delete
                ? `
                    <form method="post" action="/settings/users/delete" class="dlna-inline-form is-single" data-settings-async="true" data-busy-label="Usuwanie użytkownika..." data-confirm-message="Usunąć użytkownika ${username} wraz z jego plikami i zadaniami?">
                        <input type="hidden" name="username" value="${username}">
                        <button type="submit" class="btn btn-delete">Usuń użytkownika</button>
                    </form>
                `
                : "";
            const noteParts = [];
            if (user.is_current_user) {
                noteParts.push('<div class="inline-note">Własnego loginu i roli nie zmienisz w tym panelu. Własne hasło zmienisz z sekcji <code>Konto</code> po lewej stronie.</div>');
            }
            if (user.is_default_admin) {
                noteParts.push('<div class="inline-note">To jest domyślne konto administratora. Nie usuniesz go ani nie zmienisz mu loginu lub roli w tym panelu.</div>');
            }
            const notesHtml = noteParts.join("");

            return `
                <div class="dlna-item">
                    <div class="dlna-item-head">
                        <div>
                            <div class="dlna-item-title">${username}</div>
                            <div class="dlna-item-meta">
                                Rola: ${role} • Pliki: ${escapeHtml(user.file_count || 0)} • Zadania: ${escapeHtml(user.job_count || 0)} • Utworzono: ${createdAtText || "-"}
                            </div>
                        </div>
                        <div class="dlna-item-head-actions">
                            <span class="service-status-pill ${role === "admin" ? "success" : "muted"}">${role === "admin" ? "Administrator" : "Użytkownik"}</span>
                        </div>
                    </div>
                    <div class="dlna-item-body" style="display:grid;gap:12px;">
                        ${editHtml}
                        ${resetPasswordHtml}
                        ${deleteHtml}
                        ${notesHtml}
                    </div>
                </div>
            `;
        }).join("");
    }

    function applyServiceState(service) {
        if (!service) {
            return;
        }

        setPill("serviceStatusPill", service.status_kind, service.status_label);
        setText("serviceAppUptime", service.app_uptime_text || "");
        setText("serviceUptime", service.service_uptime_text || "");
        setText("serviceLastRestart", service.last_restart_text || "");
        setText("serviceName", service.service_name || "");

        let pidText = "";
        if (service.main_pid) {
            pidText = "PID: " + String(service.main_pid || "");
            if (service.sub_state) {
                pidText += " | " + String(service.sub_state);
            }
        } else if (service.sub_state) {
            pidText = String(service.sub_state);
        } else {
            pidText = "Brak PID";
        }
        setText("servicePidText", pidText);

        const hasError = !!service.error;
        setHidden("serviceErrorBox", !hasError);
        setText("serviceErrorText", hasError ? ("Nie udało się odczytać pełnego statusu usługi: " + service.error) : "");
    }

    function applyYtDlpState(state, task) {
        if (!state) {
            return;
        }

        const taskActive = !!(task && task.active);
        const pillKind = taskActive ? "queued" : state.status_pill_kind;
        const pillLabel = taskActive ? "Trwa aktualizacja yt-dlp" : state.status_pill_label;

        setPill("ytDlpStatusPill", pillKind, pillLabel);
        setText("ytDlpCheckedAt", "Ostatnie sprawdzenie: " + String(state.checked_at_text || ""));
        setText("ytDlpCurrentVersion", state.current_version || "");
        setText("ytDlpLatestVersion", state.latest_version || "");

        const hasError = !!state.check_error;
        setHidden("ytDlpCheckErrorBox", !hasError);
        setText("ytDlpCheckErrorText", hasError ? ("Ostatnia próba sprawdzenia zakończyła się błędem: " + state.check_error) : "");

        const actionForm = document.getElementById("ytDlpActionForm");
        if (actionForm) {
            actionForm.hidden = !taskActive && !state.action_needed;
        }
        setHidden("ytDlpActionNote", taskActive || !!state.action_needed);
        setGroupBusy("yt_dlp_update", task, "Aktualizacja trwa...");
        updateTaskPanel("ytDlp", task, "Aktualizacja yt-dlp");
    }

    function applyFfmpegState(state, task) {
        if (!state) {
            return;
        }

        const taskActive = !!(task && task.active);
        const pillKind = taskActive ? "queued" : state.status_pill_kind;
        const pillLabel = taskActive ? "Trwa instalacja ffmpeg" : state.status_pill_label;

        setPill("ffmpegStatusPill", pillKind, pillLabel);
        setText("ffmpegCheckedAt", "Ostatnie sprawdzenie: " + String(state.checked_at_text || ""));
        setText("ffmpegCurrentVersion", state.current_version || "");
        setText("ffmpegLatestVersion", state.latest_version || "");
        setText("ffmpegCurrentSource", state.current_source_label || "");
        setText("ffmpegCurrentBuild", state.current_build_label || "");
        setText("ffmpegCurrentPath", state.current_path || "");

        const hasError = !!state.check_error;
        setHidden("ffmpegCheckErrorBox", !hasError);
        setText("ffmpegCheckErrorText", hasError ? ("Ostatnia próba sprawdzenia zakończyła się błędem: " + state.check_error) : "");

        const actionForm = document.getElementById("ffmpegActionForm");
        if (actionForm) {
            actionForm.hidden = !taskActive && !state.action_needed;
        }
        setHidden("ffmpegActionNote", taskActive || !!state.action_needed);
        setHidden("ffmpegExternalNote", !!state.managed || !state.installed);
        setGroupBusy("ffmpeg_install", task, "Instalacja trwa...");
        updateTaskPanel("ffmpeg", task, "Instalacja ffmpeg");
    }

    function applyDlnaPackageState(state, task) {
        if (!state) {
            return;
        }

        const taskActive = !!(task && task.active);
        const pillKind = taskActive ? "queued" : state.status_pill_kind;
        const pillLabel = taskActive ? "Trwa instalacja serwera DLNA" : state.status_pill_label;

        setPill("settingsDlnaPackageStatusPill", pillKind, pillLabel);
        setText("settingsDlnaPackageCheckedAt", "Ostatnie sprawdzenie: " + String(state.checked_at_text || ""));
        setText("settingsDlnaCurrentVersion", state.current_version || "");
        setText("settingsDlnaLatestVersion", state.latest_version || "");

        const hasError = !!state.check_error;
        setHidden("settingsDlnaPackageErrorBox", !hasError);
        setText("settingsDlnaPackageErrorText", hasError ? ("Ostatnia próba sprawdzenia zakończyła się błędem: " + state.check_error) : "");

        const actionForm = document.getElementById("settingsDlnaActionForm");
        if (actionForm) {
            actionForm.hidden = !taskActive && !state.action_needed;
        }
        const actionButton = document.getElementById("settingsDlnaActionButton");
        if (actionButton) {
            actionButton.textContent = state.action_button_label || actionButton.textContent;
            actionButton.dataset.idleLabel = actionButton.textContent;
        }
        setHidden("settingsDlnaActionNote", taskActive || !!state.action_needed);
        setGroupBusy("dlna_install", task, "Instalacja trwa...");
        updateTaskPanel("settingsDlna", task, "Instalacja serwera DLNA");
    }

    function applyDlnaServiceState(state) {
        if (!state) {
            return;
        }

        setText("settingsDlnaServiceStatus", state.status_label || "");
        setText("settingsDlnaUnitState", state.unit_file_label || "");
        setText("settingsDlnaExportRoot", state.export_root || "");

        const toggleForm = document.getElementById("settingsDlnaToggleForm");
        if (toggleForm) {
            const hiddenInput = toggleForm.querySelector('input[name="enabled"]');
            if (hiddenInput) {
                hiddenInput.value = state.desired_enabled ? "0" : "1";
            }
        }

        const toggleButton = document.getElementById("settingsDlnaToggleButton");
        if (toggleButton) {
            toggleButton.textContent = state.toggle_button_label || toggleButton.textContent;
            toggleButton.dataset.idleLabel = toggleButton.textContent;
        }

        const hasError = !!state.error;
        setHidden("settingsDlnaServiceErrorBox", !hasError);
        setText("settingsDlnaServiceErrorText", hasError ? ("Nie udało się odczytać pełnego statusu usługi DLNA: " + state.error) : "");
    }

    function findRadioPackage(state, packageName) {
        const packages = Array.isArray(state && state.packages) ? state.packages : [];
        return packages.find(function(item) {
            return String(item && item.name || "").toLowerCase() === String(packageName || "").toLowerCase();
        }) || null;
    }

    function applyRadioPackageState(state, task) {
        if (!state) {
            return;
        }

        const taskActive = !!(task && task.active);
        const pillKind = taskActive ? "queued" : state.status_pill_kind;
        const pillLabel = taskActive ? "Trwa instalacja backendu radia" : state.status_pill_label;
        const icecastPackage = findRadioPackage(state, "icecast2");
        const liquidsoapPackage = findRadioPackage(state, "liquidsoap");

        setPill("settingsRadioPackageStatusPill", pillKind, pillLabel);
        setText("settingsRadioPackageCheckedAt", "Ostatnie sprawdzenie: " + String(state.checked_at_text || ""));
        setText("settingsRadioIcecastCurrentVersion", (icecastPackage && icecastPackage.current_version) || "brak");
        setText("settingsRadioLiquidsoapCurrentVersion", (liquidsoapPackage && liquidsoapPackage.current_version) || "brak");

        const hasError = !!state.check_error;
        setHidden("settingsRadioPackageErrorBox", !hasError);
        setText("settingsRadioPackageErrorText", hasError ? ("Ostatnia próba sprawdzenia zakończyła się błędem: " + state.check_error) : "");

        const actionForm = document.getElementById("settingsRadioActionForm");
        if (actionForm) {
            actionForm.hidden = !taskActive && !state.action_needed;
        }
        const actionButton = document.getElementById("settingsRadioActionButton");
        if (actionButton) {
            actionButton.textContent = state.action_button_label || actionButton.textContent;
            actionButton.dataset.idleLabel = actionButton.textContent;
        }
        setHidden("settingsRadioActionNote", taskActive || !!state.action_needed);
        setGroupBusy("radio_backend_install", task, "Instalacja trwa...");
        updateTaskPanel("settingsRadio", task, "Instalacja backendu radia");
    }

    function applyRadioServiceState(state) {
        if (!state) {
            return;
        }

        setText("settingsRadioServiceStatus", state.status_label || "");
        setText("settingsRadioUnitState", state.unit_file_label || "");
        setText("settingsRadioRuntimeRoot", state.runtime_root || "");

        const toggleForm = document.getElementById("settingsRadioToggleForm");
        if (toggleForm) {
            const hiddenInput = toggleForm.querySelector('input[name="enabled"]');
            if (hiddenInput) {
                hiddenInput.value = state.service_active ? "0" : "1";
            }
        }

        const toggleButton = document.getElementById("settingsRadioToggleButton");
        if (toggleButton) {
            toggleButton.textContent = state.toggle_button_label || toggleButton.textContent;
            toggleButton.dataset.idleLabel = toggleButton.textContent;
        }

        const hasError = !!state.error;
        setHidden("settingsRadioServiceErrorBox", !hasError);
        setText("settingsRadioServiceErrorText", hasError ? ("Nie udało się odczytać pełnego statusu backendu radia: " + state.error) : "");
    }

    function applyStateEnvelope(envelope) {
        const state = (envelope && (envelope.settings_state || envelope.state)) ? (envelope.settings_state || envelope.state) : envelope;
        if (!state) {
            return;
        }

        const tasks = state.maintenance_tasks || state.tasks || {};
        applyMountState(state.mount || null);
        applyConfigState(state.config || null, state.mount || null, state.today_download_dir || "", state.today_audio_download_dir || "");
        if (Object.prototype.hasOwnProperty.call(state, "user_rows")) {
            renderUserRows(state.user_rows || []);
        }
        applyServiceState(state.service_state || null);
        applyYtDlpState(state.yt_dlp_state || {}, tasks.yt_dlp_update || null);
        applyFfmpegState(state.ffmpeg_state || {}, tasks.ffmpeg_install || null);
        applyDlnaPackageState(state.dlna_package_state || {}, tasks.dlna_install || null);
        applyDlnaServiceState(state.dlna_service_state || null);
        applyRadioPackageState(state.radio_backend_package_state || {}, tasks.radio_backend_install || null);
        applyRadioServiceState(state.radio_backend_service_state || null);
    }

    function applyLiveSettingsPayload(data) {
        if (dirtyForms.size > 0) {
            return;
        }
        applyStateEnvelope(data);
    }

    async function fetchSettingsState() {
        if (dirtyForms.size > 0) {
            return null;
        }
        try {
            const response = await fetch("/api/settings/state", {
                headers: {
                    "Accept": "application/json",
                    "X-Requested-With": "fetch"
                }
            });
            if (!response.ok) {
                return null;
            }
            const data = await response.json();
            applyStateEnvelope(data);
            return data;
        } catch (err) {
            // Stan ustawień jest odświeżany w tle. W razie chwilowego błędu po prostu próbujemy ponownie później.
            return null;
        }
    }

    async function handleAsyncFormSubmit(form, submitter) {
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        const submitAction = String((submitter && submitter.getAttribute("formaction")) || form.action || "");
        let busyLabel = String((submitter && submitter.dataset.busyLabel) || form.dataset.busyLabel || "").trim();
        if (!busyLabel) {
            busyLabel = "Trwa...";
            if (form.id === "settingsConfigForm") {
                busyLabel = "Zapisywanie...";
            } else if (form.id === "settingsCreateUserForm") {
                busyLabel = "Tworzenie użytkownika...";
            } else if (form.id === "restartServiceForm") {
                busyLabel = "Wysyłanie restartu...";
            } else if (form.id === "ytDlpCheckForm" || form.id === "ffmpegCheckForm" || form.id === "settingsDlnaCheckForm") {
                busyLabel = "Sprawdzanie...";
            } else if (form.id === "ytDlpActionForm" || form.id === "ffmpegActionForm" || form.id === "settingsDlnaActionForm") {
                busyLabel = "Uruchamianie...";
            } else if (form.id === "settingsRadioActionForm") {
                busyLabel = "Uruchamianie...";
            } else if (form.id === "settingsDlnaToggleForm") {
                busyLabel = "Przełączanie...";
            } else if (form.id === "settingsRadioToggleForm") {
                busyLabel = "Przełączanie...";
            } else if (form.id === "settingsDlnaRestartForm") {
                busyLabel = "Restartowanie...";
            } else if (form.id === "settingsRadioRestartForm") {
                busyLabel = "Restartowanie...";
            } else if (form.id === "settingsRadioCheckForm") {
                busyLabel = "Sprawdzanie...";
            }
        }

        setFormBusy(form, true, busyLabel, submitter || null);

        try {
            const response = await fetch(submitAction || form.action, {
                method: "POST",
                body: new FormData(form),
                headers: {
                    "Accept": "application/json",
                    "X-Requested-With": "fetch"
                }
            });
            const data = await response.json().catch(function() {
                return null;
            });

            if (data && (data.settings_state || data.state)) {
                applyStateEnvelope(data);
            }

            if (!response.ok || !data || data.ok === false) {
                showToast((data && (data.error || data.message)) || "Nie udało się wykonać operacji.", "error");
                return;
            }

            if (form.dataset.resetAfterSuccess === "true") {
                form.reset();
            }
            clearProtectedFormDirty(form);

            if (data.message) {
                showToast(data.message, data.kind || "success");
            }

            if (liveSubscription && typeof liveSubscription.refreshNow === "function") {
                liveSubscription.refreshNow();
            } else {
                fetchSettingsState();
            }
        } catch (err) {
            showToast("Nie udało się połączyć z serwerem.", "error");
        } finally {
            if (!form.dataset.maintenanceStart) {
                setFormBusy(form, false, "", submitter || null);
            }
        }
    }

    function handleSettingsSubmit(event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        if (!root.contains(form)) {
            return;
        }
        if (form.dataset.settingsAsync !== "true") {
            return;
        }

        if (form.dataset.confirmMessage && !confirm(form.dataset.confirmMessage)) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        handleAsyncFormSubmit(form, event.submitter || null);
    }

    function handleProtectedFormInput(event) {
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        const form = target.closest("form");
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        if (!root.contains(form)) {
            return;
        }
        markProtectedFormDirty(form);
        if (target.id === "activeStorageBackend") {
            toggleNetworkFields(target.value || "local");
        }
    }

    document.addEventListener("submit", handleSettingsSubmit, true);
    document.addEventListener("input", handleProtectedFormInput, true);
    document.addEventListener("change", handleProtectedFormInput, true);

    renderUserRows(pageData.userRows || []);
    if (window.appLive && typeof window.appLive.createSubscription === "function") {
        liveSubscription = window.appLive.createSubscription({
            url: "/api/settings/stream",
            fallbackIntervalMs: pollIntervalMs,
            fetchFallback: fetchSettingsState,
            onData: applyLiveSettingsPayload,
        });
        liveSubscription.start();
    } else {
        fetchSettingsState();
        const settingsRefreshTimer = setInterval(fetchSettingsState, pollIntervalMs);
        liveSubscription = {
            stop: function() {
                clearInterval(settingsRefreshTimer);
            },
            refreshNow: fetchSettingsState,
        };
    }

    if (typeof window.registerPageCleanup === "function") {
        window.registerPageCleanup(function() {
            if (liveSubscription && typeof liveSubscription.stop === "function") {
                liveSubscription.stop();
            }
            document.removeEventListener("submit", handleSettingsSubmit, true);
            document.removeEventListener("input", handleProtectedFormInput, true);
            document.removeEventListener("change", handleProtectedFormInput, true);
        });
    }
})();
