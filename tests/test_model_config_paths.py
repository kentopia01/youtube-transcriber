"""Focused tests for T021 model-setting read paths.

These tests keep model selection coverage non-networked by replacing every LLM
boundary with local fakes.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("relative_path", "expected", "deprecated_reference"),
    [
        (
            "app/tasks/summarize.py",
            "model=settings.summary_model",
            "settings.anthropic_summary_model",
        ),
        (
            "app/tasks/cleanup.py",
            "model=settings.cleanup_model",
            "settings.anthropic_cleanup_model",
        ),
        ("app/services/chat.py", "settings.chat_model", "settings.anthropic_chat_model"),
        ("app/telegram_bot.py", "settings.chat_model", "settings.anthropic_chat_model"),
        (
            "app/services/persona.py",
            "settings.persona_model",
            "settings.anthropic_persona_model",
        ),
        (
            "app/services/digest.py",
            "settings.digest_model",
            "settings.anthropic_summary_model",
        ),
        (
            "scripts/backfill_scan_first_summaries.py",
            "model = settings.summary_model",
            "settings.anthropic_summary_model",
        ),
        (
            "scripts/evaluate_scan_first_summaries.py",
            "model = settings.summary_model",
            "settings.anthropic_summary_model",
        ),
    ],
)
def test_llm_paths_reference_canonical_model_settings(relative_path, expected, deprecated_reference):
    source = (ROOT / relative_path).read_text()

    assert expected in source
    assert deprecated_reference not in source


def test_summarization_defaults_to_canonical_summary_model(monkeypatch):
    from app.services import summarization

    monkeypatch.setattr(settings, "summary_llm_provider", "anthropic")
    monkeypatch.setattr(settings, "summary_model", "summary-canonical")
    monkeypatch.setattr(summarization.anthropic, "Anthropic", lambda api_key: object())
    monkeypatch.setattr(summarization, "_count_tokens", lambda _text: 1)

    observed: dict[str, str] = {}

    def fake_summarize_single(
        client,
        provider,
        api_key,
        model,
        text,
        title,
        *,
        record_usage_enabled=True,
        duration_seconds=None,
        quality_feedback=None,
        output_format="structured",
    ):
        observed["model"] = model
        observed["provider"] = provider
        observed["api_key"] = api_key
        observed["text"] = text
        observed["title"] = title
        observed["output_format"] = output_format
        return {
            "summary": "ok",
            "model": model,
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }

    monkeypatch.setattr(summarization, "_summarize_single", fake_summarize_single)

    result = summarization.summarize_text("transcript", video_title="Title", api_key="api-key")

    assert observed == {
        "model": "summary-canonical",
        "provider": "anthropic",
        "api_key": "api-key",
        "text": "transcript",
        "title": "Title",
        "output_format": "structured",
    }
    assert result["model"] == "summary-canonical"


def test_summarization_can_use_openai_compatible_provider(monkeypatch):
    from app.services import summarization

    monkeypatch.setattr(settings, "summary_llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "summary_llm_base_url", "http://127.0.0.1:8400/v1")
    monkeypatch.setattr(settings, "summary_llm_api_key", "")
    monkeypatch.setattr(summarization, "_count_tokens", lambda _text: 1)
    monkeypatch.setattr(
        summarization.anthropic,
        "Anthropic",
        lambda api_key: pytest.fail("Anthropic should not be constructed for OpenAI-compatible summary"),
    )

    observed: dict[str, object] = {}

    def fake_generate(**kwargs):
        observed.update(kwargs)
        return summarization.LLMTextResponse(
            content="# Summary\n\nCodex route worked.",
            model="codex-actual",
            prompt_tokens=11,
            completion_tokens=5,
        )

    monkeypatch.setattr(summarization, "generate_openai_compatible", fake_generate)

    result = summarization.summarize_text(
        "transcript",
        video_title="Title",
        model="codex",
        record_usage_enabled=False,
        output_format="markdown",
    )

    assert observed["base_url"] == "http://127.0.0.1:8400/v1"
    assert observed["api_key"] == ""
    assert observed["model"] == "codex"
    assert observed["max_tokens"] == 12000
    assert result == {
        "summary": "# Summary\n\nCodex route worked.",
        "model": "codex-actual",
        "prompt_tokens": 11,
        "completion_tokens": 5,
    }


def test_summarization_falls_back_to_anthropic_when_openai_compatible_fails(monkeypatch):
    from app.services import summarization

    monkeypatch.setattr(settings, "summary_llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "summary_llm_fallback_provider", "anthropic")
    monkeypatch.setattr(settings, "summary_llm_fallback_model", "claude-fallback")
    monkeypatch.setattr(summarization, "_count_tokens", lambda _text: 1)
    monkeypatch.setattr(
        summarization,
        "generate_openai_compatible",
        lambda **_kwargs: (_ for _ in ()).throw(summarization.LLMProviderError("router down")),
    )
    monkeypatch.setattr(summarization.anthropic, "Anthropic", lambda api_key: object())

    observed: dict[str, str] = {}

    def fake_anthropic(_client, **kwargs):
        observed["model"] = kwargs["model"]
        return SimpleNamespace(
            content=[SimpleNamespace(text="# Summary\n\nFallback worked.")],
            model="claude-fallback",
            usage=SimpleNamespace(input_tokens=7, output_tokens=8),
        )

    monkeypatch.setattr(summarization, "_call_anthropic_with_retry", fake_anthropic)

    result = summarization.summarize_text(
        "transcript",
        video_title="Title",
        api_key="api-key",
        model="codex",
        record_usage_enabled=False,
        output_format="markdown",
    )

    assert observed["model"] == "claude-fallback"
    assert result["summary"] == "# Summary\n\nFallback worked."
    assert result["model"] == "claude-fallback"


def test_persona_derivation_defaults_to_canonical_persona_model(monkeypatch):
    from app.services import persona

    chunk_id = str(uuid.uuid4())
    monkeypatch.setattr(settings, "persona_model", "persona-canonical")
    monkeypatch.setattr(settings, "anthropic_api_key", "api-key")

    observed: dict[str, str] = {}

    def fake_call_derivation_llm(user_message, model, api_key):
        observed["model"] = model
        observed["api_key"] = api_key
        return (
            json.dumps(
                {
                    "display_name": "Channel",
                    "persona_prompt": "You are Channel.",
                    "style_notes": {"tone": "direct"},
                    "exemplar_chunk_ids": [chunk_id],
                    "confidence": 0.8,
                }
            ),
            "persona-actual",
        )

    monkeypatch.setattr(persona, "_call_derivation_llm", fake_call_derivation_llm)

    derivation = persona.derive_persona(
        "Channel",
        None,
        [{"id": chunk_id, "source_type": "transcript", "chunk_text": "specific excerpt"}],
    )

    assert observed == {"model": "persona-canonical", "api_key": "api-key"}
    assert derivation.model == "persona-actual"


def test_digest_render_defaults_to_canonical_digest_model(monkeypatch):
    from app.services import cost_tracker, digest

    monkeypatch.setattr(settings, "digest_model", "digest-canonical")
    monkeypatch.setattr(settings, "digest_llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "api-key")
    monkeypatch.setattr(cost_tracker, "check_budget", lambda: None)
    monkeypatch.setattr(cost_tracker, "record_usage", lambda *_args, **_kwargs: None)

    observed: dict[str, str] = {}

    class FakeMessages:
        def create(self, **kwargs):
            observed["model"] = kwargs["model"]
            return SimpleNamespace(
                content=[SimpleNamespace(text="Brief")],
                model="digest-actual",
                usage=SimpleNamespace(input_tokens=3, output_tokens=4),
            )

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(digest.anthropic, "Anthropic", lambda api_key: FakeClient())

    now = datetime(2026, 5, 12, tzinfo=timezone.utc)
    inputs = digest.DigestInput(
        window_start=now,
        window_end=now,
        videos_completed=[],
        videos_failed=[],
        personas_touched=[],
        cost_auto_ingest_usd=0.0,
        cost_manual_usd=0.0,
        subscription_names=[],
    )

    result = digest.render_digest_via_llm(inputs)

    assert observed["model"] == "digest-canonical"
    assert result["model"] == "digest-actual"
