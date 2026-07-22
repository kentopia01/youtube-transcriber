(function () {
    window.htmxChatToggled = function (event) {
        if (!event.detail.successful) return;
        const button = document.getElementById('chat-toggle-btn');
        const label = document.getElementById('chat-toggle-label');
        if (!button || !label) return;
        const isNowEnabled = button.classList.contains('toggle-off');
        button.classList.toggle('toggle-on', isNowEnabled);
        button.classList.toggle('toggle-off', !isNowEnabled);
        button.setAttribute('hx-vals', JSON.stringify({enabled: !isNowEnabled}));
        button.setAttribute('aria-pressed', isNowEnabled ? 'true' : 'false');
        label.textContent = isNowEnabled ? 'Enabled' : 'Disabled';
        label.className = isNowEnabled ? 'text-sm text-accent' : 'text-sm text-faint';
        window.htmx?.process(button);
    };
})();
