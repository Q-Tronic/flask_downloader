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
    let newCollectionDraft = null;
    const collectionDrafts = new Map();
    let newClientDraft = null;
    const clientDrafts = new Map();
    let collectionModalState = {mode: "create", collectionId: ""};
    let clientModalState = {mode: "create", clientId: ""};

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

    function getAvailableUsers() {
        return Array.isArray(currentState.available_users) ? currentState.available_users : [];
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

    function getClientById(clientId) {
        const normalizedId = String(clientId || "");
        const clients = Array.isArray(currentState.clients) ? currentState.clients : [];
        return clients.find(function (item) {
            return String((item && item.id) || "") === normalizedId;
        }) || null;
    }

    function normalizeStringList(values) {
        const result = [];
        const seen = new Set();
        (values || []).forEach(function (item) {
            const value = String(item || "").trim();
            if (!value || seen.has(value)) {
                return;
            }
            seen.add(value);
            result.push(value);
        });
        return result;
    }

    function normalizeSortedStringList(values) {
        return normalizeStringList(values).slice().sort();
    }

    function sameStringList(left, right) {
        const a = normalizeSortedStringList(left);
        const b = normalizeSortedStringList(right);
        if (a.length !== b.length) {
            return false;
        }
        for (let index = 0; index < a.length; index += 1) {
            if (a[index] !== b[index]) {
                return false;
            }
        }
        return true;
    }

    function buildEffectiveCollectionIds(explicitCollectionIds, usernames) {
        const result = normalizeStringList(explicitCollectionIds);
        const seen = new Set(result);
        const assignedUsers = new Set(normalizeStringList(usernames));
        getCollections().forEach(function (item) {
            const collectionId = String((item && item.id) || "").trim();
            const ownerUsername = String((item && item.owner_username) || "").trim();
            if (!collectionId || !ownerUsername || !assignedUsers.has(ownerUsername) || seen.has(collectionId)) {
                return;
            }
            seen.add(collectionId);
            result.push(collectionId);
        });
        return result;
    }

    function mapCollectionNames(collectionIds) {
        const names = [];
        normalizeStringList(collectionIds).forEach(function (collectionId) {
            const collection = getCollectionById(collectionId);
            if (collection && collection.name) {
                names.push(String(collection.name));
            }
        });
        return names;
    }

    function mapUserLabels(usernames) {
        const userMap = new Map(getAvailableUsers().map(function (item) {
            return [String((item && item.username) || ""), item || {}];
        }));
        return normalizeStringList(usernames).map(function (username) {
            const item = userMap.get(username) || {};
            const role = String(item.role || "user").toLowerCase() === "admin" ? "admin" : "user";
            return {
                username: username,
                role: role,
                text: username + " (" + (role === "admin" ? "Administrator" : "Użytkownik") + ")",
            };
        });
    }

    function getClientDraft(clientId) {
        return clientDrafts.get(String(clientId || "")) || null;
    }

    function hasClientDrafts() {
        return !!newClientDraft || clientDrafts.size > 0;
    }

    function getCollectionDraft(collectionId) {
        return collectionDrafts.get(String(collectionId || "")) || null;
    }

    function clearClientDraft(clientId) {
        clientDrafts.delete(String(clientId || ""));
    }

    function clearNewClientDraft() {
        newClientDraft = null;
    }

    function clearCollectionDraft(collectionId) {
        collectionDrafts.delete(String(collectionId || ""));
    }

    function clearNewCollectionDraft() {
        newCollectionDraft = null;
    }

    function createClientViewModel(client) {
        const clientId = String((client && client.id) || "");
        const draft = getClientDraft(clientId);
        const explicitCollectionIds = draft ? normalizeStringList(draft.collection_ids) : normalizeStringList((client && client.collection_ids) || []);
        const usernames = draft ? normalizeStringList(draft.usernames) : normalizeStringList((client && client.usernames) || []);
        const effectiveCollectionIds = buildEffectiveCollectionIds(
            explicitCollectionIds,
            usernames,
        );
        return Object.assign({}, client || {}, draft || {}, {
            collection_ids: explicitCollectionIds,
            collection_names: mapCollectionNames(explicitCollectionIds),
            effective_collection_ids: effectiveCollectionIds,
            effective_collection_names: mapCollectionNames(effectiveCollectionIds),
            usernames: usernames,
            user_labels: mapUserLabels(usernames),
        });
    }

    function createCollectionViewModel(collection) {
        const collectionId = String((collection && collection.id) || "");
        const draft = getCollectionDraft(collectionId);
        return Object.assign({}, collection || {}, draft || {});
    }

    function readClientFormDraft(form, scopePrefix, clientId) {
        return {
            id: String(clientId || ""),
            ip: String((form && form.ip && form.ip.value) || ""),
            description: String((form && form.description && form.description.value) || ""),
            enabled: !!((form && form.enabled && form.enabled.checked)),
            collection_ids: readCheckboxScope(scopePrefix, form || root),
            usernames: readCheckboxScope(scopePrefix + "-users", form || root),
        };
    }

    function syncClientDraft(form, scopePrefix, clientId) {
        if (!form) {
            return;
        }
        const normalizedClientId = String(clientId || "");
        if (!normalizedClientId) {
            return;
        }
        const draft = readClientFormDraft(form, scopePrefix, normalizedClientId);
        const serverClient = getClientById(normalizedClientId);
        if (!serverClient) {
            clientDrafts.set(normalizedClientId, draft);
            return;
        }
        const shouldKeepDraft = (
            String(serverClient.ip || "") !== draft.ip
            || String(serverClient.description || "") !== draft.description
            || !!serverClient.enabled !== !!draft.enabled
            || !sameStringList(serverClient.collection_ids || [], draft.collection_ids)
            || !sameStringList(serverClient.usernames || [], draft.usernames)
        );
        if (shouldKeepDraft) {
            clientDrafts.set(normalizedClientId, draft);
        } else {
            clientDrafts.delete(normalizedClientId);
        }
    }

    function readNewClientDraft(form) {
        return readClientFormDraft(form, "new-client-modal", "");
    }

    function syncNewClientDraft(form) {
        if (!form) {
            return;
        }
        const draft = readNewClientDraft(form);
        const shouldKeepDraft = (
            !!draft.ip
            || !!draft.description
            || !draft.enabled
            || (draft.collection_ids || []).length > 0
            || (draft.usernames || []).length > 0
        );
        newClientDraft = shouldKeepDraft ? draft : null;
    }

    function readCollectionFormDraft(form) {
        return {
            name: String((form && form.name && form.name.value) || ""),
            description: String((form && form.description && form.description.value) || ""),
        };
    }

    function syncCollectionModalDraft(form) {
        if (!form) {
            return;
        }
        const draft = readCollectionFormDraft(form);
        const mode = String(collectionModalState.mode || "create");
        if (mode === "create") {
            const shouldKeepDraft = !!draft.name || !!draft.description;
            newCollectionDraft = shouldKeepDraft ? draft : null;
            return;
        }
        const collectionId = String(collectionModalState.collectionId || "");
        if (!collectionId) {
            return;
        }
        const serverCollection = getCollectionById(collectionId);
        if (!serverCollection) {
            collectionDrafts.set(collectionId, draft);
            return;
        }
        const shouldKeepDraft = (
            String(serverCollection.name || "") !== draft.name
            || String(serverCollection.description || "") !== draft.description
        );
        if (shouldKeepDraft) {
            collectionDrafts.set(collectionId, draft);
        } else {
            collectionDrafts.delete(collectionId);
        }
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

    function setModalOpen(modalId, open) {
        const modal = document.getElementById(modalId);
        if (!modal) {
            return;
        }
        modal.hidden = !open;
        document.body.classList.toggle(
            "has-modal-open",
            Array.from(root.querySelectorAll(".app-modal")).some(function (node) {
                return !node.hidden;
            })
        );
    }

    function openCollectionModal(mode, collectionId) {
        collectionModalState = {
            mode: String(mode || "create"),
            collectionId: String(collectionId || ""),
        };
        renderCollectionModal();
        setModalOpen("dlnaCollectionModal", true);
    }

    function closeCollectionModal() {
        setModalOpen("dlnaCollectionModal", false);
    }

    function openClientModal(mode, clientId) {
        clientModalState = {
            mode: String(mode || "create"),
            clientId: String(clientId || ""),
        };
        renderClientModal();
        setModalOpen("dlnaClientModal", true);
    }

    function closeClientModal() {
        setModalOpen("dlnaClientModal", false);
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

    function renderUserCheckboxGrid(selectedUsernames, scopeName) {
        const selectedSet = new Set((selectedUsernames || []).map(function (item) { return String(item || ""); }));
        const users = getAvailableUsers();
        if (!users.length) {
            return '<div class="dlna-empty">Brak dostępnych użytkowników.</div>';
        }
        return users.map(function (item) {
            const username = String((item && item.username) || "");
            const checked = selectedSet.has(username);
            const roleLabel = String((item && item.role) || "user").toLowerCase() === "admin" ? "Administrator" : "Użytkownik";
            return `
                <label class="dlna-checkbox">
                    <input type="checkbox" value="${escapeHtml(username)}" data-checkbox-scope="${escapeHtml(scopeName)}" ${checked ? "checked" : ""}>
                    <span class="dlna-checkbox-text">
                        <strong>${escapeHtml(username)}</strong>
                        <span class="small">${escapeHtml(roleLabel)}</span>
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

    function renderCollectionModal() {
        const form = document.getElementById("dlnaCollectionModalForm");
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        const title = document.getElementById("dlnaCollectionModalTitle");
        const subtitle = document.getElementById("dlnaCollectionModalSubtitle");
        const submit = document.getElementById("dlnaCollectionModalSubmit");
        const mode = String(collectionModalState.mode || "create");
        const collection = mode === "edit" ? createCollectionViewModel(getCollectionById(collectionModalState.collectionId) || {}) : null;
        const draft = mode === "edit"
            ? (getCollectionDraft(collectionModalState.collectionId) || null)
            : (newCollectionDraft || null);
        const value = Object.assign({
            name: "",
            description: "",
        }, collection || {}, draft || {});
        if (title) {
            title.textContent = mode === "edit" ? "Edytuj bukiet" : "Nowy bukiet";
        }
        if (subtitle) {
            subtitle.textContent = mode === "edit"
                ? "Zmień nazwę albo opis wybranego bukietu DLNA."
                : "Utwórz nowy bukiet DLNA i później przypisz do niego pliki.";
        }
        if (submit) {
            submit.textContent = mode === "edit" ? "Zapisz bukiet" : "Dodaj bukiet";
            submit.dataset.idleLabel = submit.textContent;
        }
        if (form.name) {
            form.name.value = String(value.name || "");
        }
        if (form.description) {
            form.description.value = String(value.description || "");
        }
    }

    function renderClientModal() {
        const form = document.getElementById("dlnaClientModalForm");
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        const title = document.getElementById("dlnaClientModalTitle");
        const submit = document.getElementById("dlnaClientModalSubmit");
        const mode = String(clientModalState.mode || "create");
        const client = mode === "edit" ? createClientViewModel(getClientById(clientModalState.clientId) || {}) : null;
        const draft = mode === "edit"
            ? (getClientDraft(clientModalState.clientId) || null)
            : (newClientDraft || null);
        const clientView = Object.assign({
            ip: "",
            description: "",
            enabled: true,
            collection_ids: [],
            usernames: [],
        }, client || {}, draft || {});
        if (title) {
            title.textContent = mode === "edit" ? "Edytuj klienta DLNA" : "Nowy klient DLNA";
        }
        if (submit) {
            submit.textContent = mode === "edit" ? "Zapisz klienta" : "Dodaj klienta";
            submit.dataset.idleLabel = submit.textContent;
        }
        if (form.ip) {
            form.ip.value = String(clientView.ip || "");
        }
        if (form.description) {
            form.description.value = String(clientView.description || "");
        }
        if (form.enabled) {
            form.enabled.checked = !!clientView.enabled;
        }
        const collectionsBox = document.getElementById("dlnaClientModalCollections");
        if (collectionsBox) {
            collectionsBox.innerHTML = renderCollectionCheckboxGrid(
                clientView.collection_ids || [],
                mode === "edit" ? ("client-modal-" + clientModalState.clientId) : "new-client-modal"
            );
        }
        const usersBox = document.getElementById("dlnaClientModalUsers");
        if (usersBox) {
            usersBox.innerHTML = renderUserCheckboxGrid(
                clientView.usernames || [],
                mode === "edit" ? ("client-modal-" + clientModalState.clientId + "-users") : "new-client-modal-users"
            );
        }
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
            const collectionView = createCollectionViewModel(item);
            const selected = String(item.id || "") === String(activeCollectionId || "");
            const canManage = !!item.can_manage;
            const itemCount = Number(collectionView.item_count || 0);
            const metaParts = [];
            if (isAdmin()) {
                metaParts.push("Właściciel: " + String(collectionView.owner_username || "-"));
            }
            metaParts.push(itemCount + " " + (itemCount === 1 ? "plik" : "plików"));
            if (collectionView.description) {
                metaParts.push(String(collectionView.description));
            }
            return `
                <article class="dlna-compact-row ${selected ? "is-selected" : ""}">
                    <div class="dlna-compact-main">
                        <div class="dlna-compact-head">
                            <div class="dlna-compact-title">${escapeHtml(collectionView.name)}</div>
                            <span class="service-status-pill muted dlna-inline-status">${itemCount} ${itemCount === 1 ? "plik" : "plików"}</span>
                        </div>
                        <div class="dlna-compact-meta">${escapeHtml(metaParts.join(" · "))}</div>
                    </div>
                    <div class="dlna-compact-actions">
                        <button type="button" class="btn btn-secondary js-dlna-select-collection" data-collection-id="${escapeHtml(item.id)}">${selected ? "Edytujesz pliki" : "Pliki"}</button>
                        ${canManage ? `
                            <button type="button" class="btn js-dlna-open-edit-collection" data-collection-id="${escapeHtml(item.id)}">Edytuj</button>
                            <button type="button" class="btn btn-stop js-dlna-delete-collection" data-collection-id="${escapeHtml(item.id)}">Usuń</button>
                        ` : ""}
                    </div>
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

    function renderClients(options) {
        if (!isAdmin()) {
            return;
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
            const clientView = createClientViewModel(client);
            const visibleCollections = Array.isArray(clientView.effective_collection_names) ? clientView.effective_collection_names : [];
            const userLabels = Array.isArray(clientView.user_labels) ? clientView.user_labels.map(function (item) { return item.text || item.username || ""; }) : [];
            return `
                <article class="dlna-compact-row">
                    <div class="dlna-compact-main">
                        <div class="dlna-compact-head">
                            <div class="dlna-compact-title">${escapeHtml(clientView.ip || "")}</div>
                            <span class="service-status-pill ${clientView.enabled ? "success" : "muted"} dlna-inline-status">${clientView.enabled ? "Aktywny" : "Wyłączony"}</span>
                        </div>
                        <div class="dlna-compact-meta">${escapeHtml(clientView.description || "Brak opisu urządzenia.")} · Widoczne pliki: ${escapeHtml(clientView.visible_media_count || 0)}</div>
                        <div class="dlna-compact-tags">
                            <span class="dlna-token">${visibleCollections.length ? escapeHtml("Bukiety: " + visibleCollections.join(", ")) : "Brak widocznych bukietów"}</span>
                            ${userLabels.length ? ('<span class="dlna-token">' + escapeHtml("Użytkownicy: " + userLabels.join(", ")) + '</span>') : ""}
                        </div>
                    </div>
                    <div class="dlna-compact-actions">
                        <button type="button" class="btn btn-secondary js-dlna-open-edit-client" data-client-id="${escapeHtml(clientView.id)}">Edytuj</button>
                        <button type="button" class="btn btn-stop js-dlna-delete-client" data-client-id="${escapeHtml(clientView.id)}">Usuń klienta</button>
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
        renderClients({force: true});
        renderCollectionModal();
        renderClientModal();
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

        const openCreateCollectionModalButton = event.target.closest("#dlnaOpenCreateCollectionModal");
        if (openCreateCollectionModalButton) {
            event.preventDefault();
            openCollectionModal("create", "");
            return;
        }

        const openCreateClientModalButton = event.target.closest("#dlnaOpenCreateClientModal");
        if (openCreateClientModalButton) {
            event.preventDefault();
            openClientModal("create", "");
            return;
        }

        const closeCollectionModalButton = event.target.closest('[data-modal-close="collection"]');
        if (closeCollectionModalButton) {
            event.preventDefault();
            closeCollectionModal();
            return;
        }

        const closeClientModalButton = event.target.closest('[data-modal-close="client"]');
        if (closeClientModalButton) {
            event.preventDefault();
            closeClientModal();
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

        const openEditCollectionButton = event.target.closest(".js-dlna-open-edit-collection");
        if (openEditCollectionButton) {
            event.preventDefault();
            const collectionId = String(openEditCollectionButton.dataset.collectionId || "");
            if (!collectionId) {
                return;
            }
            openCollectionModal("edit", collectionId);
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
            clearCollectionDraft(collectionId);
            if (String(collectionModalState.collectionId || "") === collectionId) {
                closeCollectionModal();
            }
            if (String(activeCollectionId || "") === collectionId) {
                activeCollectionId = "";
            }
            return;
        }

        const openEditClientButton = event.target.closest(".js-dlna-open-edit-client");
        if (openEditClientButton) {
            event.preventDefault();
            const clientId = String(openEditClientButton.dataset.clientId || "");
            if (!clientId) {
                return;
            }
            openClientModal("edit", clientId);
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
            clearClientDraft(clientId);
            if (String(clientModalState.clientId || "") === clientId) {
                closeClientModal();
            }
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

        if (form.id === "dlnaCollectionModalForm") {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            const isEdit = String(collectionModalState.mode || "create") === "edit";
            const ok = await performAction(button, isEdit ? "Zapisywanie..." : "Dodawanie...", function () {
                return postJson("/api/dlna/collections", isEdit ? {
                    action: "update",
                    collection_id: String(collectionModalState.collectionId || ""),
                    name: String(form.name.value || ""),
                    description: String(form.description.value || ""),
                } : {
                    action: "create",
                    name: String(form.name.value || ""),
                    description: String(form.description.value || ""),
                });
            });
            if (ok) {
                form.reset();
                if (isEdit) {
                    clearCollectionDraft(collectionModalState.collectionId);
                } else {
                    clearNewCollectionDraft();
                }
                closeCollectionModal();
                renderCollections();
            }
            return;
        }

        if (form.id === "dlnaClientModalForm") {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            const isEdit = String(clientModalState.mode || "create") === "edit";
            const scopeSuffix = isEdit ? String(clientModalState.clientId || "") : "";
            const ok = await performAction(button, isEdit ? "Zapisywanie..." : "Dodawanie...", function () {
                return postJson("/api/dlna/clients", isEdit ? {
                    action: "update",
                    client_id: String(clientModalState.clientId || ""),
                    ip: String(form.ip.value || ""),
                    description: String(form.description.value || ""),
                    enabled: !!form.enabled.checked,
                    collection_ids: readCheckboxScope("client-modal-" + scopeSuffix),
                    usernames: readCheckboxScope("client-modal-" + scopeSuffix + "-users"),
                } : {
                    action: "create",
                    ip: String(form.ip.value || ""),
                    description: String(form.description.value || ""),
                    enabled: !!form.enabled.checked,
                    collection_ids: readCheckboxScope("new-client-modal"),
                    usernames: readCheckboxScope("new-client-modal-users"),
                });
            });
            if (ok) {
                form.reset();
                const enabledInput = form.querySelector("#dlnaClientModalEnabled");
                if (enabledInput) {
                    enabledInput.checked = true;
                }
                if (isEdit) {
                    clearClientDraft(clientModalState.clientId);
                } else {
                    clearNewClientDraft();
                }
                closeClientModal();
                renderClients({force: true});
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
        const clientModalForm = target.closest("#dlnaClientModalForm");
        if (clientModalForm instanceof HTMLFormElement) {
            if (String(clientModalState.mode || "create") === "edit") {
                syncClientDraft(clientModalForm, "client-modal-" + String(clientModalState.clientId || ""), String(clientModalState.clientId || ""));
            } else {
                syncNewClientDraft(clientModalForm);
            }
        }
        const collectionModalForm = target.closest("#dlnaCollectionModalForm");
        if (collectionModalForm instanceof HTMLFormElement) {
            syncCollectionModalDraft(collectionModalForm);
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

    function handleRootInput(event) {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }
        const clientModalForm = target.closest("#dlnaClientModalForm");
        if (clientModalForm instanceof HTMLFormElement) {
            if (String(clientModalState.mode || "create") === "edit") {
                syncClientDraft(clientModalForm, "client-modal-" + String(clientModalState.clientId || ""), String(clientModalState.clientId || ""));
            } else {
                syncNewClientDraft(clientModalForm);
            }
            return;
        }
        const collectionModalForm = target.closest("#dlnaCollectionModalForm");
        if (collectionModalForm instanceof HTMLFormElement) {
            syncCollectionModalDraft(collectionModalForm);
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
    root.addEventListener("input", handleRootInput, true);
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
            root.removeEventListener("input", handleRootInput, true);
            root.removeEventListener("change", handleRootChange, true);
            root.removeEventListener("submit", handleRootSubmit, true);
            if (liveSubscription && typeof liveSubscription.stop === "function") {
                liveSubscription.stop();
            }
        });
    }
})();
