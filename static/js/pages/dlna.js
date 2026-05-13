(function() {
    const pageData = window.pageBootstrapData || {};
    const root = document.getElementById("dlnaPageRoot");
    if (!root) {
        return;
    }

    let currentState = pageData.initialState || {};
    let currentLibraryResults = {items: [], total_items: 0, shown_items: 0, collection_id: "", collection_name: "", mode: "files"};
    let searchTimer = null;
    let pollTimer = null;
    let activeTab = "serwer";
    let activeCollectionId = "";
    let libraryMode = "files";
    const expandedState = {
        collections: new Set(),
        clients: new Set(),
        rules: new Set()
    };

    try {
        const storedTab = window.sessionStorage ? window.sessionStorage.getItem("dlnaActiveTab") : "";
        if (storedTab === "serwer" || storedTab === "dostep" || storedTab === "biblioteka") {
            activeTab = storedTab;
        }
    } catch (err) {
        activeTab = "serwer";
    }

    try {
        activeCollectionId = window.sessionStorage ? String(window.sessionStorage.getItem("dlnaActiveCollectionId") || "") : "";
        const storedLibraryMode = window.sessionStorage ? String(window.sessionStorage.getItem("dlnaLibraryMode") || "") : "";
        if (storedLibraryMode === "folders" || storedLibraryMode === "all" || storedLibraryMode === "files") {
            libraryMode = storedLibraryMode;
        }
    } catch (err) {
        activeCollectionId = "";
        libraryMode = "files";
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function showToast(message, kind) {
        if (window.appUi && typeof window.appUi.showToast === "function") {
            window.appUi.showToast(message, kind);
            return;
        }
        alert(message);
    }

    function setButtonBusy(button, busy, label) {
        if (!button) {
            return;
        }
        if (!button.dataset.idleLabel) {
            button.dataset.idleLabel = String(button.textContent || "").trim();
        }
        button.disabled = !!busy;
        button.textContent = busy ? String(label || "Trwa...") : (button.dataset.idleLabel || button.textContent);
    }

    function getNamedCollections() {
        return (currentState.collections || []).filter(function(item) {
            return item && !item.builtin;
        });
    }

    function getAllCollections() {
        return currentState.collections || [];
    }

    function renderTokenList(names, emptyLabel) {
        const values = (names || []).filter(Boolean);
        if (!values.length) {
            return `<span class="dlna-token">${escapeHtml(emptyLabel || "Brak")}</span>`;
        }
        return values.map(function(name) {
            return `<span class="dlna-token">${escapeHtml(name)}</span>`;
        }).join("");
    }

    function setMetaText(elementId, value) {
        const node = document.getElementById(elementId);
        if (!node) {
            return;
        }
        node.textContent = String(value || "");
    }

    function isExpanded(scope, itemId) {
        return !!(expandedState[scope] && expandedState[scope].has(String(itemId || "")));
    }

    function toggleExpanded(scope, itemId) {
        const normalizedId = String(itemId || "");
        const stateSet = expandedState[scope];
        if (!stateSet || !normalizedId) {
            return;
        }
        if (stateSet.has(normalizedId)) {
            stateSet.delete(normalizedId);
        } else {
            stateSet.add(normalizedId);
        }
    }

    function rerenderScope(scope) {
        if (scope === "collections") {
            renderCollections();
            return;
        }
        if (scope === "clients") {
            renderClients();
            return;
        }
        if (scope === "rules") {
            renderMediaRules();
        }
    }

    function setActiveTab(nextTab, persist) {
        const allowedTabs = new Set(["serwer", "dostep", "biblioteka"]);
        activeTab = allowedTabs.has(String(nextTab || "")) ? String(nextTab) : "serwer";

        root.querySelectorAll("[data-dlna-tab-button]").forEach(function(button) {
            const isActive = button.dataset.dlnaTabButton === activeTab;
            button.classList.toggle("is-active", isActive);
        });
        root.querySelectorAll("[data-dlna-panel]").forEach(function(panel) {
            panel.hidden = panel.dataset.dlnaPanel !== activeTab;
        });

        if (persist !== false) {
            try {
                if (window.sessionStorage) {
                    window.sessionStorage.setItem("dlnaActiveTab", activeTab);
                }
            } catch (err) {
                // Ignorujemy błędy storage; panel nadal działa lokalnie.
            }
        }
    }

    function persistLibraryPreferences() {
        try {
            if (!window.sessionStorage) {
                return;
            }
            window.sessionStorage.setItem("dlnaActiveCollectionId", activeCollectionId);
            window.sessionStorage.setItem("dlnaLibraryMode", libraryMode);
        } catch (err) {
            // Ignorujemy błędy storage; stan pozostaje lokalny dla bieżącego widoku.
        }
    }

    function ensureActiveCollectionId() {
        const namedCollections = getNamedCollections();
        if (!namedCollections.length) {
            activeCollectionId = "";
            return;
        }

        const exists = namedCollections.some(function(item) {
            return String(item.id || "") === String(activeCollectionId || "");
        });
        if (!exists) {
            activeCollectionId = String((namedCollections[0] || {}).id || "");
        }
    }

    function syncLibraryControlValues() {
        ensureActiveCollectionId();
        const select = document.getElementById("dlnaCollectionEditorSelect");
        const modeSelect = document.getElementById("dlnaLibraryMode");
        const namedCollections = getNamedCollections();

        if (select) {
            select.innerHTML = namedCollections.length
                ? namedCollections.map(function(item) {
                    return `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`;
                }).join("")
                : '<option value="">Brak bukietów</option>';
            select.disabled = !namedCollections.length;
            select.value = activeCollectionId;
        }

        if (modeSelect) {
            modeSelect.value = libraryMode;
            modeSelect.disabled = !namedCollections.length;
        }

        persistLibraryPreferences();
    }

    function readVisibleLibraryItems() {
        return Array.from(root.querySelectorAll(".js-dlna-library-checkbox")).map(function(input) {
            return {
                kind: String(input.dataset.itemKind || ""),
                storage_kind: String(input.dataset.storageKind || "video"),
                relative_path: String(input.dataset.relativePath || ""),
                checked: !!input.checked
            };
        });
    }

    function updateLibrarySelectionSummary() {
        const summaryNode = document.getElementById("dlnaLibrarySelectionSummary");
        const saveButton = document.getElementById("dlnaSaveVisibleSelectionButton");
        const selectVisibleButton = document.getElementById("dlnaSelectVisibleButton");
        const unselectVisibleButton = document.getElementById("dlnaUnselectVisibleButton");
        const items = readVisibleLibraryItems();
        const checkedCount = items.filter(function(item) { return !!item.checked; }).length;
        const collectionLabel = String(currentLibraryResults.collection_name || "");
        const hasCollection = !!activeCollectionId;

        if (summaryNode) {
            if (!getNamedCollections().length) {
                summaryNode.textContent = "Najpierw utwórz bukiet DLNA. Po jego dodaniu lista poniżej zacznie działać od razu, bez przeładowania strony.";
            } else if (!hasCollection) {
                summaryNode.textContent = "Wybierz bukiet, żeby zaznaczać widoczne pozycje checkboxami.";
            } else if (!items.length) {
                summaryNode.textContent = collectionLabel
                    ? ('Brak widocznych pozycji dla bukietu "' + collectionLabel + '".')
                    : "Brak widocznych pozycji dla wybranego bukietu.";
            } else {
                summaryNode.textContent = checkedCount + " z " + items.length + ' widocznych pozycji należy teraz do bukietu "' + collectionLabel + '". Zapis obejmie tylko bieżącą listę.';
            }
        }

        [saveButton, selectVisibleButton, unselectVisibleButton].forEach(function(button) {
            if (!button) {
                return;
            }
            button.disabled = !hasCollection || !items.length;
        });
    }

    function renderCollectionCheckboxes(selectedIds, includeBuiltinAll, scopeName) {
        const selectedSet = new Set((selectedIds || []).map(function(item) { return String(item || ""); }));
        return getAllCollections().filter(function(item) {
            return includeBuiltinAll || !item.builtin;
        }).map(function(item) {
            const checked = selectedSet.has(String(item.id || ""));
            const itemDescription = item.description || (item.builtin ? "Ta kolekcja oznacza pełny dostęp do wszystkich aktywnych mediów." : "Brak dodatkowego opisu.");
            return `
                <label class="dlna-checkbox">
                    <input type="checkbox" value="${escapeHtml(item.id)}" data-checkbox-scope="${escapeHtml(scopeName)}" ${checked ? "checked" : ""}>
                    <span class="dlna-checkbox-text">
                        <strong>${escapeHtml(item.name)}</strong>
                        <span class="small">${escapeHtml(itemDescription)}</span>
                    </span>
                </label>
            `;
        }).join("");
    }

    function renderUserCheckboxes(selectedUsernames, scopeName) {
        const selectedSet = new Set((selectedUsernames || []).map(function(item) { return String(item || ""); }));
        const availableUsers = currentState.available_users || [];
        if (!availableUsers.length) {
            return '<div class="dlna-empty">Brak użytkowników do przypisania.</div>';
        }
        return availableUsers.map(function(item) {
            const username = String(item.username || "");
            const checked = selectedSet.has(username);
            const roleLabel = item.role === "admin" ? "Administrator" : "Użytkownik";
            const detail = item.enabled === false
                ? (roleLabel + " • konto wyłączone")
                : roleLabel;
            return `
                <label class="dlna-checkbox">
                    <input type="checkbox" value="${escapeHtml(username)}" data-checkbox-scope="${escapeHtml(scopeName)}" ${checked ? "checked" : ""}>
                    <span class="dlna-checkbox-text">
                        <strong>${escapeHtml(username)}</strong>
                        <span class="small">${escapeHtml(detail)}</span>
                    </span>
                </label>
            `;
        }).join("");
    }

    function readCheckboxScope(scopeName, container) {
        return Array.from((container || root).querySelectorAll('input[data-checkbox-scope="' + scopeName + '"]:checked')).map(function(input) {
            return String(input.value || "");
        });
    }

    function renderMount() {
        const mount = currentState.mount || {};
        const mountBox = document.getElementById("dlnaMountStatus");
        mountBox.className = mount.online ? "mount-ok" : "mount-bad";
        mountBox.textContent = String(mount.message || "");
    }

    function renderSummary(updateFormValues) {
        const summary = currentState.summary || {};
        const grid = document.getElementById("dlnaSummaryGrid");
        grid.innerHTML = `
            <div class="overview-tile">
                <span>Aktywne media</span>
                <strong>${escapeHtml(summary.effective_media_count || 0)}</strong>
            </div>
            <div class="overview-tile">
                <span>Wpisy DLNA</span>
                <strong>${escapeHtml(summary.media_rule_count || 0)}</strong>
            </div>
            <div class="overview-tile">
                <span>Kolekcje użytkownika</span>
                <strong>${escapeHtml(summary.named_collection_count || 0)}</strong>
            </div>
            <div class="overview-tile">
                <span>Klienci whitelisty</span>
                <strong>${escapeHtml(summary.active_client_count || 0)} / ${escapeHtml(summary.client_count || 0)}</strong>
            </div>
            <div class="overview-tile">
                <span>Ostatnia synchronizacja</span>
                <strong>${escapeHtml(summary.last_sync_text || "jeszcze nie synchronizowano")}</strong>
            </div>
            <div class="overview-tile">
                <span>Status synchronizacji</span>
                <strong>${summary.last_sync_error ? "Błąd" : "OK"}</strong>
                <div class="inline-note">${escapeHtml(summary.last_sync_error || "Eksport DLNA jest zsynchronizowany z konfiguracją.")}</div>
            </div>
        `;

        if (updateFormValues) {
            document.getElementById("dlnaServerName").value = String((currentState.dlna_config || {}).server_name || "");
            document.getElementById("dlnaBindIp").value = String((currentState.dlna_config || {}).bind_ip || "");
            document.getElementById("dlnaPort").value = String((currentState.dlna_config || {}).port || "");
        }
    }

    function taskBarClass(task) {
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

    function renderTaskPanel() {
        const task = ((currentState.maintenance_tasks || {}).dlna_install) || null;
        const panel = document.getElementById("dlnaTaskPanel");
        if (!task || !task.visible) {
            panel.hidden = true;
            return;
        }

        panel.hidden = false;
        document.getElementById("dlnaTaskStatusPill").className = "service-status-pill " + String(task.status_kind || "muted");
        document.getElementById("dlnaTaskStatusPill").textContent = String(task.status_label || "...");
        document.getElementById("dlnaTaskLabel").textContent = String(task.title || "Instalacja serwera DLNA");
        document.getElementById("dlnaTaskPercent").textContent = task.progress_percent === null || task.progress_percent === undefined ? "..." : Number(task.progress_percent).toFixed(1) + "%";
        document.getElementById("dlnaTaskDetail").textContent = String(task.detail || task.message || "");
        document.getElementById("dlnaTaskTime").textContent = task.active && task.started_at_text
            ? "Start: " + task.started_at_text
            : (task.finished_at_text ? "Zakończono: " + task.finished_at_text : "");

        const progress = document.getElementById("dlnaTaskProgress");
        const bar = document.getElementById("dlnaTaskBar");
        if (task.progress_percent === null || task.progress_percent === undefined) {
            progress.classList.add("is-indeterminate");
            bar.style.width = "38%";
        } else {
            progress.classList.remove("is-indeterminate");
            bar.style.width = Math.max(0, Math.min(100, Number(task.progress_percent) || 0)) + "%";
        }
        bar.className = "progress-bar " + taskBarClass(task);
    }

    function renderPackageAndService() {
        const packageState = currentState.dlna_package_state || {};
        const serviceState = currentState.dlna_service_state || {};
        const task = ((currentState.maintenance_tasks || {}).dlna_install) || null;
        const taskActive = !!(task && task.active);

        const packagePill = document.getElementById("dlnaPackageStatusPill");
        packagePill.className = "service-status-pill " + String(taskActive ? "queued" : (packageState.status_pill_kind || "muted"));
        packagePill.textContent = String(taskActive ? "Trwa instalacja serwera DLNA" : (packageState.status_pill_label || "..."));
        document.getElementById("dlnaPackageCheckedAt").textContent = "Ostatnie sprawdzenie: " + String(packageState.checked_at_text || "jeszcze nie sprawdzano");
        document.getElementById("dlnaPackageCurrentVersion").textContent = String(packageState.current_version || "brak");
        document.getElementById("dlnaPackageLatestVersion").textContent = String(packageState.latest_version || "brak danych");
        document.getElementById("dlnaPackageSource").textContent = String(packageState.source_label || "Pakiet Debian / apt");

        const packageErrorBox = document.getElementById("dlnaPackageErrorBox");
        packageErrorBox.hidden = !packageState.check_error;
        packageErrorBox.textContent = packageState.check_error ? ("Ostatnia próba sprawdzenia pakietu zakończyła się błędem: " + packageState.check_error) : "";

        const actionButton = document.getElementById("dlnaPackageActionButton");
        actionButton.hidden = !taskActive && !packageState.action_needed;
        actionButton.textContent = String(packageState.action_button_label || "Zainstaluj serwer DLNA");
        actionButton.dataset.idleLabel = actionButton.textContent;
        document.getElementById("dlnaPackageActionNote").hidden = taskActive || !!packageState.action_needed;

        const servicePill = document.getElementById("dlnaServiceStatusPill");
        servicePill.className = "service-status-pill " + String(serviceState.status_kind || "muted");
        servicePill.textContent = String(serviceState.status_label || "Nieznany");
        document.getElementById("dlnaServicePidText").textContent = serviceState.main_pid
            ? ("PID: " + String(serviceState.main_pid) + (serviceState.sub_state ? " | " + String(serviceState.sub_state) : ""))
            : (serviceState.sub_state ? String(serviceState.sub_state) : "Brak PID");
        document.getElementById("dlnaServiceUnitState").textContent = String(serviceState.unit_file_label || "nieznany");
        document.getElementById("dlnaServiceUptime").textContent = String(serviceState.service_uptime_text || "nieznany");
        document.getElementById("dlnaServiceLastRestart").textContent = String(serviceState.last_restart_text || "nieznany");
        document.getElementById("dlnaServiceName").textContent = String(serviceState.service_name || pageData.serviceName || "");
        document.getElementById("dlnaExportRoot").textContent = String(serviceState.export_root || "");
        document.getElementById("dlnaConfigFile").textContent = String(serviceState.config_file || "");

        const serviceErrorBox = document.getElementById("dlnaServiceErrorBox");
        serviceErrorBox.hidden = !serviceState.error;
        serviceErrorBox.textContent = serviceState.error ? ("Nie udało się odczytać pełnego statusu usługi DLNA: " + serviceState.error) : "";

        const diagnosticsBox = document.getElementById("dlnaServiceDiagnostics");
        const diagnosticParts = [];
        if (serviceState.diagnostic_text) {
            diagnosticParts.push(String(serviceState.diagnostic_text));
        }
        ((serviceState.feature_support || {}).notes || []).forEach(function(note) {
            if (note) {
                diagnosticParts.push(String(note));
            }
        });
        diagnosticsBox.hidden = !diagnosticParts.length;
        diagnosticsBox.textContent = diagnosticParts.join(" | ");

        const logBox = document.getElementById("dlnaServiceLogBox");
        const shouldShowLog = !!serviceState.recent_log_excerpt && (
            !!serviceState.result
            || !!serviceState.restart_count
            || serviceState.active_state === "failed"
            || serviceState.active_state === "inactive"
        );
        logBox.hidden = !shouldShowLog;
        logBox.textContent = shouldShowLog ? ("Ostatni log usługi: " + String(serviceState.recent_log_excerpt || "")) : "";

        document.getElementById("dlnaServiceToggleButton").textContent = String(serviceState.toggle_button_label || "Włącz serwer DLNA");
        document.getElementById("dlnaServiceToggleButton").dataset.idleLabel = document.getElementById("dlnaServiceToggleButton").textContent;
        renderTaskPanel();
    }

    function renderCollections() {
        document.getElementById("dlnaNewClientCollections").innerHTML = renderCollectionCheckboxes([], true, "new-client");
        document.getElementById("dlnaNewClientUsers").innerHTML = renderUserCheckboxes([], "new-client-user");
        syncLibraryControlValues();

        const list = document.getElementById("dlnaCollectionsList");
        const namedCollections = getNamedCollections();
        setMetaText("dlnaCollectionsMeta", namedCollections.length ? (namedCollections.length + " zapisane") : "0 zapisanych");
        if (!namedCollections.length) {
            list.innerHTML = '<div class="dlna-empty">Nie masz jeszcze własnych kolekcji. Aktywne media nadal mogą być widoczne przez wbudowaną kolekcję String(pageData.allCollectionName || "Wszystkie aktywne media").</div>';
            return;
        }

        list.innerHTML = namedCollections.map(function(item) {
            const expanded = isExpanded("collections", item.id);
            return `
                <div class="dlna-item" data-collection-id="${escapeHtml(item.id)}">
                    <div class="dlna-item-head">
                        <div>
                            <div class="dlna-item-title">${escapeHtml(item.name)}</div>
                            <div class="dlna-item-meta">${escapeHtml(item.description || "Brak opisu")} • ID: ${escapeHtml(item.id)}</div>
                        </div>
                        <div class="dlna-item-head-actions">
                            <button type="button" class="dlna-plain-button js-dlna-toggle-item" data-toggle-scope="collections">${expanded ? "Zwiń" : "Edytuj"}</button>
                            <button type="button" class="btn btn-delete js-dlna-delete-collection">Usuń</button>
                        </div>
                    </div>
                    <div class="dlna-item-body" ${expanded ? "" : "hidden"}>
                        <div class="auth-form">
                            <label class="field-label">Nazwa kolekcji</label>
                            <input type="text" data-collection-field="name" value="${escapeHtml(item.name)}">
                            <label class="field-label">Opis</label>
                            <input type="text" data-collection-field="description" value="${escapeHtml(item.description || "")}">
                        </div>
                        <div class="dlna-item-actions">
                            <button type="button" class="btn js-dlna-save-collection">Zapisz kolekcję</button>
                        </div>
                    </div>
                </div>
            `;
        }).join("");
    }

    function renderClients() {
        const list = document.getElementById("dlnaClientsList");
        const clients = currentState.clients || [];
        setMetaText("dlnaClientsMeta", clients.length ? ((clients.filter(function(client) { return !!client.enabled; }).length) + " aktywnych z " + clients.length) : "0 klientów");
        if (!clients.length) {
            list.innerHTML = '<div class="dlna-empty">Brak klientów na whiteliście. Domyślnie nikt nie dostaje dostępu do serwera DLNA.</div>';
            return;
        }

        list.innerHTML = clients.map(function(client) {
            const expanded = isExpanded("clients", client.id);
            const userLabels = client.user_labels || client.usernames || [];
            return `
                <div class="dlna-item" data-client-id="${escapeHtml(client.id)}">
                    <div class="dlna-item-head">
                        <div>
                            <div class="dlna-item-title">${escapeHtml(client.ip)}</div>
                            <div class="dlna-item-meta">${escapeHtml(client.description || "Brak opisu")} • Widoczne media: ${escapeHtml(client.visible_media_count || 0)}</div>
                            <div class="dlna-token-list" style="margin-top: 8px;">${renderTokenList(client.collection_names || [], "Brak kolekcji")}</div>
                            <div class="dlna-token-list" style="margin-top: 8px;">${renderTokenList(userLabels, "Brak użytkowników")}</div>
                        </div>
                        <div class="dlna-item-head-actions">
                            <span class="status ${client.enabled ? "completed" : "canceled"}">${client.enabled ? "Aktywny" : "Wyłączony"}</span>
                            <button type="button" class="dlna-plain-button js-dlna-toggle-item" data-toggle-scope="clients">${expanded ? "Zwiń" : "Edytuj"}</button>
                            <button type="button" class="btn btn-delete js-dlna-delete-client">Usuń</button>
                        </div>
                    </div>
                    <div class="dlna-item-body" ${expanded ? "" : "hidden"}>
                        <div class="auth-form">
                            <label class="field-label">Adres IP</label>
                            <input type="text" data-client-field="ip" value="${escapeHtml(client.ip)}">
                            <label class="field-label">Opis urządzenia</label>
                            <input type="text" data-client-field="description" value="${escapeHtml(client.description || "")}">
                            <label class="dlna-checkbox">
                                <input type="checkbox" data-client-field="enabled" ${client.enabled ? "checked" : ""}>
                                <span class="dlna-checkbox-text">
                                    <strong>Klient aktywny</strong>
                                    <span class="small">Po odznaczeniu wpis IP zostaje zachowany, ale dostęp i autostart dla tego klienta są blokowane.</span>
                                </span>
                            </label>
                            <div>
                                <div class="field-label">Kolekcje widoczne dla klienta</div>
                                <div class="dlna-checkbox-grid">${renderCollectionCheckboxes(client.collection_ids || [], true, "client-" + client.id)}</div>
                            </div>
                            <div>
                                <div class="field-label">Użytkownicy widoczni dla klienta</div>
                                <div class="dlna-checkbox-grid">${renderUserCheckboxes(client.usernames || [], "client-user-" + client.id)}</div>
                            </div>
                        </div>
                        <div class="dlna-item-actions">
                            <button type="button" class="btn js-dlna-save-client">Zapisz klienta</button>
                        </div>
                    </div>
                </div>
            `;
        }).join("");
    }

    function renderMediaRules() {
        const list = document.getElementById("dlnaMediaRulesList");
        const rules = currentState.media_rules || [];
        setMetaText("dlnaMediaRulesMeta", rules.length ? (rules.length + " wpisów") : "0 wpisów");
        if (!rules.length) {
            list.innerHTML = '<div class="dlna-empty">Nie zaznaczono jeszcze żadnych folderów ani plików dla DLNA.</div>';
            return;
        }

        list.innerHTML = rules.map(function(rule) {
            const tags = [];
            tags.push(rule.kind === "folder" ? "Folder" : "Plik");
            tags.push(rule.storage_kind === "audio" ? "Audio" : "Wideo");
            if (rule.enabled) {
                tags.push("Aktywny");
            }
            if (rule.collection_names && rule.collection_names.length) {
                tags.push("Bukiety: " + rule.collection_names.join(", "));
            } else {
                tags.push("Tylko " + String(pageData.allCollectionName || "Wszystkie aktywne media"));
            }
            return `
                <div class="dlna-library-row ${rule.enabled ? "is-selected" : ""}" data-rule-id="${escapeHtml(rule.id)}">
                    <label class="dlna-library-check">
                        <input type="checkbox" data-rule-field="enabled" ${rule.enabled ? "checked" : ""}>
                    </label>
                    <div class="dlna-library-copy">
                        <div class="dlna-library-name">${escapeHtml(rule.display_path)}</div>
                        <div class="dlna-library-meta">${escapeHtml(tags.join(" • ") + " • Dopasowane pliki: " + String(rule.matched_files || 0) + (rule.exists ? "" : " • źródło zniknęło"))}</div>
                    </div>
                    <div class="dlna-library-flags">
                        <button type="button" class="dlna-plain-button js-dlna-save-rule">Zapisz</button>
                        <button type="button" class="btn btn-delete js-dlna-delete-rule">Usuń</button>
                    </div>
                </div>
            `;
        }).join("");
    }

    function renderLibraryResults() {
        syncLibraryControlValues();
        const container = document.getElementById("dlnaLibraryResults");
        const metaNode = document.getElementById("dlnaLibraryResultsMeta");
        const items = currentLibraryResults.items || [];

        if (!getNamedCollections().length) {
            if (metaNode) {
                metaNode.textContent = "";
            }
            container.innerHTML = '<div class="dlna-empty">Najpierw utwórz bukiet DLNA w zakładce kolekcji.</div>';
            updateLibrarySelectionSummary();
            return;
        }

        if (metaNode) {
            const totalText = currentLibraryResults.total_items
                ? (String(currentLibraryResults.shown_items || items.length) + " / " + String(currentLibraryResults.total_items))
                : String(currentLibraryResults.shown_items || items.length || 0);
            const collectionLabel = currentLibraryResults.collection_name ? ('Bukiet: ' + String(currentLibraryResults.collection_name)) : "";
            metaNode.textContent = collectionLabel ? (totalText + " • " + collectionLabel) : totalText;
        }

        if (!items.length) {
            const hasQuery = !!String((document.getElementById("dlnaLibraryQuery") || {}).value || "").trim();
            container.innerHTML = '<div class="dlna-empty">' + escapeHtml(hasQuery ? "Brak pozycji pasujących do tego filtra." : "Brak pozycji do pokazania w tym widoku.") + '</div>';
            updateLibrarySelectionSummary();
            return;
        }

        container.innerHTML = items.map(function(item) {
            const tags = [];
            tags.push(`<span class="dlna-mini-tag">${escapeHtml(item.storage_label || (item.storage_kind === "audio" ? "Audio" : "Wideo"))}</span>`);
            if (item.kind === "folder") {
                tags.push('<span class="dlna-mini-tag">Folder</span>');
            }
            if (item.selected_via === "inherited") {
                tags.push('<span class="dlna-mini-tag is-inherited">z folderu</span>');
            }
            if (item.active_in_dlna) {
                tags.push('<span class="dlna-mini-tag is-active">DLNA</span>');
            }
            const rowClass = item.selected ? "dlna-library-row is-selected" : "dlna-library-row";
            return `
                <label class="${rowClass}">
                    <input
                        type="checkbox"
                        class="dlna-library-check js-dlna-library-checkbox"
                        data-item-kind="${escapeHtml(item.kind || "file")}"
                        data-storage-kind="${escapeHtml(item.storage_kind || "video")}"
                        data-relative-path="${escapeHtml(item.relative_path || "")}"
                        ${item.selected ? "checked" : ""}
                    >
                    <span class="dlna-library-copy">
                        <span class="dlna-library-name">${escapeHtml(item.title || item.display_path || "")}</span>
                        <span class="dlna-library-meta">${escapeHtml((item.display_path || "") + " • " + (item.detail_text || ""))}</span>
                    </span>
                    <span class="dlna-library-flags">${tags.join("")}</span>
                </label>
            `;
        }).join("");
        updateLibrarySelectionSummary();
    }

    function renderAllStaticSections() {
        renderCollections();
        renderClients();
        renderMediaRules();
        renderLibraryResults();
    }

    function renderLiveSections() {
        renderMount();
        renderSummary(false);
        renderPackageAndService();
    }

    function applyState(state, rerenderAll) {
        if (!state) {
            return;
        }
        currentState = state;
        renderLiveSections();
        if (rerenderAll) {
            renderSummary(true);
            renderAllStaticSections();
        }
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, Object.assign({
            headers: {
                "Accept": "application/json",
                "X-Requested-With": "fetch"
            }
        }, options || {}));
        const data = await response.json().catch(function() { return null; });
        if (!response.ok || !data) {
            throw new Error((data && (data.error || data.message)) || "Nie udało się wykonać operacji.");
        }
        if (data.ok === false) {
            throw new Error(data.error || data.message || "Operacja zakończyła się błędem.");
        }
        return data;
    }

    async function postJson(url, payload) {
        return fetchJson(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Requested-With": "fetch"
            },
            body: JSON.stringify(payload || {})
        });
    }

    async function refreshState(rerenderAll) {
        try {
            const data = await fetchJson("/api/dlna/state");
            applyState(data.state, !!rerenderAll);
        } catch (err) {
            // Tło tylko odświeża stan. Przy chwilowym błędzie po prostu próbujemy ponownie później.
        }
    }

    async function refreshLibraryResults() {
        const query = String(document.getElementById("dlnaLibraryQuery").value || "");
        syncLibraryControlValues();
        if (!activeCollectionId) {
            currentLibraryResults = {
                items: [],
                total_items: 0,
                shown_items: 0,
                collection_id: "",
                collection_name: "",
                mode: libraryMode
            };
            renderLibraryResults();
            return;
        }
        try {
            const data = await fetchJson(
                "/api/dlna/library?query=" + encodeURIComponent(query)
                + "&collection_id=" + encodeURIComponent(activeCollectionId)
                + "&mode=" + encodeURIComponent(libraryMode)
                + "&limit=200"
            );
            currentLibraryResults = data.results || {
                items: [],
                total_items: 0,
                shown_items: 0,
                collection_id: activeCollectionId,
                collection_name: "",
                mode: libraryMode
            };
            renderLibraryResults();
        } catch (err) {
            currentLibraryResults = {
                items: [],
                total_items: 0,
                shown_items: 0,
                collection_id: activeCollectionId,
                collection_name: "",
                mode: libraryMode
            };
            renderLibraryResults();
        }
    }

    async function performAction(button, busyLabel, action) {
        setButtonBusy(button, true, busyLabel);
        try {
            const data = await action();
            if (data && data.dlna_state) {
                applyState(data.dlna_state, true);
            }
            if (data && data.message) {
                showToast(data.message, data.kind || "success");
            }
            await refreshLibraryResults();
            return true;
        } catch (err) {
            showToast(String(err), "error");
            return false;
        } finally {
            setButtonBusy(button, false);
        }
    }

    async function handleRootClick(event) {
        const tabButton = event.target.closest("[data-dlna-tab-button]");
        if (tabButton) {
            event.preventDefault();
            setActiveTab(tabButton.dataset.dlnaTabButton || "serwer");
            return;
        }

        const toggleItemButton = event.target.closest(".js-dlna-toggle-item");
        if (toggleItemButton) {
            event.preventDefault();
            const scope = String(toggleItemButton.dataset.toggleScope || "");
            if (scope === "collections") {
                const card = toggleItemButton.closest("[data-collection-id]");
                toggleExpanded(scope, card ? card.dataset.collectionId : "");
                renderCollections();
                return;
            }
            if (scope === "clients") {
                const card = toggleItemButton.closest("[data-client-id]");
                toggleExpanded(scope, card ? card.dataset.clientId : "");
                renderClients();
                return;
            }
            if (scope === "rules") {
                const card = toggleItemButton.closest("[data-rule-id]");
                toggleExpanded(scope, card ? card.dataset.ruleId : "");
                renderMediaRules();
                return;
            }
        }

        const packageCheckButton = event.target.closest("#dlnaPackageCheckButton");
        if (packageCheckButton) {
            event.preventDefault();
            return performAction(packageCheckButton, "Sprawdzanie...", function() {
                return postJson("/api/dlna/package-check");
            });
        }

        const packageActionButton = event.target.closest("#dlnaPackageActionButton");
        if (packageActionButton) {
            event.preventDefault();
            return performAction(packageActionButton, "Uruchamianie...", function() {
                return postJson("/api/dlna/package-install");
            });
        }

        const serviceToggleButton = event.target.closest("#dlnaServiceToggleButton");
        if (serviceToggleButton) {
            event.preventDefault();
            const enabled = !((currentState.dlna_service_state || {}).desired_enabled);
            return performAction(serviceToggleButton, enabled ? "Włączanie..." : "Wyłączanie...", function() {
                return postJson("/api/dlna/service-toggle", {enabled: enabled});
            });
        }

        const serviceRestartButton = event.target.closest("#dlnaServiceRestartButton");
        if (serviceRestartButton) {
            event.preventDefault();
            return performAction(serviceRestartButton, "Restartowanie...", function() {
                return postJson("/api/dlna/service-restart");
            });
        }

        const resyncButton = event.target.closest("#dlnaResyncButton");
        if (resyncButton) {
            event.preventDefault();
            return performAction(resyncButton, "Synchronizacja...", function() {
                return postJson("/api/dlna/resync");
            });
        }

        const saveCollectionButton = event.target.closest(".js-dlna-save-collection");
        if (saveCollectionButton) {
            event.preventDefault();
            const card = saveCollectionButton.closest("[data-collection-id]");
            if (!card) {
                return;
            }
            return performAction(saveCollectionButton, "Zapisywanie...", function() {
                return postJson("/api/dlna/collections", {
                    action: "update",
                    collection_id: card.dataset.collectionId || "",
                    name: (card.querySelector('[data-collection-field="name"]') || {}).value || "",
                    description: (card.querySelector('[data-collection-field="description"]') || {}).value || ""
                });
            });
        }

        const deleteCollectionButton = event.target.closest(".js-dlna-delete-collection");
        if (deleteCollectionButton) {
            event.preventDefault();
            if (!confirm("Usunąć tę kolekcję? Zostanie też odpięta od klientów i mediów.")) {
                return;
            }
            const card = deleteCollectionButton.closest("[data-collection-id]");
            if (!card) {
                return;
            }
            expandedState.collections.delete(String(card.dataset.collectionId || ""));
            return performAction(deleteCollectionButton, "Usuwanie...", function() {
                return postJson("/api/dlna/collections", {
                    action: "delete",
                    collection_id: card.dataset.collectionId || ""
                });
            });
        }

        const saveClientButton = event.target.closest(".js-dlna-save-client");
        if (saveClientButton) {
            event.preventDefault();
            const card = saveClientButton.closest("[data-client-id]");
            if (!card) {
                return;
            }
            return performAction(saveClientButton, "Zapisywanie...", function() {
                return postJson("/api/dlna/clients", {
                    action: "update",
                    client_id: card.dataset.clientId || "",
                    ip: (card.querySelector('[data-client-field="ip"]') || {}).value || "",
                    description: (card.querySelector('[data-client-field="description"]') || {}).value || "",
                    enabled: !!((card.querySelector('[data-client-field="enabled"]') || {}).checked),
                    collection_ids: readCheckboxScope("client-" + (card.dataset.clientId || ""), card),
                    usernames: readCheckboxScope("client-user-" + (card.dataset.clientId || ""), card)
                });
            });
        }

        const deleteClientButton = event.target.closest(".js-dlna-delete-client");
        if (deleteClientButton) {
            event.preventDefault();
            if (!confirm("Usunąć tego klienta z whitelisty DLNA?")) {
                return;
            }
            const card = deleteClientButton.closest("[data-client-id]");
            if (!card) {
                return;
            }
            expandedState.clients.delete(String(card.dataset.clientId || ""));
            return performAction(deleteClientButton, "Usuwanie...", function() {
                return postJson("/api/dlna/clients", {
                    action: "delete",
                    client_id: card.dataset.clientId || ""
                });
            });
        }

        const selectVisibleButton = event.target.closest("#dlnaSelectVisibleButton");
        if (selectVisibleButton) {
            event.preventDefault();
            root.querySelectorAll(".js-dlna-library-checkbox").forEach(function(input) {
                input.checked = true;
                const row = input.closest(".dlna-library-row");
                if (row) {
                    row.classList.add("is-selected");
                }
            });
            updateLibrarySelectionSummary();
            return;
        }

        const unselectVisibleButton = event.target.closest("#dlnaUnselectVisibleButton");
        if (unselectVisibleButton) {
            event.preventDefault();
            root.querySelectorAll(".js-dlna-library-checkbox").forEach(function(input) {
                input.checked = false;
                const row = input.closest(".dlna-library-row");
                if (row) {
                    row.classList.remove("is-selected");
                }
            });
            updateLibrarySelectionSummary();
            return;
        }

        const saveVisibleSelectionButton = event.target.closest("#dlnaSaveVisibleSelectionButton");
        if (saveVisibleSelectionButton) {
            event.preventDefault();
            if (!activeCollectionId) {
                showToast("Najpierw wybierz bukiet DLNA do edycji.", "error");
                return;
            }
            const items = readVisibleLibraryItems();
            return performAction(saveVisibleSelectionButton, "Zapisywanie...", function() {
                return postJson("/api/dlna/media", {
                    action: "bulk_assign_collection",
                    collection_id: activeCollectionId,
                    items: items
                });
            });
        }

        const saveRuleButton = event.target.closest(".js-dlna-save-rule");
        if (saveRuleButton) {
            event.preventDefault();
            const card = saveRuleButton.closest("[data-rule-id]");
            if (!card) {
                return;
            }
            const existingRule = (currentState.media_rules || []).find(function(rule) {
                return String(rule.id || "") === String(card.dataset.ruleId || "");
            }) || {};
            return performAction(saveRuleButton, "Zapisywanie...", function() {
                return postJson("/api/dlna/media", {
                    action: "update",
                    rule_id: card.dataset.ruleId || "",
                    enabled: !!((card.querySelector('[data-rule-field="enabled"]') || {}).checked),
                    collection_ids: existingRule.collection_ids || []
                });
            });
        }

        const deleteRuleButton = event.target.closest(".js-dlna-delete-rule");
        if (deleteRuleButton) {
            event.preventDefault();
            if (!confirm("Usunąć ten wpis z listy aktywnych mediów DLNA?")) {
                return;
            }
            const card = deleteRuleButton.closest("[data-rule-id]");
            if (!card) {
                return;
            }
            expandedState.rules.delete(String(card.dataset.ruleId || ""));
            return performAction(deleteRuleButton, "Usuwanie...", function() {
                return postJson("/api/dlna/media", {
                    action: "delete",
                    rule_id: card.dataset.ruleId || ""
                });
            });
        }
    }

    async function handleRootSubmit(event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        if (form.id === "dlnaServerSettingsForm") {
            event.preventDefault();
            const button = form.querySelector("button[type='submit']");
            return performAction(button, "Zapisywanie...", function() {
                return postJson("/api/dlna/settings", {
                    server_name: form.server_name.value,
                    bind_ip: form.bind_ip.value,
                    port: form.port.value
                });
            });
        }

        if (form.id === "dlnaCreateCollectionForm") {
            event.preventDefault();
            const button = form.querySelector("button[type='submit']");
            return performAction(button, "Dodawanie...", function() {
                return postJson("/api/dlna/collections", {
                    action: "create",
                    name: form.name.value,
                    description: form.description.value
                });
            }).then(function(ok) {
                if (ok) {
                    form.reset();
                }
            });
        }

        if (form.id === "dlnaCreateClientForm") {
            event.preventDefault();
            const button = form.querySelector("button[type='submit']");
            return performAction(button, "Dodawanie...", function() {
                return postJson("/api/dlna/clients", {
                    action: "create",
                    ip: form.ip.value,
                    description: form.description.value,
                    enabled: !!form.enabled.checked,
                    collection_ids: readCheckboxScope("new-client"),
                    usernames: readCheckboxScope("new-client-user")
                });
            }).then(function(ok) {
                if (ok) {
                    form.reset();
                    const newClientUsers = document.getElementById("dlnaNewClientUsers");
                    if (newClientUsers) {
                        newClientUsers.innerHTML = renderUserCheckboxes([], "new-client-user");
                    }
                }
            });
        }
    }

    function handleSearchInput() {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function() {
            refreshLibraryResults();
        }, 260);
    }

    function handleRootChange(event) {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }

        if (target.matches("#dlnaCollectionEditorSelect")) {
            activeCollectionId = String(target.value || "");
            persistLibraryPreferences();
            refreshLibraryResults();
            return;
        }

        if (target.matches("#dlnaLibraryMode")) {
            const nextMode = String(target.value || "files");
            libraryMode = nextMode === "folders" || nextMode === "all" ? nextMode : "files";
            persistLibraryPreferences();
            refreshLibraryResults();
            return;
        }

        if (target.matches(".js-dlna-library-checkbox")) {
            const row = target.closest(".dlna-library-row");
            if (row) {
                row.classList.toggle("is-selected", !!target.checked);
            }
            updateLibrarySelectionSummary();
            return;
        }

        if (target.matches('[data-rule-field="enabled"]')) {
            const row = target.closest(".dlna-library-row");
            if (row) {
                row.classList.toggle("is-selected", !!target.checked);
            }
        }
    }

    renderMount();
    renderSummary(true);
    renderPackageAndService();
    renderAllStaticSections();
    setActiveTab(activeTab, false);
    refreshLibraryResults();

    document.addEventListener("click", handleRootClick);
    document.addEventListener("change", handleRootChange, true);
    document.addEventListener("submit", handleRootSubmit, true);
    document.getElementById("dlnaLibraryQuery").addEventListener("input", handleSearchInput);

    pollTimer = setInterval(function() {
        refreshState(false);
    }, 1500);

    if (typeof window.registerPageCleanup === "function") {
        window.registerPageCleanup(function() {
            clearTimeout(searchTimer);
            clearInterval(pollTimer);
            document.removeEventListener("click", handleRootClick);
            document.removeEventListener("change", handleRootChange, true);
            document.removeEventListener("submit", handleRootSubmit, true);
            const queryInput = document.getElementById("dlnaLibraryQuery");
            if (queryInput) {
                queryInput.removeEventListener("input", handleSearchInput);
            }
        });
    }
})();
