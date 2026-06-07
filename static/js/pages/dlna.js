(function () {
    const root = document.getElementById("dlnaPageRoot");
    if (!root) {
        return;
    }

    const pageData = window.pageBootstrapData || {};
    const tabButtons = Array.from(root.querySelectorAll("[data-dlna-tab-button]"));
    const availableTabs = new Set(tabButtons.map(function (button) {
        return String(button.dataset.dlnaTabButton || "").trim();
    }).filter(Boolean));

    let currentState = pageData.initialState || {};
    let currentLibraryResults = {
        items: [],
        total_items: 0,
        shown_items: 0,
        collection_id: "",
        collection_name: "",
        mode: "files",
    };
    let searchTimer = null;
    let liveSubscription = null;
    let activeTab = availableTabs.has("bukiety") ? "bukiety" : (Array.from(availableTabs)[0] || "");
    let activeCollectionId = "";
    let librarySelectionDirty = false;
    let librarySelectionDirtyCollectionId = "";

    try {
        const storedTab = window.sessionStorage ? String(window.sessionStorage.getItem("dlnaActiveTab") || "") : "";
        if (availableTabs.has(storedTab)) {
            activeTab = storedTab;
        }
        activeCollectionId = window.sessionStorage ? String(window.sessionStorage.getItem("dlnaActiveCollectionId") || "") : "";
    } catch (err) {
        activeCollectionId = "";
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
        alert(String(message || ""));
    }

    function setButtonBusy(button, busy, busyLabel) {
        if (!button) {
            return;
        }
        if (!button.dataset.idleLabel) {
            button.dataset.idleLabel = String(button.textContent || "").trim();
        }
        button.disabled = !!busy;
        button.textContent = busy ? String(busyLabel || "Trwa...") : button.dataset.idleLabel;
    }

    function getPermissions() {
        return currentState.permissions || {logged_in: false, is_admin: false, current_username: ""};
    }

    function isAdmin() {
        return !!getPermissions().is_admin;
    }

    function getCollections() {
        return Array.isArray(currentState.collections) ? currentState.collections : [];
    }

    function getManageableCollections() {
        return getCollections().filter(function (item) {
            return !!item && !!item.can_manage;
        });
    }

    function getCollectionById(collectionId) {
        const normalizedId = String(collectionId || "");
        return getCollections().find(function (item) {
            return String((item && item.id) || "") === normalizedId;
        }) || null;
    }

    function persistUiState() {
        try {
            if (!window.sessionStorage) {
                return;
            }
            if (activeTab) {
                window.sessionStorage.setItem("dlnaActiveTab", activeTab);
            }
            if (activeCollectionId) {
                window.sessionStorage.setItem("dlnaActiveCollectionId", activeCollectionId);
            } else {
                window.sessionStorage.removeItem("dlnaActiveCollectionId");
            }
        } catch (err) {
            // Pomijamy błędy sessionStorage.
        }
    }

    function ensureActiveCollectionId() {
        const manageableCollections = getManageableCollections();
        if (!manageableCollections.length) {
            activeCollectionId = "";
            return;
        }
        const exists = manageableCollections.some(function (item) {
            return String(item.id || "") === String(activeCollectionId || "");
        });
        if (!exists) {
            activeCollectionId = String((manageableCollections[0] || {}).id || "");
        }
    }

    function isLibrarySelectionDirtyForActiveCollection() {
        return !!librarySelectionDirty && String(librarySelectionDirtyCollectionId || "") === String(activeCollectionId || "");
    }

    function markLibrarySelectionDirty() {
        librarySelectionDirty = true;
        librarySelectionDirtyCollectionId = String(activeCollectionId || "");
        renderLibrarySelectionSummary();
    }

    function clearLibrarySelectionDirty() {
        librarySelectionDirty = false;
        librarySelectionDirtyCollectionId = "";
    }

    function setActiveTab(nextTab, persist) {
        const desiredTab = String(nextTab || "");
        activeTab = availableTabs.has(desiredTab) ? desiredTab : (availableTabs.has("bukiety") ? "bukiety" : (Array.from(availableTabs)[0] || ""));
        root.querySelectorAll("[data-dlna-tab-button]").forEach(function (button) {
            button.classList.toggle("is-active", String(button.dataset.dlnaTabButton || "") === activeTab);
        });
        root.querySelectorAll("[data-dlna-panel]").forEach(function (panel) {
            panel.hidden = String(panel.dataset.dlnaPanel || "") !== activeTab;
        });
        if (persist !== false) {
            persistUiState();
        }
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, Object.assign({
            headers: {
                "Accept": "application/json",
                "X-Requested-With": "fetch",
            },
            credentials: "same-origin",
        }, options || {}));
        const data = await response.json().catch(function () { return null; });
        if (!response.ok || !data) {
            throw new Error((data && (data.error || data.message)) || ("Błąd HTTP " + response.status));
        }
        if (data.ok === false) {
            throw new Error(data.error || data.message || "Operacja zakończyła się błędem.");
        }
        return data;
    }

    async function postJson(url, payload) {
        return fetchJson(url, {
            method: "POST",
            body: JSON.stringify(payload || {}),
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Requested-With": "fetch",
            },
            credentials: "same-origin",
        });
    }

    async function postFormData(url, formData) {
        return fetchJson(url, {
            method: "POST",
            body: formData,
            credentials: "same-origin",
        });
    }

    function renderMount() {
        const mount = currentState.mount || {};
        const mountBox = document.getElementById("dlnaMountStatus");
        if (!mountBox) {
            return;
        }
        const online = !!mount.online;
        mountBox.className = "page-status-inline " + (online ? "is-online" : "is-offline");
        mountBox.title = String(mount.message || "");
        mountBox.innerHTML = `
            <span class="page-status-icon" aria-hidden="true"></span>
            <span class="page-status-text">
                <span class="page-status-icon-dot" aria-hidden="true"></span>
                ${online ? "Serwer danych online" : "Serwer danych offline"}
            </span>
        `;
    }

    function renderSummary() {
        const summary = currentState.summary || {};
        const grid = document.getElementById("dlnaSummaryGrid");
        if (!grid) {
            return;
        }
        grid.innerHTML = `
            <div class="overview-tile">
                <span>Aktywne pliki w bukietach</span>
                <strong>${escapeHtml(summary.effective_media_count || 0)}</strong>
            </div>
            <div class="overview-tile">
                <span>Liczba bukietów</span>
                <strong>${escapeHtml(summary.named_collection_count || 0)}</strong>
            </div>
            <div class="overview-tile">
                <span>Klienci whitelisty</span>
                <strong>${escapeHtml(summary.active_client_count || 0)} / ${escapeHtml(summary.client_count || 0)}</strong>
            </div>
            <div class="overview-tile">
                <span>Stan runtime</span>
                <strong>${escapeHtml(summary.runtime_phase_label || "Nieznany")}</strong>
                <div class="inline-note">${escapeHtml(summary.runtime_phase_detail || "")}</div>
            </div>
            <div class="overview-tile">
                <span>Ostatnia synchronizacja</span>
                <strong>${escapeHtml(summary.last_sync_text || "jeszcze nie synchronizowano")}</strong>
            </div>
            <div class="overview-tile">
                <span>Status synchronizacji</span>
                <strong>${summary.last_sync_error ? "Błąd" : "OK"}</strong>
                <div class="inline-note">${escapeHtml(summary.last_sync_error || "Eksport DLNA jest gotowy.")}</div>
            </div>
        `;
    }

    function renderCollectionEditorSelect() {
        ensureActiveCollectionId();
        const select = document.getElementById("dlnaCollectionEditorSelect");
        const collections = getManageableCollections();
        if (!select) {
            return;
        }
        if (!collections.length) {
            select.innerHTML = '<option value="">Brak bukietów</option>';
            select.disabled = true;
            return;
        }
        select.innerHTML = collections.map(function (item) {
            return `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`;
        }).join("");
        select.disabled = false;
        select.value = activeCollectionId;
    }

    function renderCollectionCheckboxGrid(selectedIds, scopeName) {
        const selectedSet = new Set((selectedIds || []).map(function (item) { return String(item || ""); }));
        const collections = getCollections();
        if (!collections.length) {
            return '<div class="dlna-empty">Najpierw utwórz bukiet DLNA.</div>';
        }
        return collections.map(function (item) {
            const checked = selectedSet.has(String(item.id || ""));
            const ownerInfo = isAdmin() ? ("Właściciel: " + String(item.owner_username || "")) : "";
            return `
                <label class="dlna-checkbox">
                    <input type="checkbox" value="${escapeHtml(item.id)}" data-checkbox-scope="${escapeHtml(scopeName)}" ${checked ? "checked" : ""}>
                    <span class="dlna-checkbox-text">
                        <strong>${escapeHtml(item.name)}</strong>
                        <span class="small">${escapeHtml(item.description || ownerInfo || "Brak dodatkowego opisu.")}</span>
                    </span>
                </label>
            `;
        }).join("");
    }

    function readCheckboxScope(scopeName, container) {
        return Array.from((container || root).querySelectorAll('input[data-checkbox-scope="' + scopeName + '"]:checked')).map(function (input) {
            return String(input.value || "");
        });
    }

    function renderCollections() {
        const list = document.getElementById("dlnaCollectionsList");
        const meta = document.getElementById("dlnaCollectionsMeta");
        const collections = getCollections();
        if (meta) {
            meta.textContent = collections.length ? (collections.length + " bukietów") : "Brak bukietów";
        }
        if (!list) {
            return;
        }
        if (!collections.length) {
            list.innerHTML = '<div class="dlna-empty">Nie ma jeszcze żadnych bukietów DLNA.</div>';
            return;
        }
        list.innerHTML = collections.map(function (item) {
            const selected = String(item.id || "") === String(activeCollectionId || "");
            const ownerLine = isAdmin() ? ('<div class="small">Właściciel: ' + escapeHtml(item.owner_username || "") + '</div>') : "";
            const canManage = !!item.can_manage;
            const actions = canManage ? `
                <div class="dlna-item-actions">
                    <button type="button" class="btn btn-secondary js-dlna-select-collection" data-collection-id="${escapeHtml(item.id)}">${selected ? "Edytujesz ten bukiet" : "Edytuj pliki"}</button>
                    <button type="button" class="btn js-dlna-save-collection" data-collection-id="${escapeHtml(item.id)}">Zapisz bukiet</button>
                    <button type="button" class="btn btn-stop js-dlna-delete-collection" data-collection-id="${escapeHtml(item.id)}">Usuń bukiet</button>
                </div>
            ` : "";
            return `
                <article class="dlna-card ${selected ? "is-selected" : ""}" data-collection-id="${escapeHtml(item.id)}">
                    <div class="dlna-item-header">
                        <div>
                            <div class="dlna-item-title">${escapeHtml(item.name)}</div>
                            <div class="small">${escapeHtml(item.item_count || 0)} plików</div>
                            ${ownerLine}
                        </div>
                    </div>
                    <div class="dlna-inline-form is-wide">
                        <div class="field-group">
                            <label class="field-label" for="dlnaCollectionName-${escapeHtml(item.id)}">Nazwa bukietu</label>
                            <input id="dlnaCollectionName-${escapeHtml(item.id)}" data-collection-field="name" type="text" value="${escapeHtml(item.name)}" ${canManage ? "" : "disabled"}>
                        </div>
                        <div class="field-group">
                            <label class="field-label" for="dlnaCollectionDescription-${escapeHtml(item.id)}">Opis bukietu</label>
                            <input id="dlnaCollectionDescription-${escapeHtml(item.id)}" data-collection-field="description" type="text" value="${escapeHtml(item.description || "")}" ${canManage ? "" : "disabled"}>
                        </div>
                    </div>
                    ${actions || '<div class="inline-note">Ten bukiet należy do innego użytkownika. Możesz go tylko przeglądać.</div>'}
                </article>
            `;
        }).join("");
    }

    function renderMediaEntries() {
        const list = document.getElementById("dlnaMediaRulesList");
        const meta = document.getElementById("dlnaMediaRulesMeta");
        const entries = Array.isArray(currentState.media_rules) ? currentState.media_rules : [];
        if (meta) {
            meta.textContent = entries.length ? (entries.length + " plików w bukietach") : "Brak plików w bukietach";
        }
        if (!list) {
            return;
        }
        if (!entries.length) {
            list.innerHTML = '<div class="dlna-empty">Żaden plik nie został jeszcze przypisany do bukietu DLNA.</div>';
            return;
        }
        list.innerHTML = entries.map(function (entry) {
            const pendingPublication = !!entry.pending_publication;
            const statusLabel = pendingPublication
                ? "Czeka na publikację"
                : (entry.current_exists ? "W bukiecie" : "Brak na dysku");
            const statusClass = pendingPublication ? "queued" : (entry.current_exists ? "success" : "error");
            const collectionText = Array.isArray(entry.collection_names) && entry.collection_names.length
                ? entry.collection_names.join(", ")
                : "bez bukietu";
            const ownerLine = isAdmin() ? ('<div class="small">Właściciel: ' + escapeHtml(entry.owner_username || "") + '</div>') : "";
            return `
                <article class="dlna-card">
                    <div class="dlna-item-header">
                        <div>
                            <div class="dlna-item-title">${escapeHtml(entry.file_name || entry.display_path || "plik")}</div>
                            <div class="small">${escapeHtml(collectionText)}</div>
                            ${ownerLine}
                        </div>
                        <span class="service-status-pill ${statusClass}">${escapeHtml(statusLabel)}</span>
                    </div>
                    <div class="small">Źródło: ${escapeHtml(entry.display_path || entry.relative_path || "")}</div>
                    <div class="small">Folder bukietu: ${escapeHtml(entry.current_relative_path || "")}</div>
                </article>
            `;
        }).join("");
    }

    function renderLibrarySelectionSummary() {
        const summaryNode = document.getElementById("dlnaLibrarySelectionSummary");
        if (!summaryNode) {
            return;
        }
        const items = Array.from(root.querySelectorAll(".js-dlna-library-checkbox"));
        const checkedCount = items.filter(function (input) { return !!input.checked; }).length;
        const collection = getCollectionById(activeCollectionId);
        if (!collection) {
            summaryNode.textContent = "Najpierw wybierz lub utwórz bukiet DLNA. Lista pokaże wtedy pliki właściciela bukietu.";
            return;
        }
        if (!items.length) {
            summaryNode.textContent = 'Brak widocznych pozycji dla bukietu "' + collection.name + '".';
            return;
        }
        summaryNode.textContent = checkedCount + " z " + items.length + ' widocznych pozycji należy teraz do bukietu "' + collection.name + '".'
            + (isLibrarySelectionDirtyForActiveCollection() ? " Masz niezapisane zmiany wyboru." : "");
    }

    function renderLibraryResults() {
        const list = document.getElementById("dlnaLibraryResults");
        const meta = document.getElementById("dlnaLibraryResultsMeta");
        const selectButton = document.getElementById("dlnaSelectVisibleButton");
        const unselectButton = document.getElementById("dlnaUnselectVisibleButton");
        const saveButton = document.getElementById("dlnaSaveVisibleSelectionButton");
        const collection = getCollectionById(activeCollectionId);
        if (!list) {
            return;
        }
        if (meta) {
            if (currentLibraryResults.total_items) {
                meta.textContent = currentLibraryResults.shown_items + " z " + currentLibraryResults.total_items + " pozycji";
            } else {
                meta.textContent = "";
            }
        }
        if (!collection) {
            list.innerHTML = '<div class="dlna-empty">Najpierw wybierz bukiet DLNA do edycji.</div>';
            if (selectButton) selectButton.disabled = true;
            if (unselectButton) unselectButton.disabled = true;
            if (saveButton) saveButton.disabled = true;
            renderLibrarySelectionSummary();
            return;
        }
        const items = Array.isArray(currentLibraryResults.items) ? currentLibraryResults.items : [];
        if (!items.length) {
            list.innerHTML = '<div class="dlna-empty">Brak pasujących plików dla tego bukietu.</div>';
            if (selectButton) selectButton.disabled = true;
            if (unselectButton) unselectButton.disabled = true;
            if (saveButton) saveButton.disabled = true;
            renderLibrarySelectionSummary();
            return;
        }
        list.innerHTML = items.map(function (item) {
            const checked = !!item.selected;
            const disabled = !!item.blocked_by_other_collection;
            const note = item.blocked_by_other_collection
                ? ('Plik znajduje się już w bukiecie "' + (item.blocked_collection_name || "innego użytkownika") + '".')
                : (item.missing ? "Plik zniknął z dysku i zniknie przy najbliższym czyszczeniu." : item.detail_text || "");
            return `
                <label class="dlna-library-row ${checked ? "is-selected" : ""} ${disabled ? "is-disabled" : ""}">
                    <input
                        class="js-dlna-library-checkbox"
                        type="checkbox"
                        data-entry-id="${escapeHtml(item.entry_id || "")}"
                        data-storage-id="${escapeHtml(item.storage_id || "local")}"
                        data-storage-kind="${escapeHtml(item.storage_kind || "video")}"
                        data-relative-path="${escapeHtml(item.relative_path || "")}"
                        ${checked ? "checked" : ""}
                        ${disabled ? "disabled" : ""}
                    >
                    <span class="dlna-library-row-body">
                        <strong>${escapeHtml(item.title || item.display_path || "plik")}</strong>
                        <span class="small">${escapeHtml(item.display_path || "")}</span>
                        <span class="small">${escapeHtml(note || "")}</span>
                    </span>
                </label>
            `;
        }).join("");
        if (selectButton) selectButton.disabled = false;
        if (unselectButton) unselectButton.disabled = false;
        if (saveButton) saveButton.disabled = false;
        renderLibrarySelectionSummary();
    }

    function renderClients() {
        if (!isAdmin()) {
            return;
        }
        const newClientCollections = document.getElementById("dlnaNewClientCollections");
        if (newClientCollections) {
            newClientCollections.innerHTML = renderCollectionCheckboxGrid([], "new-client");
        }

        const list = document.getElementById("dlnaClientsList");
        const meta = document.getElementById("dlnaClientsMeta");
        const clients = Array.isArray(currentState.clients) ? currentState.clients : [];
        if (meta) {
            meta.textContent = clients.length ? (clients.filter(function (item) { return !!item.enabled; }).length + " aktywnych z " + clients.length) : "Brak klientów";
        }
        if (!list) {
            return;
        }
        if (!clients.length) {
            list.innerHTML = '<div class="dlna-empty">Nie dodano jeszcze żadnych klientów DLNA.</div>';
            return;
        }
        list.innerHTML = clients.map(function (client) {
            return `
                <article class="dlna-card" data-client-id="${escapeHtml(client.id)}">
                    <div class="dlna-item-header">
                        <div>
                            <div class="dlna-item-title">${escapeHtml(client.ip || "")}</div>
                            <div class="small">${escapeHtml(client.description || "Brak opisu urządzenia.")}</div>
                            <div class="small">Widoczne pliki: ${escapeHtml(client.visible_media_count || 0)}</div>
                        </div>
                        <span class="service-status-pill ${client.enabled ? "success" : "muted"}">${client.enabled ? "Aktywny" : "Wyłączony"}</span>
                    </div>
                    <div class="dlna-inline-form is-wide">
                        <div class="field-group">
                            <label class="field-label" for="dlnaClientIp-${escapeHtml(client.id)}">Adres IP</label>
                            <input id="dlnaClientIp-${escapeHtml(client.id)}" data-client-field="ip" type="text" value="${escapeHtml(client.ip || "")}">
                        </div>
                        <div class="field-group">
                            <label class="field-label" for="dlnaClientDescription-${escapeHtml(client.id)}">Opis urządzenia</label>
                            <input id="dlnaClientDescription-${escapeHtml(client.id)}" data-client-field="description" type="text" value="${escapeHtml(client.description || "")}">
                        </div>
                    </div>
                    <label class="dlna-checkbox" style="margin-top: 12px;">
                        <input type="checkbox" data-client-field="enabled" ${client.enabled ? "checked" : ""}>
                        <span class="dlna-checkbox-text">
                            <strong>Klient aktywny</strong>
                            <span class="small">Wyłącz klienta bez kasowania wpisu IP.</span>
                        </span>
                    </label>
                    <div style="margin-top: 12px;">
                        <div class="field-label">Bukiety widoczne dla klienta</div>
                        <div class="dlna-checkbox-grid">${renderCollectionCheckboxGrid(client.collection_ids || [], "client-" + client.id)}</div>
                    </div>
                    <div class="dlna-item-actions">
                        <button type="button" class="btn js-dlna-save-client" data-client-id="${escapeHtml(client.id)}">Zapisz klienta</button>
                        <button type="button" class="btn btn-stop js-dlna-delete-client" data-client-id="${escapeHtml(client.id)}">Usuń klienta</button>
                    </div>
                </article>
            `;
        }).join("");
    }

    function renderPackageAndService() {
        if (!isAdmin()) {
            return;
        }
        const packageState = currentState.dlna_package_state || {};
        const serviceState = currentState.dlna_service_state || {};
        const maintenanceTasks = currentState.maintenance_tasks || {};
        const task = maintenanceTasks.dlna_install || null;
        const taskPanel = document.getElementById("dlnaTaskPanel");
        const busy = !!serviceState.operation_busy;

        const packageStatusPill = document.getElementById("dlnaPackageStatusPill");
        if (packageStatusPill) {
            packageStatusPill.className = "service-status-pill " + String(packageState.status_pill_kind || "muted");
            packageStatusPill.textContent = String(packageState.status_pill_label || "Nieznany");
        }
        const checkedAt = document.getElementById("dlnaPackageCheckedAt");
        if (checkedAt) {
            checkedAt.textContent = "Ostatnie sprawdzenie: " + String(packageState.checked_at_text || "jeszcze nie sprawdzano");
        }
        const currentVersion = document.getElementById("dlnaPackageCurrentVersion");
        if (currentVersion) {
            currentVersion.textContent = String(packageState.current_version || "brak");
        }
        const latestVersion = document.getElementById("dlnaPackageLatestVersion");
        if (latestVersion) {
            latestVersion.textContent = String(packageState.latest_version || "brak danych");
        }
        const packageSource = document.getElementById("dlnaPackageSource");
        if (packageSource) {
            packageSource.textContent = String(packageState.source_label || "Pakiet Debian / apt");
        }
        const packageError = document.getElementById("dlnaPackageErrorBox");
        if (packageError) {
            packageError.hidden = !packageState.check_error;
            packageError.textContent = packageState.check_error ? ("Błąd sprawdzania pakietu: " + packageState.check_error) : "";
        }
        const packageActionButton = document.getElementById("dlnaPackageActionButton");
        if (packageActionButton) {
            packageActionButton.hidden = !packageState.action_needed;
            packageActionButton.textContent = String(packageState.action_button_label || "Zainstaluj lub zaktualizuj DLNA");
            packageActionButton.dataset.idleLabel = packageActionButton.textContent;
            packageActionButton.disabled = !!(task && task.active);
        }
        const packageActionNote = document.getElementById("dlnaPackageActionNote");
        if (packageActionNote) {
            packageActionNote.hidden = !!packageState.action_needed;
            packageActionNote.textContent = packageState.action_needed ? "" : "Pakiet Gerbera jest już aktualny.";
        }

        if (taskPanel) {
            if (!task || !task.visible) {
                taskPanel.hidden = true;
            } else {
                taskPanel.hidden = false;
                const taskPill = document.getElementById("dlnaTaskStatusPill");
                const taskLabel = document.getElementById("dlnaTaskLabel");
                const taskPercent = document.getElementById("dlnaTaskPercent");
                const taskBar = document.getElementById("dlnaTaskBar");
                const taskProgress = document.getElementById("dlnaTaskProgress");
                const taskDetail = document.getElementById("dlnaTaskDetail");
                const taskTime = document.getElementById("dlnaTaskTime");
                if (taskPill) {
                    taskPill.className = "service-status-pill " + String(task.status_kind || "muted");
                    taskPill.textContent = String(task.status_label || "...");
                }
                if (taskLabel) taskLabel.textContent = String(task.title || "Instalacja serwera DLNA");
                if (taskPercent) taskPercent.textContent = task.progress_percent === null || task.progress_percent === undefined ? "..." : (Number(task.progress_percent).toFixed(1) + "%");
                if (taskBar) {
                    taskBar.className = "progress-bar " + (task.status === "error" ? "error" : (task.status === "success" ? "completed" : "downloading"));
                    taskBar.style.width = task.progress_percent === null || task.progress_percent === undefined
                        ? "38%"
                        : (Math.max(0, Math.min(100, Number(task.progress_percent) || 0)) + "%");
                }
                if (taskProgress) {
                    taskProgress.classList.toggle("is-indeterminate", task.progress_percent === null || task.progress_percent === undefined);
                }
                if (taskDetail) taskDetail.textContent = String(task.detail || task.message || "");
                if (taskTime) {
                    taskTime.textContent = task.active
                        ? ("Start: " + String(task.started_at_text || ""))
                        : (task.finished_at_text ? ("Zakończono: " + String(task.finished_at_text || "")) : "");
                }
            }
        }

        const servicePill = document.getElementById("dlnaServiceStatusPill");
        if (servicePill) {
            servicePill.className = "service-status-pill " + String(serviceState.status_kind || "muted");
            servicePill.textContent = String(serviceState.status_label || "Nieznany");
        }
        const servicePid = document.getElementById("dlnaServicePidText");
        if (servicePid) {
            servicePid.textContent = serviceState.main_pid
                ? ("PID: " + String(serviceState.main_pid) + (serviceState.sub_state ? " | " + String(serviceState.sub_state) : ""))
                : String(serviceState.sub_state || "Brak PID");
        }
        const serviceUnitState = document.getElementById("dlnaServiceUnitState");
        if (serviceUnitState) {
            serviceUnitState.textContent = String(serviceState.unit_file_label || "nieznany");
        }
        const serviceUptime = document.getElementById("dlnaServiceUptime");
        if (serviceUptime) {
            serviceUptime.textContent = String(serviceState.service_uptime_text || "nieznany");
        }
        const serviceLastRestart = document.getElementById("dlnaServiceLastRestart");
        if (serviceLastRestart) {
            serviceLastRestart.textContent = String(serviceState.last_restart_text || "nieznany");
        }
        const exportRoot = document.getElementById("dlnaExportRoot");
        if (exportRoot) {
            exportRoot.textContent = String(serviceState.export_root || "");
        }
        const configFile = document.getElementById("dlnaConfigFile");
        if (configFile) {
            configFile.textContent = String(serviceState.config_file || "");
        }
        const diagnostics = document.getElementById("dlnaServiceDiagnostics");
        if (diagnostics) {
            const message = String(serviceState.operation_busy_label || serviceState.runtime_phase_detail || "");
            diagnostics.hidden = !message;
            diagnostics.textContent = message;
        }
        const serviceError = document.getElementById("dlnaServiceErrorBox");
        if (serviceError) {
            const errorText = String(serviceState.error || "");
            serviceError.hidden = !errorText;
            serviceError.textContent = errorText;
        }
        const serviceLogBox = document.getElementById("dlnaServiceLogBox");
        if (serviceLogBox) {
            const logSnippet = String(serviceState.last_log_excerpt || "");
            serviceLogBox.hidden = !logSnippet;
            serviceLogBox.textContent = logSnippet;
        }
        const toggleButton = document.getElementById("dlnaServiceToggleButton");
        if (toggleButton) {
            toggleButton.textContent = String(serviceState.toggle_button_label || "Zmień stan usługi");
            toggleButton.dataset.idleLabel = toggleButton.textContent;
            toggleButton.disabled = !serviceState.allow_toggle;
        }
        const restartButton = document.getElementById("dlnaServiceRestartButton");
        if (restartButton) {
            restartButton.textContent = String(serviceState.restart_button_label || "Uruchom ponownie serwer DLNA");
            restartButton.dataset.idleLabel = restartButton.textContent;
            restartButton.disabled = !serviceState.allow_restart;
        }
        const resyncButton = document.getElementById("dlnaResyncButton");
        if (resyncButton) {
            resyncButton.disabled = !serviceState.allow_resync;
        }

        const serverName = document.getElementById("dlnaServerName");
        if (serverName && document.activeElement !== serverName) {
            serverName.value = String((currentState.dlna_config || {}).server_name || "");
        }
        const bindIp = document.getElementById("dlnaBindIp");
        if (bindIp && document.activeElement !== bindIp) {
            bindIp.value = String((currentState.dlna_config || {}).bind_ip || "");
        }
        const port = document.getElementById("dlnaPort");
        if (port && document.activeElement !== port) {
            port.value = String((currentState.dlna_config || {}).port || "");
        }

        const iconState = currentState.dlna_icon_state || {};
        const iconImage = document.getElementById("dlnaIconPreviewImage");
        if (iconImage) {
            iconImage.src = "/api/dlna/icon-preview?v=" + encodeURIComponent(String(iconState.updated_at || Date.now()));
        }
        const iconModeLabel = document.getElementById("dlnaIconModeLabel");
        if (iconModeLabel) {
            iconModeLabel.textContent = iconState.mode === "custom" ? "Własna ikona DLNA" : "Domyślna ikona Gerbery";
        }
        const iconSourceName = document.getElementById("dlnaIconSourceName");
        if (iconSourceName) {
            iconSourceName.textContent = iconState.source_name
                ? ("Plik źródłowy: " + String(iconState.source_name))
                : "Brak własnego pliku źródłowego.";
        }
        const iconUpdatedAt = document.getElementById("dlnaIconUpdatedAt");
        if (iconUpdatedAt) {
            iconUpdatedAt.textContent = iconState.updated_at_text
                ? ("Ostatnia zmiana: " + String(iconState.updated_at_text))
                : "";
        }
    }

    function applyState(nextState, rerenderAll) {
        currentState = nextState || {};
        ensureActiveCollectionId();
        renderMount();
        renderSummary();
        renderCollectionEditorSelect();
        renderCollections();
        renderMediaEntries();
        renderClients();
        renderPackageAndService();
        setActiveTab(activeTab, false);
        persistUiState();
        if (isLibrarySelectionDirtyForActiveCollection()) {
            renderLibrarySelectionSummary();
            return;
        }
        if (rerenderAll || String(currentLibraryResults.collection_id || "") !== String(activeCollectionId || "")) {
            refreshLibraryResults();
        } else {
            renderLibraryResults();
        }
    }

    async function refreshState(rerenderAll) {
        try {
            const data = await fetchJson("/api/dlna/state");
            applyState(data.state || {}, !!rerenderAll);
            return data;
        } catch (err) {
            return null;
        }
    }

    async function refreshLibraryResults() {
        clearLibrarySelectionDirty();
        renderCollectionEditorSelect();
        const queryInput = document.getElementById("dlnaLibraryQuery");
        const query = queryInput ? String(queryInput.value || "") : "";
        if (!activeCollectionId) {
            currentLibraryResults = {
                items: [],
                total_items: 0,
                shown_items: 0,
                collection_id: "",
                collection_name: "",
                mode: "files",
            };
            renderLibraryResults();
            return;
        }
        try {
            const data = await fetchJson(
                "/api/dlna/library?collection_id=" + encodeURIComponent(activeCollectionId)
                + "&query=" + encodeURIComponent(query)
                + "&mode=files&limit=300"
            );
            currentLibraryResults = data.results || currentLibraryResults;
        } catch (err) {
            currentLibraryResults = {
                items: [],
                total_items: 0,
                shown_items: 0,
                collection_id: activeCollectionId,
                collection_name: (getCollectionById(activeCollectionId) || {}).name || "",
                mode: "files",
            };
        }
        renderLibraryResults();
    }

    async function performAction(button, busyLabel, action, options) {
        const opts = options || {};
        const preserveDirtyLibrary = Object.prototype.hasOwnProperty.call(opts, "preserveDirtyLibrarySelection")
            ? !!opts.preserveDirtyLibrarySelection
            : isLibrarySelectionDirtyForActiveCollection();
        setButtonBusy(button, true, busyLabel);
        try {
            const data = await action();
            if (data && data.dlna_state) {
                applyState(data.dlna_state, true);
            }
            if (data && data.message) {
                showToast(data.message, data.kind || "success");
            }
            if (opts.refreshLibrary !== false) {
                if (preserveDirtyLibrary) {
                    renderLibrarySelectionSummary();
                } else {
                    await refreshLibraryResults();
                }
            }
            return true;
        } catch (err) {
            showToast(String(err || "Operacja zakończyła się błędem."), "error");
            return false;
        } finally {
            setButtonBusy(button, false);
        }
    }

    function readVisibleLibraryItems() {
        return Array.from(root.querySelectorAll(".js-dlna-library-checkbox")).map(function (input) {
            return {
                entry_id: String(input.dataset.entryId || ""),
                storage_id: String(input.dataset.storageId || "local"),
                storage_kind: String(input.dataset.storageKind || "video"),
                relative_path: String(input.dataset.relativePath || ""),
                checked: !!input.checked,
            };
        });
    }

    async function handleRootClick(event) {
        const tabButton = event.target.closest("[data-dlna-tab-button]");
        if (tabButton) {
            event.preventDefault();
            setActiveTab(tabButton.dataset.dlnaTabButton || "bukiety");
            return;
        }

        const selectCollectionButton = event.target.closest(".js-dlna-select-collection");
        if (selectCollectionButton) {
            event.preventDefault();
            activeCollectionId = String(selectCollectionButton.dataset.collectionId || "");
            clearLibrarySelectionDirty();
            persistUiState();
            renderCollections();
            await refreshLibraryResults();
            return;
        }

        const saveCollectionButton = event.target.closest(".js-dlna-save-collection");
        if (saveCollectionButton) {
            event.preventDefault();
            const collectionId = String(saveCollectionButton.dataset.collectionId || "");
            const card = saveCollectionButton.closest("[data-collection-id]");
            if (!collectionId || !card) {
                return;
            }
            await performAction(saveCollectionButton, "Zapisywanie...", function () {
                return postJson("/api/dlna/collections", {
                    action: "update",
                    collection_id: collectionId,
                    name: String((card.querySelector('[data-collection-field="name"]') || {}).value || ""),
                    description: String((card.querySelector('[data-collection-field="description"]') || {}).value || ""),
                });
            });
            return;
        }

        const deleteCollectionButton = event.target.closest(".js-dlna-delete-collection");
        if (deleteCollectionButton) {
            event.preventDefault();
            if (!confirm("Usunąć ten bukiet? Wszystkie jego pliki wrócą do oryginalnych lokalizacji.")) {
                return;
            }
            const collectionId = String(deleteCollectionButton.dataset.collectionId || "");
            await performAction(deleteCollectionButton, "Usuwanie...", function () {
                return postJson("/api/dlna/collections", {
                    action: "delete",
                    collection_id: collectionId,
                });
            });
            if (String(activeCollectionId || "") === collectionId) {
                activeCollectionId = "";
            }
            return;
        }

        const saveClientButton = event.target.closest(".js-dlna-save-client");
        if (saveClientButton) {
            event.preventDefault();
            const card = saveClientButton.closest("[data-client-id]");
            const clientId = card ? String(card.dataset.clientId || "") : "";
            if (!card || !clientId) {
                return;
            }
            await performAction(saveClientButton, "Zapisywanie...", function () {
                return postJson("/api/dlna/clients", {
                    action: "update",
                    client_id: clientId,
                    ip: String((card.querySelector('[data-client-field="ip"]') || {}).value || ""),
                    description: String((card.querySelector('[data-client-field="description"]') || {}).value || ""),
                    enabled: !!((card.querySelector('[data-client-field="enabled"]') || {}).checked),
                    collection_ids: readCheckboxScope("client-" + clientId, card),
                });
            });
            return;
        }

        const deleteClientButton = event.target.closest(".js-dlna-delete-client");
        if (deleteClientButton) {
            event.preventDefault();
            if (!confirm("Usunąć tego klienta DLNA z whitelisty?")) {
                return;
            }
            const clientId = String(deleteClientButton.dataset.clientId || "");
            await performAction(deleteClientButton, "Usuwanie...", function () {
                return postJson("/api/dlna/clients", {
                    action: "delete",
                    client_id: clientId,
                });
            });
            return;
        }

        const selectVisibleButton = event.target.closest("#dlnaSelectVisibleButton");
        if (selectVisibleButton) {
            event.preventDefault();
            root.querySelectorAll(".js-dlna-library-checkbox:not([disabled])").forEach(function (input) {
                input.checked = true;
                const row = input.closest(".dlna-library-row");
                if (row) {
                    row.classList.add("is-selected");
                }
            });
            markLibrarySelectionDirty();
            renderLibrarySelectionSummary();
            return;
        }

        const unselectVisibleButton = event.target.closest("#dlnaUnselectVisibleButton");
        if (unselectVisibleButton) {
            event.preventDefault();
            root.querySelectorAll(".js-dlna-library-checkbox:not([disabled])").forEach(function (input) {
                input.checked = false;
                const row = input.closest(".dlna-library-row");
                if (row) {
                    row.classList.remove("is-selected");
                }
            });
            markLibrarySelectionDirty();
            renderLibrarySelectionSummary();
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
            await performAction(saveVisibleSelectionButton, "Zapisywanie...", function () {
                return postJson("/api/dlna/media", {
                    action: "bulk_assign_collection",
                    collection_id: activeCollectionId,
                    items: items,
                });
            }, {preserveDirtyLibrarySelection: false});
            return;
        }

        const packageCheckButton = event.target.closest("#dlnaPackageCheckButton");
        if (packageCheckButton) {
            event.preventDefault();
            await performAction(packageCheckButton, "Sprawdzanie...", function () {
                return postJson("/api/dlna/package-check");
            });
            return;
        }

        const packageActionButton = event.target.closest("#dlnaPackageActionButton");
        if (packageActionButton) {
            event.preventDefault();
            await performAction(packageActionButton, "Uruchamianie...", function () {
                return postJson("/api/dlna/package-install");
            });
            return;
        }

        const toggleButton = event.target.closest("#dlnaServiceToggleButton");
        if (toggleButton) {
            event.preventDefault();
            const enabled = !((currentState.dlna_service_state || {}).desired_enabled);
            await performAction(toggleButton, enabled ? "Włączanie..." : "Wyłączanie...", function () {
                return postJson("/api/dlna/service-toggle", {enabled: enabled});
            });
            return;
        }

        const restartButton = event.target.closest("#dlnaServiceRestartButton");
        if (restartButton) {
            event.preventDefault();
            await performAction(restartButton, "Restartowanie...", function () {
                return postJson("/api/dlna/service-restart");
            });
            return;
        }

        const resyncButton = event.target.closest("#dlnaResyncButton");
        if (resyncButton) {
            event.preventDefault();
            await performAction(resyncButton, "Synchronizacja...", function () {
                return postJson("/api/dlna/resync");
            });
            return;
        }

        const resetIconButton = event.target.closest("#dlnaIconResetButton");
        if (resetIconButton) {
            event.preventDefault();
            await performAction(resetIconButton, "Przywracanie...", function () {
                return postJson("/api/dlna/icon-reset");
            });
        }
    }

    async function handleRootSubmit(event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        if (form.id === "dlnaCreateCollectionForm") {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            const ok = await performAction(button, "Dodawanie...", function () {
                return postJson("/api/dlna/collections", {
                    action: "create",
                    name: String(form.name.value || ""),
                    description: String(form.description.value || ""),
                });
            });
            if (ok) {
                form.reset();
            }
            return;
        }

        if (form.id === "dlnaCreateClientForm") {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            const ok = await performAction(button, "Dodawanie...", function () {
                return postJson("/api/dlna/clients", {
                    action: "create",
                    ip: String(form.ip.value || ""),
                    description: String(form.description.value || ""),
                    enabled: !!form.enabled.checked,
                    collection_ids: readCheckboxScope("new-client"),
                });
            });
            if (ok) {
                form.reset();
                const enabledInput = form.querySelector("#dlnaNewClientEnabled");
                if (enabledInput) {
                    enabledInput.checked = true;
                }
                renderClients();
            }
            return;
        }

        if (form.id === "dlnaServerSettingsForm") {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            await performAction(button, "Zapisywanie...", function () {
                return postJson("/api/dlna/settings", {
                    server_name: String(form.server_name.value || ""),
                    bind_ip: String(form.bind_ip.value || ""),
                    port: String(form.port.value || ""),
                });
            });
            return;
        }

        if (form.id === "dlnaIconUploadForm") {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            const ok = await performAction(button, "Wgrywanie...", function () {
                return postFormData("/api/dlna/icon-upload", new FormData(form));
            });
            if (ok) {
                form.reset();
            }
        }
    }

    function handleRootChange(event) {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }
        if (target.matches("#dlnaCollectionEditorSelect")) {
            activeCollectionId = String(target.value || "");
            clearLibrarySelectionDirty();
            persistUiState();
            renderCollections();
            refreshLibraryResults();
            return;
        }
        if (target.matches(".js-dlna-library-checkbox")) {
            const row = target.closest(".dlna-library-row");
            if (row) {
                row.classList.toggle("is-selected", !!target.checked);
            }
            markLibrarySelectionDirty();
            renderLibrarySelectionSummary();
        }
    }

    function handleLibrarySearchInput() {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () {
            refreshLibraryResults();
        }, 260);
    }

    function handleLivePayload(data) {
        if (!data || !data.state) {
            return;
        }
        applyState(data.state, false);
    }

    root.addEventListener("click", handleRootClick);
    root.addEventListener("change", handleRootChange, true);
    root.addEventListener("submit", handleRootSubmit, true);
    const libraryQueryInput = document.getElementById("dlnaLibraryQuery");
    if (libraryQueryInput) {
        libraryQueryInput.addEventListener("input", handleLibrarySearchInput);
    }

    applyState(currentState, true);

    if (window.appLive && typeof window.appLive.createSubscription === "function") {
        liveSubscription = window.appLive.createSubscription({
            url: "/api/dlna/stream",
            fallbackIntervalMs: 2000,
            fetchFallback: function () {
                return refreshState(false);
            },
            onData: handleLivePayload,
        });
        liveSubscription.start();
    } else {
        const timer = setInterval(function () {
            refreshState(false);
        }, 2000);
        liveSubscription = {
            stop: function () {
                clearInterval(timer);
            },
        };
    }

    if (typeof window.registerPageCleanup === "function") {
        window.registerPageCleanup(function () {
            clearTimeout(searchTimer);
            if (libraryQueryInput) {
                libraryQueryInput.removeEventListener("input", handleLibrarySearchInput);
            }
            root.removeEventListener("click", handleRootClick);
            root.removeEventListener("change", handleRootChange, true);
            root.removeEventListener("submit", handleRootSubmit, true);
            if (liveSubscription && typeof liveSubscription.stop === "function") {
                liveSubscription.stop();
            }
        });
    }
})();
