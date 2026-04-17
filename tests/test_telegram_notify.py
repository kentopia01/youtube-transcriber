"""Tests for the Telegram push notifier (Phase B)."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from app.services import telegram_messages, telegram_notify


@pytest.fixture(autouse=True)
def _reset_dedupe():
    telegram_notify._DEDUPE.clear()
    yield
    telegram_notify._DEDUPE.clear()


@pytest.fixture(autouse=True)
def _fake_settings(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "fake-token:123")
    monkeypatch.setattr(settings, "telegram_allowed_users", [999])
    monkeypatch.setattr(settings, "telegram_notify_enabled", True)
    monkeypatch.setattr(settings, "telegram_notify_muted_events", [])
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(settings, "telegram_notify_state_path", str(state_path))
    yield


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


class TestRenderers:
    def test_video_completed(self):
        out = telegram_messages._render_video_completed({
            "title": "Ep 12",
            "duration": 3600,
            "speakers": 3,
            "video_id": "v1",
            "channel_id": "c1",
        })
        assert "Processed" in out["text"]
        assert "Ep 12" in out["text"]
        assert "1h" in out["text"]
        kb = out["reply_markup"]["inline_keyboard"]
        assert any("video:chat:v1" == b["callback_data"] for row in kb for b in row)

    def test_video_failed(self):
        out = telegram_messages._render_video_failed({
            "title": "Ep 12", "stage": "diarize", "error_message": "MPS blew up",
            "job_id": "j1",
        })
        assert "Failed" in out["text"]
        assert "diarize" in out["text"]
        assert "MPS blew up" in out["text"]
        kb = out["reply_markup"]["inline_keyboard"]
        assert any("job:retry:j1" == b["callback_data"] for row in kb for b in row)

    def test_persona_generated_vs_refreshed(self):
        gen = telegram_messages._render_persona_generated({
            "display_name": "Lex", "confidence": 0.83, "channel_id": "c2",
            "is_refresh": False,
        })
        assert "ready" in gen["text"]
        assert "✨" in gen["text"]
        refr = telegram_messages._render_persona_generated({
            "display_name": "Lex", "confidence": 0.83, "channel_id": "c2",
            "is_refresh": True,
        })
        assert "refreshed" in refr["text"]
        assert "♻️" in refr["text"]
        assert gen["dedupe_key"] != refr["dedupe_key"]

    def test_cost_thresholds(self):
        warn = telegram_messages._render_cost_threshold_80({"spent": 4.0, "cap": 5.0})
        assert "80%" in warn["text"]
        fatal = telegram_messages._render_cost_threshold_100({"spent": 5.0, "cap": 5.0})
        assert "exceeded" in fatal["text"]

    def test_digest_weekly_requires_text(self):
        with pytest.raises(telegram_messages.UnknownEvent):
            telegram_messages._render_digest_weekly({})


# ---------------------------------------------------------------------------
# notify() dispatch
# ---------------------------------------------------------------------------


class TestNotifyDispatch:
    def test_sends_payload_for_video_completed(self, monkeypatch):
        captured = {}

        def fake_post(url, data=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            return MagicMock()

        import requests as _requests
        monkeypatch.setattr(_requests, "post", fake_post)

        telegram_notify.notify("video.completed", {
            "video_id": "vid-1", "title": "Ep", "duration": 60, "speakers": 2,
        })

        assert "sendMessage" in captured["url"]
        assert captured["data"]["chat_id"] == 999
        assert "Ep" in captured["data"]["text"]

    def test_mute_prevents_send(self, monkeypatch, tmp_path):
        from app.config import settings
        state = {"enabled": True, "muted_events": ["video.completed"]}
        (tmp_path / "state.json").write_text(json.dumps(state))
        monkeypatch.setattr(settings, "telegram_notify_state_path", str(tmp_path / "state.json"))

        sent = []
        monkeypatch.setattr("requests.post", lambda *a, **kw: sent.append(a) or MagicMock())

        telegram_notify.notify("video.completed", {"video_id": "v", "title": "t"})
        assert sent == []

    def test_global_disable_prevents_send(self, monkeypatch, tmp_path):
        from app.config import settings
        state = {"enabled": False, "muted_events": []}
        (tmp_path / "state.json").write_text(json.dumps(state))
        monkeypatch.setattr(settings, "telegram_notify_state_path", str(tmp_path / "state.json"))

        sent = []
        monkeypatch.setattr("requests.post", lambda *a, **kw: sent.append(a) or MagicMock())

        telegram_notify.notify("video.completed", {"video_id": "v", "title": "t"})
        assert sent == []

    def test_dedupes_repeats_within_window(self, monkeypatch):
        counter = {"n": 0}
        monkeypatch.setattr(
            "requests.post",
            lambda *a, **kw: counter.__setitem__("n", counter["n"] + 1) or MagicMock(),
        )

        for _ in range(5):
            telegram_notify.notify("video.completed", {
                "video_id": "same-id", "title": "same", "duration": 1, "speakers": 1,
            })

        assert counter["n"] == 1

    def test_unknown_event_is_noop(self, monkeypatch):
        sent = []
        monkeypatch.setattr("requests.post", lambda *a, **kw: sent.append(a) or MagicMock())
        telegram_notify.notify("completely.made.up", {})
        assert sent == []

    def test_missing_token_is_noop(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "")
        sent = []
        monkeypatch.setattr("requests.post", lambda *a, **kw: sent.append(a) or MagicMock())
        telegram_notify.notify("video.completed", {
            "video_id": "v", "title": "t", "duration": 1, "speakers": 1,
        })
        assert sent == []

    def test_network_failure_never_raises(self, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("network fell over")

        monkeypatch.setattr("requests.post", boom)
        # Must not raise
        telegram_notify.notify("video.completed", {
            "video_id": "v", "title": "t", "duration": 1, "speakers": 1,
        })


class TestSourceAgnosticEmits:
    """Prove the notifier is called from each hook site."""

    def test_record_pipeline_failure_emits(self, monkeypatch):
        from app.services import pipeline_recovery

        calls = []
        monkeypatch.setattr(
            "app.services.telegram_notify.notify",
            lambda event, payload=None: calls.append((event, payload)),
        )
        # The prior-failure counter and state setter both need a real DB to work;
        # stub them so this test focuses on the notifier wiring.
        monkeypatch.setattr(
            pipeline_recovery, "count_prior_identical_failures",
            lambda db, job, sig: 0,
        )
        monkeypatch.setattr(
            pipeline_recovery, "set_pipeline_job_state",
            lambda *a, **kw: None,
        )

        from types import SimpleNamespace as NS

        job = NS(
            id="job-1",
            video_id="v-1",
            failure_signature=None,
            failure_signature_count=0,
            recovery_status=None,
            recovery_reason=None,
        )
        video = NS(id="v-1", title="Title", status="running", error_message=None)

        pipeline_recovery.record_pipeline_failure(
            db=None,
            job=job,
            video=video,
            stage="transcribe",
            error=RuntimeError("boom"),
            default_message="test failure",
        )

        assert any(event == "video.failed" for event, _ in calls)
        payload = next(p for e, p in calls if e == "video.failed")
        assert payload["stage"] == "transcribe"
        assert payload["title"] == "Title"

    def test_check_budget_emits_80_then_100(self, monkeypatch):
        from app.services import cost_tracker
        from app.config import settings

        monkeypatch.setattr(settings, "daily_llm_budget_usd", 5.0)

        sent = []
        monkeypatch.setattr(
            "app.services.telegram_notify.notify",
            lambda event, payload=None: sent.append(event),
        )

        monkeypatch.setattr(cost_tracker, "get_today_cost", lambda: 4.50)
        try:
            cost_tracker.check_budget()
        except cost_tracker.BudgetExceededError:
            pass
        assert "cost.threshold_80" in sent

        sent.clear()
        monkeypatch.setattr(cost_tracker, "get_today_cost", lambda: 6.0)
        try:
            cost_tracker.check_budget()
        except cost_tracker.BudgetExceededError:
            pass
        assert "cost.threshold_100" in sent
