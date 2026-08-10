(function() {
    "use strict";

    const root = document.getElementById("iptvPageRoot");
    if (!root || root.dataset.accessDenied === "true") return;

    const pageData = window.pageBootstrapData || {};
    let currentState = pageData.initialState || {};
    let pendingState = null;
    let liveSubscription = null;
    let activeTab = localStorage.getItem("flaskDownloaderIptvTab") || "status";
    let testedProfile = null;

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function showToast(message, kind) {
        if (window.appUi && typeof window.appUi.showToast === "function") {
            window.appUi.showToast(String(message || ""), kind || "success");
        }
    }

    function setBusy(button, busy, label) {
        if (!button) return;
        if (!button.dataset.idleLabel) button.dataset.idleLabel = button.textContent.trim();
        button.disabled = !!busy;
        button.textContent = busy ? (label || "Trwa...") : button.dataset.idleLabel;
    }

    async function postJson(url, payload) {
        const response = await fetch(url, {
            method: "POST",
            headers: {"Accept": "application/json", "Content-Type": "application/json"},
            body: JSON.stringify(payload || {}),
        });
        const data = await response.json().catch(function() { return {}; });
        if (!response.ok || data.ok === false) {
            throw new Error(data.message || "Operacja IPTV zakończyła się błędem.");
        }
        return data;
    }

    function profiles() {
        return Array.isArray(currentState.profiles) ? currentState.profiles : [];
    }

    function users() {
        return Array.isArray(currentState.users) ? currentState.users : [];
    }

    function profileById(profileId) {
        return profiles().find(function(item) { return String(item.id) === String(profileId); }) || null;
    }

    function gatewayBaseUrl() {
        const settings = currentState.settings || {};
        const configured = String(settings.public_base_url || "").replace(/\/$/, "");
        if (configured) return configured;
        return "http://" + window.location.hostname + ":" + String(settings.port || 9988);
    }

    function isDraftLocked() {
        const modalOpen = Array.from(root.querySelectorAll(".app-modal")).some(function(modal) {
            return !modal.hidden;
        });
        const settingsForm = document.getElementById("iptvSettingsForm");
        return modalOpen || !!(settingsForm && settingsForm.dataset.dirty === "true");
    }

    function applyState(nextState, options) {
        if (!nextState || typeof nextState !== "object") return;
        if (options && options.fromLive && isDraftLocked()) {
            pendingState = nextState;
            return;
        }
        currentState = nextState;
        pendingState = null;
        renderAll();
    }

    function applyPendingState() {
        if (!isDraftLocked() && pendingState) applyState(pendingState);
    }

    function statusPill(kind, label) {
        const normalized = ["success", "error", "queued", "muted"].includes(kind) ? kind : "muted";
        return '<span class="service-status-pill ' + normalized + '">' + escapeHtml(label) + "</span>";
    }

    function renderTabs() {
        const valid = ["status", "sources", "users", "catalog", "vod"];
        if (!valid.includes(activeTab)) activeTab = "status";
        localStorage.setItem("flaskDownloaderIptvTab", activeTab);
        root.querySelectorAll(".iptv-tab-button").forEach(function(button) {
            const selected = button.dataset.iptvTab === activeTab;
            button.classList.toggle("is-active", selected);
            button.setAttribute("aria-pressed", selected ? "true" : "false");
        });
        root.querySelectorAll(".iptv-panel").forEach(function(panel) {
            panel.hidden = panel.dataset.iptvPanel !== activeTab;
        });
    }

    function renderHeader() {
        const service = currentState.service || {};
        const gateway = currentState.gateway || {};
        const online = !!(service.active && gateway.online);
        const top = document.getElementById("iptvTopStatus");
        const text = document.getElementById("iptvTopStatusText");
        if (top) {
            top.classList.toggle("is-online", online);
            top.classList.toggle("is-offline", !online);
        }
        if (text) text.textContent = online ? "Bramka IPTV online" : "Bramka IPTV offline";

        const summary = document.getElementById("iptvSummaryGrid");
        if (summary) {
            const readyProfiles = profiles().filter(function(item) {
                return (item.runtime || {}).status === "ready";
            }).length;
            summary.innerHTML = [
                ["Bramka", online ? "online" : "offline"],
                ["Źródła", readyProfiles + " / " + profiles().length + " gotowe"],
                ["Konta IPTV", String(users().length)],
                ["Aktywne połączenia", String(gateway.active_connections || 0)],
            ].map(function(item) {
                return '<div class="overview-tile"><span>' + escapeHtml(item[0]) + "</span><strong>" + escapeHtml(item[1]) + "</strong></div>";
            }).join("");
        }
    }

    function renderStatus() {
        const service = currentState.service || {};
        const gateway = currentState.gateway || {};
        const pill = document.getElementById("iptvServicePill");
        if (pill) {
            pill.className = "service-status-pill " + (service.active && gateway.online ? "success" : "error");
            pill.textContent = service.active && gateway.online ? "Aktywna" : (service.status_label || "Nieaktywna");
        }
        const meta = document.getElementById("iptvServiceMeta");
        if (meta) meta.textContent = (service.service_name || pageData.serviceName || "flask-downloader-iptv") + ".service";
        const metrics = document.getElementById("iptvGatewayMetrics");
        if (metrics) {
            metrics.innerHTML = [
                ["Adres Xtream", gatewayBaseUrl()],
                ["PID", service.main_pid || "brak"],
                ["Autostart", service.enabled ? "włączony" : "wyłączony"],
                ["Połączenia", String(gateway.active_connections || 0)],
            ].map(function(item) {
                return '<div class="overview-tile"><span>' + escapeHtml(item[0]) + "</span><strong>" + escapeHtml(item[1]) + "</strong></div>";
            }).join("");
        }
        const errorBox = document.getElementById("iptvServiceError");
        if (errorBox) {
            const error = String(service.error || gateway.error || "").trim();
            errorBox.hidden = !error;
            errorBox.textContent = error;
        }
    }

    function fillSettingsForm(force) {
        const form = document.getElementById("iptvSettingsForm");
        if (!form || (!force && form.dataset.dirty === "true")) return;
        const settings = currentState.settings || {};
        form.elements.bind_host.value = settings.bind_host || "0.0.0.0";
        form.elements.port.value = settings.port || 9988;
        form.elements.public_base_url.value = settings.public_base_url || "";
        form.elements.refresh_hour.value = settings.refresh_hour == null ? 2 : settings.refresh_hour;
        form.elements.refresh_minute.value = settings.refresh_minute == null ? 0 : settings.refresh_minute;
        form.elements.epg_days.value = settings.epg_days || 7;
        form.elements.enabled.checked = settings.enabled !== false;
        form.dataset.dirty = "false";
    }

    function formatProfileMeta(profile) {
        const bouquets = (profile.selected_bouquets || []).map(function(item) { return item.name || item.reference; });
        return profile.host + ":" + profile.web_port + " • " + (bouquets.length ? bouquets.join(", ") : "brak bukietów");
    }

    function renderProfiles() {
        const list = document.getElementById("iptvProfileList");
        if (!list) return;
        if (!profiles().length) {
            list.innerHTML = '<div class="iptv-empty">Nie dodano jeszcze żadnego dekodera.</div>';
            return;
        }
        list.innerHTML = profiles().map(function(profile) {
            const runtime = profile.runtime || {};
            const kind = runtime.status === "ready" ? "success" : (runtime.status === "refreshing" ? "queued" : (runtime.status === "error" ? "error" : "muted"));
            return '<div class="dlna-compact-row">' +
                '<div class="dlna-compact-main"><div class="dlna-compact-head"><span class="dlna-compact-title">' + escapeHtml(profile.name) + "</span>" + statusPill(kind, runtime.status_label || "Nieodświeżany") + "</div>" +
                '<div class="dlna-compact-meta">' + escapeHtml(formatProfileMeta(profile)) + "</div>" +
                '<div class="dlna-compact-tags"><span class="dlna-token">' + escapeHtml(String(runtime.channel_count || 0)) + ' kanałów</span><span class="dlna-token">' + escapeHtml(String(runtime.epg_event_count || 0)) + ' EPG</span><span class="dlna-token">' + escapeHtml(String(runtime.vod_count || 0)) + " VOD</span></div></div>" +
                '<div class="dlna-compact-actions"><button class="btn btn-secondary" type="button" data-profile-action="refresh" data-profile-id="' + escapeHtml(profile.id) + '">Odśwież</button><button class="btn btn-secondary" type="button" data-profile-action="edit" data-profile-id="' + escapeHtml(profile.id) + '">Edytuj</button><button class="btn btn-delete" type="button" data-profile-action="delete" data-profile-id="' + escapeHtml(profile.id) + '">Usuń</button></div></div>';
        }).join("");
    }

    function renderUsers() {
        const list = document.getElementById("iptvUserList");
        if (!list) return;
        if (!users().length) {
            list.innerHTML = '<div class="iptv-empty">Nie utworzono jeszcze kont IPTV.</div>';
            return;
        }
        list.innerHTML = users().map(function(user) {
            const profile = profileById(user.profile_id);
            const kind = !user.enabled || user.expired ? "error" : "success";
            const label = user.expired ? "Wygasło" : (user.enabled ? "Aktywne" : "Wyłączone");
            return '<div class="dlna-compact-row"><div class="dlna-compact-main"><div class="dlna-compact-head"><span class="dlna-compact-title">' + escapeHtml(user.username) + "</span>" + statusPill(kind, label) + "</div>" +
                '<div class="dlna-compact-meta">Źródło: ' + escapeHtml(profile ? profile.name : user.profile_id) + " • ważne: " + escapeHtml(user.expires_at_text || "bezterminowo") + " • maks. połączeń: " + escapeHtml(user.max_connections || 1) + "</div>" +
                '<div class="dlna-compact-tags"><span class="dlna-token">Xtream</span><span class="dlna-token">M3U + XMLTV</span>' + (user.vod_enabled ? '<span class="dlna-token">VOD</span>' : "") + "</div></div>" +
                '<div class="dlna-compact-actions"><button class="btn btn-secondary" type="button" data-user-action="access" data-user-id="' + escapeHtml(user.id) + '">Dane dostępu</button><button class="btn btn-secondary" type="button" data-user-action="edit" data-user-id="' + escapeHtml(user.id) + '">Edytuj</button><button class="btn btn-delete" type="button" data-user-action="delete" data-user-id="' + escapeHtml(user.id) + '">Usuń</button></div></div>';
        }).join("");
    }

    function renderCatalog() {
        const list = document.getElementById("iptvCatalogList");
        if (!list) return;
        if (!profiles().length) {
            list.innerHTML = '<div class="iptv-empty">Dodaj źródło, aby zbudować katalog kanałów.</div>';
            return;
        }
        list.innerHTML = profiles().map(function(profile) {
            const runtime = profile.runtime || {};
            const refreshing = runtime.status === "refreshing";
            const percent = Math.max(0, Math.min(100, Number(runtime.progress_percent || 0)));
            return '<div class="stack-card iptv-catalog-card"><div class="iptv-panel-toolbar"><div><div class="card-title">' + escapeHtml(profile.name) + '</div><div class="card-subtitle">Ostatni poprawny katalog: ' + escapeHtml(profile.last_success_text || "nigdy") + "</div></div>" +
                statusPill(runtime.status === "ready" ? "success" : (refreshing ? "queued" : "error"), runtime.status_label || "Brak danych") + "</div>" +
                '<div class="settings-overview-grid"><div class="overview-tile"><span>Kanały</span><strong>' + escapeHtml(runtime.channel_count || 0) + '</strong></div><div class="overview-tile"><span>Kategorie</span><strong>' + escapeHtml(runtime.category_count || 0) + '</strong></div><div class="overview-tile"><span>Wpisy EPG</span><strong>' + escapeHtml(runtime.epg_event_count || 0) + '</strong></div><div class="overview-tile"><span>VOD</span><strong>' + escapeHtml(runtime.vod_count || 0) + "</strong></div></div>" +
                '<div class="progress ' + (refreshing && !percent ? "is-indeterminate" : "") + '"><div class="progress-bar ' + (refreshing ? "queued" : "completed") + '" style="width:' + (refreshing && !percent ? 38 : percent) + '%"></div></div>' +
                '<div class="maintenance-task-detail">' + escapeHtml(runtime.detail || runtime.last_error || "Katalog nie był jeszcze budowany.") + "</div></div>";
        }).join("");
    }

    function renderVod() {
        const list = document.getElementById("iptvVodList");
        if (!list) return;
        const sources = Array.isArray(currentState.vod_sources) ? currentState.vod_sources : [];
        if (!sources.length) {
            list.innerHTML = '<div class="iptv-empty">Nie znaleziono katalogów wideo w aktywnych storage. VOD można włączyć później po pojawieniu się plików.</div>';
            return;
        }
        list.innerHTML = sources.map(function(source) {
            const assigned = profiles().filter(function(profile) {
                return profile.vod_enabled && (profile.vod_source_ids || []).includes(source.id);
            }).map(function(profile) { return profile.name; });
            return '<div class="dlna-compact-row"><div class="dlna-compact-main"><div class="dlna-compact-title">' + escapeHtml(source.label) + '</div><div class="dlna-compact-meta">' + (assigned.length ? "Udostępniane przez: " + escapeHtml(assigned.join(", ")) : "Nieprzypisane do żadnego źródła") + "</div></div>" +
                '<div class="dlna-compact-tags"><span class="dlna-token">' + escapeHtml(source.storage_id) + '</span><span class="dlna-token">' + escapeHtml(source.kind) + "</span></div></div>";
        }).join("");
    }

    function renderAll() {
        renderTabs();
        renderHeader();
        renderStatus();
        fillSettingsForm(false);
        renderProfiles();
        renderUsers();
        renderCatalog();
        renderVod();
    }

    function showModal(name) {
        const modal = document.getElementById(name === "profile" ? "iptvProfileModal" : "iptvUserModal");
        if (modal) modal.hidden = false;
    }

    function closeModal(name) {
        const modal = document.getElementById(name === "profile" ? "iptvProfileModal" : "iptvUserModal");
        if (modal) modal.hidden = true;
        if (name === "profile") testedProfile = null;
        applyPendingState();
    }

    function profilePayload() {
        return {
            id: document.getElementById("iptvProfileId").value.trim(),
            name: document.getElementById("iptvProfileName").value.trim(),
            host: document.getElementById("iptvProfileHost").value.trim(),
            username: document.getElementById("iptvProfileUsername").value.trim(),
            web_port: document.getElementById("iptvProfileWebPort").value,
            stream_port: document.getElementById("iptvProfileStreamPort").value,
            password: document.getElementById("iptvProfilePassword").value,
            max_streams: document.getElementById("iptvProfileMaxStreams").value,
            enabled: document.getElementById("iptvProfileEnabled").checked,
            dvb_only: document.getElementById("iptvProfileDvbOnly").checked,
            vod_enabled: document.getElementById("iptvProfileVodEnabled").checked,
            existing_profile_id: document.getElementById("iptvProfileExistingId").value,
        };
    }

    function invalidateProfileTest() {
        testedProfile = null;
        document.getElementById("iptvBouquetSection").hidden = true;
        document.getElementById("iptvSaveProfileButton").disabled = true;
        document.getElementById("iptvProfileTestResult").textContent = "Po zmianie danych połączenia sprawdź źródło ponownie.";
    }

    function renderVodSourceChoices(selectedIds) {
        const section = document.getElementById("iptvVodSourceSection");
        const list = document.getElementById("iptvVodSourceChoices");
        const enabled = document.getElementById("iptvProfileVodEnabled").checked;
        const sources = Array.isArray(currentState.vod_sources) ? currentState.vod_sources : [];
        section.hidden = !enabled;
        list.innerHTML = sources.length ? sources.map(function(source) {
            return '<label class="iptv-choice"><input type="checkbox" data-vod-source-id="' + escapeHtml(source.id) + '" ' + (selectedIds.includes(source.id) ? "checked" : "") + '><span><strong>' + escapeHtml(source.label) + '</strong><small>' + escapeHtml(source.storage_id + " • " + source.kind) + "</small></span></label>";
        }).join("") : '<div class="small">Brak dostępnych katalogów VOD.</div>';
    }

    function openProfileModal(profile) {
        const existing = profile || null;
        document.getElementById("iptvProfileModalTitle").textContent = existing ? "Edytuj źródło " + existing.name : "Nowe źródło IPTV";
        document.getElementById("iptvProfileExistingId").value = existing ? existing.id : "";
        const idInput = document.getElementById("iptvProfileId");
        idInput.value = existing ? existing.id : "";
        idInput.disabled = !!existing;
        document.getElementById("iptvProfileName").value = existing ? existing.name : "";
        document.getElementById("iptvProfileHost").value = existing ? existing.host : "";
        document.getElementById("iptvProfileUsername").value = existing ? existing.username : "root";
        document.getElementById("iptvProfileWebPort").value = existing ? existing.web_port : 1234;
        document.getElementById("iptvProfileStreamPort").value = existing ? existing.stream_port : 8001;
        document.getElementById("iptvProfilePassword").value = "";
        document.getElementById("iptvProfilePassword").placeholder = existing && existing.password_saved ? "zostaw puste, aby zachować zapisane" : "wymagane przy pierwszym zapisie";
        document.getElementById("iptvProfileMaxStreams").value = existing ? existing.max_streams : 2;
        document.getElementById("iptvProfileEnabled").checked = existing ? existing.enabled : true;
        document.getElementById("iptvProfileDvbOnly").checked = existing ? existing.dvb_only : true;
        document.getElementById("iptvProfileVodEnabled").checked = existing ? existing.vod_enabled : false;
        document.getElementById("iptvProfileTestResult").textContent = "Kliknij „Sprawdź źródło”, aby pobrać aktualne bukiety.";
        document.getElementById("iptvBouquetSection").hidden = true;
        document.getElementById("iptvSaveProfileButton").disabled = true;
        document.getElementById("iptvBouquetList").innerHTML = "";
        renderVodSourceChoices(existing ? (existing.vod_source_ids || []) : []);
        testedProfile = null;
        showModal("profile");
    }

    function selectedBouquets() {
        return Array.from(document.querySelectorAll("#iptvBouquetList input[data-bouquet-reference]:checked")).map(function(input) {
            return {reference: input.dataset.bouquetReference, name: input.dataset.bouquetName};
        });
    }

    function updateProfileSaveState() {
        document.getElementById("iptvSaveProfileButton").disabled = !(testedProfile && selectedBouquets().length);
    }

    async function testProfile(button) {
        const payload = profilePayload();
        setBusy(button, true, "Sprawdzanie...");
        try {
            const data = await postJson("/api/iptv/profile-test", payload);
            testedProfile = data.test_result || null;
            const existing = profileById(payload.existing_profile_id || payload.id);
            const selected = new Set((existing && existing.selected_bouquets || []).map(function(item) { return item.reference; }));
            const bouquets = (testedProfile && testedProfile.bouquets) || [];
            document.getElementById("iptvBouquetList").innerHTML = bouquets.map(function(item) {
                const count = payload.dvb_only ? item.channel_count : item.total_count;
                return '<label class="iptv-choice"><input type="checkbox" data-bouquet-reference="' + escapeHtml(item.reference) + '" data-bouquet-name="' + escapeHtml(item.name) + '" ' + (selected.has(item.reference) ? "checked" : "") + '><span><strong>' + escapeHtml(item.name) + '</strong><small>' + escapeHtml(String(count || 0)) + " kanałów" + (item.network_count ? " • " + escapeHtml(String(item.network_count)) + " sieciowych" : "") + "</small></span></label>";
            }).join("");
            document.getElementById("iptvBouquetSection").hidden = false;
            document.getElementById("iptvProfileTestResult").textContent = "Połączono z " + String((testedProfile.about || {}).model || payload.host) + ". Znaleziono " + bouquets.length + " bukietów.";
            updateProfileSaveState();
            showToast(data.message, "success");
        } catch (error) {
            invalidateProfileTest();
            document.getElementById("iptvProfileTestResult").textContent = error.message;
            showToast(error.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    function expirationDateValue(timestamp) {
        if (!timestamp) return "";
        const date = new Date(Number(timestamp) * 1000);
        const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
        return local.toISOString().slice(0, 10);
    }

    function userById(id) {
        return users().find(function(item) { return String(item.id) === String(id); }) || null;
    }

    function fillProfileSelect(selectedId) {
        const select = document.getElementById("iptvUserProfile");
        select.innerHTML = profiles().map(function(profile) {
            return '<option value="' + escapeHtml(profile.id) + '" ' + (profile.id === selectedId ? "selected" : "") + ">" + escapeHtml(profile.name) + "</option>";
        }).join("");
    }

    function openUserModal(user, accessOnly) {
        const existing = user || null;
        document.getElementById("iptvUserModalTitle").textContent = accessOnly ? "Dane dostępu " + existing.username : (existing ? "Edytuj konto " + existing.username : "Nowe konto IPTV");
        document.getElementById("iptvUserId").value = existing ? existing.id : "";
        fillProfileSelect(existing ? existing.profile_id : (profiles()[0] || {}).id);
        document.getElementById("iptvUsername").value = existing ? existing.username : "";
        document.getElementById("iptvUserPassword").value = "";
        document.getElementById("iptvUserPassword").placeholder = existing ? "zostaw puste, aby zachować" : "wymagane";
        document.getElementById("iptvUserExpires").value = existing ? expirationDateValue(existing.expires_at) : "";
        document.getElementById("iptvUserMaxConnections").value = existing ? existing.max_connections : 1;
        document.getElementById("iptvUserEnabled").checked = existing ? existing.enabled : true;
        document.getElementById("iptvUserVodEnabled").checked = existing ? existing.vod_enabled : true;
        document.getElementById("iptvSaveUserButton").textContent = existing ? "Zapisz konto" : "Utwórz konto";
        document.getElementById("iptvSaveUserButton").dataset.idleLabel = document.getElementById("iptvSaveUserButton").textContent;
        renderAccessBox(existing, "");
        if (accessOnly) document.getElementById("iptvCreatedAccess").scrollIntoView({block: "nearest"});
        showModal("user");
    }

    function renderAccessBox(user, password) {
        const box = document.getElementById("iptvCreatedAccess");
        if (!user) {
            box.hidden = true;
            box.innerHTML = "";
            return;
        }
        const base = gatewayBaseUrl();
        const shownPassword = password || "{TWOJE_HASŁO}";
        const m3u = base + "/get.php?username=" + encodeURIComponent(user.username) + "&password=" + encodeURIComponent(shownPassword) + "&type=m3u_plus&output=ts";
        const epg = base + "/xmltv.php?username=" + encodeURIComponent(user.username) + "&password=" + encodeURIComponent(shownPassword);
        box.hidden = false;
        box.innerHTML = '<strong>Ultimate IPTV / IBO</strong><span>Adres serwera: <code>' + escapeHtml(base) + '</code></span><span>Login: <code>' + escapeHtml(user.username) + '</code></span><span>Hasło: <code>' + escapeHtml(shownPassword) + '</code></span><div class="iptv-access-actions"><button type="button" class="btn btn-secondary" data-copy-value="base">Kopiuj Xtream</button><button type="button" class="btn btn-secondary" data-copy-value="m3u">Kopiuj M3U</button><button type="button" class="btn btn-secondary" data-copy-value="epg">Kopiuj EPG</button></div>';
        box.querySelector('[data-copy-value="base"]').dataset.copyText = ["Serwer: " + base, "Login: " + user.username, "Hasło: " + shownPassword].join("\n");
        box.querySelector('[data-copy-value="m3u"]').dataset.copyText = m3u;
        box.querySelector('[data-copy-value="epg"]').dataset.copyText = epg;
    }

    function userPayload() {
        const expires = document.getElementById("iptvUserExpires").value;
        let expiresAt = 0;
        if (expires) expiresAt = Math.floor(new Date(expires + "T23:59:59").getTime() / 1000);
        return {
            user_id: document.getElementById("iptvUserId").value,
            profile_id: document.getElementById("iptvUserProfile").value,
            username: document.getElementById("iptvUsername").value.trim(),
            password: document.getElementById("iptvUserPassword").value,
            expires_at: expiresAt,
            max_connections: document.getElementById("iptvUserMaxConnections").value,
            enabled: document.getElementById("iptvUserEnabled").checked,
            vod_enabled: document.getElementById("iptvUserVodEnabled").checked,
        };
    }

    async function perform(button, busyLabel, action) {
        setBusy(button, true, busyLabel);
        try {
            const data = await action();
            if (data.iptv_state) applyState(data.iptv_state);
            if (data.message) showToast(data.message, data.kind || "success");
            return data;
        } catch (error) {
            showToast(error.message, "error");
            return null;
        } finally {
            setBusy(button, false);
        }
    }

    root.addEventListener("click", function(event) {
        const tab = event.target.closest(".iptv-tab-button");
        if (tab) {
            activeTab = tab.dataset.iptvTab || "status";
            renderTabs();
            return;
        }
        const close = event.target.closest("[data-iptv-modal-close]");
        if (close) {
            closeModal(close.dataset.iptvModalClose);
            return;
        }
        if (event.target.closest("#iptvAddProfileButton")) {
            openProfileModal(null);
            return;
        }
        if (event.target.closest("#iptvAddUserButton")) {
            if (!profiles().length) return showToast("Najpierw dodaj źródło IPTV.", "error");
            openUserModal(null, false);
            return;
        }
        const serviceButton = event.target.closest("[data-iptv-service]");
        if (serviceButton) {
            perform(serviceButton, "Trwa...", function() {
                return postJson("/api/iptv/service", {action: serviceButton.dataset.iptvService});
            });
            return;
        }
        const profileButton = event.target.closest("[data-profile-action]");
        if (profileButton) {
            const profile = profileById(profileButton.dataset.profileId);
            const action = profileButton.dataset.profileAction;
            if (action === "edit") return openProfileModal(profile);
            if (action === "refresh") return perform(profileButton, "Start...", function() { return postJson("/api/iptv/refresh", {profile_id: profile.id}); });
            if (action === "delete" && confirm("Usunąć źródło „" + profile.name + "”?")) {
                perform(profileButton, "Usuwanie...", function() { return postJson("/api/iptv/profiles", {action: "delete", profile_id: profile.id}); });
            }
            return;
        }
        const userButton = event.target.closest("[data-user-action]");
        if (userButton) {
            const user = userById(userButton.dataset.userId);
            const action = userButton.dataset.userAction;
            if (action === "edit" || action === "access") return openUserModal(user, action === "access");
            if (action === "delete" && confirm("Usunąć konto IPTV „" + user.username + "”?")) {
                perform(userButton, "Usuwanie...", function() { return postJson("/api/iptv/users", {action: "delete", user_id: user.id}); });
            }
            return;
        }
        const testButton = event.target.closest("#iptvTestProfileButton");
        if (testButton) {
            testProfile(testButton);
            return;
        }
        const refreshButton = event.target.closest("#iptvRefreshAllButton, #iptvRefreshCatalogButton");
        if (refreshButton) {
            perform(refreshButton, "Start...", function() { return postJson("/api/iptv/refresh", {}); });
            return;
        }
        if (event.target.closest("#iptvGeneratePassword")) {
            const values = new Uint32Array(4);
            window.crypto.getRandomValues(values);
            document.getElementById("iptvUserPassword").value = Array.from(values).map(function(value) { return value.toString(36); }).join("-").slice(0, 24);
            return;
        }
        const copyButton = event.target.closest("[data-copy-text]");
        if (copyButton) {
            navigator.clipboard.writeText(copyButton.dataset.copyText || "").then(function() {
                showToast("Skopiowano dane dostępu.", "success");
            }).catch(function() { showToast("Nie udało się skopiować danych.", "error"); });
        }
    });

    document.getElementById("iptvSettingsForm").addEventListener("input", function() {
        this.dataset.dirty = "true";
    });

    document.getElementById("iptvSettingsForm").addEventListener("submit", function(event) {
        event.preventDefault();
        const form = this;
        const button = form.querySelector('button[type="submit"]');
        const payload = {
            enabled: form.elements.enabled.checked,
            bind_host: form.elements.bind_host.value,
            port: form.elements.port.value,
            public_base_url: form.elements.public_base_url.value,
            refresh_hour: form.elements.refresh_hour.value,
            refresh_minute: form.elements.refresh_minute.value,
            epg_days: form.elements.epg_days.value,
        };
        perform(button, "Zapisywanie...", function() { return postJson("/api/iptv/settings", payload); }).then(function(data) {
            if (data) {
                form.dataset.dirty = "false";
                fillSettingsForm(true);
                applyPendingState();
            }
        });
    });

    document.getElementById("iptvProfileForm").addEventListener("input", function(event) {
        const connectionIds = ["iptvProfileId", "iptvProfileHost", "iptvProfileUsername", "iptvProfileWebPort", "iptvProfileStreamPort", "iptvProfilePassword"];
        if (connectionIds.includes(event.target.id) && testedProfile) invalidateProfileTest();
        if (event.target.id === "iptvProfileVodEnabled") {
            const existing = profileById(document.getElementById("iptvProfileExistingId").value);
            renderVodSourceChoices(existing ? (existing.vod_source_ids || []) : []);
        }
        if (event.target.matches("[data-bouquet-reference]")) updateProfileSaveState();
    });

    document.getElementById("iptvProfileForm").addEventListener("submit", function(event) {
        event.preventDefault();
        if (!testedProfile) return showToast("Najpierw sprawdź źródło.", "error");
        const payload = profilePayload();
        payload.action = "save";
        payload.selected_bouquets = selectedBouquets();
        payload.vod_source_ids = Array.from(document.querySelectorAll("#iptvVodSourceChoices input[data-vod-source-id]:checked")).map(function(input) { return input.dataset.vodSourceId; });
        const button = document.getElementById("iptvSaveProfileButton");
        perform(button, "Zapisywanie...", function() { return postJson("/api/iptv/profiles", payload); }).then(function(data) {
            if (data) closeModal("profile");
        });
    });

    document.getElementById("iptvUserForm").addEventListener("submit", function(event) {
        event.preventDefault();
        const payload = userPayload();
        const creating = !payload.user_id;
        if (creating && !payload.password) return showToast("Podaj albo wygeneruj hasło IPTV.", "error");
        payload.action = creating ? "create" : "update";
        const button = document.getElementById("iptvSaveUserButton");
        perform(button, creating ? "Tworzenie..." : "Zapisywanie...", function() { return postJson("/api/iptv/users", payload); }).then(function(data) {
            if (!data) return;
            const saved = (data.iptv_state.users || []).find(function(item) { return item.username === payload.username; });
            if (creating && saved) {
                document.getElementById("iptvUserId").value = saved.id;
                document.getElementById("iptvUserModalTitle").textContent = "Konto utworzone";
                renderAccessBox(saved, payload.password);
                button.textContent = "Zapisz zmiany";
                button.dataset.idleLabel = "Zapisz zmiany";
            } else {
                closeModal("user");
            }
        });
    });

    document.addEventListener("keydown", function(event) {
        if (event.key !== "Escape") return;
        if (!document.getElementById("iptvProfileModal").hidden) closeModal("profile");
        else if (!document.getElementById("iptvUserModal").hidden) closeModal("user");
    });

    async function fetchState() {
        const response = await fetch("/api/iptv/state", {headers: {"Accept": "application/json"}});
        if (!response.ok) throw new Error("Nie udało się odświeżyć stanu IPTV.");
        const data = await response.json();
        if (data.iptv_state) applyState(data.iptv_state, {fromLive: true});
        return data;
    }

    fillSettingsForm(true);
    renderAll();
    if (window.appLive && typeof window.appLive.createSubscription === "function") {
        liveSubscription = window.appLive.createSubscription({
            url: "/api/iptv/stream",
            fallbackIntervalMs: 3000,
            fetchFallback: fetchState,
            onData: function(data) {
                if (data && data.iptv_state) applyState(data.iptv_state, {fromLive: true});
            },
        });
        liveSubscription.start();
    }

    window.registerPageCleanup(function() {
        if (liveSubscription && typeof liveSubscription.stop === "function") liveSubscription.stop();
        liveSubscription = null;
    });
})();
