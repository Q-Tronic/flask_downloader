(function() {
    var appUi = window.appUi = window.appUi || {};

    if (!Array.isArray(appUi.pageCleanupFns)) {
        appUi.pageCleanupFns = [];
    }

    if (typeof window.registerPageCleanup !== "function") {
        window.registerPageCleanup = function(callback) {
            if (typeof callback === "function") {
                appUi.pageCleanupFns.push(callback);
            }
        };
    }

    function createLiveSubscription(options) {
        var eventSource = null;
        var pollTimer = null;
        var reconnectTimer = null;
        var stopped = false;
        var fallbackIntervalMs = Math.max(750, Number((options && options.fallbackIntervalMs) || 2000) || 2000);
        var reconnectDelayMs = Math.max(1500, Number((options && options.reconnectDelayMs) || 3500) || 3500);

        function getUrl() {
            if (options && typeof options.buildUrl === "function") {
                return String(options.buildUrl() || "").trim();
            }
            return String((options && options.url) || "").trim();
        }

        function emitStatus(kind) {
            if (options && typeof options.onStatus === "function") {
                try {
                    options.onStatus(kind);
                } catch (err) {
                    // Status live jest dodatkiem i nie może psuć strony.
                }
            }
        }

        function handlePayload(payload, transport) {
            if (!(options && typeof options.onData === "function")) {
                return;
            }
            options.onData(payload, {
                transport: transport || "sse",
            });
        }

        function stopPolling() {
            if (pollTimer) {
                window.clearInterval(pollTimer);
                pollTimer = null;
            }
        }

        function closeEventSource() {
            if (eventSource) {
                try {
                    eventSource.close();
                } catch (err) {
                    // Zamknięcie EventSource nie powinno psuć sprzątania.
                }
                eventSource = null;
            }
        }

        function clearReconnectTimer() {
            if (reconnectTimer) {
                window.clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        }

        function scheduleReconnect() {
            if (stopped || reconnectTimer) {
                return;
            }
            reconnectTimer = window.setTimeout(function() {
                reconnectTimer = null;
                if (!stopped) {
                    connect();
                }
            }, reconnectDelayMs);
        }

        function runFallbackFetch() {
            if (!(options && typeof options.fetchFallback === "function")) {
                return Promise.resolve(null);
            }
            return Promise.resolve()
                .then(function() {
                    return options.fetchFallback();
                })
                .then(function(payload) {
                    if (options && options.applyFallbackPayload === true && payload !== undefined && payload !== null) {
                        handlePayload(payload, "poll");
                    }
                    return payload;
                })
                .catch(function(err) {
                    emitStatus("fallback-error");
                    return null;
                });
        }

        function startPolling(immediate) {
            if (pollTimer || !(options && typeof options.fetchFallback === "function")) {
                if (immediate) {
                    return runFallbackFetch();
                }
                return Promise.resolve(null);
            }
            if (immediate) {
                runFallbackFetch();
            }
            pollTimer = window.setInterval(function() {
                runFallbackFetch();
            }, fallbackIntervalMs);
            emitStatus("fallback");
            return Promise.resolve(null);
        }

        function openEventSource(url) {
            if (!("EventSource" in window) || !url) {
                return startPolling(true);
            }

            closeEventSource();
            clearReconnectTimer();
            emitStatus("connecting");

            try {
                eventSource = new window.EventSource(url);
            } catch (err) {
                eventSource = null;
                return startPolling(true);
            }

            eventSource.onopen = function() {
                stopPolling();
                clearReconnectTimer();
                emitStatus("open");
            };

            eventSource.onmessage = function(event) {
                stopPolling();
                clearReconnectTimer();
                if (!event || !event.data) {
                    return;
                }
                try {
                    handlePayload(JSON.parse(event.data), "sse");
                } catch (err) {
                    // Wadliwa pojedyncza wiadomość nie powinna zrywać całego streamu.
                }
            };

            eventSource.onerror = function() {
                emitStatus("error");
                startPolling(true);
                if (eventSource && eventSource.readyState === 2) {
                    closeEventSource();
                    scheduleReconnect();
                }
            };

            return Promise.resolve(null);
        }

        function connect() {
            if (stopped) {
                return Promise.resolve(null);
            }
            return openEventSource(getUrl());
        }

        return {
            start: function() {
                stopped = false;
                return connect();
            },
            restart: function() {
                stopped = false;
                closeEventSource();
                stopPolling();
                clearReconnectTimer();
                return connect();
            },
            refreshNow: function() {
                return runFallbackFetch();
            },
            stop: function() {
                stopped = true;
                clearReconnectTimer();
                stopPolling();
                closeEventSource();
                emitStatus("stopped");
            },
        };
    }

    window.appLive = window.appLive || {};
    window.appLive.createSubscription = createLiveSubscription;
})();
