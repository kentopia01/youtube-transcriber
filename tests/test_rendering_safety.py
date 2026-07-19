"""Static contracts for dynamic browser rendering sinks."""

from pathlib import Path


def _template(name: str) -> str:
    return Path("app/templates", name).read_text()


def test_dashboard_escapes_api_errors_and_external_metadata() -> None:
    source = _template("index.html")
    assert "escapeHtml(data.detail || 'Error')" in source
    assert "escapeHtml(v.title || 'Untitled')" in source
    assert "safeHttpUrl(v.thumbnail)" in source
    assert "safeHttpUrl(v.url)" in source


def test_legacy_submit_template_escapes_api_and_channel_values() -> None:
    source = _template("submit.html")
    assert "escapeHtml(data.detail || 'Error')" in source
    assert "escapeHtml(data.channel_name || '')" in source
    assert "escapeHtml(v.title || 'Untitled')" in source


def test_server_rendered_chat_uses_shared_safe_markdown_path() -> None:
    source = _template("partials/chat_messages.html")
    assert "window.renderSafeMarkdown(el.textContent)" in source
    assert "marked.parse(el.textContent)" not in source
