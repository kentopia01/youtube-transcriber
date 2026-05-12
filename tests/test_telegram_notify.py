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
    telegram_notify._DEDUPE_PENDING.clear()
    yield
    telegram_notify._DEDUPE.clear()
    telegram_notify._DEDUPE_PENDING.clear()


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

    def test_video_report_ready_is_buttonless_document_event(self, tmp_path):
        report = tmp_path / "report.html"
        report.write_text("<html>report</html>")
        out = telegram_messages._render_video_report_ready({
            "video_id": "v1",
            "title": "Ep <12>",
            "channel_name": "20VC",
            "duration": 3600,
            "report_path": str(report),
        })
        assert "Report ready" in out["text"]
        assert "Attached: summary report" not in out["text"]
        assert "Ep &lt;12&gt;" in out["text"]
        assert "20VC · 1h 0m" in out["text"]
        assert out["reply_markup"] is None
        assert out["document_path"] == str(report)
        assert out["document_mime_type"] == "text/html"

    def test_video_report_ready_uses_summary_as_caption(self, tmp_path):
        report = tmp_path / "report.html"
        report.write_text("<html>report</html>")
        out = telegram_messages._render_video_report_ready({
            "video_id": "v1",
            "title": "Ep",
            "report_path": str(report),
            "summary": """
## 30-second take
The speaker argues GPT-5.5 is best used as an execution model when another model writes the plan.

## Key takes
- It performs much better on coding benchmarks with a detailed Opus-written plan.
- It is faster than Opus but weaker for sharp judgment.
""",
        })

        assert "execution model" in out["text"]
        assert "coding benchmarks" in out["text"]
        assert "Attached:" not in out["text"]

    def test_video_report_ready_requires_path(self):
        with pytest.raises(telegram_messages.UnknownEvent):
            telegram_messages._render_video_report_ready({"video_id": "v1", "title": "Ep"})

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

    def test_sends_document_for_video_report_ready(self, monkeypatch, tmp_path):
        report = tmp_path / "report.html"
        report.write_text("<html>report</html>")
        captured = {}

        def fake_post(url, data=None, files=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["timeout"] = timeout
            doc = files["document"]
            captured["filename"] = doc[0]
            captured["mime"] = doc[2]
            captured["content"] = doc[1].read()
            return MagicMock(ok=True)

        monkeypatch.setattr("requests.post", fake_post)

        ok = telegram_notify.notify("video.report_ready", {
            "video_id": "vid-1",
            "title": "Ep",
            "channel_name": "20VC",
            "duration": 60,
            "report_path": str(report),
        })

        assert ok is True
        assert "sendDocument" in captured["url"]
        assert captured["data"]["chat_id"] == 999
        assert "Report ready" in captured["data"]["caption"]
        assert "Attached:" not in captured["data"]["caption"]
        assert captured["data"]["parse_mode"] == "HTML"
        assert captured["filename"] == "report.html"
        assert captured["mime"] == "text/html"
        assert captured["content"] == b"<html>report</html>"

    def test_report_ready_missing_file_returns_false(self, monkeypatch, tmp_path):
        logs = []
        monkeypatch.setattr(
            telegram_notify.logger,
            "warning",
            lambda event, **fields: logs.append((event, fields)),
        )

        ok = telegram_notify.notify("video.report_ready", {
            "video_id": "vid-1",
            "title": "Ep",
            "report_path": str(tmp_path / "missing.html"),
        })

        assert ok is False
        event, fields = logs[0]
        assert event == "telegram_notify_document_missing"
        assert fields["boundary"] == "telegram_notify.send_document"
        assert fields["category"] == "expected_external_failure"
        assert fields["event_type"] == "video.report_ready"
        assert fields["video_id"] == "vid-1"
        assert fields["report_path"].endswith("missing.html")
        assert fields["outcome"] == "suppressed"

    def test_mute_prevents_send(self, monkeypatch, tmp_path):
        from app.config import settings
        state = {"enabled": True, "muted_events": ["video.completed"]}
        (tmp_path / "state.json").write_text(json.dumps(state))
        monkeypatch.setattr(settings, "telegram_notify_state_path", str(tmp_path / "state.json"))

        sent = []
        monkeypatch.setattr("requests.post", lambda *a, **kw: sent.append(a) or MagicMock())

        ok = telegram_notify.notify("video.completed", {"video_id": "v", "title": "t"})
        assert ok is False
        assert sent == []

    def test_global_disable_prevents_send(self, monkeypatch, tmp_path):
        from app.config import settings
        state = {"enabled": False, "muted_events": []}
        (tmp_path / "state.json").write_text(json.dumps(state))
        monkeypatch.setattr(settings, "telegram_notify_state_path", str(tmp_path / "state.json"))

        sent = []
        monkeypatch.setattr("requests.post", lambda *a, **kw: sent.append(a) or MagicMock())

        ok = telegram_notify.notify("video.completed", {"video_id": "v", "title": "t"})
        assert ok is False
        assert sent == []

    def test_dedupes_repeats_within_window(self, monkeypatch):
        counter = {"n": 0}
        debug_logs = []
        monkeypatch.setattr(
            telegram_notify.logger,
            "debug",
            lambda event, **fields: debug_logs.append((event, fields)),
        )
        monkeypatch.setattr(
            "requests.post",
            lambda *a, **kw: counter.__setitem__("n", counter["n"] + 1) or MagicMock(),
        )

        for _ in range(5):
            telegram_notify.notify("video.completed", {
                "video_id": "same-id", "title": "same", "duration": 1, "speakers": 1,
            })

        assert counter["n"] == 1
        deduped = [fields for event, fields in debug_logs if event == "telegram_notify_deduped"]
        assert deduped
        assert deduped[0]["boundary"] == "telegram_notify.dedupe"
        assert deduped[0]["category"] == "best_effort_side_effect"
        assert deduped[0]["video_id"] == "same-id"
        assert deduped[0]["outcome"] == "suppressed"

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
        logs = []
        monkeypatch.setattr(
            telegram_notify.logger,
            "warning",
            lambda event, **fields: logs.append((event, fields)),
        )

        def boom(*a, **kw):
            raise RuntimeError("network fell over")

        monkeypatch.setattr("requests.post", boom)
        # Must not raise
        telegram_notify.notify("video.completed", {
            "video_id": "v", "title": "t", "duration": 1, "speakers": 1,
        })

        event, fields = logs[0]
        assert event == "telegram_notify_send_failed"
        assert fields["boundary"] == "telegram_notify.send_message"
        assert fields["category"] == "expected_external_failure"
        assert fields["event_type"] == "video.completed"
        assert fields["video_id"] == "v"
        assert fields["exception_type"] == "RuntimeError"
        assert fields["outcome"] == "suppressed"

    def test_failed_send_does_not_poison_dedupe(self, monkeypatch):
        calls = {"n": 0}

        def flaky_post(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("network fell over")
            return MagicMock(ok=True)

        monkeypatch.setattr("requests.post", flaky_post)

        first = telegram_notify.notify("video.completed", {
            "video_id": "same-id", "title": "same", "duration": 1, "speakers": 1,
        })
        second = telegram_notify.notify("video.completed", {
            "video_id": "same-id", "title": "same", "duration": 1, "speakers": 1,
        })

        assert first is False
        assert second is True
        assert calls["n"] == 2


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
