"""Tests for the Perplexity-style response formatter."""

from __future__ import annotations

import re

from app.services.response_formatter import (
    _fmt_timestamp,
    _parse_bracket_body,
    _parse_timestamp,
    format_response,
)


def _source(
    *,
    idx: str,
    title: str,
    start: float,
    end: float | None = None,
    yt_id: str = "abcDEFGhij0",
    source_type: str = "transcript",
) -> dict:
    return {
        "video_id": f"uuid-{idx}",
        "youtube_video_id": yt_id,
        "video_title": title,
        "start_time": start,
        "end_time": end if end is not None else start + 60,
        "source_type": source_type,
    }


class TestParseTimestamp:
    def test_mm_ss(self):
        assert _parse_timestamp("0:42") == 42
        assert _parse_timestamp("19:07") == 19 * 60 + 7

    def test_h_mm_ss(self):
        assert _parse_timestamp("1:20:05") == 3600 + 20 * 60 + 5


class TestFormatTimestamp:
    def test_under_hour(self):
        assert _fmt_timestamp(42) == "0:42"
        assert _fmt_timestamp(19 * 60 + 7) == "19:07"

    def test_over_hour(self):
        assert _fmt_timestamp(3600 + 5) == "1:00:05"


class TestParseBracketBody:
    def test_pure_index(self):
        sources = [_source(idx="1", title="Ep 1", start=0)]
        chips = _parse_bracket_body("1", sources)
        assert len(chips) == 1
        _, link = chips[0]
        assert "Ep 1" in link
        assert "youtu.be/abcDEFGhij0" in link

    def test_multi_index(self):
        sources = [
            _source(idx="1", title="Ep 1", start=0),
            _source(idx="2", title="Ep 2", start=100, yt_id="yyyYYYyyy22"),
        ]
        chips = _parse_bracket_body("1, 2", sources)
        assert len(chips) == 2
        assert "Ep 1" in chips[0][1]
        assert "Ep 2" in chips[1][1]

    def test_index_with_timestamp(self):
        sources = [_source(idx="1", title="Ep 1", start=0)]
        chips = _parse_bracket_body("1 19:07", sources)
        assert len(chips) == 1
        _, link = chips[0]
        assert "19:07" in link
        assert "?t=1147" in link

    def test_index_with_range(self):
        sources = [_source(idx="1", title="Ep 1", start=0)]
        chips = _parse_bracket_body("1 19:07 - 19:51", sources)
        assert len(chips) == 1
        assert "19:07" in chips[0][1]

    def test_timestamp_only_resolves_by_window(self):
        sources = [
            _source(idx="1", title="Ep 1", start=0, end=1200),
            _source(idx="2", title="Ep 2", start=1200, end=2400),
        ]
        # 19:07 = 1147s → should match first chunk's window [0, 1200]
        chips = _parse_bracket_body("19:07 - 19:51", sources)
        assert len(chips) == 1
        assert "Ep 1" in chips[0][1]

    def test_unparseable_body_yields_no_chip(self):
        sources = [_source(idx="1", title="Ep 1", start=0)]
        assert _parse_bracket_body("Summary", sources) == []
        assert _parse_bracket_body("see chapter 3", sources) == []

    def test_out_of_range_index_yields_no_chip(self):
        sources = [_source(idx="1", title="Ep 1", start=0)]
        assert _parse_bracket_body("99", sources) == []


class TestFormatResponseStructure:
    def test_inline_citations_moved_to_end_of_paragraph(self):
        sources = [_source(idx="1", title="Ep 1", start=0)]
        raw = "First point [1]. Second point continues [1]."
        out = format_response(raw, sources)
        # Chip should live at paragraph end, not inline
        assert "[1]" not in out
        assert out.endswith(")")  # closes a markdown link
        # Dedupe — two citations of same chunk collapse to one chip
        assert out.count("▶ Ep 1") == 1

    def test_paragraphs_get_independent_chip_groups(self):
        sources = [
            _source(idx="1", title="Ep 1", start=0),
            _source(idx="2", title="Ep 2", start=100, yt_id="yyyYYYyyy22"),
        ]
        raw = "Paragraph one with [1].\n\nParagraph two with [2]."
        out = format_response(raw, sources)
        parts = out.split("\n\n")
        assert len(parts) == 2
        assert "Ep 1" in parts[0] and "Ep 2" not in parts[0]
        assert "Ep 2" in parts[1] and "Ep 1" not in parts[1]

    def test_timestamp_only_citation_replaced(self):
        sources = [_source(idx="1", title="Ep 1", start=0, end=1200)]
        raw = 'Peter says "I think" [19:07 - 19:51] in response.'
        out = format_response(raw, sources)
        assert "[19:07 - 19:51]" not in out
        assert "▶ Ep 1" in out
        assert "19:07" in out

    def test_multiple_citations_capped_at_3_per_paragraph(self):
        sources = [
            _source(idx=str(i), title=f"Ep {i}", start=i * 100, yt_id=f"{i}" * 11)
            for i in range(1, 6)
        ]
        raw = "Everything citing [1] and [2] and [3] and [4] and [5]."
        out = format_response(raw, sources)
        # 5 unique chips, only 3 rendered
        chip_count = out.count("▶ Ep ")
        assert chip_count == 3

    def test_empty_content_returns_empty(self):
        assert format_response("", []) == ""

    def test_no_citations_passes_through(self):
        raw = "Just a paragraph with no citations."
        out = format_response(raw, [])
        assert out == raw

    def test_unparseable_bracket_kept_in_place(self):
        """We should not mangle things like '[Summary]' when we can't resolve."""
        sources = [_source(idx="1", title="Ep 1", start=0)]
        raw = "Peter mentioned [Summary] in his talk."
        out = format_response(raw, sources)
        assert "[Summary]" in out

    def test_summary_chunk_chip_rendering(self):
        sources = [_source(idx="1", title="Ep 1", start=0, source_type="summary")]
        out = format_response("Overview from [1].", sources)
        assert "📄 Ep 1 · Summary" in out

    def test_fail_open_on_internal_error(self, monkeypatch):
        """If the paragraph processor blows up, return original content."""
        def boom(p, s):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "app.services.response_formatter._process_paragraph", boom
        )
        raw = "Some answer [1]."
        out = format_response(raw, [_source(idx="1", title="Ep 1", start=0)])
        assert out == raw


class TestRealWorldShapes:
    """Shape fixtures inspired by actual Haiku output from the bot."""

    def test_persona_style_with_timestamp_ranges(self):
        sources = [
            _source(
                idx="1",
                title="State of the Claw — Peter Steinberger",
                start=1140,  # ~19:00
                end=1195,
                yt_id="STATECLAW01",
            ),
            _source(
                idx="2",
                title="State of the Claw — Peter Steinberger",
                start=994,  # ~16:34
                end=1065,
                yt_id="STATECLAW01",
            ),
        ]
        raw = (
            "Peter addresses the concern directly. He notes [19:07 - 19:51]:\n\n"
            'People were worried about "Close Claw".\n\n'
            "To address this he built the OpenClaw Foundation [16:34 - 17:44]."
        )
        out = format_response(raw, sources)
        # All timestamp citations replaced with chips
        assert "[19:07 - 19:51]" not in out
        assert "[16:34 - 17:44]" not in out
        # Chip text appears
        assert "▶ State of the Claw" in out
        # Paragraph boundaries preserved
        assert out.count("\n\n") == 2
