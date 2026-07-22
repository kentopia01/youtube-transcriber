(function () {
    const query = new URLSearchParams(window.location.search).get('q');
    const input = document.getElementById('global-search-query');
    if (!query || !input) return;
    input.value = query;
    window.htmx.ajax('POST', '/api/global-search', {
        values: {query},
        target: '#global-search-results',
        swap: 'innerHTML'
    });
})();
