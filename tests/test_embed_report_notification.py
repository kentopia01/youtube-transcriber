from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.channel import Channel
from app.tasks import embed as embed_task


class _Query:
    def __init__(self, items):
        self.items = items

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    def __init__(self, channel=None, report=None):
        self.channel = channel
        self.report = report
        self.commits = 0
        self.rollbacks = 0

    def get(self, model, item_id):
        if model is Channel:
            return self.channel if self.channel and self.channel.id == item_id else None
        return None

    def query(self, model):
        return _Query([self.report] if self.report else [])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _video(channel_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        channel_id=channel_id,
        title="Report Video",
        duration_seconds=120.0,
    )


def _transcription():
    return SimpleNamespace(speakers=["SPEAKER_00", "SPEAKER_01"])


def test_notify_completion_sends_report_ready_without_fallback(monkeypatch, tmp_path):
    channel_id = uuid.uuid4()
    channel = SimpleNamespace(id=channel_id, name="20VC")
    video = _video(channel_id)
    report = SimpleNamespace(
        title="Report Video",
        artifact_path=str(tmp_path / "report.html"),
        delivery_status="pending",
        delivery_error=None,
    )
    db = _FakeSession(channel=channel, report=report)

    monkeypatch.setattr(embed_task.settings, "report_generation_enabled", True)
    monkeypatch.setattr(embed_task.settings, "report_delivery_enabled", True)
    monkeypatch.setattr("app.services.reporting.generate_video_report", lambda db_arg, video_id: report)
    calls = []
    monkeypatch.setattr(
        "app.services.telegram_notify.notify",
        lambda event, payload=None: calls.append((event, payload)) or True,
    )

    embed_task._notify_completion(db, video, _transcription())

    assert [event for event, _ in calls] == ["video.report_ready"]
    payload = calls[0][1]
    assert payload["channel_name"] == "20VC"
    assert payload["speakers"] == 2
    assert payload["report_path"] == report.artifact_path
    assert report.delivery_status == "sent"
    assert db.commits == 1


def test_notify_completion_falls_back_when_report_delivery_fails(monkeypatch, tmp_path):
    video = _video()
    report = SimpleNamespace(
        title="Report Video",
        artifact_path=str(tmp_path / "report.html"),
        delivery_status="pending",
        delivery_error=None,
    )
    db = _FakeSession(report=report)

    monkeypatch.setattr(embed_task.settings, "report_generation_enabled", True)
    monkeypatch.setattr(embed_task.settings, "report_delivery_enabled", True)
    monkeypatch.setattr("app.services.reporting.generate_video_report", lambda db_arg, video_id: report)
    calls = []

    def fake_notify(event, payload=None):
        calls.append((event, payload))
        return event != "video.report_ready"

    monkeypatch.setattr("app.services.telegram_notify.notify", fake_notify)

    embed_task._notify_completion(db, video, _transcription())

    assert [event for event, _ in calls] == ["video.report_ready", "video.completed"]
    assert report.delivery_status == "failed"
    assert report.delivery_error == "telegram_notify_returned_false"
    assert db.commits == 1


def test_notify_completion_uses_original_completion_when_reports_disabled(monkeypatch):
    video = _video()
    db = _FakeSession()

    monkeypatch.setattr(embed_task.settings, "report_generation_enabled", False)
    monkeypatch.setattr(embed_task.settings, "report_delivery_enabled", True)
    calls = []
    monkeypatch.setattr(
        "app.services.telegram_notify.notify",
        lambda event, payload=None: calls.append((event, payload)) or True,
    )

    embed_task._notify_completion(db, video, _transcription())

    assert [event for event, _ in calls] == ["video.completed"]
    assert calls[0][1]["title"] == "Report Video"
