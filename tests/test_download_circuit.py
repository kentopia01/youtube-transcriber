from __future__ import annotations

import json

from app.services import download_circuit as mod


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
            self.sets.pop(key, None)

    def sadd(self, key, value):
        values = self.sets.setdefault(key, set())
        before = len(values)
        values.add(value)
        return int(len(values) != before)

    def expire(self, key, seconds):
        return True

    def scard(self, key):
        return len(self.sets.get(key, set()))


def test_access_degradation_classifier_covers_observed_antibot_signature():
    assert mod.is_youtube_access_degradation(
        "ERROR: [youtube] abc: Sign in to confirm you’re not a bot"
    )
    assert mod.is_youtube_access_degradation("HTTP Error 403: Forbidden")
    assert not mod.is_youtube_access_degradation("Video duration exceeds limit")


def test_circuit_opens_only_after_distinct_video_threshold(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(mod.settings, "download_circuit_enabled", True)
    monkeypatch.setattr(mod.settings, "download_circuit_failure_threshold", 2)
    monkeypatch.setattr(mod.settings, "download_circuit_cooldown_seconds", 1800)

    first = mod.record_download_access_failure(
        "video-a", "HTTP Error 403: Forbidden", client=client, now=1000
    )
    duplicate = mod.record_download_access_failure(
        "video-a", "Sign in to confirm you're not a bot", client=client, now=1001
    )
    second = mod.record_download_access_failure(
        "video-b", "Sign in to confirm you're not a bot", client=client, now=1002
    )

    assert first.open is False and first.failure_count == 1
    assert duplicate.open is False and duplicate.failure_count == 1
    assert second.open is True and second.failure_count == 2
    payload = json.loads(client.values[mod._OPEN_KEY])
    assert payload["open_until"] == 2802


def test_success_closes_circuit(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(mod.settings, "download_circuit_enabled", True)
    client.values[mod._OPEN_KEY] = json.dumps(
        {"open_until": 9999, "failure_count": 2, "reason": "test"}
    )
    client.sets[mod._FAILURE_SET_KEY] = {"a", "b"}

    mod.record_download_access_success(client=client)

    assert mod.get_download_circuit_state(client=client, now=1000).open is False


def test_redis_failure_is_fail_open(monkeypatch):
    class _BrokenRedis:
        def get(self, key):
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(mod.settings, "download_circuit_enabled", True)

    state = mod.get_download_circuit_state(client=_BrokenRedis())

    assert state.open is False
    assert state.available is False
