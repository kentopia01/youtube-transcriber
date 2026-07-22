"""Static contracts for dynamic browser rendering sinks."""

from pathlib import Path


def _template(name: str) -> str:
    return Path("app/templates", name).read_text()


def _script(name: str) -> str:
    return Path("app/static/js", name).read_text()


def test_dashboard_escapes_api_errors_and_external_metadata() -> None:
    template = _template("index.html")
    source = _script("submission.js")
    assert '/static/js/submission.js?v=20260721' in template
    assert "escapeHtml(data.detail || 'Error')" in source
    assert "escapeHtml(video.title || 'Untitled')" in source
    assert "safeHttpUrl(video.thumbnail)" in source
    assert "safeHttpUrl(video.url)" in source


def test_legacy_submit_template_escapes_api_and_channel_values() -> None:
    template = _template("submit.html")
    source = _script("submission.js")
    assert '/static/js/submission.js?v=20260721' in template
    assert "escapeHtml(data.detail || 'Error')" in source
    assert "textContent = 'Select Videos from ' + channelName" in source
    assert "escapeHtml(video.title || 'Untitled')" in source


def test_server_rendered_chat_uses_shared_safe_markdown_path() -> None:
    template = _template("partials/chat_messages.html")
    source = _script("chat.js")
    assert "chat-md-content" in template
    assert "element.innerHTML = renderMarkdown(element.textContent)" in source
    assert "marked.parse(element.textContent)" not in source
