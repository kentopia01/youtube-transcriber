(function () {
    window.toggleWorkspaceNav = function (button, navId) {
        const nav = document.getElementById(navId);
        if (!nav) return;
        const isOpen = nav.classList.toggle('is-open');
        button.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        button.setAttribute('aria-label', isOpen ? 'Close workspace navigation' : 'Open workspace navigation');
    };
})();
