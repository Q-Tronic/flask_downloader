(function() {
const pageData = window.pageBootstrapData || {};
const quickUrlInput = document.getElementById("quickUrlInput");
const quickDlnaCollectionSelect = document.getElementById("quickDlnaCollectionSelect");

function showUiToastMessage(message, kind) {
    if (window.appUi && typeof window.appUi.showToast === "function") {
        window.appUi.showToast(message, kind);
        return;
    }
    if (kind === "error") {
        alert(message);
    }
}

function getQuickDlnaCollectionId() {
    if (!quickDlnaCollectionSelect || quickDlnaCollectionSelect.disabled) {
        return "";
    }
    return String(quickDlnaCollectionSelect.value || "").trim();
}

function setQuickButtonsBusy(busy, activeButton) {
    document.querySelectorAll(".js-quick-download-trigger").forEach(function(button) {
        const isActive = activeButton && button === activeButton;
        if (!button.dataset.idleLabel) {
            button.dataset.idleLabel = String(button.textContent || "").trim();
        }
        button.disabled = !!busy;
        if (isActive) {
            button.textContent = busy ? "Trwa..." : (button.dataset.idleLabel || button.textContent);
        } else if (!busy) {
            button.textContent = button.dataset.idleLabel || button.textContent;
        }
    });
}

async function runQuickDownload(mediaKind, triggerButton) {
    if (!quickUrlInput) {
        return;
    }

    const urlsText = String(quickUrlInput.value || "").trim();
    if (!urlsText) {
        showUiToastMessage("Wklej co najmniej jeden link do pobrania.", "error");
        quickUrlInput.focus();
        return;
    }

    setQuickButtonsBusy(true, triggerButton);

    try {
        const response = await fetch("/api/quick-downloads", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                urls_text: urlsText,
                media_kind: mediaKind,
                auto_dlna_collection_id: getQuickDlnaCollectionId(),
            })
        });

        const data = await response.json().catch(function() {
            return {};
        });

        if (!response.ok || !data.ok) {
            showUiToastMessage((data && data.error) || "Nie udało się dodać szybkich pobrań.", "error");
            return;
        }

        const queuedCount = Number(data.queued_count || 0);
        const failedCount = Number(data.failed_count || 0);
        const noun = mediaKind === "audio" ? "audio" : "wideo";
        let toastMessage = queuedCount === 1
            ? "Dodano 1 pobieranie " + noun + " do kolejki."
            : "Dodano " + queuedCount + " pobrań " + noun + " do kolejki.";

        if (failedCount > 0) {
            toastMessage += " " + failedCount + " link" + (failedCount === 1 ? "" : (failedCount >= 2 && failedCount <= 4 ? "i" : "ów")) + " pominięto.";
        }

        showUiToastMessage(toastMessage, "success");
        if (window.appUi && typeof window.appUi.refreshDownloadToasts === "function") {
            window.appUi.refreshDownloadToasts();
        }

        quickUrlInput.value = String(data.remaining_urls_text || "").trim();
        if (!quickUrlInput.value) {
            quickUrlInput.blur();
        }
    } catch (err) {
        showUiToastMessage("Błąd połączenia z serwerem: " + err, "error");
    } finally {
        setQuickButtonsBusy(false, triggerButton);
    }
}

function buildExistingDownloadNotice(existingDownloads) {
    if (!existingDownloads) {
        return "";
    }

    const sameQuality = Array.isArray(existingDownloads.same_quality) ? existingDownloads.same_quality : [];
    const otherQualities = Array.isArray(existingDownloads.other_qualities) ? existingDownloads.other_qualities : [];
    const sections = [];

    if (sameQuality.length) {
        const itemsHtml = sameQuality.map(item => `
            <div class="source-existing-item">
                <strong>${escapeSourceHtml(item.display_path || item.relative_path || item.filename || "")}</strong><br>
                Rozmiar: ${escapeSourceHtml(item.size_text || "-")} | Zmiana: ${escapeSourceHtml(item.mtime_text || "-")}
            </div>
        `).join("");

        sections.push(`
            <div class="source-warning-box">
                <div class="source-existing-title">Ta sama jakość jest już na serwerze (${sameQuality.length})</div>
                <div class="small">Przy próbie ponownego pobrania aplikacja zapyta, czy nadpisać istniejący plik. Stara kopia zostanie usunięta dopiero po poprawnym zapisaniu nowej.</div>
                <div class="source-existing-list">${itemsHtml}</div>
            </div>
        `);
    }

    if (otherQualities.length) {
        const itemsHtml = otherQualities.map(item => `
            <div class="source-existing-item">
                <strong>${escapeSourceHtml(item.display_path || item.relative_path || item.filename || "")}</strong><br>
                ${escapeSourceHtml(item.matched_label || "Inna jakość")} | Rozmiar: ${escapeSourceHtml(item.size_text || "-")} | Zmiana: ${escapeSourceHtml(item.mtime_text || "-")}
            </div>
        `).join("");

        sections.push(`
            <div class="source-info-box">
                <div class="source-existing-title">Na serwerze są też inne jakości tego materiału (${otherQualities.length})</div>
                <div class="source-existing-list">${itemsHtml}</div>
            </div>
        `);
    }

    if (!sections.length) {
        return "";
    }

    return '<div class="source-existing-wrap">' + sections.join("") + '</div>';
}

function buildOverwriteConfirmMessage(existingDownloads) {
    const sameCount = Number(existingDownloads && existingDownloads.same_quality_count || 0);
    if (!sameCount) {
        return "";
    }

    const plural = sameCount === 1 ? "plik" : (sameCount >= 2 && sameCount <= 4 ? "pliki" : "plików");
    return "Na serwerze istnieje już " + sameCount + " " + plural + " w tej samej jakości. Nadpisać tę jakość nowym pobraniem? Stare kopie zostaną usunięte dopiero po poprawnym ukończeniu nowego pobrania.";
}

function clearSourceContextToast() {
    const host = document.getElementById("sourceContextToastStack");
    if (host) {
        host.innerHTML = "";
    }
}

async function startServerDownload(pageUrl, formatId, overwriteExisting) {
    try {
        const response = await fetch("/enqueue-download", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                page_url: pageUrl,
                format_id: formatId,
                overwrite_existing: Boolean(overwriteExisting),
                auto_dlna_collection_id: getQuickDlnaCollectionId(),
            })
        });

        const data = await response.json();

        if (response.status === 409 && data.requires_confirmation) {
            const confirmMessage = buildOverwriteConfirmMessage(data.existing_downloads);
            if (confirmMessage && confirm(confirmMessage)) {
                return startServerDownload(pageUrl, formatId, true);
            }
            return;
        }

        if (!response.ok || !data.ok) {
            showUiToastMessage(data.error || "Nie udało się dodać pobierania.", "error");
            return;
        }

        showUiToastMessage("Dodano pobieranie do kolejki. Status możesz śledzić w zadaniach bez odświeżania strony.", "success");
        if (window.appUi && typeof window.appUi.refreshDownloadToasts === "function") {
            window.appUi.refreshDownloadToasts();
        }
    } catch (err) {
        showUiToastMessage("Błąd połączenia z serwerem: " + err, "error");
    }
}

if (pageData.hasResult) {
const sourceCatalog = (pageData.result && pageData.result.sources) || [];
const sourcePageUrl = (pageData.result && pageData.result.page_url) || "";
const sourceExtractor = (pageData.result && pageData.result.extractor) || "";
const sourceDetailCache = {};

function escapeSourceHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function collectSourceFormats() {
    const seen = new Set();
    return sourceCatalog.filter(item => {
        const mediaKind = String(item.media_kind || "video").toLowerCase();
        const ext = String(item.ext || "unknown").toLowerCase();
        const key = mediaKind + ":" + ext;
        if (seen.has(key)) {
            return false;
        }
        seen.add(key);
        return true;
    }).map(item => ({
        value: String(item.media_kind || "video").toLowerCase() + ":" + String(item.ext || "unknown").toLowerCase(),
        label: (String(item.media_kind || "video").toLowerCase() === "audio" ? "Audio" : "Wideo") + " • " + String(item.ext || "unknown").toUpperCase()
    }));
}

function getSourceFormatKey(item) {
    return String(item.media_kind || "video").toLowerCase() + ":" + String(item.ext || "unknown").toLowerCase();
}

function getSourceBitrate(item) {
    const numericValue = Number(item && item.bitrate_kbps);
    if (!Number.isNaN(numericValue) && numericValue > 0) {
        return numericValue;
    }

    const label = String(item && item.label || "");
    const match = label.match(/(\d+(?:\.\d+)?)k\b/i);
    if (!match) {
        return 0;
    }

    const parsed = Number(match[1]);
    return Number.isNaN(parsed) ? 0 : parsed;
}

function getSourceQualityRank(item) {
    const height = Number(item && item.height || 0);
    const width = Number(item && item.width || 0);
    const bitrate = getSourceBitrate(item);
    const hasAudio = item && item.has_audio ? 1 : 0;
    return [height, width, bitrate, hasAudio];
}

function getSourceContainerPreference(item) {
    const ext = String(item && item.ext || "").toLowerCase();
    if (ext === "mp4") {
        return 3;
    }
    if (ext === "mkv") {
        return 2;
    }
    if (ext === "webm") {
        return 1;
    }
    return 0;
}

function compareRankDescending(left, right) {
    for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
        const leftValue = Number(left[index] || 0);
        const rightValue = Number(right[index] || 0);
        if (leftValue > rightValue) {
            return -1;
        }
        if (leftValue < rightValue) {
            return 1;
        }
    }
    return 0;
}

function isYoutubeExtractor() {
    return String(sourceExtractor || "").trim().toLowerCase().includes("youtube");
}

function chooseBestSource(items) {
    const candidates = Array.isArray(items) ? items.slice() : [];
    if (!candidates.length) {
        return null;
    }

    candidates.sort(function(left, right) {
        const leftMediaKind = String(left.media_kind || "video").toLowerCase();
        const rightMediaKind = String(right.media_kind || "video").toLowerCase();
        const leftIsVideo = leftMediaKind === "video" ? 1 : 0;
        const rightIsVideo = rightMediaKind === "video" ? 1 : 0;

        if (leftIsVideo !== rightIsVideo) {
            return rightIsVideo - leftIsVideo;
        }

        const qualityDiff = compareRankDescending(getSourceQualityRank(left), getSourceQualityRank(right));
        if (qualityDiff !== 0) {
            return qualityDiff;
        }

        const leftContainer = getSourceContainerPreference(left);
        const rightContainer = getSourceContainerPreference(right);
        if (leftContainer !== rightContainer) {
            return rightContainer - leftContainer;
        }

        if (isYoutubeExtractor()) {
            const leftHasAudio = left && left.has_audio ? 1 : 0;
            const rightHasAudio = right && right.has_audio ? 1 : 0;
            if (leftHasAudio !== rightHasAudio) {
                return rightHasAudio - leftHasAudio;
            }
        }

        return String(left.format_id || "").localeCompare(String(right.format_id || ""));
    });

    return candidates[0];
}

function buildSizeOptionLabel(item, duplicateCountMap) {
    const baseLabel = item.label || item.format_id || "Źródło";
    const duplicates = duplicateCountMap[baseLabel] || 0;
    if (duplicates > 1 && item.protocol) {
        return baseLabel + " • " + item.protocol;
    }
    return baseLabel;
}

function renderFormatOptions(selectedFormat) {
    const select = document.getElementById("sourceFormatSelect");
    const formats = collectSourceFormats();
    select.innerHTML = formats.map(item => {
        const isSelected = item.value === selectedFormat ? " selected" : "";
        return '<option value="' + escapeSourceHtml(item.value) + '"' + isSelected + '>' + escapeSourceHtml(item.label) + '</option>';
    }).join("");
}

function renderSizeOptions(selectedFormat, preferredFormatId) {
    const select = document.getElementById("sourceSizeSelect");
    const items = sourceCatalog.filter(item => {
        return getSourceFormatKey(item) === selectedFormat;
    });
    const duplicateCountMap = {};

    items.forEach(item => {
        const key = item.label || item.format_id || "Źródło";
        duplicateCountMap[key] = (duplicateCountMap[key] || 0) + 1;
    });

    if (!items.length) {
        select.innerHTML = "";
        return null;
    }

    const bestItem = chooseBestSource(items) || items[items.length - 1];
    const activeFormatId = preferredFormatId && items.some(item => String(item.format_id) === String(preferredFormatId))
        ? String(preferredFormatId)
        : String((bestItem && bestItem.format_id) || items[items.length - 1].format_id);

    select.innerHTML = items.map(item => {
        const isSelected = String(item.format_id) === activeFormatId ? " selected" : "";
        return '<option value="' + escapeSourceHtml(item.format_id) + '"' + isSelected + '>' + escapeSourceHtml(buildSizeOptionLabel(item, duplicateCountMap)) + '</option>';
    }).join("");

    return activeFormatId;
}

function renderSourceDetail(item) {
    const panel = document.getElementById("sourceDetailPanel");
    const badges = [];

    if (item.media_kind) badges.push('<span class="badge">' + escapeSourceHtml(String(item.media_kind).toLowerCase() === "audio" ? "audio" : "wideo") + '</span>');
    if (item.label) badges.push('<span class="badge">' + escapeSourceHtml(item.label) + '</span>');
    if (item.ext) badges.push('<span class="badge">' + escapeSourceHtml(item.ext) + '</span>');
    if (item.protocol) badges.push('<span class="badge">' + escapeSourceHtml(item.protocol) + '</span>');

    panel.innerHTML = `
        <div class="source-detail-card">
            <div class="source-detail-head">
                <div>
                    <div class="source-detail-title">Szczegóły wybranego źródła</div>
                    <div class="source-badges">${badges.join("")}</div>
                </div>
            </div>

            <div class="source-detail-grid">
                <div>
                    <div class="small muted">Lokalny URL do VLC</div>
                    <pre>${escapeSourceHtml(item.proxy_url || "")}</pre>
                </div>

                <div>
                    <div class="small muted">Komenda VLC</div>
                    <pre>${escapeSourceHtml(item.vlc_command || "")}</pre>
                </div>

                <div>
                    <div class="small muted">Format ID</div>
                    <pre>${escapeSourceHtml(item.format_id || "")}</pre>
                </div>

                <div>
                    <div class="small muted">URL z yt-dlp</div>
                    <pre>${escapeSourceHtml(item.url || "")}</pre>
                </div>

                <div>
                    <div class="small muted">Link do pobrania przez aplikację</div>
                    <pre>${escapeSourceHtml(item.download_url || "")}</pre>
                </div>
            </div>

            <div class="actions">
                <a class="btn" href="${escapeSourceHtml(item.proxy_url || "#")}" target="_blank" rel="noopener">Otwórz przez proxy</a>
                <a class="btn btn-secondary" href="/single-playlist?page_url=${encodeURIComponent(sourcePageUrl)}&format_id=${encodeURIComponent(item.format_id || "")}" target="_blank">M3U tylko dla tej jakości</a>
                <a class="btn btn-download" href="${escapeSourceHtml(item.download_url || "#")}" rel="noopener">Pobierz do przeglądarki</a>
                <button type="button" class="btn btn-server js-source-server-download" data-page-url="${escapeSourceHtml(sourcePageUrl)}" data-format-id="${escapeSourceHtml(item.format_id || "")}">
                    Pobierz na serwer
                </button>
            </div>
        </div>
    `;
}

function buildSourceContextSections(item) {
    const sections = [];
    const existingDownloads = item && item.existing_downloads ? item.existing_downloads : null;
    const sameQuality = existingDownloads && Array.isArray(existingDownloads.same_quality) ? existingDownloads.same_quality : [];
    const otherQualities = existingDownloads && Array.isArray(existingDownloads.other_qualities) ? existingDownloads.other_qualities : [];

    if (sameQuality.length) {
        sections.push({
            tone: "warning",
            title: "Ta sama jakość jest już na serwerze (" + sameQuality.length + ")",
            lines: sameQuality.slice(0, 2).map(function(entry) {
                return (entry.relative_path || entry.filename || "Plik") + " | " + (entry.size_text || "-") + " | " + (entry.mtime_text || "-");
            }).concat([
                "Przy próbie pobrania aplikacja zapyta, czy nadpisać istniejący plik."
            ]),
        });
    }

    if (otherQualities.length) {
        const detailLines = otherQualities.slice(0, 3).map(function(entry) {
            const label = entry.matched_label || "Inna jakość";
            return label + " | " + (entry.size_text || "-") + " | " + (entry.mtime_text || "-");
        });
        sections.push({
            tone: "info",
            title: "Na serwerze są też inne jakości tego materiału (" + otherQualities.length + ")",
            lines: detailLines,
        });
    }

    if (String(item.media_kind || "video").toLowerCase() === "video" && !item.has_audio) {
        sections.push({
            tone: "info",
            title: "Wybrane źródło ma osobne audio",
            lines: [
                "Pobranie do przeglądarki lub proxy może nie zawierać dźwięku.",
                "Przycisk Pobierz na serwer połączy wideo z audio przez yt-dlp.",
            ],
        });
    }

    if (String(item.media_kind || "video").toLowerCase() === "audio") {
        sections.push({
            tone: "info",
            title: "Audio na serwerze zapisze się jako MP3",
            lines: [
                "Na serwerze ten strumień zostanie przekonwertowany przez ffmpeg do MP3 VBR q=0.",
                "Pobierz do przeglądarki dalej zwraca surowy plik źródłowy, np. m4a albo webm.",
            ],
        });
    }

    return sections;
}

function renderSourceContextToast(item) {
    const host = document.getElementById("sourceContextToastStack");
    if (!host) {
        return;
    }

    const sections = buildSourceContextSections(item || {});
    if (!sections.length) {
        host.innerHTML = "";
        return;
    }

    const sectionsHtml = sections.map(function(section) {
        const lines = Array.isArray(section.lines) ? section.lines : [];
        return `
            <div class="source-context-section ${escapeSourceHtml(section.tone || "info")}">
                <div class="source-context-section-title">${escapeSourceHtml(section.title || "")}</div>
                <div class="source-context-lines">${lines.map(function(line) {
                    return '<div>' + escapeSourceHtml(line) + '</div>';
                }).join("")}</div>
            </div>
        `;
    }).join("");

    host.innerHTML = `
        <div class="toast source-context-toast" role="status">
            <div class="source-context-toast-head">
                <div class="source-context-toast-title">Uwagi do wybranego źródła</div>
                <div class="source-context-toast-note">${escapeSourceHtml(item.label || item.format_id || "")}</div>
            </div>
            <div class="source-context-sections">${sectionsHtml}</div>
        </div>
    `;
}

function beginSourceDetailRefresh(panel, loadingText) {
    if (!panel) {
        return;
    }

    const currentHeight = Math.ceil(panel.getBoundingClientRect().height || 0);
    if (currentHeight > 0) {
        panel.style.minHeight = currentHeight + "px";
    }

    panel.classList.add("is-loading");
    panel.setAttribute("aria-busy", "true");

    let loadingNode = panel.querySelector(".source-detail-loading");
    if (!loadingNode) {
        loadingNode = document.createElement("div");
        loadingNode.className = "source-detail-loading";
        panel.appendChild(loadingNode);
    }

    loadingNode.textContent = String(loadingText || "Pobieranie szczegółów źródła...");
}

function finishSourceDetailRefresh(panel, anchorNode, preservedAnchorTop) {
    if (!panel) {
        return;
    }

    panel.classList.remove("is-loading");
    panel.removeAttribute("aria-busy");

    const loadingNode = panel.querySelector(".source-detail-loading");
    if (loadingNode && loadingNode.parentNode) {
        loadingNode.parentNode.removeChild(loadingNode);
    }

    window.requestAnimationFrame(function() {
        if (anchorNode && typeof preservedAnchorTop === "number") {
            const delta = anchorNode.getBoundingClientRect().top - preservedAnchorTop;
            if (Math.abs(delta) >= 1) {
                window.scrollBy({top: delta, behavior: "auto"});
            }
        }

        window.requestAnimationFrame(function() {
            panel.style.minHeight = "";
        });
    });
}

async function loadSourceDetail(formatId) {
    const panel = document.getElementById("sourceDetailPanel");
    const anchorNode = document.getElementById("sourceFormatSelect") || panel;
    const preservedAnchorTop = anchorNode ? anchorNode.getBoundingClientRect().top : null;

    if (!formatId) {
        panel.innerHTML = '<div class="source-detail-empty">Brak wybranego źródła.</div>';
        renderSourceContextToast(null);
        finishSourceDetailRefresh(panel, anchorNode, preservedAnchorTop);
        return;
    }

    if (sourceDetailCache[formatId]) {
        renderSourceDetail(sourceDetailCache[formatId]);
        renderSourceContextToast(sourceDetailCache[formatId]);
        finishSourceDetailRefresh(panel, anchorNode, preservedAnchorTop);
        return;
    }

    if (!panel.children.length) {
        panel.innerHTML = '<div class="source-detail-empty">Pobieranie szczegółów źródła...</div>';
    }
    beginSourceDetailRefresh(panel, "Pobieranie szczegółów źródła...");

    try {
        const response = await fetch("/api/source-detail?page_url=" + encodeURIComponent(sourcePageUrl) + "&format_id=" + encodeURIComponent(formatId));
        const data = await response.json();

        if (!response.ok || !data.ok) {
            panel.innerHTML = '<div class="source-detail-empty">Nie udało się pobrać szczegółów źródła: ' + escapeSourceHtml(data.error || "nieznany błąd") + '</div>';
            renderSourceContextToast(null);
            finishSourceDetailRefresh(panel, anchorNode, preservedAnchorTop);
            return;
        }

        sourceDetailCache[formatId] = data.item;
        renderSourceDetail(data.item);
        renderSourceContextToast(data.item);
        finishSourceDetailRefresh(panel, anchorNode, preservedAnchorTop);
    } catch (err) {
        panel.innerHTML = '<div class="source-detail-empty">Błąd ładowania szczegółów źródła: ' + escapeSourceHtml(err) + '</div>';
        renderSourceContextToast(null);
        finishSourceDetailRefresh(panel, anchorNode, preservedAnchorTop);
    }
}

function initializeSourcePicker() {
    if (!sourceCatalog.length) {
        document.getElementById("sourceDetailPanel").innerHTML =
            '<div class="source-detail-empty">Brak źródeł do wyświetlenia.</div>';
        return;
    }

    const defaultSource = chooseBestSource(sourceCatalog) || sourceCatalog[0];
    const defaultFormat = getSourceFormatKey(defaultSource);
    const defaultFormatId = String(defaultSource.format_id || "");

    renderFormatOptions(defaultFormat);
    const activeFormatId = renderSizeOptions(defaultFormat, defaultFormatId);
    loadSourceDetail(activeFormatId);

    const formatSelect = document.getElementById("sourceFormatSelect");
    const sizeSelect = document.getElementById("sourceSizeSelect");

    function handleFormatChange(event) {
        const chosenFormat = String(event.target.value || "").toLowerCase();
        const nextFormatId = renderSizeOptions(chosenFormat, null);
        loadSourceDetail(nextFormatId);
    }

    function handleSizeChange(event) {
        loadSourceDetail(String(event.target.value || ""));
    }

    formatSelect.addEventListener("change", handleFormatChange);
    sizeSelect.addEventListener("change", handleSizeChange);

    if (typeof window.registerPageCleanup === "function") {
        window.registerPageCleanup(function() {
            formatSelect.removeEventListener("change", handleFormatChange);
            sizeSelect.removeEventListener("change", handleSizeChange);
        });
    }
}

function handleSourceServerDownloadClick(event) {
    const serverButton = event.target.closest(".js-source-server-download");
    if (!serverButton) {
        return;
    }

    event.preventDefault();
    startServerDownload(serverButton.dataset.pageUrl || "", serverButton.dataset.formatId || "", false);
}

function handleQuickDownloadClick(event) {
    const quickButton = event.target.closest(".js-quick-download-trigger");
    if (!quickButton) {
        return;
    }

    event.preventDefault();
    runQuickDownload(quickButton.dataset.mediaKind || "video", quickButton);
}

    initializeSourcePicker();
}

document.addEventListener("click", handleSourceServerDownloadClick);
document.addEventListener("click", handleQuickDownloadClick);

if (typeof window.registerPageCleanup === "function") {
    window.registerPageCleanup(function() {
        clearSourceContextToast();
        document.removeEventListener("click", handleSourceServerDownloadClick);
        document.removeEventListener("click", handleQuickDownloadClick);
    });
}

if (!pageData.hasResult) {
    clearSourceContextToast();
}
})();
