(function () {
    let channelId = null;

    function escapeHtml(value) {
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    function safeHttpUrl(value) {
        try {
            const parsed = new URL(String(value ?? ''), window.location.origin);
            return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : '';
        } catch (error) {
            return '';
        }
    }

    function formatDuration(seconds) {
        if (typeof seconds !== 'number') return '--:--';
        const total = Math.max(0, Math.floor(seconds));
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const remainder = total % 60;
        if (hours) return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
        return `${minutes}:${String(remainder).padStart(2, '0')}`;
    }

    function refreshQueue() {
        if (document.getElementById('queue-content')) {
            window.htmx?.ajax('GET', '/ops/queue', {target: '#queue-content', swap: 'innerHTML'});
        }
    }

    function showChannelConfirmDialog(channelName, videos) {
        document.getElementById('channel-dialog-title').textContent = 'Select Videos from ' + channelName;
        document.getElementById('video-count').textContent = videos.length;
        const list = document.getElementById('channel-video-list');
        list.innerHTML = videos.map((video, index) => {
            const thumbnail = safeHttpUrl(video.thumbnail);
            const link = safeHttpUrl(video.url);
            return `
                <div class="flex items-start gap-3 px-4 py-3" style="border-bottom: 1px solid var(--border-muted);">
                    <input type="checkbox" id="vid-${index}" value="${escapeHtml(video.video_id)}" checked class="checkbox-field channel-video-cb">
                    <label for="vid-${index}" class="flex gap-3 flex-1 cursor-pointer">
                        <span class="rounded-md overflow-hidden shrink-0" style="width: 7rem; height: 3.9rem; background: var(--bg-elevated); border: 1px solid var(--border-default);">
                            ${thumbnail
                                ? `<img src="${escapeHtml(thumbnail)}" alt="" style="width:100%;height:100%;object-fit:cover">`
                                : '<span class="h-full w-full flex items-center justify-center text-xs text-faint">No thumb</span>'}
                        </span>
                        <span class="flex-1 min-w-0">
                            <span class="font-medium text-sm block leading-snug">${escapeHtml(video.title || 'Untitled')}</span>
                            <span class="font-mono text-xs text-faint block mt-1">${formatDuration(video.duration)}</span>
                        </span>
                    </label>
                    ${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener" class="link text-xs shrink-0">Open</a>` : ''}
                </div>`;
        }).join('');
        document.getElementById('select-all').checked = true;
        document.getElementById('channel-confirm-dialog').showModal();
    }

    const quickSearchForm = document.getElementById('quick-search-form');
    quickSearchForm?.addEventListener('submit', (event) => {
        event.preventDefault();
        const query = document.getElementById('quick-search-input').value.trim();
        if (query) window.location.href = '/search?q=' + encodeURIComponent(query);
    });

    const videoForm = document.getElementById('video-form');
    videoForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const input = document.getElementById('video-url');
        const result = document.getElementById('video-result');
        result.innerHTML = '<span class="spinner spinner-sm"></span> <span class="text-sm">Processing...</span>';
        try {
            const response = await fetch('/api/videos', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({url: input.value})
            });
            const data = await response.json();
            if (!response.ok) {
                result.innerHTML = '<p class="text-sm text-error mt-1">' + escapeHtml(data.detail || 'Error') + '</p>';
                return;
            }
            result.innerHTML = '<p class="text-sm text-success mt-1">Queued. <a href="/ops/jobs/' + escapeHtml(data.job_id) + '" class="link">Open job</a></p>';
            input.value = '';
            refreshQueue();
        } catch (error) {
            result.innerHTML = '<p class="text-sm text-error mt-1">Network error</p>';
        }
    });

    const channelForm = document.getElementById('channel-form');
    channelForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const input = document.getElementById('channel-url');
        const result = document.getElementById('channel-result');
        result.innerHTML = '<span class="spinner spinner-sm"></span> <span class="text-sm">Discovering...</span>';
        try {
            const response = await fetch('/api/channels', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({url: input.value})
            });
            const data = await response.json();
            if (!response.ok) {
                result.innerHTML = '<p class="text-sm text-error mt-1">' + escapeHtml(data.detail || 'Error') + '</p>';
                return;
            }
            channelId = data.channel_id;
            const videos = data.videos || [];
            if (!videos.length) {
                result.innerHTML = '<p class="text-sm text-warning mt-1">No videos found for that channel.</p>';
                return;
            }
            showChannelConfirmDialog(data.channel_name, videos);
            result.innerHTML = '<p class="text-sm text-success mt-1">Found ' + videos.length + ' videos</p>';
        } catch (error) {
            result.innerHTML = '<p class="text-sm text-error mt-1">Network error</p>';
        }
    });

    document.getElementById('select-all')?.addEventListener('change', (event) => {
        document.querySelectorAll('.channel-video-cb').forEach((checkbox) => {
            checkbox.checked = event.target.checked;
        });
    });

    document.getElementById('confirm-process-btn')?.addEventListener('click', async () => {
        const selected = Array.from(document.querySelectorAll('.channel-video-cb:checked')).map((checkbox) => checkbox.value);
        if (!selected.length) {
            window.alert('Select at least one video');
            return;
        }
        const button = document.getElementById('confirm-process-btn');
        button.classList.add('is-loading');
        button.disabled = true;
        try {
            const response = await fetch(`/api/channels/${encodeURIComponent(channelId)}/process`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({video_ids: selected})
            });
            const data = await response.json();
            if (!response.ok) {
                window.alert(data.detail || 'Error processing videos');
                return;
            }
            document.getElementById('channel-confirm-dialog').close();
            document.getElementById('channel-result').innerHTML =
                '<p class="text-sm text-success mt-1">Queued ' + escapeHtml(data.total_videos) + ' videos. <a href="/ops/queue" class="link">View queue</a></p>';
            refreshQueue();
        } catch (error) {
            window.alert('Network error');
        } finally {
            button.classList.remove('is-loading');
            button.disabled = false;
        }
    });
})();
