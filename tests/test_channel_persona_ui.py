"""Tests for the channel-persona UI templates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.main import create_app


def _render(template_name: str, context: dict) -> str:
    app = create_app()
    return app.state.templates.get_template(template_name).render({**context, "request": SimpleNamespace(url="http://x")})


def _channel():
    return SimpleNamespace(
        id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
        name="Test Channel",
        thumbnail_url=None,
        video_count=5,
        description=None,
        last_synced_at=None,
        url="https://youtube.com/@test",
    )


def _persona(style_notes=None, confidence=0.72):
    return SimpleNamespace(
        id=uuid.uuid4(),
        display_name="Test Voice",
        persona_prompt="You are Test Voice.",
        style_notes=style_notes or {"tone": "dry", "vocab_tells": ["clearly", "right?"]},
        confidence=confidence,
        source_chunk_count=30,
        videos_at_generation=5,
        generated_at=datetime(2026, 4, 17, tzinfo=UTC),
    )


class TestChannelDetailPersonaCard:
    def test_building_state_shows_progress(self):
        html = _render("channel_detail.html", {
            "channel": _channel(),
            "videos": [],
            "persona": None,
            "completed_videos": 1,
            "persona_min_videos": 3,
        })
        assert "1/3 videos needed" in html
        assert "Talk to" not in html

    def test_ready_but_not_yet_built_shows_manual_trigger(self):
        html = _render("channel_detail.html", {
            "channel": _channel(),
            "videos": [],
            "persona": None,
            "completed_videos": 5,
            "persona_min_videos": 3,
        })
        assert "Build persona now" in html
        assert "Talk to" not in html

    def test_persona_ready_shows_talk_button(self):
        persona = _persona()
        html = _render("channel_detail.html", {
            "channel": _channel(),
            "videos": [],
            "persona": persona,
            "completed_videos": 5,
            "persona_min_videos": 3,
        })
        assert "Talk to Test Voice" in html
        assert "Refresh persona" in html
        # style notes appear in the expandable details
        assert "dry" in html
        assert "confidence 0.72" in html

    def test_persona_prompt_not_leaked_to_ui(self):
        """The raw persona system prompt is internal; never render it in-page."""
        persona = _persona()
        persona.persona_prompt = "SECRET_DO_NOT_LEAK"
        html = _render("channel_detail.html", {
            "channel": _channel(),
            "videos": [],
            "persona": persona,
            "completed_videos": 5,
            "persona_min_videos": 3,
        })
        assert "SECRET_DO_NOT_LEAK" not in html


class TestChannelChatPage:
    def test_renders_send_form_and_persona_name(self):
        persona = _persona()
        html = _render("channel_chat.html", {
            "channel": _channel(),
            "persona": persona,
        })
        assert "Test Voice" in html
        assert "Ask Test Voice" in html
        assert "/api/agents/channel/" in html
        assert "sessions" in html
