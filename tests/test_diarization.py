"""Tests for speaker diarization and alignment services."""

import sys
import types

import pytest

from app.services import diarization as diarization_service
from app.services.alignment import _find_speaker, align_and_merge


class TestFindSpeaker:
    """Test the majority-vote speaker assignment."""

    def test_single_speaker_full_overlap(self):
        diar = [{"start": 0.0, "end": 10.0, "speaker": "SPEAKER_00"}]
        assert _find_speaker(0.0, 5.0, diar) == "SPEAKER_00"

    def test_multiple_speakers_majority_wins(self):
        diar = [
            {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
            {"start": 3.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]
        # Segment 2.0-8.0: SPEAKER_00 covers 1.0s, SPEAKER_01 covers 5.0s
        assert _find_speaker(2.0, 8.0, diar) == "SPEAKER_01"

    def test_no_overlap_returns_none(self):
        diar = [{"start": 10.0, "end": 20.0, "speaker": "SPEAKER_00"}]
        assert _find_speaker(0.0, 5.0, diar) is None

    def test_exact_boundary(self):
        diar = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]
        # Exactly at boundary — no overlap with SPEAKER_00
        assert _find_speaker(5.0, 8.0, diar) == "SPEAKER_01"

    def test_equal_overlap_picks_one(self):
        diar = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]
        # 3.0-7.0: both have 2.0s overlap
        result = _find_speaker(3.0, 7.0, diar)
        assert result in ("SPEAKER_00", "SPEAKER_01")

    def test_empty_diarization(self):
        assert _find_speaker(0.0, 5.0, []) is None


class TestAlignAndMerge:
    """Test alignment and speaker merge (without whisperX)."""

    def test_no_diarization_returns_none_speakers(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "hello", "confidence": -0.5},
        ]
        result = align_and_merge("/fake.wav", segments, [], "en")
        assert len(result) == 1
        assert result[0]["speaker"] is None
        assert result[0]["text"] == "hello"

    def test_basic_speaker_assignment(self):
        segments = [
            {"start": 0.0, "end": 3.0, "text": "Hello everyone", "confidence": -0.3},
            {"start": 3.5, "end": 7.0, "text": "Thanks for having me", "confidence": -0.4},
        ]
        diar = [
            {"start": 0.0, "end": 3.5, "speaker": "SPEAKER_00"},
            {"start": 3.5, "end": 8.0, "speaker": "SPEAKER_01"},
        ]
        result = align_and_merge("/fake.wav", segments, diar, "en")
        assert len(result) == 2
        assert result[0]["speaker"] == "SPEAKER_00"
        assert result[1]["speaker"] == "SPEAKER_01"

    def test_preserves_original_fields(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "test", "confidence": -0.2},
        ]
        diar = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
        result = align_and_merge("/fake.wav", segments, diar, "en")
        assert result[0]["text"] == "test"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.0


class _FakeTurn:
    def __init__(self, start: float, end: float):
        self.start = start
        self.end = end


class _FakeDiarizationResult:
    def __init__(self, tracks):
        self._tracks = tracks

    def itertracks(self, yield_label=False):
        for start, end, speaker in self._tracks:
            yield _FakeTurn(start, end), None, speaker


class _FakeDiarizeOutput:
    def __init__(self, speaker_tracks, exclusive_tracks=None):
        self.speaker_diarization = _FakeDiarizationResult(speaker_tracks)
        if exclusive_tracks is not None:
            self.exclusive_speaker_diarization = _FakeDiarizationResult(exclusive_tracks)


def _patch_pyannote(monkeypatch, pipeline_cls):
    fake_audio_module = types.ModuleType("pyannote.audio")
    fake_audio_module.Pipeline = pipeline_cls
    fake_pyannote_module = types.ModuleType("pyannote")
    fake_pyannote_module.audio = fake_audio_module
    monkeypatch.setitem(sys.modules, "pyannote", fake_pyannote_module)
    monkeypatch.setitem(sys.modules, "pyannote.audio", fake_audio_module)


class TestDiarizeService:
    def test_diarize_uses_audio_path_by_default(self, monkeypatch):
        calls = []

        class FakePipeline:
            @classmethod
            def from_pretrained(cls, *args, **kwargs):
                return cls()

            def __call__(self, audio_input, **kwargs):
                calls.append(audio_input)
                return _FakeDiarizationResult([(0.0, 1.0, "SPEAKER_00")])

        _patch_pyannote(monkeypatch, FakePipeline)

        segments = diarization_service.diarize("/tmp/demo.wav", hf_token="hf_test")

        assert calls == ["/tmp/demo.wav"]
        assert segments == [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]

    def test_diarize_falls_back_when_audio_decoder_missing(self, monkeypatch):
        calls = []

        class FakePipeline:
            @classmethod
            def from_pretrained(cls, *args, **kwargs):
                return cls()

            def __call__(self, audio_input, **kwargs):
                calls.append(audio_input)
                if isinstance(audio_input, str):
                    raise NameError("name 'AudioDecoder' is not defined")
                return _FakeDiarizationResult([(1.5, 2.5, "SPEAKER_01")])

        _patch_pyannote(monkeypatch, FakePipeline)
        monkeypatch.setattr(
            diarization_service,
            "_load_audio_for_pyannote",
            lambda path: {"waveform": "wf", "sample_rate": 16000},
        )

        segments = diarization_service.diarize("/tmp/demo.wav", hf_token="hf_test")

        assert calls == ["/tmp/demo.wav", {"waveform": "wf", "sample_rate": 16000}]
        assert segments == [{"start": 1.5, "end": 2.5, "speaker": "SPEAKER_01"}]

    def test_diarize_handles_pyannote_v4_diarize_output(self, monkeypatch):
        class FakePipeline:
            @classmethod
            def from_pretrained(cls, *args, **kwargs):
                return cls()

            def __call__(self, audio_input, **kwargs):
                return _FakeDiarizeOutput(
                    speaker_tracks=[(0.0, 2.0, "SPEAKER_00")],
                    exclusive_tracks=[(0.25, 1.75, "SPEAKER_01")],
                )

        _patch_pyannote(monkeypatch, FakePipeline)

        segments = diarization_service.diarize("/tmp/demo.wav", hf_token="hf_test")

        # Prefer exclusive diarization when present (pyannote>=4 output)
        assert segments == [{"start": 0.25, "end": 1.75, "speaker": "SPEAKER_01"}]

    def test_diarize_handles_pyannote_v4_output_without_exclusive(self, monkeypatch):
        class FakePipeline:
            @classmethod
            def from_pretrained(cls, *args, **kwargs):
                return cls()

            def __call__(self, audio_input, **kwargs):
                return _FakeDiarizeOutput(
                    speaker_tracks=[(2.0, 3.0, "SPEAKER_02")],
                    exclusive_tracks=None,
                )

        _patch_pyannote(monkeypatch, FakePipeline)

        segments = diarization_service.diarize("/tmp/demo.wav", hf_token="hf_test")

        assert segments == [{"start": 2.0, "end": 3.0, "speaker": "SPEAKER_02"}]
