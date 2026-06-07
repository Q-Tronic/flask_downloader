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
    if (job && job.processing_stage) {
        return "przetwarzanie";
    }
    if (job.progress_percent === null || job.progress_percent === undefined) {
        if (job && job.status === "paused") {
            return "wstrzymane";
        }
        return "brak danych";
    }
    return job.progress_percent.toFixed(1) + "%";
}

function formatProgressLine(job) {
    if (job && job.processing_stage) {
        const stageLabel = String(job.status_label || "Przetwarzanie pliku").toLowerCase();
        const sizeBits = [];
        if (job.downloaded_bytes !== null && job.downloaded_bytes !== undefined) {
            sizeBits.push(formatBytes(job.downloaded_bytes));
        }
        if (job.total_bytes !== null && job.total_bytes !== undefined && job.total_bytes !== job.downloaded_bytes) {
            sizeBits.push(formatBytes(job.total_bytes));
        }
        const sizeText = sizeBits.length ? " (" + sizeBits.join(" / ") + ")" : "";
        return "Pobieranie zakończone - trwa " + stageLabel + sizeText;
    }
    return formatPercent(job) + " - " + formatBytes(job.downloaded_bytes) + " / " + formatBytes(job.total_bytes);
}

let liveSubscription = null;
let latestJobsPayload = null;

function showToast(message, kind) {
    if (window.appUi && typeof window.appUi.showToast === "function") {
        window.appUi.showToast(message, kind);
        return;
    }
    if (kind === "error") {
        alert(message);
    }
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

async function pauseJob(jobId) {
    if (!confirm("Wstrzymać to pobieranie i zachować dane do późniejszego wznowienia?")) {
        return;
    }

    try {
        const response = await fetch("/api/jobs/" + encodeURIComponent(jobId) + "/pause", {
            method: "POST"
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            showToast(data.error || "Nie udało się wstrzymać pobierania.", "error");
            return;
        }

        showToast(data.message || "Wstrzymano pobieranie.", "success");
        refreshData();
    } catch (err) {
        showToast("Błąd wstrzymywania pobierania: " + err, "error");
    }
}

async function resumeJob(jobId) {
    try {
        const response = await fetch("/api/jobs/" + encodeURIComponent(jobId) + "/resume", {
            method: "POST"
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            showToast(data.error || "Nie udało się wznowić pobierania.", "error");
            return;
        }

        showToast(data.message || "Wznowiono pobieranie.", "success");
        refreshData();
    } catch (err) {
        showToast("Błąd wznawiania pobierania: " + err, "error");
    }
}

async function retryJob(jobId, failureHint) {
    try {
        const response = await fetch("/api/jobs/" + encodeURIComponent(jobId) + "/retry", {
            method: "POST"
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            showToast(data.error || "Nie udało się ponowić zadania.", "error");
            return;
        }

        const successMessage = failureHint
            ? (data.message || "Ponowiono zadanie.") + " " + failureHint
            : (data.message || "Ponowiono zadanie.");
        showToast(successMessage.trim(), "success");
        refreshData();
    } catch (err) {
        showToast("Błąd ponawiania zadania: " + err, "error");
    }
}

async function cancelJob(jobId, jobStatus) {
    const confirmMessage = String(jobStatus || "") === "paused"
        ? "Anulować to wstrzymane pobieranie i usunąć jego dane tymczasowe?"
        : "Przerwać aktywne pobieranie i usunąć niedokończony plik?";
    if (!confirm(confirmMessage)) {
        return;
    }

    try {
        const response = await fetch("/api/jobs/" + encodeURIComponent(jobId) + "/cancel", {
            method: "POST"
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            showToast(data.error || "Nie udało się przerwać pobierania.", "error");
            return;
        }

        showToast(data.message || "Wysłano żądanie anulowania.", "success");
        refreshData();
    } catch (err) {
        showToast("Błąd przerywania pobierania: " + err, "error");
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

function getJobsTypeFilterValue() {
    const select = document.getElementById("jobsTypeFilterSelect");
    return select && select.value ? String(select.value) : "all";
}

function renderJobsTypeFilter(jobs) {
    const select = document.getElementById("jobsTypeFilterSelect");
    if (!select) {
        return;
    }

    const currentValue = getJobsTypeFilterValue();
    const allCount = (jobs || []).length;
    const liveCount = (jobs || []).filter(function(job) {
        return !!job && !!job.is_live_capture;
    }).length;
    const pausedCount = (jobs || []).filter(function(job) {
        return String((job || {}).status || "") === "paused";
    }).length;
    const standardCount = (jobs || []).filter(function(job) {
        return !!job && !job.is_live_capture;
    }).length;

    const optionLabels = {
        all: "Wszystkie zadania (" + allCount + ")",
        live: "Tylko LIVE (" + liveCount + ")",
        paused: "Tylko wstrzymane (" + pausedCount + ")",
        standard: "Tylko zwykłe (" + standardCount + ")",
    };

    Array.from(select.options || []).forEach(function(option) {
        const key = String(option.value || "");
        if (Object.prototype.hasOwnProperty.call(optionLabels, key)) {
            option.textContent = optionLabels[key];
        }
    });

    select.value = currentValue || "all";
}

function renderJobs(jobs, adminLoggedIn) {
    const container = document.getElementById("jobs");
    const activeFilter = getJobsTypeFilterValue();
    const filteredJobs = (jobs || []).filter(function(job) {
        if (activeFilter === "live") {
            return !!job.is_live_capture;
        }
        if (activeFilter === "paused") {
            return String(job.status || "") === "paused";
        }
        if (activeFilter === "standard") {
            return !job.is_live_capture;
        }
        return true;
    });

    if (!filteredJobs.length) {
        container.innerHTML = '<div class="empty">Brak zadań pobierania.</div>';
        return;
    }

    container.innerHTML = filteredJobs.map(job => {
        const isProcessing = !!String(job.processing_stage || "").trim();
        const status = escapeHtml(job.status);
        const statusClass = isProcessing ? "downloading processing" : status;
        const liveBadge = job.is_live_capture
            ? '<span class="badge" style="margin-left:8px;">LIVE</span>'
            : "";
        const pausedBadge = String(job.status || "") === "paused"
            ? '<span class="badge" style="margin-left:8px;">PAUSED</span>'
            : "";
        const width = isProcessing
            ? 38
            : job.progress_percent === null || job.progress_percent === undefined
            ? (job.status === "completed" ? 100 : 0)
            : Math.max(0, Math.min(100, job.progress_percent));
        const progressWrapClass = isProcessing ? "progress is-indeterminate" : "progress";

        const errorHtml = job.error
            ? '<div class="row"><div class="label">Szczegóły</div><div class="value">' + escapeHtml(job.error) + '</div></div>'
            : '';
        const hintHtml = job.failure_hint
            ? '<div class="small" style="margin-top:6px;">' + escapeHtml(job.failure_hint) + '</div>'
            : "";

        const fileHtml = job.file_url
            ? '<div class="row"><div class="label">Plik</div><div class="value"><a class="file-link" href="' + escapeHtml(job.file_url) + '" target="_blank" rel="noopener">' + escapeHtml(job.file_display_name || job.relative_path || job.filename || "") + '</a></div></div>'
            : '';
        const ownerHtml = adminLoggedIn
            ? '<div class="row"><div class="label">Właściciel</div><div class="value">' + escapeHtml(job.owner_username || "-") + '</div></div>'
            : '';

        let actionButtons = "";

        if (job.can_pause) {
            actionButtons += '<button type="button" class="btn btn-secondary js-pause-job" data-job-id="' + escapeHtml(job.job_id) + '">Pauza</button>';
        }

        if (job.can_resume) {
            actionButtons += '<button type="button" class="btn btn-secondary js-resume-job" data-job-id="' + escapeHtml(job.job_id) + '">Wznów</button>';
        }

        if (job.can_retry) {
            actionButtons += '<button type="button" class="btn btn-secondary js-retry-job" data-job-id="' + escapeHtml(job.job_id) + '" data-job-failure-hint="' + escapeHtml(job.failure_hint || "") + '">Pobierz ponownie</button>';
        }

        if (job.can_cancel) {
            actionButtons += '<button type="button" class="btn btn-stop js-cancel-job" data-job-id="' + escapeHtml(job.job_id) + '" data-job-status="' + escapeHtml(job.status) + '">' + (job.status === "paused" ? "Anuluj i usuń" : "Przerwij pobieranie") + '</button>';
        }

        if (job.can_delete_from_list) {
            actionButtons += '<button type="button" class="btn btn-delete js-delete-job" data-job-id="' + escapeHtml(job.job_id) + '">Usuń z listy</button>';
        }

        const actionsHtml = actionButtons ? '<div class="job-actions">' + actionButtons + '</div>' : "";

        return `
            <div class="job ${status}">
                <div class="row">
                    <div class="label">Status</div>
                    <div class="value"><span class="status ${statusClass}">${escapeHtml(job.status_label)}</span>${liveBadge}${pausedBadge}</div>
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
                        ${escapeHtml(formatProgressLine(job))}
                        <div class="${progressWrapClass}">
                            <div class="progress-bar ${statusClass}" style="width:${width}%;"></div>
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
                ${hintHtml}
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

function applyJobsPayload(data) {
    latestJobsPayload = data || null;
    renderMount(data.mount);
    renderScope(Boolean(data.admin_logged_in), data.available_users || [], data.scope_username || "", data.current_user || "");
    renderJobsTypeFilter(data.jobs || []);
    renderJobs(data.jobs || [], Boolean(data.admin_logged_in));
}

async function handleJobsClick(event) {
    const scopeSelect = event.target.closest("#jobsScopeSelect");
    if (scopeSelect) {
        if (liveSubscription && typeof liveSubscription.restart === "function") {
            liveSubscription.restart();
        } else {
            refreshData();
        }
        return;
    }

    const typeSelect = event.target.closest("#jobsTypeFilterSelect");
    if (typeSelect) {
        if (latestJobsPayload) {
            applyJobsPayload(latestJobsPayload);
        }
        return;
    }

    const pauseBtn = event.target.closest(".js-pause-job");
    if (pauseBtn) {
        event.preventDefault();
        const jobId = pauseBtn.dataset.jobId || "";
        if (jobId) {
            await pauseJob(jobId);
        }
        return;
    }

    const resumeBtn = event.target.closest(".js-resume-job");
    if (resumeBtn) {
        event.preventDefault();
        const jobId = resumeBtn.dataset.jobId || "";
        if (jobId) {
            await resumeJob(jobId);
        }
        return;
    }

    const cancelBtn = event.target.closest(".js-cancel-job");
    if (cancelBtn) {
        event.preventDefault();
        const jobId = cancelBtn.dataset.jobId || "";
        if (jobId) {
            await cancelJob(jobId, cancelBtn.dataset.jobStatus || "");
        }
        return;
    }

    const retryBtn = event.target.closest(".js-retry-job");
    if (retryBtn) {
        event.preventDefault();
        const jobId = retryBtn.dataset.jobId || "";
        if (jobId) {
            await retryJob(jobId, retryBtn.dataset.jobFailureHint || "");
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
        applyJobsPayload(data);
        return data;
    } catch (err) {
        document.getElementById("jobs").innerHTML =
            '<div class="empty">Błąd odczytu statusów: ' + escapeHtml(err) + '</div>';
        return null;
    }
}

function buildStreamUrl() {
    const scopeSelect = document.getElementById("jobsScopeSelect");
    const scopeValue = scopeSelect && scopeSelect.value ? scopeSelect.value : "";
    return "/api/jobs/stream" + (scopeValue ? ("?user=" + encodeURIComponent(scopeValue)) : "");
}

document.addEventListener("click", handleJobsClick);
document.addEventListener("change", handleJobsClick);

if (window.appLive && typeof window.appLive.createSubscription === "function") {
    liveSubscription = window.appLive.createSubscription({
        buildUrl: buildStreamUrl,
        fallbackIntervalMs: 2000,
        fetchFallback: refreshData,
        onData: applyJobsPayload,
    });
    liveSubscription.start();
} else {
    refreshData();
    liveSubscription = {
        stop: function() {
            clearInterval(jobsRefreshTimer);
        },
    };
    var jobsRefreshTimer = setInterval(refreshData, 2000);
}

if (typeof window.registerPageCleanup === "function") {
    window.registerPageCleanup(function() {
        if (liveSubscription && typeof liveSubscription.stop === "function") {
            liveSubscription.stop();
        }
        document.removeEventListener("click", handleJobsClick);
        document.removeEventListener("change", handleJobsClick);
    });
}
})();
