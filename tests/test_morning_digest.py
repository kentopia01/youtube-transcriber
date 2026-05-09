"""Tests for the morning digest service + task + renderer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import digest as digest_svc
from app.services import telegram_messages as tg_msgs
from app.tasks import morning_digest as morning_task


# ---------------------------------------------------------------------------
# DigestInput.to_prompt_block
# ---------------------------------------------------------------------------


def _window(hours_back=24):
    end = datetime.now(UTC)
    return end - timedelta(hours=hours_back), end


class TestDigestInputPromptBlock:
    def test_empty_window_renders_minimal(self):
        start, end = _window()
        d = digest_svc.DigestInput(
            window_start=start,
            window_end=end,
            videos_completed=[],
            videos_failed=[],
            personas_touched=[],
            cost_auto_ingest_usd=0.0,
            cost_manual_usd=0.0,
            subscription_names=["20VC", "Stripe"],
        )
        text = d.to_prompt_block()
        assert "Window:" in text
        assert "auto-ingest=$0.00" in text
        assert "active_pipeline_jobs=0" in text
        assert "Health: not captured" in text
        assert "20VC" in text
        assert "Videos completed" not in text  # skipped when empty

    def test_with_pipeline_ops_status_includes_retries_manual_review_and_health(self):
        start, end = _window()
        d = digest_svc.DigestInput(
            window_start=start,
            window_end=end,
            videos_completed=[
                {
                    "id": str(uuid.uuid4()),
                    "title": "AI Agents Brief",
                    "duration_seconds": 1800,
                    "channel_name": "Latent Space",
                    "summary_excerpt": "Agents are shifting from demos to operations.",
                    "report_delivery_status": "sent",
                }
            ],
            videos_failed=[
                {"title": "Broken upload", "channel_name": "Ops", "error_message": "diarization failed"},
            ],
            personas_touched=[],
            cost_auto_ingest_usd=2.50,
            cost_manual_usd=0.75,
            subscription_names=["Latent Space"],
            pipeline_status_counts={"pending": 2, "running": 1},
            pending_jobs=[
                {
                    "title": "Queued video",
                    "channel_name": "Queue Channel",
                    "status": "pending",
                    "current_stage": "audio",
                    "progress_pct": 0.0,
                }
            ],
            retrying_jobs=[
                {
                    "title": "Retry video",
                    "channel_name": "Retry Channel",
                    "status": "running",
                    "current_stage": "diarize",
                    "progress_pct": 55.0,
                    "attempt_number": 2,
                    "attempt_creation_reason": "transient_auto_retry",
                    "failure_signature_count": 1,
                }
            ],
            manual_review_jobs=[
                {
                    "title": "Manual video",
                    "channel_name": "Review Channel",
                    "status": "failed",
                    "current_stage": "cleanup",
                    "progress_pct": 80.0,
                    "attempt_number": 3,
                    "failure_signature_count": 2,
                    "error_message": "same failure repeated",
                }
            ],
            report_delivery_counts={"sent": 1, "failed": 1},
            health_summary={
                "active_jobs": 3,
                "active_workers": 1,
                "manual_review": 1,
                "failed_undismissed": 2,
                "last_activity_at": "2026-05-09T01:00:00+00:00",
            },
        )
        text = d.to_prompt_block()
        assert "Activity totals" in text
        assert "status_counts=pending=2, running=1" in text
        assert "report_delivery_counts=failed=1, sent=1" in text
        assert "report_delivery=sent" in text
        assert "Queued/pending/running pipeline jobs (1)" in text
        assert "Retrying pipeline jobs (1)" in text
        assert "retry_reason=transient_auto_retry" in text
        assert "Manual-review items (1)" in text
        assert "same failure repeated" in text
        assert "Health: active_jobs=3, active_workers=1, manual_review=1, failed_undismissed=2" in text

    def test_with_completions_includes_summaries(self):
        start, end = _window()
        d = digest_svc.DigestInput(
            window_start=start,
            window_end=end,
            videos_completed=[
                {
                    "id": str(uuid.uuid4()),
                    "title": "Empire Collapse Framework",
                    "duration_seconds": 3600,
                    "channel_name": "Predictive History",
                    "summary_excerpt": "Three metrics matter: energy, openness, cohesion.",
                }
            ],
            videos_failed=[],
            personas_touched=[
                {"display_name": "Lex", "generated_at": start + timedelta(hours=2)},
            ],
            cost_auto_ingest_usd=1.23,
            cost_manual_usd=0.45,
            subscription_names=["Predictive History"],
        )
        text = d.to_prompt_block()
        assert "Empire Collapse Framework" in text
        assert "Three metrics matter" in text
        assert "1h 0m" in text
        assert "Persona updates (1)" in text
        assert "auto-ingest=$1.23" in text


# ---------------------------------------------------------------------------
# render_digest_via_llm — mocked Anthropic
# ---------------------------------------------------------------------------


class TestRenderDigest:
    def test_calls_anthropic_and_parses(self, monkeypatch):
        start, end = _window()
        d = digest_svc.DigestInput(
            window_start=start,
            window_end=end,
            videos_completed=[],
            videos_failed=[],
            personas_touched=[],
            cost_auto_ingest_usd=0.0,
            cost_manual_usd=0.0,
            subscription_names=[],
        )

        fake_resp = MagicMock()
        fake_resp.content = [MagicMock(text="**Opener** Quiet night.\n\n**Ledger** 0 ingests.")]
        fake_resp.model = "claude-sonnet-4-5"
        fake_resp.usage = MagicMock(input_tokens=123, output_tokens=45)

        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp
        monkeypatch.setattr(digest_svc.anthropic, "Anthropic", lambda api_key: fake_client)
        monkeypatch.setattr("app.services.cost_tracker.check_budget", lambda: None)
        monkeypatch.setattr("app.services.cost_tracker.record_usage", lambda *a, **kw: None)

        result = digest_svc.render_digest_via_llm(d, api_key="k", model="claude-sonnet-4-5")
        assert "Opener" in result["text"]
        assert result["prompt_tokens"] == 123
        assert result["completion_tokens"] == 45
        # Verify system prompt passes Chief-of-staff operations framing
        call_kwargs = fake_client.messages.create.call_args.kwargs
        assert "Chief of Staff" in call_kwargs["system"]
        assert "operations" in call_kwargs["system"]


# ---------------------------------------------------------------------------
# morning digest task end-to-end
# ---------------------------------------------------------------------------


class TestMorningDigestTask:
    def test_invokes_notifier_with_digest_morning(self, monkeypatch):
        fake_input = digest_svc.DigestInput(
            window_start=datetime.now(UTC) - timedelta(hours=24),
            window_end=datetime.now(UTC),
            videos_completed=[],
            videos_failed=[],
            personas_touched=[],
            cost_auto_ingest_usd=0.0,
            cost_manual_usd=0.0,
            subscription_names=[],
        )
        fake_render = {
            "text": "**Opener** nothing overnight.",
            "model": "claude-sonnet-4-5",
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "window_start": fake_input.window_start.isoformat(),
            "window_end": fake_input.window_end.isoformat(),
        }

        class _CtxStub:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(
            morning_task, "create_engine",
            lambda *a, **kw: MagicMock(dispose=lambda: None),
        )
        monkeypatch.setattr(morning_task, "Session", lambda engine: _CtxStub())
        monkeypatch.setattr(morning_task, "gather_digest_inputs", lambda db, window_hours=24: fake_input)
        monkeypatch.setattr(morning_task, "render_digest_via_llm", lambda inputs: fake_render)

        sent = []
        monkeypatch.setattr(
            "app.services.telegram_notify.notify",
            lambda event, payload=None: sent.append((event, payload)),
        )

        result = morning_task.run_morning_digest()
        assert result["videos_completed"] == 0
        assert ("digest.morning", {
            "text": "**Opener** nothing overnight.",
            "window_start": fake_render["window_start"],
            "window_end": fake_render["window_end"],
        }) in sent


# ---------------------------------------------------------------------------
# digest.morning Telegram renderer
# ---------------------------------------------------------------------------


class TestTelegramRenderer:
    def test_converts_markdown_to_html(self):
        out = tg_msgs._render_digest_morning({
            "text": "**Opener** Quiet night. [source](https://youtu.be/abc)",
            "window_start": "2026-04-20T00:00:00+00:00",
        })
        assert out["parse_mode"] == "HTML"
        assert "<b>🌅 Morning brief</b>" in out["text"]
        assert "<b>Opener</b>" in out["text"]
        assert '<a href="https://youtu.be/abc">source</a>' in out["text"]

    def test_empty_text_raises_unknown(self):
        with pytest.raises(tg_msgs.UnknownEvent):
            tg_msgs._render_digest_morning({"text": ""})


class TestEventCatalogRegistration:
    def test_digest_morning_in_renderers_map(self):
        assert "digest.morning" in tg_msgs.EVENT_RENDERERS
