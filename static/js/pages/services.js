(function() {
    const filterInput = document.getElementById("serviceFilterInput");
    const grid = document.getElementById("servicesGrid");
    const emptyState = document.getElementById("servicesEmptyState");

    if (!filterInput || !grid || !emptyState) {
        return;
    }

    function applyServiceFilter() {
        const query = String(filterInput.value || "").trim().toLowerCase();
        const items = Array.from(grid.querySelectorAll(".service-pill"));
        let visibleCount = 0;

        items.forEach(function(item) {
            const name = String(item.dataset.serviceName || "");
            const visible = !query || name.includes(query);
            item.style.display = visible ? "" : "none";
            if (visible) {
                visibleCount += 1;
            }
        });

        emptyState.style.display = visibleCount ? "none" : "";
    }

    filterInput.addEventListener("input", applyServiceFilter);
})();
