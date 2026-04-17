"""Tests for the compression task."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.tasks import compress_stale_videos as mod


class TestResolveWavPath:
    def test_uses_explicit_path_when_set(self):
        v = SimpleNamespace(audio_file_path="/data/audio/foo.wav", youtube_video_id="abc")
        p = mod._resolve_wav_path(v)
        assert p == Path("/data/audio/foo.wav")

    def test_falls_back_to_dir_and_id(self, monkeypatch):
        monkeypatch.setattr(mod.settings, "audio_dir", "/data/audio")
        v = SimpleNamespace(audio_file_path=None, youtube_video_id="xyz987")
        p = mod._resolve_wav_path(v)
        assert p == Path("/data/audio/xyz987.wav")


class TestCompressOne:
    def test_deletes_existing_wav_and_sets_timestamp(self, tmp_path):
        wav = tmp_path / "abc.wav"
        wav.write_bytes(b"\x00" * 1024)

        video = SimpleNamespace(
            id=uuid.uuid4(),
            youtube_video_id="abc",
            audio_file_path=str(wav),
            compressed_at=None,
        )

        res = mod._compress_one(db=None, video=video)
        assert res["wav_deleted"] is True
        assert res["bytes_reclaimed"] == 1024
        assert video.compressed_at is not None
        assert not wav.exists()

    def test_missing_wav_still_marks_compressed(self, tmp_path):
        video = SimpleNamespace(
            id=uuid.uuid4(),
            youtube_video_id="missing",
            audio_file_path=str(tmp_path / "does-not-exist.wav"),
            compressed_at=None,
        )
        res = mod._compress_one(db=None, video=video)
        assert res["wav_deleted"] is False
        assert res["note"] == "wav_already_absent"
        assert video.compressed_at is not None


class TestEndToEnd:
    def test_disabled_via_settings_skips(self, monkeypatch):
        monkeypatch.setattr(mod.settings, "compression_enabled", False)
        result = mod.compress_stale_videos()
        assert result["skipped"] == "disabled"
        assert result["processed"] == 0

    def test_runs_and_returns_stats(self, monkeypatch):
        """Integration-ish: mocks out the DB layer but exercises the full flow."""
        monkeypatch.setattr(mod.settings, "compression_enabled", True)

        fake_video = SimpleNamespace(
            id=uuid.uuid4(),
            youtube_video_id="test123",
            audio_file_path=None,
            compressed_at=None,
            status="completed",
            last_activity_at=datetime.now(UTC) - timedelta(days=60),
        )

        # Stub the session + query chain
        class FakeExec:
            def scalars(self):
                class _S:
                    def all(inner_self):
                        return [fake_video]
                return _S()

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, stmt):
                return FakeExec()

            def commit(self):
                pass

        monkeypatch.setattr(mod, "create_engine", lambda *a, **kw: MagicMock(dispose=lambda: None))
        monkeypatch.setattr(mod, "Session", lambda engine: FakeSession())

        # Ensure _resolve_wav_path returns a path that doesn't exist → note=wav_already_absent
        monkeypatch.setattr(mod, "_resolve_wav_path", lambda v: Path("/nonexistent.wav"))

        result = mod.compress_stale_videos_once()
        assert result["processed"] == 1
        assert result["stale_days"] == mod.settings.compression_stale_days
