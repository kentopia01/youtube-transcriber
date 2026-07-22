from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    light, dark = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)


def _tokens() -> dict[str, str]:
    css = (ROOT / "app/static/css/main.css").read_text(encoding="utf-8")
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", css))


def test_normal_text_tokens_meet_wcag_aa_on_default_surface():
    tokens = _tokens()
    for token in ("text-primary", "text-secondary", "text-tertiary", "accent", "success", "error", "warning", "info"):
        assert _contrast(tokens[token], tokens["bg-surface"]) >= 4.5, token


def test_core_shell_has_no_runtime_cdn_or_tailwind_compiler():
    base = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
    assert "tailwindcss/browser" not in base
    assert "type=\"text/tailwindcss\"" not in base
    assert "fonts.googleapis.com" not in base
    assert "cdn.jsdelivr.net" not in base
    assert "unpkg.com" not in base
    assert '/static/js/htmx-lite.js' in base
    assert '/static/css/utilities.css' in base


def test_page_behavior_is_served_from_versioned_static_modules():
    templates = ROOT / "app/templates"
    inline_script = re.compile(r"<script(?:\s[^>]*)?>\s*(?!</script>)", re.IGNORECASE)
    for path in templates.rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        for match in inline_script.finditer(source):
            tag = match.group(0)
            assert "src=" in tag, f"inline script remains in {path.relative_to(ROOT)}"

    operations = (templates / "index.html").read_text(encoding="utf-8")
    legacy_submit = (templates / "submit.html").read_text(encoding="utf-8")
    assert '/static/js/submission.js?v=20260721' in operations
    assert '/static/js/submission.js?v=20260721' in legacy_submit


def test_reader_and_operations_expose_names_states_and_live_regions():
    reader = (ROOT / "app/templates/reader_document.html").read_text(encoding="utf-8")
    chat = (ROOT / "app/templates/chat.html").read_text(encoding="utf-8")
    queue = (ROOT / "app/templates/queue.html").read_text(encoding="utf-8")
    job = (ROOT / "app/templates/job_detail.html").read_text(encoding="utf-8")

    assert 'role="progressbar"' in reader and 'aria-valuenow=' in reader
    assert 'aria-labelledby="reader-tools-title"' in reader
    assert 'aria-controls="chat-sidebar"' in chat and 'aria-expanded="false"' in chat
    assert 'aria-live="polite"' in queue
    assert 'aria-live="polite"' in job


def test_mobile_operations_use_job_card_reflow_and_shared_focus_ring():
    operations = (ROOT / "app/static/css/operations.css").read_text(encoding="utf-8")
    shared = (ROOT / "app/static/css/main.css").read_text(encoding="utf-8")

    assert "@media (max-width: 640px)" in operations
    assert ".recent-jobs-table tr" in operations
    assert "content: attr(data-label)" in operations
    assert "button:focus-visible" in shared
    assert "outline: 3px solid var(--accent)" in shared
