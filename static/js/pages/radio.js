(function() {
    const pageData = window.pageBootstrapData || {};
    const root = document.getElementById("radioPageRoot");
    if (!root) {
        return;
    }

    const ACTIVE_TAB_STORAGE_KEY = "flask-downloader-radio-active-tab";
    const ALLOWED_UPLOAD_EXTENSIONS = new Set([
        ".aac",
        ".flac",
        ".m4a",
        ".mp3",
        ".oga",
        ".ogg",
        ".opus",
        ".wav",
        ".webm",
        ".wma",
    ]);
    const BITRATE_PRESETS = {
        mp3: ["128", "160", "192", "256", "320"],
        aac: ["160", "192", "256", "320"],
    };
    const PROTECTED_FORM_IDS = new Set(["radioGlobalForm", "radioStationForm", "radioErdsForm", "radioLibraryForm"]);

    let currentState = pageData.initialState || {};
    let pollTimer = null;
    let libraryFilter = "";
    let libraryMode = "manual";
    let libraryDraftRows = [];
    let libraryDirty = false;
    let formDirtyState = {
        global: false,
        station: false,
        erds: false,
    };
    let uploadHideTimer = null;
    let activeTab = readStoredActiveTab() || "library";

    function readStoredActiveTab() {
        try {
            return window.localStorage ? String(window.localStorage.getItem(ACTIVE_TAB_STORAGE_KEY) || "").trim() : "";
        } catch (err) {
            return "";
        }
    }

    function storeActiveTab(value) {
        try {
            if (window.localStorage) {
                window.localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, value);
            }
        } catch (err) {
            // Pomijam błąd storage.
        }
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function formatPercent(value) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) {
            return "...";
        }
        return Number(value).toFixed(1) + "%";
    }

    function formatBytes(bytes) {
        const size = Number(bytes || 0);
        if (!Number.isFinite(size) || size <= 0) {
            return "0 B";
        }
        const units = ["B", "KB", "MB", "GB", "TB"];
        let value = size;
        let index = 0;
        while (value >= 1024 && index < units.length - 1) {
            value /= 1024;
            index += 1;
        }
        return (index === 0 ? value.toFixed(0) : value.toFixed(2)) + " " + units[index];
    }

    function formatSpeed(bytesPerSecond) {
        const speed = Number(bytesPerSecond || 0);
        if (!Number.isFinite(speed) || speed <= 0) {
            return "0 B/s";
        }
        return formatBytes(speed) + "/s";
    }

    function setText(id, value) {
        const node = document.getElementById(id);
        if (node) {
            node.textContent = String(value ?? "");
        }
    }

    function setHidden(id, hidden) {
        const node = document.getElementById(id);
        if (node) {
            node.hidden = !!hidden;
        }
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
        if (window.appUi && typeof window.appUi.showToast === "function") {
            window.appUi.showToast(message, kind);
            return;
        }
        if (kind === "error") {
            alert(message);
        }
    }

    function hasProtectedFormActivity() {
        if (formDirtyState.global || formDirtyState.station || formDirtyState.erds || libraryDirty) {
            return true;
        }
        const activeElement = document.activeElement;
        if (!(activeElement instanceof Element)) {
            return false;
        }
        const form = activeElement.closest("form");
        if (!form || !form.id) {
            return false;
        }
        return PROTECTED_FORM_IDS.has(String(form.id || ""));
    }

    function setButtonBusy(button, busy, busyLabel) {
        if (!button) {
            return;
        }
        if (!button.dataset.idleLabel) {
            button.dataset.idleLabel = String(button.textContent || "").trim();
        }
        button.disabled = !!busy;
        button.textContent = busy ? String(busyLabel || "Trwa...") : (button.dataset.idleLabel || button.textContent);
    }

    function syncPasswordToggleButton(button, input) {
        if (!(button instanceof HTMLElement) || !(input instanceof HTMLInputElement)) {
            return;
        }
        const isVisible = String(input.type || "").toLowerCase() === "text";
        const showLabel = String(button.dataset.showLabel || "Pokaż");
        const hideLabel = String(button.dataset.hideLabel || "Ukryj");
        button.textContent = isVisible ? hideLabel : showLabel;
        button.setAttribute("aria-pressed", isVisible ? "true" : "false");
    }

    function togglePasswordVisibility(button) {
        if (!(button instanceof HTMLElement)) {
            return;
        }
        const targetId = String(button.dataset.passwordTarget || "").trim();
        if (!targetId) {
            return;
        }
        const input = document.getElementById(targetId);
        if (!(input instanceof HTMLInputElement)) {
            return;
        }
        input.type = String(input.type || "").toLowerCase() === "password" ? "text" : "password";
        syncPasswordToggleButton(button, input);
    }

    function syncAllPasswordToggleButtons() {
        root.querySelectorAll(".radio-password-toggle").forEach(function(button) {
            if (!(button instanceof HTMLElement)) {
                return;
            }
            const targetId = String(button.dataset.passwordTarget || "").trim();
            const input = targetId ? document.getElementById(targetId) : null;
            if (!(input instanceof HTMLInputElement)) {
                return;
            }
            syncPasswordToggleButton(button, input);
        });
    }

    function currentScopeUsername() {
        return String(currentState.scope_username || "");
    }

    function hasStation() {
        return !!(currentState.station_exists && currentState.station);
    }

    function buildScopeQuery() {
        if (!currentState.can_manage_global || !currentScopeUsername()) {
            return "";
        }
        return "?user=" + encodeURIComponent(currentScopeUsername());
    }

    function readScopeOwner() {
        return currentScopeUsername();
    }

    function slugifyLikeBackend(value, fallback) {
        const normalized = String(value || "")
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "");
        return normalized || String(fallback || "radio");
    }

    function createDefaultStationDraft() {
        const scope = currentScopeUsername() || "user";
        const globalConfig = currentState.global_config || {};
        const defaultFormat = String(globalConfig.default_stream_format || "mp3").toLowerCase() === "aac" ? "aac" : "mp3";
        const slug = slugifyLikeBackend(scope, "radio");
        const sourceUsername = ("source-" + slug).slice(0, 64);
        const livePortBase = 12000 + Array.from(scope).reduce(function(sum, char, index) {
            return (sum + (char.charCodeAt(0) * (index + 1))) % 8000;
        }, 0);
        return {
            enabled: false,
            autostart: false,
            name: "Radio " + scope,
            description: "",
            genre: "",
            slug: slug,
            mount_name: slug + "." + defaultFormat,
            stream: {
                format: defaultFormat,
                bitrate_kbps: defaultFormat === "aac" ? 192 : (Number(globalConfig.default_bitrate_kbps || 192) || 192),
            },
            autopilot: {
                play_mode: "random",
                crossfade_seconds: 2,
                scan_interval_seconds: 30,
                jingle_every_tracks: 0,
                repeat_guard_percent: 100,
            },
            source: {
                username: sourceUsername,
                password: "",
            },
            live: {
                enabled: true,
                port: livePortBase,
                mount_name: "live",
                show_name: "",
                dj_name: "",
            },
            erds: {
                mode: "rotation",
                fixed_text: "",
                suppress_track_titles: false,
                rotation_interval_seconds: 20,
                templates: [
                    "Aktualnie słucha {sluchacze} {sluchacze_odmiana}",
                    "Dzisiaj jest {Dzientygodnia} - {data} - {godzina}",
                    "Słuchasz {nazwa_stacji}",
                ],
            },
        };
    }

    function deriveLiveHost(globalConfig) {
        const rawBaseUrl = String((globalConfig || {}).public_base_url || "").trim();
        if (rawBaseUrl) {
            let host = rawBaseUrl.replace(/^https?:\/\//i, "").split("/", 1)[0].trim();
            if (host.startsWith("[") && host.includes("]")) {
                return host.slice(1).split("]", 1)[0].trim() || "localhost";
            }
            if ((host.match(/:/g) || []).length === 1) {
                return host.split(":")[0].trim() || "localhost";
            }
            if (host) {
                return host;
            }
        }
        const hostname = String((globalConfig || {}).hostname || "").trim();
        if (hostname) {
            return hostname;
        }
        const bindIp = String((globalConfig || {}).bind_ip || "").trim();
        if (!bindIp || bindIp === "0.0.0.0" || bindIp === "::" || bindIp === "::0") {
            return "localhost";
        }
        return bindIp;
    }

    function normalizeLiveMountName(value) {
        const normalized = String(value || "")
            .trim()
            .replace(/^\/+|\/+$/g, "")
            .replace(/[^a-zA-Z0-9_.-]+/g, "-")
            .replace(/^-+|-+$/g, "");
        return normalized || "live";
    }

    function buildStationLivePreview(station) {
        const globalConfig = currentState.global_config || {};
        const live = (station && station.live) || {};
        const host = deriveLiveHost(globalConfig);
        const port = Number(live.port || 0) || 0;
        const mountName = normalizeLiveMountName(live.mount_name || "live");
        const mountPath = "/" + mountName;
        return {
            host: host,
            port: port,
            mount_name: mountName,
            mount_path: mountPath,
            endpoint: port > 0 ? (host + ":" + port + mountPath) : (host + mountPath),
        };
    }

    function normalizeDraftRow(row) {
        return {
            relative_path: String(row.relative_path || ""),
            display_path: String(row.display_path || ""),
            user_relative_path: String(row.user_relative_path || ""),
            name: String(row.name || ""),
            display_title: String(row.display_title || row.default_display_title || row.name || ""),
            default_display_title: String(row.default_display_title || row.name || ""),
            role: String(row.role || "music"),
            included: !!row.included,
            source_type: String(row.source_type || "download"),
            source_type_label: String(row.source_type_label || ""),
            size_text: String(row.size_text || ""),
            mtime_text: String(row.mtime_text || ""),
            url: String(row.url || ""),
        };
    }

    function matchesFilter(values, filterValue) {
        const normalizedFilter = String(filterValue || "").trim().toLowerCase();
        if (!normalizedFilter) {
            return true;
        }
        return values.some(function(value) {
            return String(value || "").toLowerCase().includes(normalizedFilter);
        });
    }

    function getFilteredDraftRows() {
        return libraryDraftRows.filter(function(row) {
            return matchesFilter([
                row.display_title,
                row.display_path,
                row.name,
                row.role,
                row.source_type_label,
            ], libraryFilter);
        });
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

    async function fetchJson(url, options) {
        const response = await fetch(url, Object.assign({
            headers: {
                "Accept": "application/json",
                "X-Requested-With": "fetch",
            },
        }, options || {}));
        const data = await response.json().catch(function() {
            return null;
        });
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
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify(payload || {}),
        });
    }

    function uploadFormData(url, formData, onProgress) {
        return new Promise(function(resolve, reject) {
            const xhr = new XMLHttpRequest();
            xhr.open("POST", url, true);
            xhr.setRequestHeader("Accept", "application/json");
            xhr.setRequestHeader("X-Requested-With", "fetch");
            xhr.upload.addEventListener("progress", function(event) {
                if (typeof onProgress === "function") {
                    onProgress(event);
                }
            });
            xhr.addEventListener("load", function() {
                let data = null;
                try {
                    data = JSON.parse(xhr.responseText || "null");
                } catch (err) {
                    data = null;
                }
                if (xhr.status >= 200 && xhr.status < 300 && data && data.ok !== false) {
                    resolve(data);
                    return;
                }
                reject(new Error((data && (data.error || data.message)) || "Upload zakończył się błędem."));
            });
            xhr.addEventListener("error", function() {
                reject(new Error("Nie udało się wgrać plików audio."));
            });
            xhr.addEventListener("abort", function() {
                reject(new Error("Upload został przerwany."));
            });
            xhr.send(formData);
        });
    }

    function applyState(state, options) {
        if (!state) {
            return;
        }
        const previousScope = currentScopeUsername();
        currentState = state;
        const forceLibraryReset = !!((options || {}).forceLibraryReset);
        const preserveLibraryDraft = !!((options || {}).preserveLibraryDraft);
        const resetDirtyForms = Array.isArray((options || {}).resetDirtyForms) ? (options || {}).resetDirtyForms : [];
        const scopeChanged = previousScope !== currentScopeUsername();

        if (forceLibraryReset || scopeChanged || !preserveLibraryDraft || !libraryDirty) {
            libraryMode = String(currentState.library_mode || "manual");
            libraryDraftRows = (currentState.library_table_rows || []).map(normalizeDraftRow);
            libraryDirty = false;
        }
        if (scopeChanged) {
            formDirtyState = {
                global: false,
                station: false,
                erds: false,
            };
        }
        resetDirtyForms.forEach(function(formKey) {
            if (Object.prototype.hasOwnProperty.call(formDirtyState, formKey)) {
                formDirtyState[formKey] = false;
            }
        });

        renderAll();
    }

    function renderAll() {
        renderMount();
        renderScope();
        renderSummary();
        renderTabs();
        renderRuntimeCards();
        renderGlobalPanel();
        renderStationPanel();
        renderErdsPanel();
        renderLibraryPanel();
        syncAllPasswordToggleButtons();
    }

    function renderMount() {
        const mount = currentState.mount || {};
        const node = document.getElementById("radioMountStatus");
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

    function renderScope() {
        const wrap = document.getElementById("radioScopeWrap");
        const select = document.getElementById("radioScopeSelect");
        if (!wrap || !select) {
            return;
        }

        if (!currentState.can_manage_global) {
            wrap.hidden = true;
            select.innerHTML = "";
            return;
        }

        const options = (currentState.available_users || []).map(function(item) {
            const username = String(item.username || "");
            const roleLabel = item.role === "admin" ? "admin" : "user";
            return '<option value="' + escapeHtml(username) + '">' + escapeHtml(username + " (" + roleLabel + ")") + "</option>";
        });
        select.innerHTML = options.join("");
        select.value = currentScopeUsername();
        wrap.hidden = false;
    }

    function renderSummary() {
        const grid = document.getElementById("radioSummaryGrid");
        if (!grid) {
            return;
        }
        const summary = currentState.summary || {};
        const station = currentState.station || {};
        const stationRuntime = currentState.station_runtime_state || {};
        const publicUrl = summary.public_stream_url || "";
        const sourceUsername = String((stationRuntime.source_username || ((station.source || {}).username) || "")).trim();
        const livePort = Number(stationRuntime.live_port || (((station.live || {}).port) || 0)) || 0;
        const statusLabel = hasStation()
            ? (summary.station_service_active ? "Stream działa" : (station.enabled ? "Zapisane, gotowe do startu" : "Zapisane, ale wyłączone"))
            : "Brak radia";
        const erdsModeLabels = {
            titles: "Tytuły utworów",
            fixed: "Stały tekst",
            rotation: "Rotacja tekstów",
        };
        const erdsMode = erdsModeLabels[String((((station || {}).erds) || {}).mode || "rotation")] || "Rotacja tekstów";

        grid.innerHTML = [
            ["Stan radia", statusLabel],
            ["Publiczny URL", publicUrl || "brak"],
            ["Tryb biblioteki", summary.library_mode_label || "Ręczny wybór"],
            ["Pozycje w radiu", summary.library_count || 0],
            ["Dostępne audio", summary.available_audio_count || 0],
            ["Wgrane ręcznie", summary.upload_count || 0],
            ["Źródła z pobrań", summary.download_count || 0],
            ["Tryb eRDS", erdsMode],
            ["Słuchacze", summary.listeners || 0],
            ["Status mountu", stationRuntime.mount_status_label || "brak"],
            ["Login do nadawania", sourceUsername || "brak"],
            ["Port live DJ", livePort || "brak"],
            ["Aktywne audio", String(summary.playable_music_count || 0) + " + " + String(summary.playable_insert_count || 0)],
            ["Aktualne eRDS", summary.current_erds_text || "brak"],
        ].map(function(item) {
            return `
                <div class="overview-tile">
                    <span>${escapeHtml(item[0])}</span>
                    <strong>${escapeHtml(item[1])}</strong>
                </div>
            `;
        }).join("");

        const createButton = document.getElementById("radioCreateButton");
        const deleteButton = document.getElementById("radioDeleteButton");
        const topNote = document.getElementById("radioTopNote");
        if (createButton) {
            createButton.hidden = hasStation();
            createButton.textContent = currentState.can_manage_global
                ? ("Utwórz radio użytkownika " + currentScopeUsername())
                : "Utwórz moje radio";
            createButton.dataset.idleLabel = createButton.textContent;
        }
        if (deleteButton) {
            deleteButton.hidden = !hasStation();
            deleteButton.textContent = currentState.can_manage_global
                ? ("Usuń radio użytkownika " + currentScopeUsername())
                : "Usuń moje radio";
            deleteButton.dataset.idleLabel = deleteButton.textContent;
        }
        if (topNote) {
            topNote.textContent = hasStation()
                ? "Możesz przełączyć radio na całą bibliotekę użytkownika jednym kliknięciem, a potem tylko odhaczać wyjątki."
                : "Nie musisz dodawać plików pojedynczo. Możesz od razu zbudować bibliotekę całego użytkownika z ewentualnymi wykluczeniami.";
        }
    }

    function getVisibleTabs() {
        return ["runtime", "backend", "station", "erds", "library"];
    }

    function renderTabs() {
        const visibleTabs = getVisibleTabs();
        if (!visibleTabs.includes(activeTab)) {
            activeTab = visibleTabs.includes("library") ? "library" : visibleTabs[0];
        }
        storeActiveTab(activeTab);

        root.querySelectorAll(".radio-tab-button").forEach(function(button) {
            const tabName = String(button.dataset.radioTab || "");
            const isVisible = visibleTabs.includes(tabName);
            button.hidden = !isVisible;
            button.classList.toggle("is-active", isVisible && tabName === activeTab);
            button.setAttribute("aria-pressed", isVisible && tabName === activeTab ? "true" : "false");
        });

        root.querySelectorAll(".radio-panel").forEach(function(panel) {
            const panelName = String(panel.dataset.radioPanel || "");
            panel.hidden = panelName !== activeTab;
        });
    }

    function renderBackendTask(task) {
        const panel = document.getElementById("radioBackendTaskPanel");
        const progress = document.getElementById("radioBackendTaskProgress");
        const bar = document.getElementById("radioBackendTaskBar");
        if (!panel || !progress || !bar) {
            return;
        }

        const visible = !!(task && task.visible);
        panel.hidden = !visible;
        if (!visible) {
            return;
        }

        setPill("radioBackendTaskStatusPill", task.status_kind, task.status_label || "Przetwarzanie");
        setText("radioBackendTaskLabel", task.title || "Instalacja backendu radia");
        setText("radioBackendTaskPercent", formatPercent(task.progress_percent));
        setText("radioBackendTaskDetail", task.detail || task.message || "Trwa przetwarzanie zadania.");

        let timeText = "";
        if (task.active && task.started_at_text) {
            timeText = "Start: " + task.started_at_text;
        } else if (task.finished_at_text) {
            timeText = "Zakończono: " + task.finished_at_text;
        }
        setText("radioBackendTaskTime", timeText);

        if (task.progress_percent === null || task.progress_percent === undefined) {
            progress.classList.add("is-indeterminate");
            bar.style.width = "38%";
        } else {
            progress.classList.remove("is-indeterminate");
            bar.style.width = Math.max(0, Math.min(100, Number(task.progress_percent) || 0)) + "%";
        }

        bar.className = "progress-bar " + getTaskProgressBarClass(task);
    }

    function renderRuntimeCards() {
        const backendPackage = currentState.backend_package_state || {};
        const backendService = currentState.backend_service_state || {};
        const stationRuntime = currentState.station_runtime_state || {};
        const backendTask = currentState.backend_install_task || {};
        const backendCard = document.getElementById("radioBackendRuntimeCard");
        const backendPackages = Array.isArray(backendPackage.packages) ? backendPackage.packages : [];
        const icecastPackage = backendPackages.find(function(item) { return String(item && item.name || "") === "icecast2"; }) || {};
        const liquidsoapPackage = backendPackages.find(function(item) { return String(item && item.name || "") === "liquidsoap"; }) || {};
        const stationLogLink = document.getElementById("radioStationLogLink");

        if (backendCard) {
            backendCard.hidden = !currentState.can_manage_global;
        }
        if (stationLogLink) {
            stationLogLink.href = "/logs-radio-station" + buildScopeQuery();
        }

        setPill("radioBackendStatusPill", backendService.status_kind || backendPackage.status_pill_kind, backendService.status_label || backendPackage.status_pill_label || "Nieznany");
        setText("radioBackendStatusMeta", !backendPackage.linux_supported
            ? "To środowisko nie obsługuje uruchamiania backendu radia. Do streamingu potrzebny jest Linux z apt i systemd."
            : (backendPackage.checked_at_text ? ("Ostatnie sprawdzenie: " + backendPackage.checked_at_text) : "Backend radia nie był jeszcze sprawdzany."));
        setText("radioBackendPackagesLabel", "Icecast: " + String(icecastPackage.current_version || "brak") + " | Liquidsoap: " + String(liquidsoapPackage.current_version || "brak"));
        setText("radioBackendServiceLabel", backendService.status_label || "nieznany");
        setText("radioBackendRuntimeRoot", backendService.runtime_root || "-");
        setText("radioBackendLogPath", backendService.log_file || "-");
        setHidden("radioBackendErrorBox", !backendPackage.check_error && !backendService.error);
        setText("radioBackendErrorText", backendPackage.check_error || backendService.error || "");

        const backendInstallButton = document.getElementById("radioBackendInstallButton");
        if (backendInstallButton) {
            backendInstallButton.hidden = !backendPackage.action_needed && !backendTask.active;
            backendInstallButton.textContent = backendPackage.action_button_label || "Zainstaluj backend";
            backendInstallButton.dataset.idleLabel = backendInstallButton.textContent;
            backendInstallButton.disabled = !backendPackage.linux_supported;
        }
        const backendToggleButton = document.getElementById("radioBackendToggleButton");
        if (backendToggleButton) {
            backendToggleButton.textContent = backendService.toggle_button_label || "Włącz backend";
            backendToggleButton.dataset.idleLabel = backendToggleButton.textContent;
            backendToggleButton.disabled = !currentState.can_manage_global || !backendPackage.linux_supported;
        }
        const backendCheckButton = document.getElementById("radioBackendCheckButton");
        if (backendCheckButton) {
            backendCheckButton.disabled = !backendPackage.linux_supported;
        }
        const backendRestartButton = document.getElementById("radioBackendRestartButton");
        if (backendRestartButton) {
            backendRestartButton.disabled = !backendPackage.linux_supported;
        }

        renderBackendTask(backendTask);

        const runtimeStatusLabel = hasStation()
            ? (stationRuntime.status_label || "Nieznany")
            : "Brak radia";
        const runtimeMeta = hasStation()
            ? (stationRuntime.mount_connected ? "Mount streamu jest aktywny i widoczny w Icecast." : "Możesz uruchomić stację albo najpierw uzupełnić bibliotekę audio.")
            : "Najpierw utwórz radio albo zapisz bibliotekę audio dla tego użytkownika.";
        setPill("radioStationRuntimeStatusPill", stationRuntime.status_kind || "muted", runtimeStatusLabel);
        setText("radioStationRuntimeMeta", runtimeMeta);
        setText("radioStationMountLabel", stationRuntime.mount_status_label || "brak");
        setText("radioStationListenersLabel", stationRuntime.listeners || 0);
        setText("radioStationPublicUrlLabel", stationRuntime.public_stream_url || "brak");
        setText("radioStationLiveStatusLabel", stationRuntime.live_status_label || "wyłączony");
        setText("radioStationPlayableLabel", String(stationRuntime.playable_music_count || 0) + " + " + String(stationRuntime.playable_insert_count || 0));
        setText("radioStationLiveEndpointLabel", stationRuntime.live_enabled
            ? ((stationRuntime.live_connected ? "Na żywo: " : "Wejście: ") + String(stationRuntime.live_endpoint || "brak"))
            : "Live takeover wyłączony");
        setText("radioStationCurrentErds", stationRuntime.current_erds_text || "brak aktywnego tekstu");
        setText("radioStationCurrentSong", stationRuntime.current_song || "brak danych");
        setHidden("radioStationRuntimeErrorBox", !stationRuntime.error);
        setText("radioStationRuntimeErrorText", stationRuntime.error || "");

        const stationStartButton = document.getElementById("radioStationStartButton");
        const stationStopButton = document.getElementById("radioStationStopButton");
        const stationRestartButton = document.getElementById("radioStationRestartButton");
        const stationNextButton = document.getElementById("radioStationNextButton");
        if (stationStartButton) {
            stationStartButton.disabled = !hasStation();
        }
        if (stationStopButton) {
            stationStopButton.disabled = !hasStation();
        }
        if (stationRestartButton) {
            stationRestartButton.disabled = !hasStation();
        }
        if (stationNextButton) {
            stationNextButton.disabled = !hasStation() || !stationRuntime.service_active;
        }
    }

    function renderGlobalPanel() {
        const card = document.getElementById("radioGlobalCard");
        if (!card) {
            return;
        }
        const canEditGlobal = !!currentState.can_manage_global;
        const readonlyNote = document.getElementById("radioGlobalReadonlyNote");
        const form = document.getElementById("radioGlobalForm");
        if (readonlyNote) {
            readonlyNote.hidden = canEditGlobal;
        }
        if (form) {
            form.querySelectorAll("input, select, textarea").forEach(function(field) {
                if (!(field instanceof HTMLElement)) {
                    return;
                }
                if (field.name === "enabled" || field.name === "autostart_backend") {
                    field.disabled = !canEditGlobal;
                    return;
                }
                field.disabled = !canEditGlobal;
                if (field instanceof HTMLInputElement && field.type !== "checkbox") {
                    field.readOnly = !canEditGlobal;
                }
            });
            const submitButton = form.querySelector('button[type="submit"]');
            if (submitButton) {
                submitButton.hidden = !canEditGlobal;
            }
        }
        if (formDirtyState.global) {
            return;
        }
        const config = currentState.global_config || {};
        document.getElementById("radioGlobalPublicBaseUrl").value = String(config.public_base_url || "");
        document.getElementById("radioGlobalHostname").value = String(config.hostname || "");
        document.getElementById("radioGlobalBindIp").value = String(config.bind_ip || "");
        document.getElementById("radioGlobalPort").value = String(config.port || "");
        document.getElementById("radioGlobalMaxListeners").value = String(config.max_listeners || "");
        document.getElementById("radioGlobalLocation").value = String(config.location || "");
        document.getElementById("radioGlobalAdminContact").value = String(config.admin_contact || "");
        document.getElementById("radioGlobalSourcePassword").value = String(config.source_password || "");
        document.getElementById("radioGlobalAdminUsername").value = String(config.admin_username || "");
        document.getElementById("radioGlobalAdminPassword").value = String(config.admin_password || "");
        document.getElementById("radioGlobalDefaultBitrate").value = String(config.default_bitrate_kbps || "");
        document.getElementById("radioGlobalMetadataRefresh").value = String(config.metadata_refresh_seconds || "");
        document.getElementById("radioGlobalEnabled").checked = !!config.enabled;
        document.getElementById("radioGlobalAutostartBackend").checked = !!config.autostart_backend;
    }

    function setSelectValue(selectId, value) {
        const node = document.getElementById(selectId);
        if (!node) {
            return;
        }
        const targetValue = String(value || "");
        const hasOption = Array.from(node.options || []).some(function(option) {
            return String(option.value || "") === targetValue;
        });
        node.value = hasOption ? targetValue : String((node.options[0] || {}).value || "");
    }

    function renderBitrateOptions(streamFormat, selectedValue) {
        const node = document.getElementById("radioStationBitrate");
        if (!node) {
            return;
        }
        const formatKey = String(streamFormat || "mp3").toLowerCase() === "aac" ? "aac" : "mp3";
        const presets = BITRATE_PRESETS[formatKey] || BITRATE_PRESETS.mp3;
        node.innerHTML = presets.map(function(value) {
            return '<option value="' + escapeHtml(value) + '">' + escapeHtml(value + " kbps") + "</option>";
        }).join("");
        const preferredValue = String(selectedValue || "");
        const fallbackValue = "192";
        const normalizedValue = presets.includes(preferredValue) ? preferredValue : fallbackValue;
        node.value = normalizedValue;
    }

    function renderStationPanel() {
        const station = hasStation() ? (currentState.station || {}) : createDefaultStationDraft();
        const stream = station.stream || {};
        const source = station.source || {};
        const live = station.live || {};
        const autopilot = station.autopilot || {};
        const livePreview = buildStationLivePreview(station);
        if (formDirtyState.station) {
            return;
        }
        document.getElementById("radioStationName").value = String(station.name || "");
        document.getElementById("radioStationDescription").value = String(station.description || "");
        document.getElementById("radioStationGenre").value = String(station.genre || "");
        document.getElementById("radioStationSlug").value = String(station.slug || "");
        document.getElementById("radioStationMountName").value = String(station.mount_name || "");
        const streamFormat = String(stream.format || "mp3");
        setSelectValue("radioStationFormat", streamFormat);
        renderBitrateOptions(streamFormat, String(stream.bitrate_kbps || 192));
        setSelectValue("radioStationPlayMode", String(autopilot.play_mode || "random"));
        document.getElementById("radioStationCrossfade").value = String(autopilot.crossfade_seconds || "0");
        document.getElementById("radioStationScanInterval").value = String(autopilot.scan_interval_seconds || "30");
        document.getElementById("radioStationJingleEveryTracks").value = String(autopilot.jingle_every_tracks || "0");
        document.getElementById("radioStationRepeatGuardPercent").value = String(autopilot.repeat_guard_percent ?? "100");
        document.getElementById("radioStationSourceUsername").value = String(source.username || "");
        document.getElementById("radioStationSourcePassword").value = String(source.password || "");
        document.getElementById("radioStationLivePort").value = String(live.port || "");
        document.getElementById("radioStationLiveShowName").value = String(live.show_name || "");
        document.getElementById("radioStationLiveDjName").value = String(live.dj_name || "");
        document.getElementById("radioStationLiveHost").value = String(livePreview.host || "");
        document.getElementById("radioStationLiveMountName").value = String(livePreview.mount_path || "/live");
        document.getElementById("radioStationLiveEndpoint").value = String(livePreview.endpoint || "");
        document.getElementById("radioStationEnabled").checked = !!station.enabled;
        document.getElementById("radioStationAutostart").checked = !!station.autostart;
        document.getElementById("radioStationLiveEnabled").checked = !!live.enabled;
    }

    function renderErdsPanel() {
        const station = hasStation() ? (currentState.station || {}) : createDefaultStationDraft();
        const erds = station.erds || {};
        const placeholders = currentState.erds_placeholders || [];
        const previewLines = currentState.erds_preview_lines || [];
        const placeholderNode = document.getElementById("radioErdsPlaceholderList");
        const previewNode = document.getElementById("radioErdsPreviewList");
        if (!formDirtyState.erds) {
            setSelectValue("radioErdsMode", String(erds.mode || "rotation"));
            document.getElementById("radioErdsFixedText").value = String(erds.fixed_text || "");
            document.getElementById("radioErdsSuppressTrackTitles").checked = !!erds.suppress_track_titles;
            document.getElementById("radioErdsRotationInterval").value = String(erds.rotation_interval_seconds || "20");
            document.getElementById("radioErdsTemplatesText").value = (erds.templates || []).join("\n");
        }

        placeholderNode.innerHTML = placeholders.map(function(item) {
            return `
                <div class="radio-token-item">
                    <code>${escapeHtml(item.name || "")}</code>
                    <span>${escapeHtml(item.description || "")}</span>
                </div>
            `;
        }).join("");

        previewNode.innerHTML = previewLines.length
            ? previewLines.map(function(line) {
                return '<div class="radio-preview-item">' + escapeHtml(line) + "</div>";
            }).join("")
            : '<div class="dlna-empty">Brak aktywnego podglądu eRDS dla bieżącego trybu.</div>';
    }

    function renderLibraryStats() {
        const statsNode = document.getElementById("radioLibraryStats");
        const helpNode = document.getElementById("radioLibraryModeHelp");
        if (!statsNode || !helpNode) {
            return;
        }
        const total = libraryDraftRows.length;
        const included = libraryDraftRows.filter(function(row) { return row.included; }).length;
        const filtered = getFilteredDraftRows().length;
        const excluded = total - included;
        helpNode.textContent = libraryMode === "all_user_audio"
            ? "Tryb całej biblioteki: wszystko użytkownika trafia do radia, a odznaczone checkboxy są listą wykluczeń."
            : "Tryb ręczny: do radia trafiają tylko zaznaczone checkboxami wpisy.";
        statsNode.innerHTML = [
            "Widoczne: <strong>" + escapeHtml(filtered) + "</strong>",
            "W radiu: <strong>" + escapeHtml(included) + "</strong>",
            "Wykluczone / poza radiem: <strong>" + escapeHtml(excluded) + "</strong>",
            libraryDirty ? '<span class="radio-library-dirty">Masz niezapisane zmiany.</span>' : '<span class="radio-library-clean">Wszystkie zmiany zapisane.</span>',
        ].join(" <span class=\"radio-library-separator\">•</span> ");
    }

    function renderLibraryPanel() {
        const manualButton = document.getElementById("radioLibraryModeManualButton");
        const allButton = document.getElementById("radioLibraryUseAllButton");
        if (manualButton) {
            manualButton.classList.toggle("is-active", libraryMode === "manual");
        }
        if (allButton) {
            allButton.classList.toggle("is-active", libraryMode === "all_user_audio");
        }

        renderLibraryStats();

        const tbody = document.getElementById("radioLibraryTableBody");
        if (!tbody) {
            return;
        }
        const rows = getFilteredDraftRows();
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="radio-library-empty">Brak pasujących plików audio dla tego filtra.</td></tr>';
            return;
        }

        tbody.innerHTML = rows.map(function(row) {
            const sourceBadgeClass = row.source_type === "upload" ? "is-upload" : "is-download";
            const rowClass = row.included ? "is-included" : "is-excluded";
            return `
                <tr class="radio-library-table-row ${rowClass}" data-relative-path="${escapeHtml(row.relative_path)}">
                    <td class="is-check">
                        <input type="checkbox" data-library-field="included" ${row.included ? "checked" : ""}>
                    </td>
                    <td>
                        <input class="radio-table-input" type="text" data-library-field="display_title" value="${escapeHtml(row.display_title)}">
                    </td>
                    <td class="is-role">
                        <select class="radio-table-select" data-library-field="role">
                            <option value="music" ${row.role === "music" ? "selected" : ""}>Muzyka</option>
                            <option value="jingle" ${row.role === "jingle" ? "selected" : ""}>Jingle</option>
                            <option value="promo" ${row.role === "promo" ? "selected" : ""}>Promo</option>
                        </select>
                    </td>
                    <td>
                        <span class="radio-source-badge ${sourceBadgeClass}">${escapeHtml(row.source_type_label || (row.source_type === "upload" ? "Wgrany plik" : "Plik z pobrań"))}</span>
                    </td>
                    <td class="radio-file-cell">
                        <div class="radio-file-path">${escapeHtml(row.display_path || row.name || row.relative_path)}</div>
                        <div class="radio-file-meta">${escapeHtml(row.size_text || "")} • ${escapeHtml(row.mtime_text || "")}</div>
                    </td>
                    <td class="is-actions">
                        <a class="radio-table-link" href="${escapeHtml(row.url || "#")}" target="_blank" rel="noopener">Otwórz</a>
                    </td>
                </tr>
            `;
        }).join("");
    }

    function syncVisibleLibraryRowEdits() {
        root.querySelectorAll("#radioLibraryTableBody tr[data-relative-path]").forEach(function(rowElement) {
            const relativePath = String(rowElement.dataset.relativePath || "");
            const draftRow = libraryDraftRows.find(function(item) {
                return String(item.relative_path || "") === relativePath;
            });
            if (!draftRow) {
                return;
            }
            const titleInput = rowElement.querySelector('[data-library-field="display_title"]');
            const roleSelect = rowElement.querySelector('[data-library-field="role"]');
            const includedInput = rowElement.querySelector('[data-library-field="included"]');
            if (titleInput) {
                draftRow.display_title = String(titleInput.value || "");
            }
            if (roleSelect) {
                draftRow.role = String(roleSelect.value || "music");
            }
            if (includedInput) {
                draftRow.included = !!includedInput.checked;
            }
        });
    }

    function setUploadProgressVisible(visible) {
        const panel = document.getElementById("radioUploadProgressPanel");
        if (panel) {
            panel.hidden = !visible;
        }
        if (!visible && uploadHideTimer) {
            window.clearTimeout(uploadHideTimer);
            uploadHideTimer = null;
        }
    }

    function updateUploadProgressUI(percentValue, filesLabel, speedLabel, statusText) {
        const bar = document.getElementById("radioUploadProgressBar");
        setText("radioUploadProgressPercent", Math.max(0, Math.min(100, percentValue || 0)).toFixed(1) + "%");
        setText("radioUploadProgressFiles", filesLabel || "");
        setText("radioUploadProgressSpeed", speedLabel || "0 B/s");
        setText("radioUploadProgressStatus", statusText || "");
        if (bar) {
            bar.style.width = Math.max(0, Math.min(100, percentValue || 0)) + "%";
        }
    }

    function validateUploadFiles(files) {
        const invalidNames = [];
        Array.from(files || []).forEach(function(file) {
            const name = String((file && file.name) || "");
            const extension = name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "";
            if (!ALLOWED_UPLOAD_EXTENSIONS.has(extension)) {
                invalidNames.push(name || "nieznany plik");
            }
        });
        return invalidNames;
    }

    async function performButtonAction(button, busyLabel, action, applyOptions) {
        setButtonBusy(button, true, busyLabel);
        try {
            const data = await action();
            applyState(data.radio_state || {}, Object.assign({ preserveLibraryDraft: true, resetDirtyForms: [] }, applyOptions || {}));
            if (data.message) {
                showToast(data.message, data.kind || "success");
            }
            return data;
        } catch (err) {
            showToast(String(err), "error");
            return null;
        } finally {
            setButtonBusy(button, false);
        }
    }

    async function refreshState() {
        if (hasProtectedFormActivity()) {
            return;
        }
        try {
            const data = await fetchJson("/api/radio/state" + buildScopeQuery());
            applyState(data.radio_state || {}, { preserveLibraryDraft: true });
        } catch (err) {
            // Tło tylko odświeża stan.
        }
    }

    function setLibraryMode(mode, includeEverything) {
        libraryMode = mode === "all_user_audio" ? "all_user_audio" : "manual";
        if (includeEverything) {
            libraryDraftRows = libraryDraftRows.map(function(row) {
                return Object.assign({}, row, { included: true });
            });
        }
        libraryDirty = true;
        renderLibraryPanel();
    }

    function updateVisibleRowsIncluded(nextIncluded) {
        const visiblePathSet = new Set(getFilteredDraftRows().map(function(row) {
            return String(row.relative_path || "");
        }));
        libraryDraftRows = libraryDraftRows.map(function(row) {
            if (visiblePathSet.has(String(row.relative_path || ""))) {
                return Object.assign({}, row, { included: !!nextIncluded });
            }
            return row;
        });
        libraryDirty = true;
        renderLibraryPanel();
    }

    async function handleUploadSubmit(form) {
        const submitButton = form.querySelector('button[type="submit"]');
        const fileInput = document.getElementById("radioUploadInput");
        const files = Array.from((fileInput && fileInput.files) || []);
        if (!files.length) {
            showToast("Najpierw wybierz przynajmniej jeden plik audio do wgrania.", "error");
            return;
        }
        const invalidNames = validateUploadFiles(files);
        if (invalidNames.length) {
            showToast("Te pliki nie wyglądają na obsługiwane audio: " + invalidNames.join(", "), "error");
            return;
        }

        setButtonBusy(submitButton, true, "Wgrywanie...");
        setUploadProgressVisible(true);
        setText("radioUploadProgressLabel", "Wgrywanie plików audio");
        updateUploadProgressUI(0, files.length + " plików", "0 B/s", "Rozpoczynam upload plików do biblioteki radia.");

        const startedAt = Date.now();
        const formData = new FormData();
        formData.append("owner_username", readScopeOwner());
        files.forEach(function(file) {
            formData.append("files", file, file.name);
        });

        try {
            const data = await uploadFormData("/api/radio/upload", formData, function(event) {
                if (!event.lengthComputable) {
                    updateUploadProgressUI(0, files.length + " plików", "trwa...", "Wgrywanie trwa, ale przeglądarka nie podała całkowitego rozmiaru.");
                    return;
                }
                const percent = event.total > 0 ? (event.loaded / event.total) * 100 : 0;
                const elapsedSeconds = Math.max(0.25, (Date.now() - startedAt) / 1000);
                const speed = event.loaded / elapsedSeconds;
                updateUploadProgressUI(
                    percent,
                    files.length + " plików • " + formatBytes(event.loaded) + " / " + formatBytes(event.total),
                    formatSpeed(speed),
                    "Wgrywam paczkę audio do biblioteki użytkownika."
                );
            });
            applyState(data.radio_state || {}, { preserveLibraryDraft: false, forceLibraryReset: true });
            const uploadSummary = data.upload_summary || {};
            const uploadedCount = Number(uploadSummary.uploaded_count || (data.uploaded_relative_path ? 1 : 0)) || 0;
            const failedCount = Number(uploadSummary.failed_count || 0) || 0;
            const resultLines = [];
            if (failedCount && Array.isArray(uploadSummary.results)) {
                uploadSummary.results.forEach(function(item) {
                    if (!item || item.ok !== false) {
                        return;
                    }
                    resultLines.push(String(item.filename || "plik") + ": " + String(item.error || "błąd"));
                });
            }
            updateUploadProgressUI(
                100,
                uploadedCount + " / " + files.length + " plików",
                "gotowe",
                resultLines.length ? resultLines.slice(0, 3).join(" | ") : (data.message || "Wgrywanie zakończone.")
            );
            showToast(data.message || "Wgrywanie zakończone.", data.kind || "success");
            form.reset();
            uploadHideTimer = window.setTimeout(function() {
                setUploadProgressVisible(false);
            }, 3200);
        } catch (err) {
            updateUploadProgressUI(0, "0 / " + files.length + " plików", "0 B/s", String(err));
            showToast(String(err), "error");
        } finally {
            setButtonBusy(submitButton, false);
        }
    }

    async function handleRootClick(event) {
        const tabButton = event.target.closest(".radio-tab-button");
        if (tabButton) {
            event.preventDefault();
            activeTab = String(tabButton.dataset.radioTab || "library");
            renderTabs();
            return;
        }

        const createButton = event.target.closest("#radioCreateButton");
        if (createButton) {
            event.preventDefault();
            return performButtonAction(createButton, "Tworzenie...", function() {
                return postJson("/api/radio/station", {
                    action: "create",
                    owner_username: readScopeOwner(),
                });
            }, { preserveLibraryDraft: false, forceLibraryReset: true });
        }

        const deleteButton = event.target.closest("#radioDeleteButton");
        if (deleteButton) {
            event.preventDefault();
            if (!confirm("Usunąć całe radio tego użytkownika razem z konfiguracją biblioteki i eRDS?")) {
                return;
            }
            return performButtonAction(deleteButton, "Usuwanie...", function() {
                return postJson("/api/radio/station", {
                    action: "delete",
                    owner_username: readScopeOwner(),
                });
            }, { preserveLibraryDraft: false, forceLibraryReset: true });
        }

        const manualModeButton = event.target.closest("#radioLibraryModeManualButton");
        if (manualModeButton) {
            event.preventDefault();
            setLibraryMode("manual", false);
            return;
        }

        const allModeButton = event.target.closest("#radioLibraryUseAllButton");
        if (allModeButton) {
            event.preventDefault();
            setLibraryMode("all_user_audio", true);
            return;
        }

        const includeVisibleButton = event.target.closest("#radioLibraryIncludeVisibleButton");
        if (includeVisibleButton) {
            event.preventDefault();
            updateVisibleRowsIncluded(true);
            return;
        }

        const excludeVisibleButton = event.target.closest("#radioLibraryExcludeVisibleButton");
        if (excludeVisibleButton) {
            event.preventDefault();
            updateVisibleRowsIncluded(false);
            return;
        }

        const backendCheckButton = event.target.closest("#radioBackendCheckButton");
        if (backendCheckButton) {
            event.preventDefault();
            return performButtonAction(backendCheckButton, "Sprawdzanie...", function() {
                return postJson("/api/radio/backend/check", {
                    owner_username: readScopeOwner(),
                });
            });
        }

        const backendInstallButton = event.target.closest("#radioBackendInstallButton");
        if (backendInstallButton) {
            event.preventDefault();
            return performButtonAction(backendInstallButton, "Uruchamianie...", function() {
                return postJson("/api/radio/backend/install", {
                    owner_username: readScopeOwner(),
                });
            });
        }

        const backendToggleButton = event.target.closest("#radioBackendToggleButton");
        if (backendToggleButton) {
            event.preventDefault();
            const action = String((currentState.backend_service_state || {}).service_active ? "stop" : "start");
            return performButtonAction(backendToggleButton, action === "start" ? "Uruchamianie..." : "Zatrzymywanie...", function() {
                return postJson("/api/radio/backend/control", {
                    owner_username: readScopeOwner(),
                    action: action,
                });
            });
        }

        const backendRestartButton = event.target.closest("#radioBackendRestartButton");
        if (backendRestartButton) {
            event.preventDefault();
            return performButtonAction(backendRestartButton, "Restartowanie...", function() {
                return postJson("/api/radio/backend/control", {
                    owner_username: readScopeOwner(),
                    action: "restart",
                });
            });
        }

        const stationStartButton = event.target.closest("#radioStationStartButton");
        if (stationStartButton) {
            event.preventDefault();
            return performButtonAction(stationStartButton, "Uruchamianie...", function() {
                return postJson("/api/radio/station/control", {
                    owner_username: readScopeOwner(),
                    action: "start",
                });
            });
        }

        const stationStopButton = event.target.closest("#radioStationStopButton");
        if (stationStopButton) {
            event.preventDefault();
            return performButtonAction(stationStopButton, "Zatrzymywanie...", function() {
                return postJson("/api/radio/station/control", {
                    owner_username: readScopeOwner(),
                    action: "stop",
                });
            });
        }

        const stationRestartButton = event.target.closest("#radioStationRestartButton");
        if (stationRestartButton) {
            event.preventDefault();
            return performButtonAction(stationRestartButton, "Restartowanie...", function() {
                return postJson("/api/radio/station/control", {
                    owner_username: readScopeOwner(),
                    action: "restart",
                });
            });
        }

        const stationNextButton = event.target.closest("#radioStationNextButton");
        if (stationNextButton) {
            event.preventDefault();
            return performButtonAction(stationNextButton, "Przeskakiwanie...", function() {
                return postJson("/api/radio/station/control", {
                    owner_username: readScopeOwner(),
                    action: "next",
                });
            });
        }

        const passwordToggleButton = event.target.closest(".radio-password-toggle");
        if (passwordToggleButton) {
            event.preventDefault();
            togglePasswordVisibility(passwordToggleButton);
            return;
        }
    }

    async function handleRootSubmit(event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        if (form.id === "radioGlobalForm") {
            event.preventDefault();
            const submitButton = form.querySelector('button[type="submit"]');
            return performButtonAction(submitButton, "Zapisywanie...", function() {
                return postJson("/api/radio/global", {
                    owner_username: readScopeOwner(),
                    enabled: !!form.enabled.checked,
                    public_base_url: form.public_base_url.value,
                    hostname: form.hostname.value,
                    bind_ip: form.bind_ip.value,
                    port: form.port.value,
                    max_listeners: form.max_listeners.value,
                    location: form.location.value,
                    admin_contact: form.admin_contact.value,
                    source_password: form.source_password.value,
                    admin_username: form.admin_username.value,
                    admin_password: form.admin_password.value,
                    default_bitrate_kbps: form.default_bitrate_kbps.value,
                    metadata_refresh_seconds: form.metadata_refresh_seconds.value,
                    autostart_backend: !!form.autostart_backend.checked,
                });
            }, { resetDirtyForms: ["global"] });
        }

        if (form.id === "radioStationForm") {
            event.preventDefault();
            const submitButton = form.querySelector('button[type="submit"]');
            return performButtonAction(submitButton, "Zapisywanie...", function() {
                return postJson("/api/radio/station", {
                    action: "update",
                    owner_username: readScopeOwner(),
                    enabled: !!form.enabled.checked,
                    autostart: !!form.autostart.checked,
                    name: form.name.value,
                    description: form.description.value,
                    genre: form.genre.value,
                    slug: form.slug.value,
                    mount_name: form.mount_name.value,
                    stream: {
                        bitrate_kbps: form.bitrate_kbps.value,
                        format: form.stream_format.value,
                    },
                    source: {
                        username: form.source_username.value,
                        password: form.source_password.value,
                    },
                    live: {
                        enabled: !!form.live_enabled.checked,
                        port: form.live_port.value,
                        mount_name: form.live_mount_name.value,
                        show_name: form.live_show_name.value,
                        dj_name: form.live_dj_name.value,
                    },
                    autopilot: {
                        play_mode: form.play_mode.value,
                        crossfade_seconds: form.crossfade_seconds.value,
                        scan_interval_seconds: form.scan_interval_seconds.value,
                        jingle_every_tracks: form.jingle_every_tracks.value,
                        repeat_guard_percent: form.repeat_guard_percent.value,
                    },
                });
            }, { preserveLibraryDraft: true, resetDirtyForms: ["station"] });
        }

        if (form.id === "radioErdsForm") {
            event.preventDefault();
            const submitButton = form.querySelector('button[type="submit"]');
            const previousSuppressTrackTitles = !!((((currentState.station || {}).erds) || {}).suppress_track_titles);
            return performButtonAction(submitButton, "Zapisywanie...", function() {
                return postJson("/api/radio/station", {
                    action: "update",
                    owner_username: readScopeOwner(),
                    restart_runtime: previousSuppressTrackTitles !== !!form.suppress_track_titles.checked,
                    erds: {
                        mode: form.mode.value,
                        fixed_text: form.fixed_text.value,
                        suppress_track_titles: !!form.suppress_track_titles.checked,
                        rotation_interval_seconds: form.rotation_interval_seconds.value,
                    },
                    templates_text: form.templates_text.value,
                });
            }, { preserveLibraryDraft: true, resetDirtyForms: ["erds"] });
        }

        if (form.id === "radioLibraryForm") {
            event.preventDefault();
            syncVisibleLibraryRowEdits();
            const submitButton = form.querySelector('button[type="submit"]');
            return performButtonAction(submitButton, "Zapisywanie...", function() {
                return postJson("/api/radio/library", {
                    action: "bulk_save",
                    owner_username: readScopeOwner(),
                    mode: libraryMode,
                    rows: libraryDraftRows,
                });
            }, { preserveLibraryDraft: false, forceLibraryReset: true });
        }

        if (form.id === "radioUploadForm") {
            event.preventDefault();
            return handleUploadSubmit(form);
        }
    }

    function handleRootInput(event) {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }

        const form = target.closest("form");
        if (form) {
            if (form.id === "radioGlobalForm") {
                formDirtyState.global = true;
            } else if (form.id === "radioStationForm") {
                formDirtyState.station = true;
            } else if (form.id === "radioErdsForm") {
                formDirtyState.erds = true;
            }
        }

        if (target.matches("#radioLibraryFilter")) {
            libraryFilter = String(target.value || "").trim();
            renderLibraryPanel();
            return;
        }

        const rowElement = target.closest("tr[data-relative-path]");
        if (!rowElement) {
            return;
        }
        const relativePath = String(rowElement.dataset.relativePath || "");
        const draftRow = libraryDraftRows.find(function(item) {
            return String(item.relative_path || "") === relativePath;
        });
        if (!draftRow) {
            return;
        }

        const fieldName = String(target.getAttribute("data-library-field") || "");
        if (fieldName === "display_title") {
            draftRow.display_title = String(target.value || "");
            libraryDirty = true;
            renderLibraryStats();
        }
    }

    function handleRootChange(event) {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }

        const form = target.closest("form");
        if (form) {
            if (form.id === "radioGlobalForm") {
                formDirtyState.global = true;
            } else if (form.id === "radioStationForm") {
                formDirtyState.station = true;
            } else if (form.id === "radioErdsForm") {
                formDirtyState.erds = true;
            }
        }

        if (target.matches("#radioScopeSelect")) {
            const selectedUser = String(target.value || "");
            fetchJson("/api/radio/state?user=" + encodeURIComponent(selectedUser))
                .then(function(data) {
                    applyState(data.radio_state || {}, {
                        preserveLibraryDraft: false,
                        forceLibraryReset: true,
                        resetDirtyForms: ["global", "station", "erds"],
                    });
                })
                .catch(function(err) {
                    showToast(String(err), "error");
                });
            return;
        }

        if (target.matches("#radioStationFormat")) {
            const selectedFormat = String(target.value || "mp3");
            const currentBitrate = String((document.getElementById("radioStationBitrate") || {}).value || "");
            renderBitrateOptions(selectedFormat, currentBitrate);
            return;
        }

        const rowElement = target.closest("tr[data-relative-path]");
        if (!rowElement) {
            return;
        }
        const relativePath = String(rowElement.dataset.relativePath || "");
        const draftRow = libraryDraftRows.find(function(item) {
            return String(item.relative_path || "") === relativePath;
        });
        if (!draftRow) {
            return;
        }

        const fieldName = String(target.getAttribute("data-library-field") || "");
        if (fieldName === "included") {
            draftRow.included = !!target.checked;
            rowElement.classList.toggle("is-included", !!target.checked);
            rowElement.classList.toggle("is-excluded", !target.checked);
            libraryDirty = true;
            renderLibraryStats();
            return;
        }
        if (fieldName === "role") {
            draftRow.role = String(target.value || "music");
            libraryDirty = true;
            renderLibraryStats();
        }
    }

    applyState(currentState, { preserveLibraryDraft: false, forceLibraryReset: true });

    root.addEventListener("click", handleRootClick);
    root.addEventListener("submit", handleRootSubmit, true);
    root.addEventListener("input", handleRootInput, true);
    root.addEventListener("change", handleRootChange, true);

    pollTimer = window.setInterval(function() {
        refreshState();
    }, 4000);

    if (typeof window.registerPageCleanup === "function") {
        window.registerPageCleanup(function() {
            window.clearInterval(pollTimer);
            if (uploadHideTimer) {
                window.clearTimeout(uploadHideTimer);
                uploadHideTimer = null;
            }
            root.removeEventListener("click", handleRootClick);
            root.removeEventListener("submit", handleRootSubmit, true);
            root.removeEventListener("input", handleRootInput, true);
            root.removeEventListener("change", handleRootChange, true);
        });
    }
})();
