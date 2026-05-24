(function() {
function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatBytes(bytes) {
    if (bytes === null || bytes === undefined) return "nieznany";
    if (bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let num = Number(bytes);
    while (num >= 1024 && i < units.length - 1) {
        num /= 1024;
        i++;
    }
    return num.toFixed(i === 0 ? 0 : 2) + " " + units[i];
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

let liveSubscription = null;
let latestFilesPayload = null;

async function deleteServerFile(filename, storageKind, ownerUsername) {
    if (!confirm("Usunąć plik z serwera?")) {
        return;
    }

    try {
        const response = await fetch("/api/files/delete", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                relative_path: filename,
                storage_kind: storageKind,
                owner_username: ownerUsername || ""
            })
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            alert(data.error || "Nie udało się usunąć pliku.");
            return;
        }

        refreshData();
    } catch (err) {
        alert("Błąd usuwania pliku: " + err);
    }
}

async function addAudioFileToRadio(relativePath, ownerUsername, triggerButton) {
    if (!relativePath) {
        return;
    }

    if (triggerButton) {
        if (!triggerButton.dataset.idleLabel) {
            triggerButton.dataset.idleLabel = String(triggerButton.textContent || "").trim();
        }
        triggerButton.disabled = true;
        triggerButton.textContent = "Dodawanie...";
    }

    try {
        const response = await fetch("/api/radio/library", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                action: "add",
                owner_username: ownerUsername || "",
                relative_path: relativePath,
                source_type: "download"
            })
        });
        const data = await response.json().catch(function() {
            return {};
        });

        if (!response.ok || !data.ok) {
            showToast((data && (data.error || data.message)) || "Nie udało się dodać pliku do radia.", "error");
            return;
        }

        showToast(data.message || "Dodano plik do biblioteki radia.", "success");
        refreshData();
    } catch (err) {
        showToast("Błąd dodawania do radia: " + err, "error");
    } finally {
        if (triggerButton) {
            triggerButton.disabled = false;
            triggerButton.textContent = triggerButton.dataset.idleLabel || "Dodaj do radia";
        }
    }
}

function renderScope(adminLoggedIn, availableUsers, scopeUsername, currentUser) {
    const wrap = document.getElementById("filesScopeWrap");
    const select = document.getElementById("filesScopeSelect");
    if (!wrap || !select) {
        return;
    }

    if (!adminLoggedIn) {
        wrap.hidden = true;
        select.innerHTML = "";
        return;
    }

    const options = ['<option value="all">Wszyscy użytkownicy</option>']
        .concat((availableUsers || []).map(user => {
            const value = String(user || "");
            const label = value === currentUser ? value + " (ty)" : value;
            return '<option value="' + escapeHtml(value) + '">' + escapeHtml(label) + '</option>';
        }));

    wrap.hidden = false;
    select.innerHTML = options.join("");
    select.value = scopeUsername || "all";
}

function getFilesTypeFilterValue() {
    const select = document.getElementById("filesTypeFilterSelect");
    return select && select.value ? String(select.value) : "all";
}

function renderFiles(files, adminLoggedIn, jobs) {
    const container = document.getElementById("files");
    const liveKeys = new Set((jobs || []).filter(function(job) {
        return !!job && !!job.is_live_capture && !!job.relative_path;
    }).map(function(job) {
        return [String(job.owner_username || ""), String(job.storage_kind || "video"), String(job.relative_path || "")].join("|");
    }));
    const activeFilter = getFilesTypeFilterValue();
    const filteredFiles = (files || []).map(function(file) {
        const liveKey = [String(file.owner_username || ""), String(file.storage_kind || "video"), String(file.relative_path || "")].join("|");
        return Object.assign({}, file, {
            is_live_capture: liveKeys.has(liveKey),
        });
    }).filter(function(file) {
        if (activeFilter === "live") {
            return !!file.is_live_capture;
        }
        if (activeFilter === "standard") {
            return !file.is_live_capture;
        }
        return true;
    });

    if (!filteredFiles.length) {
        container.innerHTML = '<div class="empty">Brak plików w katalogu docelowym.</div>';
        return;
    }

    container.innerHTML = filteredFiles.map(file => {
        const relativePath = escapeHtml(file.relative_path || file.name || "");
        const displayPath = escapeHtml(file.display_path || file.relative_path || file.name || "");
        const storageKind = escapeHtml(file.storage_kind || "video");
        const ownerUsername = escapeHtml(file.owner_username || "");
        const liveBadge = file.is_live_capture ? '<span class="badge" style="margin-left:8px;">LIVE</span>' : "";
        const ownerHtml = adminLoggedIn
            ? '<div class="small">Właściciel: ' + ownerUsername + '</div>'
            : "";
        const radioActionHtml = storageKind === "audio"
            ? '<button type="button" class="btn btn-secondary js-add-file-to-radio" data-file-name="' + relativePath + '" data-owner-username="' + ownerUsername + '">Dodaj do radia</button>'
            : "";
        const actionsHtml = '<div class="file-actions">' + radioActionHtml + '<button type="button" class="btn btn-delete js-delete-file" data-file-name="' + relativePath + '" data-storage-kind="' + storageKind + '" data-owner-username="' + ownerUsername + '">Usuń plik</button></div>';

        return `
            <div class="file-item">
                <div><a class="file-link" href="${escapeHtml(file.url)}" target="_blank" rel="noopener">${displayPath}</a>${liveBadge}</div>
                <div class="small">Rozmiar: ${formatBytes(file.size)} | Zmiana: ${escapeHtml(file.mtime_text)}</div>
                ${ownerHtml}
                ${actionsHtml}
            </div>
        `;
    }).join("");
}

function renderMount(mount) {
    const box = document.getElementById("mountBox");
    if (box) {
        const online = !!(mount && mount.online);
        box.className = "page-status-inline " + (online ? "is-online" : "is-offline");
        box.title = String((mount && mount.message) || "");
        box.innerHTML = `
            <span class="page-status-icon" aria-hidden="true"></span>
            <span class="page-status-text">
                <span class="page-status-icon-dot" aria-hidden="true"></span>
                ${online ? "Serwer danych online" : "Serwer danych offline"}
            </span>
        `;
    }
}

function applyFilesPayload(data) {
    latestFilesPayload = data || null;
    renderMount(data.mount);
    renderScope(Boolean(data.admin_logged_in), data.available_users || [], data.scope_username || "", data.current_user || "");
    renderFiles(data.files || [], Boolean(data.admin_logged_in), data.jobs || []);
}

async function handleDownloadsClick(event) {
    const scopeSelect = event.target.closest("#filesScopeSelect");
    if (scopeSelect) {
        if (liveSubscription && typeof liveSubscription.restart === "function") {
            liveSubscription.restart();
        } else {
            refreshData();
        }
        return;
    }

    const typeSelect = event.target.closest("#filesTypeFilterSelect");
    if (typeSelect) {
        if (latestFilesPayload) {
            applyFilesPayload(latestFilesPayload);
        }
        return;
    }

    const deleteFileBtn = event.target.closest(".js-delete-file");
    if (deleteFileBtn) {
        event.preventDefault();
        const filename = deleteFileBtn.dataset.fileName || "";
        const storageKind = deleteFileBtn.dataset.storageKind || "video";
        const ownerUsername = deleteFileBtn.dataset.ownerUsername || "";
        if (filename) {
            await deleteServerFile(filename, storageKind, ownerUsername);
        }
        return;
    }

    const addToRadioBtn = event.target.closest(".js-add-file-to-radio");
    if (addToRadioBtn) {
        event.preventDefault();
        await addAudioFileToRadio(
            addToRadioBtn.dataset.fileName || "",
            addToRadioBtn.dataset.ownerUsername || "",
            addToRadioBtn
        );
    }
}

async function refreshData() {
    try {
        const scopeSelect = document.getElementById("filesScopeSelect");
        const scopeValue = scopeSelect && scopeSelect.value ? scopeSelect.value : "";
        const query = scopeValue ? ("?user=" + encodeURIComponent(scopeValue)) : "";
        const response = await fetch("/api/files" + query);
        const data = await response.json();
        applyFilesPayload(data);
        return data;
    } catch (err) {
        document.getElementById("files").innerHTML =
            '<div class="empty">Błąd odczytu plików: ' + escapeHtml(err) + '</div>';
        return null;
    }
}

function buildStreamUrl() {
    const scopeSelect = document.getElementById("filesScopeSelect");
    const scopeValue = scopeSelect && scopeSelect.value ? scopeSelect.value : "";
    return "/api/files/stream" + (scopeValue ? ("?user=" + encodeURIComponent(scopeValue)) : "");
}

document.addEventListener("click", handleDownloadsClick);
document.addEventListener("change", handleDownloadsClick);

if (window.appLive && typeof window.appLive.createSubscription === "function") {
    liveSubscription = window.appLive.createSubscription({
        buildUrl: buildStreamUrl,
        fallbackIntervalMs: 3000,
        fetchFallback: refreshData,
        onData: applyFilesPayload,
    });
    liveSubscription.start();
} else {
    refreshData();
    liveSubscription = {
        stop: function() {
            clearInterval(downloadsRefreshTimer);
        },
    };
    var downloadsRefreshTimer = setInterval(refreshData, 3000);
}

if (typeof window.registerPageCleanup === "function") {
    window.registerPageCleanup(function() {
        if (liveSubscription && typeof liveSubscription.stop === "function") {
            liveSubscription.stop();
        }
        document.removeEventListener("click", handleDownloadsClick);
        document.removeEventListener("change", handleDownloadsClick);
    });
}
})();
