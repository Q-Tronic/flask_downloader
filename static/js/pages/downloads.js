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

function renderAdminHint(adminLoggedIn) {
    const hint = document.getElementById("filesAdminHint");
    hint.textContent = adminLoggedIn
        ? "Administrator może przełączać widok między użytkownikami i usuwać ich pliki po potwierdzeniu."
        : "Widzisz tylko własne pliki i możesz usuwać je po potwierdzeniu.";
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

function renderFiles(files, adminLoggedIn) {
    const container = document.getElementById("files");
    if (!files.length) {
        container.innerHTML = '<div class="empty">Brak plików w katalogu docelowym.</div>';
        return;
    }

    container.innerHTML = files.map(file => {
        const relativePath = escapeHtml(file.relative_path || file.name || "");
        const displayPath = escapeHtml(file.display_path || file.relative_path || file.name || "");
        const storageKind = escapeHtml(file.storage_kind || "video");
        const ownerUsername = escapeHtml(file.owner_username || "");
        const ownerHtml = adminLoggedIn
            ? '<div class="small">Właściciel: ' + ownerUsername + '</div>'
            : "";
        const actionsHtml = '<div class="file-actions"><button type="button" class="btn btn-delete js-delete-file" data-file-name="' + relativePath + '" data-storage-kind="' + storageKind + '" data-owner-username="' + ownerUsername + '">Usuń plik</button></div>';

        return `
            <div class="file-item">
                <div><a class="file-link" href="${escapeHtml(file.url)}" target="_blank" rel="noopener">${displayPath}</a></div>
                <div class="small">Rozmiar: ${formatBytes(file.size)} | Zmiana: ${escapeHtml(file.mtime_text)}</div>
                ${ownerHtml}
                ${actionsHtml}
            </div>
        `;
    }).join("");
}

function renderMount(mount) {
    const box = document.getElementById("mountBox");
    const info = document.getElementById("downloadDirInfo");

    if (mount.online) {
        box.className = "mount-ok";
        box.textContent = "Udział sieciowy online: " + mount.message;
    } else {
        box.className = "mount-bad";
        box.textContent = "Udział sieciowy offline: " + mount.message;
    }

    if (mount.audio_download_dir && mount.audio_download_dir !== mount.download_dir) {
        info.textContent = "Katalogi docelowe: wideo " + (mount.download_dir || "-") + " | audio " + (mount.audio_download_dir || "-");
    } else {
        info.textContent = "Katalog docelowy: " + (mount.download_dir || "-");
    }
}

async function handleDownloadsClick(event) {
    const scopeSelect = event.target.closest("#filesScopeSelect");
    if (scopeSelect) {
        refreshData();
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
    }
}

async function refreshData() {
    try {
        const scopeSelect = document.getElementById("filesScopeSelect");
        const scopeValue = scopeSelect && scopeSelect.value ? scopeSelect.value : "";
        const query = scopeValue ? ("?user=" + encodeURIComponent(scopeValue)) : "";
        const response = await fetch("/api/files" + query);
        const data = await response.json();
        renderMount(data.mount);
        renderAdminHint(Boolean(data.admin_logged_in));
        renderScope(Boolean(data.admin_logged_in), data.available_users || [], data.scope_username || "", data.current_user || "");
        renderFiles(data.files || [], Boolean(data.admin_logged_in));
    } catch (err) {
        document.getElementById("files").innerHTML =
            '<div class="empty">Błąd odczytu plików: ' + escapeHtml(err) + '</div>';
    }
}

refreshData();
document.addEventListener("click", handleDownloadsClick);
document.addEventListener("change", handleDownloadsClick);

const downloadsRefreshTimer = setInterval(refreshData, 3000);

if (typeof window.registerPageCleanup === "function") {
    window.registerPageCleanup(function() {
        clearInterval(downloadsRefreshTimer);
        document.removeEventListener("click", handleDownloadsClick);
        document.removeEventListener("change", handleDownloadsClick);
    });
}
})();
