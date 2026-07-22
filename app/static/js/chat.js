(function () {
    const shell = document.querySelector('.chat-page-shell');
    if (!shell) return;

    const sessionId = shell.dataset.sessionId || null;
    const scopeVideoId = shell.dataset.scopeVideoId || null;
    const input = document.getElementById('chat-input');
    const scopeSelect = document.getElementById('chat-retrieval-scope');
    const channelSelect = document.getElementById('chat-channel-filter');
    let isStreaming = false;

    window.marked.setOptions({breaks: true, gfm: true});
    const markdownTags = new Set([
        'P', 'BR', 'STRONG', 'EM', 'CODE', 'PRE', 'UL', 'OL', 'LI',
        'BLOCKQUOTE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HR', 'A',
        'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD'
    ]);

    function escapeHtml(value) {
        const element = document.createElement('div');
        element.textContent = String(value ?? '');
        return element.innerHTML;
    }

    function isSafeLink(href) {
        if (!href) return false;
        try {
            const parsed = new URL(href, window.location.origin);
            return parsed.protocol === 'http:' || parsed.protocol === 'https:';
        } catch (error) {
            return false;
        }
    }

    function renderMarkdown(text) {
        const template = document.createElement('template');
        template.innerHTML = window.marked.parse(escapeHtml(text));
        for (const element of Array.from(template.content.querySelectorAll('*'))) {
            if (!markdownTags.has(element.tagName)) {
                element.replaceWith(document.createTextNode(element.textContent || ''));
                continue;
            }
            for (const attribute of Array.from(element.attributes)) {
                const allowed = element.tagName === 'A' && (attribute.name === 'href' || attribute.name === 'title');
                if (!allowed) element.removeAttribute(attribute.name);
            }
            if (element.tagName === 'A') {
                if (!isSafeLink(element.getAttribute('href'))) element.removeAttribute('href');
                else element.setAttribute('rel', 'noopener noreferrer');
            }
        }
        return template.innerHTML;
    }
    window.renderSafeMarkdown = renderMarkdown;
    document.querySelectorAll('.chat-md-content').forEach((element) => {
        element.innerHTML = renderMarkdown(element.textContent);
    });

    const requestParams = new URLSearchParams(window.location.search);
    const selectionText = (requestParams.get('selection') || '').slice(0, 4000);
    const selectionAction = requestParams.get('action');
    const actionPrompts = {
        explain: 'Explain the selected passage in plain language.',
        summarize: 'Summarize the selected passage and its main claim.',
        context: 'Give me the surrounding context for the selected passage.'
    };
    if (selectionText && actionPrompts[selectionAction]) input.value = actionPrompts[selectionAction];

    function applyRetrievalScope() {
        channelSelect.disabled = !sessionId || scopeSelect.value !== 'channel';
    }

    function scrollToBottom() {
        const container = document.getElementById('chat-messages');
        container.scrollTop = container.scrollHeight;
    }

    function formatTime(seconds) {
        const minutes = Math.floor(seconds / 60);
        const remainder = Math.floor(seconds % 60);
        return minutes + ':' + (remainder < 10 ? '0' : '') + remainder;
    }

    function buildMessageHtml(role, content, sources) {
        const isUser = role === 'user';
        const rendered = isUser ? escapeHtml(content) : renderMarkdown(content);
        let sourcesHtml = '';
        if (sources?.length) {
            const sourcesId = 'src-' + Date.now();
            sourcesHtml = '<div class="chat-sources">' +
                '<button class="chat-sources-toggle" onclick="toggleSources(this, \'' + sourcesId + '\')">' +
                '<i class="iconoir-bookmark" style="font-size:0.7rem"></i> ' +
                sources.length + ' source' + (sources.length > 1 ? 's' : '') +
                ' <i class="iconoir-nav-arrow-down chevron"></i></button>' +
                '<div class="chat-sources-list" id="' + sourcesId + '">';
            for (const source of sources) {
                const time = source.start_time != null ? formatTime(source.start_time) : '';
                const similarity = source.similarity != null ? Math.round(source.similarity * 100) + '%' : '';
                sourcesHtml += '<div class="chat-source-card"><div class="chat-source-header">' +
                    '<span class="chat-source-title">' + escapeHtml(source.video_title || '') + '</span>' +
                    (time ? '<span class="chat-source-time">' + time + '</span>' : '') +
                    (similarity ? '<span class="chat-source-similarity">' + similarity + '</span>' : '') +
                    '</div><div class="chat-source-snippet">' + escapeHtml(source.chunk_text || '') + '</div></div>';
            }
            sourcesHtml += '</div></div>';
        }
        const avatar = isUser ? 'iconoir-user' : 'iconoir-spark';
        return '<div class="chat-msg">' +
            '<div class="chat-msg-avatar ' + (isUser ? 'is-user' : 'is-assistant') + '"><i class="' + avatar + '" style="font-size:0.85rem"></i></div>' +
            '<div class="chat-msg-body"><div class="chat-msg-role">' + (isUser ? 'You' : 'Assistant') + '</div>' +
            '<div class="chat-msg-content"' + (isUser ? ' style="white-space:pre-wrap"' : '') + '>' + rendered + '</div>' +
            sourcesHtml + '</div></div>';
    }

    async function refreshSidebar() {
        try {
            const response = await fetch('/api/chat/sessions');
            if (!response.ok) return;
            const sessions = await response.json();
            const groups = {};
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const yesterday = new Date(today);
            const weekAgo = new Date(today);
            yesterday.setDate(yesterday.getDate() - 1);
            weekAgo.setDate(weekAgo.getDate() - 7);
            for (const session of sessions) {
                const updated = new Date(session.updated_at);
                let label = 'Older';
                if (updated >= today) label = 'Today';
                else if (updated >= yesterday) label = 'Yesterday';
                else if (updated >= weekAgo) label = 'This Week';
                (groups[label] ||= []).push(session);
            }
            let html = '';
            for (const label of ['Today', 'Yesterday', 'This Week', 'Older']) {
                if (!groups[label]) continue;
                html += '<div class="chat-sidebar-group-label">' + label + '</div>';
                for (const session of groups[label]) {
                    const scopeQuery = scopeVideoId ? '?video_id=' + encodeURIComponent(scopeVideoId) : '';
                    html += '<a href="/chat/' + encodeURIComponent(session.id) + scopeQuery + '" class="chat-session-item' +
                        (session.id === sessionId ? ' is-active' : '') + '" data-session-id="' + escapeHtml(session.id) + '">' +
                        '<span class="chat-session-title">' + escapeHtml(session.title || 'New Chat') + '</span>' +
                        '<span class="chat-session-actions"><button class="chat-session-action-btn is-delete" onclick="deleteSession(event, \'' +
                        escapeHtml(session.id) + '\')" aria-label="Delete chat session"><i class="iconoir-trash" style="font-size:0.8rem"></i></button></span></a>';
                }
            }
            document.getElementById('session-list').innerHTML = html ||
                '<div style="padding:1rem;text-align:center;color:var(--text-tertiary);font-size:0.82rem">No chat sessions yet</div>';
        } catch (error) {
            console.error('Failed to refresh sidebar:', error);
        }
    }

    window.handleInputKey = function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            window.sendMessage();
        }
    };

    window.createNewSession = async function () {
        try {
            const response = await fetch('/api/chat/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({platform: 'web'})
            });
            if (!response.ok) throw new Error('Unable to create chat session');
            const session = await response.json();
            window.location.href = '/chat/' + encodeURIComponent(session.id) + window.location.search;
        } catch (error) {
            console.error('Failed to create session:', error);
        }
    };

    window.sendMessage = async function () {
        if (isStreaming || !sessionId) return;
        const text = input.value.trim();
        if (!text) return;
        isStreaming = true;
        input.value = '';
        input.style.height = 'auto';
        document.getElementById('chat-send-btn').disabled = true;
        document.querySelector('.chat-empty')?.remove();
        const messages = document.getElementById('chat-messages-inner');
        messages.insertAdjacentHTML('beforeend', buildMessageHtml('user', text));
        const thinkingId = 'thinking-' + Date.now();
        messages.insertAdjacentHTML('beforeend', '<div id="' + thinkingId + '" class="chat-msg">' +
            '<div class="chat-msg-avatar is-assistant"><i class="iconoir-spark" style="font-size:0.85rem"></i></div>' +
            '<div class="chat-msg-body"><div class="chat-thinking"><div class="chat-thinking-dots"><span></span><span></span><span></span></div>' +
            '<span class="chat-thinking-text">Thinking...</span></div></div></div>');
        scrollToBottom();
        try {
            const response = await fetch('/api/chat/sessions/' + encodeURIComponent(sessionId) + '/messages', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    content: text,
                    channel_id: scopeSelect.value === 'channel' ? (channelSelect.value || null) : null,
                    video_id: scopeSelect.value === 'video' ? scopeVideoId : null,
                    selection_text: selectionText || null,
                    selection_action: selectionText ? selectionAction : null
                })
            });
            document.getElementById(thinkingId)?.remove();
            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                messages.insertAdjacentHTML('beforeend', buildMessageHtml('assistant', 'Error: ' + (error.detail || 'Something went wrong. Please try again.')));
                return;
            }
            const data = await response.json();
            messages.insertAdjacentHTML('beforeend', buildMessageHtml('assistant', data.content, data.sources));
            refreshSidebar();
        } catch (error) {
            document.getElementById(thinkingId)?.remove();
            messages.insertAdjacentHTML('beforeend', buildMessageHtml('assistant', 'Error: Network error. Please check your connection.'));
        } finally {
            isStreaming = false;
            document.getElementById('chat-send-btn').disabled = false;
            input.focus();
            scrollToBottom();
        }
    };

    window.toggleSources = function (button, listId) {
        button.classList.toggle('is-open');
        document.getElementById(listId)?.classList.toggle('is-open');
    };

    window.deleteSession = async function (event, targetSessionId) {
        event.preventDefault();
        event.stopPropagation();
        if (!window.confirm('Delete this chat session?')) return;
        try {
            const response = await fetch('/api/chat/sessions/' + encodeURIComponent(targetSessionId), {method: 'DELETE'});
            if (!response.ok) throw new Error('Unable to delete chat session');
            if (targetSessionId === sessionId) {
                window.location.href = '/chat' + (scopeVideoId ? '?video_id=' + encodeURIComponent(scopeVideoId) : '');
            } else refreshSidebar();
        } catch (error) {
            console.error('Failed to delete session:', error);
        }
    };

    window.renameSession = function (event, targetSessionId) {
        event.preventDefault();
        event.stopPropagation();
        const item = event.target.closest('.chat-session-item');
        const title = item.querySelector('.chat-session-title');
        const currentTitle = title.textContent.trim();
        const editor = document.createElement('input');
        editor.className = 'chat-session-title-input';
        editor.value = currentTitle;
        title.replaceWith(editor);
        editor.focus();
        editor.select();
        const save = async () => {
            const newTitle = editor.value.trim();
            if (newTitle && newTitle !== currentTitle) {
                try {
                    await fetch('/api/chat/sessions/' + encodeURIComponent(targetSessionId), {
                        method: 'PATCH',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({title: newTitle})
                    });
                    if (targetSessionId === sessionId) document.getElementById('chat-title').textContent = newTitle;
                } catch (error) {
                    console.error('Rename failed:', error);
                }
            }
            refreshSidebar();
        };
        editor.addEventListener('blur', save, {once: true});
        editor.addEventListener('keydown', (keyboardEvent) => {
            if (keyboardEvent.key === 'Enter') {
                keyboardEvent.preventDefault();
                editor.blur();
            }
            if (keyboardEvent.key === 'Escape') refreshSidebar();
        });
    };

    window.toggleSidebar = function () {
        const sidebar = document.getElementById('chat-sidebar');
        const isOpen = sidebar.classList.toggle('is-open');
        document.getElementById('sidebar-overlay').classList.toggle('is-open', isOpen);
        const toggle = document.querySelector('.chat-mobile-toggle');
        toggle?.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        toggle?.setAttribute('aria-label', isOpen ? 'Close chat sidebar' : 'Open chat sidebar');
    };

    scopeSelect.addEventListener('change', applyRetrievalScope);
    input.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 128) + 'px';
    });
    document.getElementById('session-list').addEventListener('dblclick', (event) => {
        const item = event.target.closest('.chat-session-item');
        if (item?.dataset.sessionId) window.renameSession(event, item.dataset.sessionId);
    });
    applyRetrievalScope();
    scrollToBottom();
})();
