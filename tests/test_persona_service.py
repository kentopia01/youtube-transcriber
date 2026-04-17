"""Tests for the persona derivation service.

Covers pure-logic paths (JSON parsing, corpus formatting, threshold logic).
The DB-touching helpers are exercised by integration tests in Phase 2.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

from app.services import persona as persona_service
from app.services.persona import (
    PersonaDerivation,
    _build_derivation_user_message,
    _format_corpus_for_derivation,
    _parse_derivation_json,
    derive_persona,
)


def _fake_chunk(idx: int, text: str, source_type: str = "transcript") -> dict:
    return {
        "id": str(uuid.UUID(int=idx)),
        "video_id": str(uuid.UUID(int=900 + idx)),
        "chunk_text": text,
        "start_time": float(idx * 10),
        "end_time": float(idx * 10 + 5),
        "speaker": None,
        "source_type": source_type,
    }


class TestFormatCorpus:
    def test_summary_tag_used_for_summary_chunks(self):
        chunks = [_fake_chunk(1, "intro", "summary")]
        out = _format_corpus_for_derivation(chunks)
        assert "[Summary]" in out
        assert "[Transcript]" not in out

    def test_transcript_tag_default(self):
        chunks = [_fake_chunk(2, "body text")]
        out = _format_corpus_for_derivation(chunks)
        assert "[Transcript]" in out
        assert "id=" in out

    def test_id_appears_so_llm_can_pick_exemplars(self):
        chunks = [_fake_chunk(3, "some quote"), _fake_chunk(4, "another quote")]
        out = _format_corpus_for_derivation(chunks)
        assert str(uuid.UUID(int=3)) in out
        assert str(uuid.UUID(int=4)) in out


class TestBuildUserMessage:
    def test_includes_name_and_description(self):
        chunks = [_fake_chunk(5, "hello")]
        msg = _build_derivation_user_message("Lex Fridman", "A podcast.", chunks)
        assert "Lex Fridman" in msg
        assert "A podcast." in msg
        assert "Number of excerpts: 1" in msg

    def test_no_description_line_when_none(self):
        chunks = [_fake_chunk(6, "x")]
        msg = _build_derivation_user_message("Some Channel", None, chunks)
        assert "Channel description:" not in msg


class TestParseDerivationJson:
    def _minimal_payload(self, exemplar_ids: list[str]) -> dict:
        return {
            "display_name": "Some Voice",
            "persona_prompt": "You are the host...",
            "style_notes": {"tone": "dry"},
            "exemplar_chunk_ids": exemplar_ids,
            "confidence": 0.72,
        }

    def test_plain_json_parses(self):
        ids = [str(uuid.UUID(int=i)) for i in range(3)]
        raw = json.dumps(self._minimal_payload(ids))
        data = _parse_derivation_json(raw, set(ids))
        assert data["display_name"] == "Some Voice"
        assert data["exemplar_chunk_ids"] == ids

    def test_fenced_json_parses(self):
        ids = [str(uuid.UUID(int=7))]
        fenced = "```json\n" + json.dumps(self._minimal_payload(ids)) + "\n```"
        data = _parse_derivation_json(fenced, set(ids))
        assert data["exemplar_chunk_ids"] == ids

    def test_exemplars_outside_corpus_are_dropped(self):
        ids_in_corpus = [str(uuid.UUID(int=11)), str(uuid.UUID(int=12))]
        fake_exemplars = ids_in_corpus + [str(uuid.UUID(int=99))]  # 99 not in corpus
        raw = json.dumps(self._minimal_payload(fake_exemplars))
        data = _parse_derivation_json(raw, set(ids_in_corpus))
        assert data["exemplar_chunk_ids"] == ids_in_corpus

    def test_missing_required_key_raises(self):
        raw = json.dumps({"display_name": "X"})
        with pytest.raises(ValueError, match="derivation missing key"):
            _parse_derivation_json(raw, set())


class TestDerivePersona:
    def test_empty_corpus_raises(self):
        with pytest.raises(ValueError):
            derive_persona("ch", None, [], api_key="k")

    def test_missing_api_key_raises(self, monkeypatch):
        from app import config

        monkeypatch.setattr(config.settings, "anthropic_api_key", "")
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            derive_persona("ch", None, [_fake_chunk(1, "hi")])

    def test_happy_path_parses_llm_output(self, monkeypatch):
        chunks = [_fake_chunk(i, f"line {i}") for i in range(1, 4)]
        valid_ids = [c["id"] for c in chunks]

        fake_resp = MagicMock()
        fake_resp.content = [MagicMock(text=json.dumps({
            "display_name": "All-In",
            "persona_prompt": "You are...",
            "style_notes": {"tone": "opinionated"},
            "exemplar_chunk_ids": valid_ids,
            "confidence": 0.82,
        }))]
        fake_resp.model = "claude-sonnet-4-5"
        fake_resp.usage = MagicMock(input_tokens=1000, output_tokens=200)

        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp

        monkeypatch.setattr(persona_service.anthropic, "Anthropic", lambda api_key: fake_client)
        monkeypatch.setattr(
            "app.services.cost_tracker.check_budget", lambda: None
        )
        monkeypatch.setattr(
            "app.services.cost_tracker.record_usage", lambda *a, **kw: None
        )

        result = derive_persona("All-In Pod", None, chunks, api_key="k", model="claude-sonnet-4-5")

        assert isinstance(result, PersonaDerivation)
        assert result.display_name == "All-In"
        assert result.confidence == pytest.approx(0.82)
        assert result.source_chunk_count == 3
        assert len(result.exemplar_chunk_ids) == 3
        assert result.model == "claude-sonnet-4-5"

    def test_confidence_clamped(self, monkeypatch):
        chunks = [_fake_chunk(1, "line")]
        fake_resp = MagicMock()
        fake_resp.content = [MagicMock(text=json.dumps({
            "display_name": "X",
            "persona_prompt": "Y",
            "style_notes": {},
            "exemplar_chunk_ids": [],
            "confidence": 1.5,
        }))]
        fake_resp.model = "m"
        fake_resp.usage = MagicMock(input_tokens=1, output_tokens=1)

        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp
        monkeypatch.setattr(persona_service.anthropic, "Anthropic", lambda api_key: fake_client)
        monkeypatch.setattr("app.services.cost_tracker.check_budget", lambda: None)
        monkeypatch.setattr("app.services.cost_tracker.record_usage", lambda *a, **kw: None)

        result = derive_persona("ch", None, chunks, api_key="k")
        assert result.confidence == 1.0

    def test_non_numeric_confidence_becomes_zero(self, monkeypatch):
        chunks = [_fake_chunk(1, "line")]
        fake_resp = MagicMock()
        fake_resp.content = [MagicMock(text=json.dumps({
            "display_name": "X",
            "persona_prompt": "Y",
            "style_notes": {},
            "exemplar_chunk_ids": [],
            "confidence": "not a number",
        }))]
        fake_resp.model = "m"
        fake_resp.usage = MagicMock(input_tokens=1, output_tokens=1)

        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp
        monkeypatch.setattr(persona_service.anthropic, "Anthropic", lambda api_key: fake_client)
        monkeypatch.setattr("app.services.cost_tracker.check_budget", lambda: None)
        monkeypatch.setattr("app.services.cost_tracker.record_usage", lambda *a, **kw: None)

        result = derive_persona("ch", None, chunks, api_key="k")
        assert result.confidence == 0.0
