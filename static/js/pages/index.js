(function() {
const pageData = window.pageBootstrapData || {};
const quickUrlInput = document.getElementById("quickUrlInput");
const quickDlnaCollectionSelect = document.getElementById("quickDlnaCollectionSelect");
const indexDynamicBrowserHost = document.getElementById("indexDynamicBrowserHost");
let collectionBrowserState = null;

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

function extractUrlCandidatesFromText(rawText) {
    const text = String(rawText || "").replaceAll("\r\n", "\n").replaceAll("\r", "\n");
    const matches = text.match(/https?:\/\/[^\s<>"']+/gi) || [];
    const seen = new Set();
    const results = [];

    matches.forEach(function(match) {
        const candidate = String(match || "").trim().replace(/[),.;]+$/g, "");
        if (!candidate) {
            return;
        }
        const dedupeKey = candidate.toLowerCase();
        if (seen.has(dedupeKey)) {
            return;
        }
        seen.add(dedupeKey);
        results.push(candidate);
    });

    return results;
}

function isPotentialTvpCollectionUrl(url) {
    const text = String(url || "").trim().toLowerCase();
    if (!text.includes("vod.tvp.pl")) {
        return false;
    }
    return !/,s\d+e\d+,/.test(text);
}

function escapeCollectionHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatCollectionCount(count, nounOne, nounFew, nounMany) {
    const numericCount = Number(count || 0);
    if (numericCount === 1) {
        return "1 " + nounOne;
    }
    const mod10 = numericCount % 10;
    const mod100 = numericCount % 100;
    if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) {
        return numericCount + " " + nounFew;
    }
    return numericCount + " " + nounMany;
}

function normalizeCollectionPayload(collection) {
    const payload = collection && typeof collection === "object" ? collection : {};
    const seasons = Array.isArray(payload.seasons) ? payload.seasons.slice() : [];
    const episodes = Array.isArray(payload.episodes) ? payload.episodes.slice() : [];
    return {
        title: String(payload.title || ""),
        page_url: String(payload.page_url || ""),
        extractor: String(payload.extractor || ""),
        seasons: seasons,
        episodes: episodes,
        episode_count: Number(payload.episode_count || episodes.length || 0),
        season_count: Number(payload.season_count || seasons.length || 0),
        default_season_value: String(payload.default_season_value || (seasons[0] && seasons[0].value) || ""),
        has_multiple_seasons: Boolean(payload.has_multiple_seasons || seasons.length > 1),
        default_media_kind: String(payload.default_media_kind || "video").toLowerCase() === "audio" ? "audio" : "video",
    };
}

function getCollectionBrowserPanel() {
    return document.getElementById("collectionBrowserPanel");
}

function buildDynamicCollectionShell(collection) {
    return `
        <section class="page-card">
            <h2 class="section-title">Wykryta kolekcja odcinków</h2>
            <div class="info-grid">
                <div class="info-label">Tytuł</div>
                <div class="info-value">${escapeCollectionHtml(collection.title || "")}</div>

                <div class="info-label">Adres strony</div>
                <div class="info-value">
                    <a class="link" href="${escapeCollectionHtml(collection.page_url || "#")}" target="_blank" rel="noopener">${escapeCollectionHtml(collection.page_url || "")}</a>
                </div>

                <div class="info-label">Extractor</div>
                <div class="info-value">${escapeCollectionHtml(collection.extractor || "")}</div>

                <div class="info-label">Sezony</div>
                <div class="info-value">${escapeCollectionHtml(String(collection.season_count || 0))}</div>

                <div class="info-label">Odcinki</div>
                <div class="info-value">${escapeCollectionHtml(String(collection.episode_count || 0))}</div>
            </div>
        </section>

        <section class="page-card">
            <h2 class="section-title">Sezony i odcinki</h2>
            <div id="collectionBrowserPanel" class="collection-browser-panel"></div>
        </section>
    `;
}

function getVisibleCollectionEpisodes() {
    if (!collectionBrowserState) {
        return [];
    }
    return collectionBrowserState.collection.episodes.filter(function(item) {
        return String(item.season_value || "") === String(collectionBrowserState.activeSeasonValue || "");
    });
}

function getSelectedCollectionEpisodeIds() {
    if (!collectionBrowserState) {
        return [];
    }
    return Array.from(collectionBrowserState.selectedEpisodeIds || []);
}

function renderCollectionBrowser(options) {
    const panel = getCollectionBrowserPanel();
    if (!panel || !collectionBrowserState) {
        return;
    }

    const renderOptions = options && typeof options === "object" ? options : {};
    const previousList = panel.querySelector(".collection-episode-list");
    const preservedScrollTop = previousList ? previousList.scrollTop : 0;
    const collection = collectionBrowserState.collection;
    const visibleEpisodes = getVisibleCollectionEpisodes();
    const selectedIds = collectionBrowserState.selectedEpisodeIds;
    const selectedVisibleCount = visibleEpisodes.filter(function(item) {
        return selectedIds.has(String(item.id || ""));
    }).length;
    const selectedTotalCount = getSelectedCollectionEpisodeIds().length;
    const mediaKind = collectionBrowserState.mediaKind || "video";

    const seasonControlHtml = collection.has_multiple_seasons ? `
        <div class="stack-card">
            <label class="field-label" for="collectionSeasonSelect">Sezon</label>
            <select id="collectionSeasonSelect">
                ${collection.seasons.map(function(season) {
                    const isSelected = String(season.value || "") === String(collectionBrowserState.activeSeasonValue || "") ? " selected" : "";
                    const seasonCountText = formatCollectionCount(season.count, "odcinek", "odcinki", "odcinków");
                    return `<option value="${escapeCollectionHtml(season.value || "")}"${isSelected}>${escapeCollectionHtml(season.label || "")} (${escapeCollectionHtml(seasonCountText)})</option>`;
                }).join("")}
            </select>
        </div>
    ` : `
        <div class="stack-card">
            <label class="field-label">Sezon</label>
            <div class="collection-static-value">${escapeCollectionHtml((collection.seasons[0] && collection.seasons[0].label) || "Jeden sezon")}</div>
        </div>
    `;

    panel.innerHTML = `
        <div class="collection-browser-shell">
            <div class="collection-browser-toolbar">
                ${seasonControlHtml}
                <div class="stack-card">
                    <label class="field-label">Tryb pobierania</label>
                    <div class="collection-media-toggle">
                        <button type="button" class="btn ${mediaKind === "video" ? "btn-green" : "btn-secondary"}" data-collection-media-kind="video">Wideo BEST</button>
                        <button type="button" class="btn ${mediaKind === "audio" ? "btn-download" : "btn-secondary"}" data-collection-media-kind="audio">Audio BEST</button>
                    </div>
                </div>
            </div>

            <div class="collection-browser-summary">
                <div>Zaznaczono ${escapeCollectionHtml(String(selectedVisibleCount))} z ${escapeCollectionHtml(String(visibleEpisodes.length))} widocznych oraz ${escapeCollectionHtml(String(selectedTotalCount))} łącznie.</div>
                <div>Wybrane odcinki zostaną dodane do kolejki i pobiorą się po kolei bez pełnego odświeżania strony.</div>
            </div>

            <div class="actions collection-browser-actions">
                <button type="button" class="btn btn-secondary" data-collection-select-visible="true">Zaznacz widoczne</button>
                <button type="button" class="btn btn-secondary" data-collection-clear-visible="true">Wyczyść widoczne</button>
                <button type="button" class="btn btn-secondary" data-collection-clear-all="true">Wyczyść wszystko</button>
                <button type="button" class="btn btn-server" data-collection-queue="true" ${selectedTotalCount ? "" : "disabled"}>Dodaj zaznaczone do kolejki</button>
            </div>

            <div class="collection-episode-list" role="list">
                ${visibleEpisodes.map(function(item) {
                    const itemId = String(item.id || "");
                    const checked = selectedIds.has(itemId) ? " checked" : "";
                    return `
                        <label class="collection-episode-row" role="listitem">
                            <input type="checkbox" data-collection-episode-id="${escapeCollectionHtml(itemId)}"${checked}>
                            <span class="collection-episode-main">
                                ${item.episode_code ? `<span class="badge">${escapeCollectionHtml(item.episode_code)}</span>` : ""}
                                <span class="collection-episode-title">${escapeCollectionHtml(item.title || item.display_title || "Odcinek")}</span>
                            </span>
                        </label>
                    `;
                }).join("") || '<div class="source-detail-empty">Brak odcinków w wybranym sezonie.</div>'}
            </div>
        </div>
    `;

    const nextList = panel.querySelector(".collection-episode-list");
    if (nextList && !renderOptions.resetScroll) {
        nextList.scrollTop = preservedScrollTop;
    }
}

function openCollectionBrowser(collection, defaultMediaKind, options) {
    const normalizedCollection = normalizeCollectionPayload(collection);
    const dynamicMode = Boolean(options && options.dynamic);
    const mediaKind = String(defaultMediaKind || normalizedCollection.default_media_kind || "video").toLowerCase() === "audio" ? "audio" : "video";

    if (dynamicMode && indexDynamicBrowserHost) {
        indexDynamicBrowserHost.innerHTML = buildDynamicCollectionShell(normalizedCollection);
    }

    collectionBrowserState = {
        collection: normalizedCollection,
        mediaKind: mediaKind,
        activeSeasonValue: String(normalizedCollection.default_season_value || (normalizedCollection.seasons[0] && normalizedCollection.seasons[0].value) || ""),
        selectedEpisodeIds: new Set(),
        dynamic: dynamicMode,
    };

    clearSourceContextToast();
    renderCollectionBrowser();

    const panel = getCollectionBrowserPanel();
    if (panel) {
        panel.scrollIntoView({behavior: "smooth", block: "start"});
    }
}

async function inspectSingleUrlForCollection(url) {
    const response = await fetch("/api/source-browser?page_url=" + encodeURIComponent(url), {
        headers: {"Accept": "application/json"},
    });
    const data = await response.json().catch(function() {
        return {};
    });
    if (!response.ok || !data.ok) {
        throw new Error((data && data.error) || "Nie udało się odczytać listy odcinków.");
    }
    return data;
}

async function queueCollectionEpisodes() {
    if (!collectionBrowserState) {
        return;
    }

    const selectedIds = getSelectedCollectionEpisodeIds();
    if (!selectedIds.length) {
        showUiToastMessage("Zaznacz co najmniej jeden odcinek do pobrania.", "error");
        return;
    }

    const selectedEpisodes = collectionBrowserState.collection.episodes.filter(function(item) {
        return collectionBrowserState.selectedEpisodeIds.has(String(item.id || ""));
    }).sort(function(left, right) {
        return Number(left.order_index || 0) - Number(right.order_index || 0);
    });

    const queueButton = document.querySelector("[data-collection-queue='true']");
    if (queueButton) {
        queueButton.disabled = true;
        queueButton.dataset.idleLabel = queueButton.dataset.idleLabel || String(queueButton.textContent || "").trim();
        queueButton.textContent = "Trwa...";
    }

    try {
        const response = await fetch("/api/collection-downloads", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                media_kind: collectionBrowserState.mediaKind || "video",
                auto_dlna_collection_id: getQuickDlnaCollectionId(),
                episodes: selectedEpisodes.map(function(item) {
                    return {
                        id: item.id,
                        page_url: item.page_url,
                        title: item.title,
                        display_title: item.display_title,
                        queue_title: item.queue_title,
                        series: item.series,
                        episode_code: item.episode_code,
                        season_number: item.season_number,
                        episode_number: item.episode_number,
                    };
                }),
            }),
        });

        const data = await response.json().catch(function() {
            return {};
        });

        if (!response.ok || !data.ok) {
            showUiToastMessage((data && data.error) || "Nie udało się dodać odcinków do kolejki.", "error");
            return;
        }

        selectedEpisodes.forEach(function(item) {
            collectionBrowserState.selectedEpisodeIds.delete(String(item.id || ""));
        });
        renderCollectionBrowser();

        const queuedCount = Number(data.queued_count || 0);
        const failedCount = Number(data.failed_count || 0);
        let message = queuedCount === 1
            ? "Dodano 1 odcinek do kolejki."
            : "Dodano " + queuedCount + " odcinków do kolejki.";
        if (failedCount > 0) {
            message += " " + failedCount + " pozycji pominięto.";
        }
        showUiToastMessage(message, "success");
        if (window.appUi && typeof window.appUi.refreshDownloadToasts === "function") {
            window.appUi.refreshDownloadToasts();
        }
    } catch (err) {
        showUiToastMessage("Błąd połączenia z serwerem: " + err, "error");
    } finally {
        if (queueButton) {
            queueButton.disabled = false;
            queueButton.textContent = queueButton.dataset.idleLabel || "Dodaj zaznaczone do kolejki";
        }
    }
}

async function runQuickDownload(mediaKind, triggerButton) {
    if (!quickUrlInput) {
        return;
    }

    const urlsText = String(quickUrlInput.value || "").trim();
    const parsedUrls = extractUrlCandidatesFromText(urlsText);
    if (!urlsText) {
        showUiToastMessage("Wklej co najmniej jeden link do pobrania.", "error");
        quickUrlInput.focus();
        return;
    }

    setQuickButtonsBusy(true, triggerButton);

    try {
        if (parsedUrls.length === 1 && isPotentialTvpCollectionUrl(parsedUrls[0])) {
            const browserData = await inspectSingleUrlForCollection(parsedUrls[0]);
            if (browserData && browserData.kind === "collection") {
                openCollectionBrowser(browserData.collection || {}, mediaKind, {dynamic: true});
                showUiToastMessage("Wykryto kolekcję TVP VOD. Wybierz sezon i zaznacz odcinki do pobrania.", "success");
                return;
            }
        }

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

        if (data && data.selection_required && data.kind === "collection") {
            openCollectionBrowser(data.collection || {}, mediaKind, {dynamic: true});
            showUiToastMessage("Wykryto kolekcję TVP VOD. Wybierz sezon i zaznacz odcinki do pobrania.", "success");
            return;
        }

        if (!response.ok || !data.ok) {
            showUiToastMessage((data && data.error) || "Nie udało się dodać szybkich pobrań.", "error");
            return;
        }

        const queuedCount = Number(data.queued_count || 0);
        const liveQueuedCount = Number(data.live_queued_count || 0);
        const failedCount = Number(data.failed_count || 0);
        const noun = mediaKind === "audio" ? "audio" : "wideo";
        let toastMessage = queuedCount === 1
            ? "Dodano 1 pobieranie " + noun + " do kolejki."
            : "Dodano " + queuedCount + " pobrań " + noun + " do kolejki.";

        if (liveQueuedCount > 0) {
            const liveNoun = liveQueuedCount === 1 ? "1 nagranie LIVE" : (liveQueuedCount >= 2 && liveQueuedCount <= 4 ? liveQueuedCount + " nagrania LIVE" : liveQueuedCount + " nagrań LIVE");
            toastMessage += " W tym " + liveNoun + " od początku streama.";
        }

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

async function startServerDownload(pageUrl, formatId, overwriteExisting, customFilename) {
    try {
        const response = await fetch("/enqueue-download", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                page_url: pageUrl,
                format_id: formatId,
                custom_filename: String(customFilename || "").trim(),
                overwrite_existing: Boolean(overwriteExisting),
                auto_dlna_collection_id: getQuickDlnaCollectionId(),
            })
        });

        const data = await response.json();

        if (response.status === 409 && data.requires_confirmation) {
            const confirmMessage = buildOverwriteConfirmMessage(data.existing_downloads);
            if (confirmMessage && confirm(confirmMessage)) {
                return startServerDownload(pageUrl, formatId, true, customFilename);
            }
            return;
        }

        if (!response.ok || !data.ok) {
            showUiToastMessage(data.error || "Nie udało się dodać pobierania.", "error");
            return;
        }

        const successMessage = data.is_live_capture
            ? "Uruchomiono nagrywanie LIVE od początku streama. To zadanie nie liczy się do limitu kolejki."
            : "Dodano pobieranie do kolejki. Status możesz śledzić w zadaniach bez odświeżania strony.";
        showUiToastMessage(successMessage, "success");
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
        const key = mediaKind;
        if (seen.has(key)) {
            return false;
        }
        seen.add(key);
        return true;
    }).map(item => ({
        value: String(item.media_kind || "video").toLowerCase(),
        label: String(item.media_kind || "video").toLowerCase() === "audio" ? "Audio" : "Wideo"
    }));
}

function getSourceFormatKey(item) {
    return String(item.media_kind || "video").toLowerCase();
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

    if (!items.length) {
        select.innerHTML = "";
        return null;
    }

    const groups = [];
    const groupMap = new Map();

    items.forEach(function(item) {
        const mediaKind = String(item.media_kind || "video").toLowerCase();
        const label = mediaKind === "audio"
            ? "Najlepsze audio"
            : String(item.label || item.format_id || "Źródło");
        const key = mediaKind === "audio" ? "audio-best" : label;
        if (!groupMap.has(key)) {
            const group = {key, label, items: []};
            groupMap.set(key, group);
            groups.push(group);
        }
        groupMap.get(key).items.push(item);
    });

    const options = groups.map(function(group) {
        return {
            key: group.key,
            label: group.label,
            items: group.items,
            representative: chooseBestSource(group.items) || group.items[group.items.length - 1],
        };
    }).filter(function(option) {
        return Boolean(option.representative);
    });

    const matchingPreferred = preferredFormatId
        ? options.find(function(option) {
            return option.items.some(function(item) {
                return String(item.format_id) === String(preferredFormatId);
            });
        })
        : null;
    const fallbackOption = options[0];
    const activeOption = matchingPreferred || fallbackOption;
    const activeFormatId = String((activeOption && activeOption.representative && activeOption.representative.format_id) || "");

    select.innerHTML = options.map(function(option) {
        const representative = option.representative;
        const optionValue = String((representative && representative.format_id) || "");
        const isSelected = optionValue === activeFormatId ? " selected" : "";
        return '<option value="' + escapeSourceHtml(optionValue) + '"' + isSelected + '>' + escapeSourceHtml(option.label) + '</option>';
    }).join("");

    return activeFormatId;
}

function renderSourceDetail(item) {
    const panel = document.getElementById("sourceDetailPanel");
    const badges = [];
    const isLiveCapture = Boolean(item && item.is_live_stream && item.supports_live_from_start);
    const serverActionLabel = isLiveCapture ? "Nagrywaj live od początku" : "Pobierz na serwer";

    if (item.media_kind) badges.push('<span class="badge">' + escapeSourceHtml(String(item.media_kind).toLowerCase() === "audio" ? "audio" : "wideo") + '</span>');
    if (item.label) badges.push('<span class="badge">' + escapeSourceHtml(item.label) + '</span>');
    if (item.ext) badges.push('<span class="badge">' + escapeSourceHtml(item.ext) + '</span>');
    if (item.protocol) badges.push('<span class="badge">' + escapeSourceHtml(item.protocol) + '</span>');
    if (isLiveCapture) badges.push('<span class="badge">LIVE od początku</span>');

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

            <div class="source-detail-rename">
                <label class="field-label" for="sourceCustomFilenameInput">Nazwa pliku na serwerze</label>
                <input
                    id="sourceCustomFilenameInput"
                    class="text-input"
                    type="text"
                    value="${escapeSourceHtml(item.target_filename || "")}"
                    placeholder="${escapeSourceHtml(item.target_filename || "")}"
                    maxlength="120"
                    autocomplete="off"
                    spellcheck="false"
                />
                <div class="small muted">Możesz wpisać własną nazwę bez rozszerzenia albo z nim. Serwer i tak zapisze poprawne rozszerzenie i oczyści nazwę pod Windows.</div>
            </div>

            <div class="actions">
                <a class="btn" href="${escapeSourceHtml(item.proxy_url || "#")}" target="_blank" rel="noopener">Otwórz przez proxy</a>
                <a class="btn btn-secondary" href="/single-playlist?page_url=${encodeURIComponent(sourcePageUrl)}&format_id=${encodeURIComponent(item.format_id || "")}" target="_blank">M3U tylko dla tej jakości</a>
                <a class="btn btn-download" href="${escapeSourceHtml(item.download_url || "#")}" rel="noopener">Pobierz do przeglądarki</a>
                <button type="button" class="btn btn-server js-source-server-download" data-page-url="${escapeSourceHtml(sourcePageUrl)}" data-format-id="${escapeSourceHtml(item.format_id || "")}">
                    ${escapeSourceHtml(serverActionLabel)}
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
            title: "Serwer automatycznie dobierze dźwięk",
            lines: [
                "Podgląd proxy lub pobranie do przeglądarki może nie zawierać dźwięku.",
                "Przycisk Pobierz na serwer automatycznie dobierze audio do tej jakości i zapisze gotowy plik z dźwiękiem.",
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

    if (item && item.is_live_stream && item.supports_live_from_start) {
        sections.push({
            tone: "info",
            title: "Aktywna transmisja LIVE",
            lines: [
                "Pobranie na serwer rozpocznie zapis od początku streama i będzie nagrywać aż do zakończenia transmisji.",
                "Takie zadanie nie liczy się do limitu równoległych pobrań użytkownika.",
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

initializeSourcePicker();
}

if (pageData.hasCollection && pageData.collection) {
    openCollectionBrowser(pageData.collection, (pageData.collection && pageData.collection.default_media_kind) || "video", {dynamic: false});
}

function handleCollectionBrowserClick(event) {
    const toggleButton = event.target.closest("[data-collection-media-kind]");
    if (toggleButton && collectionBrowserState) {
        event.preventDefault();
        collectionBrowserState.mediaKind = String(toggleButton.getAttribute("data-collection-media-kind") || "video").toLowerCase() === "audio" ? "audio" : "video";
        renderCollectionBrowser();
        return;
    }

    const selectVisibleButton = event.target.closest("[data-collection-select-visible='true']");
    if (selectVisibleButton && collectionBrowserState) {
        event.preventDefault();
        getVisibleCollectionEpisodes().forEach(function(item) {
            collectionBrowserState.selectedEpisodeIds.add(String(item.id || ""));
        });
        renderCollectionBrowser();
        return;
    }

    const clearVisibleButton = event.target.closest("[data-collection-clear-visible='true']");
    if (clearVisibleButton && collectionBrowserState) {
        event.preventDefault();
        getVisibleCollectionEpisodes().forEach(function(item) {
            collectionBrowserState.selectedEpisodeIds.delete(String(item.id || ""));
        });
        renderCollectionBrowser({resetScroll: true});
        return;
    }

    const clearAllButton = event.target.closest("[data-collection-clear-all='true']");
    if (clearAllButton && collectionBrowserState) {
        event.preventDefault();
        collectionBrowserState.selectedEpisodeIds.clear();
        renderCollectionBrowser();
        return;
    }

    const queueButton = event.target.closest("[data-collection-queue='true']");
    if (queueButton && collectionBrowserState) {
        event.preventDefault();
        queueCollectionEpisodes();
    }
}

function handleCollectionBrowserChange(event) {
    const seasonSelect = event.target.closest("#collectionSeasonSelect");
    if (seasonSelect && collectionBrowserState) {
        collectionBrowserState.activeSeasonValue = String(seasonSelect.value || "");
        renderCollectionBrowser({resetScroll: true});
        return;
    }

    const episodeCheckbox = event.target.closest("[data-collection-episode-id]");
    if (episodeCheckbox && collectionBrowserState) {
        const episodeId = String(episodeCheckbox.getAttribute("data-collection-episode-id") || "");
        if (!episodeId) {
            return;
        }
        if (episodeCheckbox.checked) {
            collectionBrowserState.selectedEpisodeIds.add(episodeId);
        } else {
            collectionBrowserState.selectedEpisodeIds.delete(episodeId);
        }
        renderCollectionBrowser();
    }
}

function handleSourceServerDownloadClick(event) {
    const serverButton = event.target.closest(".js-source-server-download");
    if (!serverButton) {
        return;
    }

    event.preventDefault();
    const filenameInput = document.getElementById("sourceCustomFilenameInput");
    const customFilename = filenameInput ? String(filenameInput.value || "").trim() : "";
    startServerDownload(serverButton.dataset.pageUrl || "", serverButton.dataset.formatId || "", false, customFilename);
}

function handleQuickDownloadClick(event) {
    const quickButton = event.target.closest(".js-quick-download-trigger");
    if (!quickButton) {
        return;
    }

    event.preventDefault();
    runQuickDownload(quickButton.dataset.mediaKind || "video", quickButton);
}

document.addEventListener("click", handleSourceServerDownloadClick);
document.addEventListener("click", handleQuickDownloadClick);
document.addEventListener("click", handleCollectionBrowserClick);
document.addEventListener("change", handleCollectionBrowserChange);

if (typeof window.registerPageCleanup === "function") {
    window.registerPageCleanup(function() {
        clearSourceContextToast();
        document.removeEventListener("click", handleSourceServerDownloadClick);
        document.removeEventListener("click", handleQuickDownloadClick);
        document.removeEventListener("click", handleCollectionBrowserClick);
        document.removeEventListener("change", handleCollectionBrowserChange);
        collectionBrowserState = null;
    });
}

if (!pageData.hasResult) {
    clearSourceContextToast();
}
})();
