(function() {
    window.appUi = window.appUi || {};

    function hideFlashToast() {
        var toast = document.getElementById("uiToast");
        if (!toast) return;
        setTimeout(function() {
            toast.classList.add("is-leaving");
            setTimeout(function() {
                if (toast && toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 600);
        }, 5000);
    }

    function showUiToast(message, kind) {
        var host = document.querySelector(".toast-host");
        if (!host || !message) {
            return;
        }

        var toast = document.createElement("div");
        toast.className = "toast " + (kind === "error" ? "error" : "success");
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

    function toastEscapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function toastFormatBytes(bytes) {
        if (bytes === null || bytes === undefined) return "nieznany rozmiar";
        if (bytes === 0) return "0 B";
        var units = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        var num = Number(bytes);
        while (num >= 1024 && i < units.length - 1) {
            num /= 1024;
            i++;
        }
        return num.toFixed(i === 0 ? 0 : 2) + " " + units[i];
    }

    function toastFormatPercent(job) {
        if (job.progress_percent === null || job.progress_percent === undefined) {
            return job.status === "queued" ? "0%" : "--";
        }
        return Number(job.progress_percent).toFixed(1) + "%";
    }

    function toastFormatJobCount(count) {
        if (count === 1) return "1 plik";
        var mod10 = count % 10;
        var mod100 = count % 100;
        if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) {
            return count + " pliki";
        }
        return count + " plików";
    }

    function calculateAggregateProgress(activeJobs) {
        var downloadedSum = 0;
        var totalSum = 0;
        var hasKnownTotal = false;
        var knownProgressSum = 0;
        var knownProgressCount = 0;

        activeJobs.forEach(function(job) {
            var downloaded = Number(job.downloaded_bytes);
            if (!Number.isNaN(downloaded) && downloaded > 0) {
                downloadedSum += downloaded;
            }

            var total = Number(job.total_bytes);
            if (!Number.isNaN(total) && total > 0) {
                totalSum += total;
                hasKnownTotal = true;
            }

            if (job.progress_percent !== null && job.progress_percent !== undefined) {
                var percent = Number(job.progress_percent);
                if (!Number.isNaN(percent)) {
                    knownProgressSum += percent;
                    knownProgressCount += 1;
                }
            }
        });

        if (hasKnownTotal && totalSum > 0) {
            return {
                percent: Math.max(0, Math.min(100, (downloadedSum * 100) / totalSum)),
                downloadedSum: downloadedSum,
                totalSum: totalSum,
                hasKnownTotal: true,
            };
        }

        if (knownProgressCount > 0) {
            return {
                percent: Math.max(0, Math.min(100, knownProgressSum / knownProgressCount)),
                downloadedSum: downloadedSum,
                totalSum: totalSum,
                hasKnownTotal: false,
            };
        }

        return {
            percent: 0,
            downloadedSum: downloadedSum,
            totalSum: totalSum,
            hasKnownTotal: false,
        };
    }

    function renderDownloadToasts(jobs) {
        var host = document.getElementById("downloadToastStack");
        if (!host) return;

        var activeJobs = (jobs || []).filter(function(job) {
            return job && (job.status === "queued" || job.status === "downloading");
        });

        if (!activeJobs.length) {
            host.innerHTML = "";
            return;
        }

        if (activeJobs.length === 1) {
            var job = activeJobs[0];
            var width = 0;
            if (job.progress_percent !== null && job.progress_percent !== undefined) {
                width = Math.max(0, Math.min(100, Number(job.progress_percent) || 0));
            }

            var statusLabel = job.status_label || (job.status === "queued" ? "W kolejce" : "Pobieranie");
            var percentLabel = toastFormatPercent(job);
            var sizeLabel = toastFormatBytes(job.downloaded_bytes) + " / " + toastFormatBytes(job.total_bytes);

            host.innerHTML = `
                <div class="toast download-toast" role="status">
                    <div class="download-toast-header">
                        <div class="download-toast-title">${toastEscapeHtml(job.title || "Aktywne pobieranie")}</div>
                        <div class="download-toast-percent">${toastEscapeHtml(percentLabel)}</div>
                    </div>
                    <div class="download-toast-meta">${toastEscapeHtml(statusLabel)} • ${toastEscapeHtml(sizeLabel)}</div>
                    <div class="download-toast-progress">
                        <div class="download-toast-bar ${toastEscapeHtml(job.status || "")}" style="width:${width}%;"></div>
                    </div>
                </div>
            `;
            return;
        }

        var downloadingCount = activeJobs.filter(function(job) {
            return job.status === "downloading";
        }).length;
        var queuedCount = activeJobs.filter(function(job) {
            return job.status === "queued";
        }).length;
        var aggregate = calculateAggregateProgress(activeJobs);
        var percentLabel = Number(aggregate.percent || 0).toFixed(1) + "%";
        var metaParts = [toastFormatJobCount(activeJobs.length)];

        if (downloadingCount && queuedCount) {
            metaParts.push("Pobieranie: " + downloadingCount + ", kolejka: " + queuedCount);
        } else if (queuedCount && !downloadingCount) {
            metaParts.push("Oczekują w kolejce");
        } else {
            metaParts.push("Pobieranie w toku");
        }

        if (aggregate.hasKnownTotal) {
            metaParts.push(toastFormatBytes(aggregate.downloadedSum) + " / " + toastFormatBytes(aggregate.totalSum));
        } else if (aggregate.downloadedSum > 0) {
            metaParts.push("Pobrano " + toastFormatBytes(aggregate.downloadedSum));
        }

        host.innerHTML = `
            <div class="toast download-toast" role="status">
                <div class="download-toast-header">
                    <div class="download-toast-title">Aktywne pobierania</div>
                    <div class="download-toast-percent">${toastEscapeHtml(percentLabel)}</div>
                </div>
                <div class="download-toast-meta">${toastEscapeHtml(metaParts.join(" • "))}</div>
                <div class="download-toast-progress">
                    <div class="download-toast-bar ${queuedCount && !downloadingCount ? "queued" : "downloading"}" style="width:${Math.max(0, Math.min(100, aggregate.percent || 0))}%;"></div>
                </div>
            </div>
        `;
    }

    async function refreshDownloadToasts() {
        try {
            var response = await fetch("/api/jobs", {headers: {"Accept": "application/json"}});
            if (!response.ok) {
                return;
            }
            var data = await response.json();
            renderDownloadToasts(data.jobs || []);
        } catch (err) {
            // Toasty postępu są dodatkiem do UI, więc w razie błędu po prostu je pomijamy.
        }
    }

    window.appUi.showToast = showUiToast;
    window.appUi.hideFlashToast = hideFlashToast;
    window.appUi.refreshDownloadToasts = refreshDownloadToasts;

    hideFlashToast();
    refreshDownloadToasts();
    setInterval(refreshDownloadToasts, 2000);
})();

(function() {
    var appUi = window.appUi = window.appUi || {};

    if (!Array.isArray(appUi.pageCleanupFns)) {
        appUi.pageCleanupFns = [];
    }

    window.registerPageCleanup = function(callback) {
        if (typeof callback === "function") {
            appUi.pageCleanupFns.push(callback);
        }
    };

    function runPageCleanups() {
        var callbacks = appUi.pageCleanupFns.splice(0, appUi.pageCleanupFns.length);
        callbacks.forEach(function(callback) {
            try {
                callback();
            } catch (err) {
                // Sprzątanie starej strony nie powinno wysadzać nawigacji AJAX.
            }
        });
    }

    function syncFlashToast(nextDocument) {
        var host = document.querySelector(".toast-host");
        if (!host) {
            return;
        }

        var currentToast = document.getElementById("uiToast");
        if (currentToast && currentToast.parentNode) {
            currentToast.parentNode.removeChild(currentToast);
        }

        var nextToast = nextDocument.getElementById("uiToast");
        if (!nextToast) {
            return;
        }

        host.insertBefore(nextToast, host.firstChild);
        if (appUi.hideFlashToast) {
            appUi.hideFlashToast();
        }
    }

    function activateScripts(container) {
        Array.from(container.querySelectorAll("script")).forEach(function(oldScript) {
            var newScript = document.createElement("script");
            Array.from(oldScript.attributes).forEach(function(attribute) {
                newScript.setAttribute(attribute.name, attribute.value);
            });
            newScript.textContent = oldScript.textContent;
            oldScript.parentNode.replaceChild(newScript, oldScript);
        });
    }

    function updateHistory(url, mode) {
        if (!url || mode === "none") {
            return;
        }

        if (mode === "push") {
            window.history.pushState({}, "", url);
            return;
        }

        window.history.replaceState({}, "", url);
    }

    function replaceShellFromHtml(html, options) {
        var parser = new DOMParser();
        var nextDocument = parser.parseFromString(String(html || ""), "text/html");
        var nextShell = nextDocument.querySelector(".app-shell");
        var currentShell = document.querySelector(".app-shell");

        if (!nextShell || !currentShell) {
            throw new Error("Nie udało się odświeżyć widoku aplikacji.");
        }

        runPageCleanups();
        currentShell.innerHTML = nextShell.innerHTML;
        document.title = nextDocument.title || document.title;
        syncFlashToast(nextDocument);
        activateScripts(currentShell);
        updateHistory(options && options.url, (options && options.historyMode) || "replace");

        var restoreTop = options && options.scrollToTop;
        var scrollY = options && typeof options.scrollY === "number" ? options.scrollY : null;
        window.requestAnimationFrame(function() {
            if (restoreTop) {
                window.scrollTo({top: 0, behavior: "auto"});
            } else if (scrollY !== null) {
                window.scrollTo({top: scrollY, behavior: "auto"});
            }
        });
    }

    async function loadShell(url, requestOptions, transitionOptions) {
        var response = await fetch(url, Object.assign({
            headers: {
                "Accept": "text/html",
                "X-Requested-With": "fetch"
            }
        }, requestOptions || {}));

        var html = await response.text();
        if (!response.ok) {
            throw new Error(html || "Nie udało się wczytać widoku.");
        }

        replaceShellFromHtml(html, Object.assign({}, transitionOptions || {}, {
            url: response.url || url
        }));
    }

    function getShellFormSubmitter(event, form) {
        if (event && event.submitter instanceof HTMLElement) {
            return event.submitter;
        }

        return form.querySelector('button[type="submit"], button:not([type]), input[type="submit"]');
    }

    function setShellSubmitterBusy(submitter, busy) {
        if (!submitter) {
            return;
        }

        var isInput = submitter.tagName === "INPUT";
        var currentLabel = isInput ? submitter.value : submitter.textContent;
        if (!submitter.dataset.idleLabel) {
            submitter.dataset.idleLabel = String(currentLabel || "").trim();
        }

        submitter.disabled = !!busy;
        var nextLabel = busy ? "Trwa..." : (submitter.dataset.idleLabel || currentLabel);
        if (isInput) {
            submitter.value = nextLabel;
        } else {
            submitter.textContent = nextLabel;
        }
    }

    async function handleShellFormSubmit(form, event) {
        var method = String(form.getAttribute("method") || "GET").toUpperCase();
        var action = form.getAttribute("action") || window.location.href;
        var submitter = getShellFormSubmitter(event, form);
        var scrollY = window.scrollY;
        var requestUrl = action;
        var requestOptions = {method: method};

        if (method === "GET") {
            var query = new URLSearchParams(new FormData(form)).toString();
            requestUrl = query ? action + (action.indexOf("?") === -1 ? "?" : "&") + query : action;
        } else {
            requestOptions.body = new FormData(form);
        }

        setShellSubmitterBusy(submitter, true);

        try {
            await loadShell(requestUrl, requestOptions, {
                historyMode: "replace",
                scrollY: scrollY,
            });
        } catch (err) {
            setShellSubmitterBusy(submitter, false);
            HTMLFormElement.prototype.submit.call(form);
        }
    }

    async function handleShellNavigation(link) {
        var scrollY = window.scrollY;
        try {
            await loadShell(link.href, {method: "GET"}, {
                historyMode: "push",
                scrollToTop: true,
                scrollY: scrollY,
            });
        } catch (err) {
            window.location.href = link.href;
        }
    }

    document.addEventListener("click", function(event) {
        if (event.defaultPrevented || event.button !== 0) {
            return;
        }

        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
            return;
        }

        var link = event.target.closest('a[data-shell-nav="true"]');
        if (!link) {
            return;
        }

        event.preventDefault();
        handleShellNavigation(link);
    }, true);

    document.addEventListener("submit", function(event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        if (form.dataset.shellAsync !== "true") {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        handleShellFormSubmit(form, event);
    }, true);

    window.addEventListener("popstate", function() {
        loadShell(window.location.href, {method: "GET"}, {
            historyMode: "none",
            scrollToTop: true,
        }).catch(function() {
            window.location.reload();
        });
    });
})();
