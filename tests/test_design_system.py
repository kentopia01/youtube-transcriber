"""Tests to verify the CSS design system and ensure no daisyUI remnants exist."""
from pathlib import Path

import pytest

TEMPLATE_DIR = Path(__file__).parent.parent / "app" / "templates"
CSS_FILE = Path(__file__).parent.parent / "app" / "static" / "css" / "main.css"

# daisyUI-specific class patterns that should NOT appear in any template
DAISYUI_CLASSES = [
    "badge-success", "badge-error", "badge-warning", "badge-info", "badge-ghost",
    "badge-sm", "badge-xs", ' card-body"', "card-title", "card-actions",
    "drawer-content", "drawer-side", "drawer-toggle", "drawer-overlay",
    "modal-box", "modal-action", "modal-backdrop",
    "collapse-title", "collapse-content", "collapse-arrow",
    "table-zebra", "join-item", "tabs-bordered", "tab-active", "tab-lg",
    "input-bordered", "label-text", "form-control",
    "alert-info", "loading-spinner", "loading loading",
    "data-theme", "bg-base-100", "bg-base-200", "bg-base-300",
    "text-base-content", "border-base-200", "border-base-300",
    "bg-neutral", "text-neutral", "text-neutral-content",
    "progress-primary", "steps-horizontal", "step-primary", "step-error",
    "btn-circle", "btn-ghost btn-sm drawer",
    "menu-title", "menu-sm",
]

# Old custom classes from previous design that should be removed
OLD_CUSTOM_CLASSES = [
    "app-shell", "app-hero-card", "app-proof-chip", "app-stat-card",
    "app-stat-label", "app-stat-value", "app-stat-desc",
    "app-bar-accent", "app-badge-accent", "app-badge-warning",
    "app-btn-primary", "app-btn-outline", "app-btn-warning",
    "app-utility-bar", "app-utility-nav", "app-utility-link",
    "app-utility-actions", "app-kicker", "app-nav-link",
    "app-heading", "app-page-title", "app-page-subtitle",
    "app-meta-grid", "app-meta-card", "app-meta-label", "app-meta-value",
    "app-chip-row", "app-chip", "app-accent-text", "app-brand-mark",
]

# New design system classes that SHOULD appear in templates
NEW_DESIGN_CLASSES = [
    "top-nav", "nav-brand", "nav-link", "page-shell",
    "surface", "surface-body", "status-pill", "stat-card",
    "section-title", "page-title", "kicker",
    "data-table", "progress-bar", "input-field",
    "btn btn-primary", "btn btn-outline",
]

# CSS custom properties that should be defined in main.css
DESIGN_TOKENS = [
    "--bg-primary", "--bg-shell", "--bg-surface", "--bg-elevated",
    "--border-default", "--border-muted",
    "--text-primary", "--text-secondary", "--text-tertiary",
    "--accent", "--accent-hover", "--accent-subtle",
    "--success", "--error", "--warning", "--info",
    "--nav-bg", "--nav-text",
    "--font-headline", "--font-body", "--font-mono",
]


def _read_all_templates():
    """Read all HTML template files and return as {path: content} dict."""
    templates = {}
    for html_file in TEMPLATE_DIR.rglob("*.html"):
        templates[str(html_file.relative_to(TEMPLATE_DIR))] = html_file.read_text()
    return templates


def _read_css():
    return CSS_FILE.read_text()


class TestNoDaisyUIRemnants:
    @pytest.fixture(scope="class")
    def templates(self):
        return _read_all_templates()

    @pytest.mark.parametrize("pattern", DAISYUI_CLASSES)
    def test_no_daisyui_class(self, templates, pattern):
        for path, content in templates.items():
            assert pattern not in content, (
                f"daisyUI class '{pattern}' found in {path}"
            )


class TestNoOldCustomClasses:
    @pytest.fixture(scope="class")
    def templates(self):
        return _read_all_templates()

    @pytest.mark.parametrize("pattern", OLD_CUSTOM_CLASSES)
    def test_no_old_class(self, templates, pattern):
        for path, content in templates.items():
            assert pattern not in content, (
                f"Old custom class '{pattern}' found in {path}"
            )


class TestNewDesignClassesExist:
    @pytest.fixture(scope="class")
    def all_templates_text(self):
        templates = _read_all_templates()
        return "\n".join(templates.values())

    @pytest.mark.parametrize("class_name", NEW_DESIGN_CLASSES)
    def test_new_class_used(self, all_templates_text, class_name):
        assert class_name in all_templates_text, (
            f"New design class '{class_name}' not found in any template"
        )


class TestCSSDesignTokens:
    @pytest.fixture(scope="class")
    def css(self):
        return _read_css()

    @pytest.mark.parametrize("token", DESIGN_TOKENS)
    def test_token_defined(self, css, token):
        assert token in css, f"Design token '{token}' not found in main.css"


class TestCSSNoOldTokens:
    def test_no_old_accent_var(self):
        css = _read_css()
        assert "--app-accent:" not in css
        assert "--app-text:" not in css
        assert "--app-muted:" not in css
        assert "--app-border:" not in css
        assert "--app-surface:" not in css
        assert "--app-shell:" not in css


class TestCSSComponentClasses:
    @pytest.fixture(scope="class")
    def css(self):
        return _read_css()

    def test_has_top_nav(self, css):
        assert ".top-nav" in css

    def test_has_surface(self, css):
        assert ".surface" in css

    def test_has_status_pill(self, css):
        assert ".status-pill" in css

    def test_has_bracket_accent(self, css):
        assert ".bracket-accent" in css

    def test_has_pipeline_steps(self, css):
        assert ".pipeline-steps" in css

    def test_has_data_table(self, css):
        assert ".data-table" in css

    def test_has_progress_bar(self, css):
        assert ".progress-bar" in css

    def test_has_video_card(self, css):
        assert ".video-card" in css

    def test_has_pagination(self, css):
        assert ".pagination" in css

    def test_has_modal(self, css):
        assert ".modal-dialog" in css

    def test_has_collapsible(self, css):
        assert ".collapsible" in css

    def test_has_spinner(self, css):
        assert ".spinner" in css
        assert "@keyframes spin" in css

    def test_has_htmx_indicator(self, css):
        assert ".htmx-indicator" in css
        assert ".htmx-request" in css


class TestTemplateStructure:
    """Verify structural properties of templates."""

    def test_all_pages_extend_base(self):
        templates = _read_all_templates()
        # Partials don't extend base
        for path, content in templates.items():
            if path.startswith("partials/"):
                assert '{% extends "base.html" %}' not in content, (
                    f"Partial {path} should not extend base.html"
                )
            elif path != "base.html":
                assert '{% extends "base.html" %}' in content, (
                    f"Page {path} should extend base.html"
                )

    def test_base_has_content_block(self):
        templates = _read_all_templates()
        base = templates.get("base.html", "")
        assert "{% block content %}" in base
        assert "{% block scripts %}" in base
        assert "{% block title %}" in base

    def test_iconoir_cdn_in_base(self):
        templates = _read_all_templates()
        base = templates.get("base.html", "")
        assert "iconoir" in base

    def test_no_daisyui_cdn_in_base(self):
        templates = _read_all_templates()
        base = templates.get("base.html", "")
        assert "daisyui" not in base

    def test_htmx_preserved_in_base(self):
        templates = _read_all_templates()
        base = templates.get("base.html", "")
        assert "htmx.org@2.0.4" in base

    def test_google_fonts_in_base(self):
        templates = _read_all_templates()
        base = templates.get("base.html", "")
        assert "Playfair+Display" in base
        assert "Inter" in base
        assert "JetBrains+Mono" in base

    def test_no_old_fonts_in_base(self):
        templates = _read_all_templates()
        base = templates.get("base.html", "")
        assert "Manrope" not in base
        assert "Public+Sans" not in base


class TestHTMXAttributesPreserved:
    """Verify all HTMX interactions are preserved."""

    @pytest.fixture(scope="class")
    def templates(self):
        return _read_all_templates()

    def test_queue_polling_in_index(self, templates):
        html = templates.get("index.html", "")
        assert 'hx-get="/queue"' in html
        assert 'hx-trigger="load delay:3s"' in html
        assert 'hx-target="#queue-content"' in html

    def test_queue_polling_in_queue(self, templates):
        html = templates.get("queue.html", "")
        assert 'hx-get="/queue"' in html
        assert 'hx-trigger="load delay:3s"' in html

    def test_job_polling_in_job_detail(self, templates):
        html = templates.get("job_detail.html", "")
        assert "hx-trigger" in html
        assert "load delay:2s" in html

    def test_search_debounce(self, templates):
        html = templates.get("search.html", "")
        assert 'hx-trigger="keyup changed delay:500ms"' in html

    def test_video_list_pagination_push(self, templates):
        html = templates.get("partials/video_list.html", "")
        assert 'hx-push-url="true"' in html

    def test_retry_forms_in_queue_content(self, templates):
        html = templates.get("partials/queue_content.html", "")
        assert "hx-post" in html
        assert "/retry" in html
        assert "/cancel" in html

    def test_job_status_cancel_retry(self, templates):
        html = templates.get("partials/job_status.html", "")
        assert "/cancel" in html
        assert "/retry" in html

    def test_auto_refresh_in_queue_content(self, templates):
        html = templates.get("partials/queue_content.html", "")
        assert 'hx-trigger="load delay:3s"' in html
        assert 'style="display:none;"' in html

    def test_auto_refresh_in_job_status(self, templates):
        html = templates.get("partials/job_status.html", "")
        assert 'hx-trigger="load delay:2s"' in html
