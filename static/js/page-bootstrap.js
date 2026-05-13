window.appUi = window.appUi || {};
if (!Array.isArray(window.appUi.pageCleanupFns)) {
    window.appUi.pageCleanupFns = [];
}
window.registerPageCleanup = window.registerPageCleanup || function(callback) {
    if (typeof callback === "function") {
        window.appUi.pageCleanupFns.push(callback);
    }
};

window.pageBootstrapData = window.pageBootstrapData || {};
