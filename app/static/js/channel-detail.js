(function () {
    window.triggerPersona = async function (channelId, button) {
        if (!button) return;
        const original = button.innerHTML;
        button.disabled = true;
        button.innerHTML = 'Queuing…';
        try {
            const response = await fetch('/api/channels/' + encodeURIComponent(channelId) + '/generate-persona', {method: 'POST'});
            if (response.ok) {
                button.innerHTML = 'Queued — persona will refresh shortly';
                window.setTimeout(() => window.location.reload(), 4000);
                return;
            }
            const body = await response.json().catch(() => ({detail: 'Failed to enqueue.'}));
            button.innerHTML = original;
            button.disabled = false;
            window.alert(body.detail || 'Failed to enqueue persona generation.');
        } catch (error) {
            button.innerHTML = original;
            button.disabled = false;
            window.alert('Network error: ' + error);
        }
    };
})();
