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

function formatPercent(job) {
    if (job.progress_percent === null || job.progress_percent === undefined) {
        return "brak danych";
    }
    return job.progress_percent.toFixed(1) + "%";
}

async function deleteJob(jobId) {
    if (!confirm("Usunąć to zadanie z listy?")) {
        return;
    }

    try {
        const response = await fetch("/api/jobs/" + encodeURIComponent(jobId) + "/delete", {
            method: "POST"
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            alert(data.error || "Nie udało się usunąć zadania.");
            return;
        }

        refreshData();
    } catch (err) {
        alert("Błąd usuwania zadania: " + err);
    }
}

async function cancelJob(jobId) {
    if (!confirm("Przerwać aktywne pobieranie i usunąć niedokończony plik?")) {
        return;
    }

    try {
        const response = await fetch("/api/jobs/" + encodeURIComponent(jobId) + "/cancel", {
            method: "POST"
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            alert(data.error || "Nie udało się przerwać pobierania.");
            return;
        }

        refreshData();
    } catch (err) {
        alert("Błąd przerywania pobierania: " + err);
    }
}

function renderScope(adminLoggedIn, availableUsers, scopeUsername, currentUser) {
    const wrap = document.getElementById("jobsScopeWrap");
    const select = document.getElementById("jobsScopeSelect");
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

function renderJobs(jobs, adminLoggedIn) {
    const container = document.getElementById("jobs");
    if (!jobs.length) {
        container.innerHTML = '<div class="empty">Brak zadań pobierania.</div>';
        return;
    }

    container.innerHTML = jobs.map(job => {
        const status = escapeHtml(job.status);
        const width = job.progress_percent === null || job.progress_percent === undefined
            ? (job.status === "completed" ? 100 : 0)
            : Math.max(0, Math.min(100, job.progress_percent));

        const errorHtml = job.error
            ? '<div class="row"><div class="label">Szczegóły</div><div class="value">' + escapeHtml(job.error) + '</div></div>'
            : '';

        const fileHtml = job.file_url
            ? '<div class="row"><div class="label">Plik</div><div class="value"><a class="file-link" href="' + escapeHtml(job.file_url) + '" target="_blank" rel="noopener">' + escapeHtml(job.file_display_name || job.relative_path || job.filename || "") + '</a></div></div>'
            : '';
        const ownerHtml = adminLoggedIn
            ? '<div class="row"><div class="label">Właściciel</div><div class="value">' + escapeHtml(job.owner_username || "-") + '</div></div>'
            : '';

        let actionButtons = "";

        if (job.can_cancel) {
            actionButtons += '<button type="button" class="btn btn-stop js-cancel-job" data-job-id="' + escapeHtml(job.job_id) + '">Przerwij pobieranie</button>';
        }

        if (job.can_delete_from_list) {
            actionButtons += '<button type="button" class="btn btn-delete js-delete-job" data-job-id="' + escapeHtml(job.job_id) + '">Usuń z listy</button>';
        }

        const actionsHtml = actionButtons ? '<div class="job-actions">' + actionButtons + '</div>' : "";

        return `
            <div class="job ${status}">
                <div class="row">
                    <div class="label">Status</div>
                    <div class="value"><span class="status ${status}">${escapeHtml(job.status_label)}</span></div>
                </div>
                <div class="row">
                    <div class="label">Tytuł</div>
                    <div class="value">${escapeHtml(job.title || "-")}</div>
                </div>
                <div class="row">
                    <div class="label">Format</div>
                    <div class="value">${escapeHtml(job.label || job.format_id || "-")}</div>
                </div>
                <div class="row">
                    <div class="label">Postęp</div>
                    <div class="value">
                        ${formatPercent(job)} - ${formatBytes(job.downloaded_bytes)} / ${formatBytes(job.total_bytes)}
                        <div class="progress">
                            <div class="progress-bar ${status}" style="width:${width}%;"></div>
                        </div>
                    </div>
                </div>
                <div class="row">
                    <div class="label">Źródło</div>
                    <div class="value">${escapeHtml(job.page_url || "-")}</div>
                </div>
                ${ownerHtml}
                ${fileHtml}
                ${errorHtml}
                <div class="small">ID: ${escapeHtml(job.job_id)}</div>
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

async function handleJobsClick(event) {
    const scopeSelect = event.target.closest("#jobsScopeSelect");
    if (scopeSelect) {
        refreshData();
        return;
    }

    const cancelBtn = event.target.closest(".js-cancel-job");
    if (cancelBtn) {
        event.preventDefault();
        const jobId = cancelBtn.dataset.jobId || "";
        if (jobId) {
            await cancelJob(jobId);
        }
        return;
    }

    const deleteJobBtn = event.target.closest(".js-delete-job");
    if (deleteJobBtn) {
        event.preventDefault();
        const jobId = deleteJobBtn.dataset.jobId || "";
        if (jobId) {
            await deleteJob(jobId);
        }
    }
}

async function refreshData() {
    try {
        const scopeSelect = document.getElementById("jobsScopeSelect");
        const scopeValue = scopeSelect && scopeSelect.value ? scopeSelect.value : "";
        const query = scopeValue ? ("?user=" + encodeURIComponent(scopeValue)) : "";
        const response = await fetch("/api/jobs" + query);
        const data = await response.json();
        renderMount(data.mount);
        renderScope(Boolean(data.admin_logged_in), data.available_users || [], data.scope_username || "", data.current_user || "");
        renderJobs(data.jobs || [], Boolean(data.admin_logged_in));
    } catch (err) {
        document.getElementById("jobs").innerHTML =
            '<div class="empty">Błąd odczytu statusów: ' + escapeHtml(err) + '</div>';
    }
}

refreshData();
document.addEventListener("click", handleJobsClick);
document.addEventListener("change", handleJobsClick);

const jobsRefreshTimer = setInterval(refreshData, 2000);

if (typeof window.registerPageCleanup === "function") {
    window.registerPageCleanup(function() {
        clearInterval(jobsRefreshTimer);
        document.removeEventListener("click", handleJobsClick);
        document.removeEventListener("change", handleJobsClick);
    });
}
})();
