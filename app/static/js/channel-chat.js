(function () {
    const chat = document.getElementById('channel-persona-chat');
    if (!chat) return;
    const channelId = chat.dataset.channelId;
    const personaName = chat.dataset.personaName;
    let sessionId = null;

    function appendMessage(role, text, sources) {
        const log = document.getElementById('chat-log');
        const wrapper = document.createElement('div');
        wrapper.style.display = 'flex';
        wrapper.style.flexDirection = 'column';
        wrapper.style.gap = '0.25rem';
        const label = document.createElement('span');
        label.className = 'text-xs text-muted';
        label.textContent = role === 'user' ? 'You' : personaName;
        wrapper.appendChild(label);
        const body = document.createElement('div');
        body.className = 'surface-body';
        body.style.background = role === 'user' ? 'var(--surface-raised)' : 'var(--surface)';
        body.style.border = '1px solid var(--border)';
        body.style.borderRadius = '8px';
        body.style.padding = '0.75rem 1rem';
        body.style.whiteSpace = 'pre-wrap';
        body.textContent = text;
        wrapper.appendChild(body);
        if (sources?.length) {
            const sourceList = document.createElement('div');
            sourceList.className = 'text-xs text-muted';
            sourceList.style.marginTop = '0.25rem';
            sourceList.textContent = 'Sources: ' + sources.map((source, index) =>
                '[' + (index + 1) + '] ' + (source.video_title || 'video') +
                (source.start_time != null ? ' @ ' + Math.floor(source.start_time) + 's' : '')
            ).join('  ');
            wrapper.appendChild(sourceList);
        }
        log.appendChild(wrapper);
        log.scrollTop = log.scrollHeight;
    }

    async function ensureSession() {
        if (sessionId) return sessionId;
        const response = await fetch('/api/agents/channel/' + encodeURIComponent(channelId) + '/sessions', {method: 'POST'});
        if (!response.ok) {
            const body = await response.json().catch(() => ({detail: 'Failed to start session'}));
            throw new Error(body.detail || 'Failed to start session');
        }
        sessionId = (await response.json()).id;
        return sessionId;
    }

    document.getElementById('chat-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const input = document.getElementById('chat-input');
        const sendButton = document.getElementById('chat-send');
        const text = input.value.trim();
        if (!text) return;
        appendMessage('user', text);
        input.value = '';
        sendButton.disabled = true;
        const thinking = document.createElement('div');
        thinking.className = 'text-sm text-muted';
        thinking.textContent = personaName + ' is thinking…';
        document.getElementById('chat-log').appendChild(thinking);
        try {
            const currentSessionId = await ensureSession();
            const response = await fetch(
                '/api/agents/channel/' + encodeURIComponent(channelId) + '/sessions/' + encodeURIComponent(currentSessionId) + '/messages',
                {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({content: text})}
            );
            thinking.remove();
            if (!response.ok) {
                const body = await response.json().catch(() => ({detail: 'Failed to send message'}));
                appendMessage('assistant', '[error] ' + (body.detail || response.statusText));
            } else {
                const data = await response.json();
                appendMessage('assistant', data.content, data.sources || []);
            }
        } catch (error) {
            thinking.remove();
            appendMessage('assistant', '[network error] ' + error.message);
        } finally {
            sendButton.disabled = false;
            input.focus();
        }
    });
})();
