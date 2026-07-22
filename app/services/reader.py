from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Iterable, Sequence

from app.models.reader_state import (
    READER_STATUS_ARCHIVED,
    READER_STATUS_FINISHED,
    READER_STATUS_LATER,
    READER_STATUS_READING,
    READER_STATUS_UNREAD,
    ReaderState,
)


_WHITESPACE = re.compile(r"\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ReaderBlock:
    anchor: str
    index: int
    start_time: float
    end_time: float
    text: str
    speaker: str | None
    segment_start_index: int | None
    segment_end_index: int | None
    word_count: int

    def to_dict(self) -> dict:
        return asdict(self)


def _clean_text(value: str | None) -> str:
    return _WHITESPACE.sub(" ", value or "").strip()


def _anchor(start_time: float, text: str) -> str:
    normalized = _clean_text(text).lower().encode("utf-8")
    digest = hashlib.sha1(normalized).hexdigest()[:12]  # noqa: S324 - stable ID, not security
    return f"t-{int(round(max(0.0, start_time))):06d}-{digest}"


def _make_block(index: int, members: Sequence[object]) -> ReaderBlock:
    text = " ".join(_clean_text(getattr(segment, "text", "")) for segment in members).strip()
    start = max(0.0, float(getattr(members[0], "start_time", 0.0) or 0.0))
    end = max(start, float(getattr(members[-1], "end_time", start) or start))
    speakers = {
        _clean_text(getattr(segment, "speaker", None))
        for segment in members
        if _clean_text(getattr(segment, "speaker", None))
    }
    speaker = next(iter(speakers)) if len(speakers) == 1 else None
    indexes = [getattr(segment, "segment_index", None) for segment in members]
    numeric_indexes = [int(value) for value in indexes if value is not None]
    return ReaderBlock(
        anchor=_anchor(start, text),
        index=index,
        start_time=start,
        end_time=end,
        text=text,
        speaker=speaker,
        segment_start_index=min(numeric_indexes) if numeric_indexes else None,
        segment_end_index=max(numeric_indexes) if numeric_indexes else None,
        word_count=len(text.split()),
    )


def _fallback_blocks(full_text: str, duration_seconds: float | None) -> list[ReaderBlock]:
    text = _clean_text(full_text)
    if not text:
        return []
    sentences = [sentence for sentence in _SENTENCE_SPLIT.split(text) if sentence]
    paragraphs: list[str] = []
    current: list[str] = []
    current_length = 0
    for sentence in sentences or [text]:
        if current and current_length + len(sentence) + 1 > 680:
            paragraphs.append(" ".join(current))
            current = []
            current_length = 0
        current.append(sentence)
        current_length += len(sentence) + 1
    if current:
        paragraphs.append(" ".join(current))

    duration = max(float(duration_seconds or 0.0), 0.0)
    total_chars = max(sum(len(paragraph) for paragraph in paragraphs), 1)
    elapsed_chars = 0
    blocks: list[ReaderBlock] = []
    for index, paragraph in enumerate(paragraphs):
        start = duration * elapsed_chars / total_chars if duration else 0.0
        elapsed_chars += len(paragraph)
        end = duration * elapsed_chars / total_chars if duration else start
        blocks.append(
            ReaderBlock(
                anchor=_anchor(start, paragraph),
                index=index,
                start_time=start,
                end_time=max(start, end),
                text=paragraph,
                speaker=None,
                segment_start_index=None,
                segment_end_index=None,
                word_count=len(paragraph.split()),
            )
        )
    return blocks


def build_reader_blocks(
    segments: Iterable[object],
    *,
    full_text: str = "",
    duration_seconds: float | None = None,
    max_chars: int = 680,
    max_seconds: float = 75.0,
    paragraph_gap_seconds: float = 2.5,
) -> list[ReaderBlock]:
    """Merge ordered transcript segments into deterministic readable blocks."""

    ordered = sorted(
        (segment for segment in segments if _clean_text(getattr(segment, "text", ""))),
        key=lambda segment: (
            int(getattr(segment, "segment_index", 0) or 0),
            float(getattr(segment, "start_time", 0.0) or 0.0),
        ),
    )
    if not ordered:
        return _fallback_blocks(full_text, duration_seconds)

    groups: list[list[object]] = []
    current: list[object] = []
    current_chars = 0
    for segment in ordered:
        text = _clean_text(getattr(segment, "text", ""))
        if not current:
            current = [segment]
            current_chars = len(text)
            continue

        first = current[0]
        previous = current[-1]
        first_start = float(getattr(first, "start_time", 0.0) or 0.0)
        next_end = float(getattr(segment, "end_time", first_start) or first_start)
        previous_end = float(getattr(previous, "end_time", first_start) or first_start)
        next_start = float(getattr(segment, "start_time", previous_end) or previous_end)
        current_speaker = _clean_text(getattr(previous, "speaker", None)) or None
        next_speaker = _clean_text(getattr(segment, "speaker", None)) or None
        speaker_changed = bool(
            current_speaker and next_speaker and current_speaker != next_speaker
        )
        too_long = current_chars + len(text) + 1 > max_chars
        too_wide = next_end - first_start > max_seconds
        paragraph_pause = (
            next_start - previous_end >= paragraph_gap_seconds
            and _clean_text(getattr(previous, "text", "")).endswith((".", "!", "?"))
        )
        if speaker_changed or too_long or too_wide or paragraph_pause:
            groups.append(current)
            current = [segment]
            current_chars = len(text)
        else:
            current.append(segment)
            current_chars += len(text) + 1
    if current:
        groups.append(current)
    return [_make_block(index, members) for index, members in enumerate(groups)]


def resolve_resume_block(
    blocks: Sequence[ReaderBlock],
    *,
    anchor: str | None,
    timestamp_seconds: float | None,
) -> ReaderBlock | None:
    if not blocks:
        return None
    if anchor:
        exact = next((block for block in blocks if block.anchor == anchor), None)
        if exact:
            return exact
    if timestamp_seconds is not None:
        timestamp = max(0.0, float(timestamp_seconds))
        containing = next(
            (block for block in blocks if block.start_time <= timestamp <= block.end_time),
            None,
        )
        if containing:
            return containing
        return min(blocks, key=lambda block: abs(block.start_time - timestamp))
    return blocks[0]


def build_reader_outline(
    blocks: Sequence[ReaderBlock], *, section_seconds: float = 600.0
) -> list[dict]:
    """Return deterministic time sections without requiring generated chapters."""
    if not blocks:
        return []
    outline = [blocks[0]]
    next_boundary = section_seconds
    for block in blocks[1:]:
        if block.start_time >= next_boundary:
            outline.append(block)
            next_boundary = (int(block.start_time // section_seconds) + 1) * section_seconds
    return [
        {
            "anchor": block.anchor,
            "start_time": block.start_time,
            "label": "Beginning" if index == 0 else f"Around {int(block.start_time // 60)} min",
        }
        for index, block in enumerate(outline)
    ]


def transcript_fingerprint(blocks: Sequence[ReaderBlock]) -> str:
    payload = "\n".join(f"{block.anchor}|{block.start_time:.3f}|{block.text}" for block in blocks)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_content_chapters(blocks: Sequence[ReaderBlock], *, section_seconds: float = 600.0) -> list[dict]:
    """Content-derived semantic labels with deterministic time fallback."""
    outline = build_reader_outline(blocks, section_seconds=section_seconds)
    by_anchor = {block.anchor: block for block in blocks}
    chapters = []
    for item in outline:
        block = by_anchor[item["anchor"]]
        first_sentence = re.split(r"(?<=[.!?])\s+", block.text, maxsplit=1)[0].strip()
        title = first_sentence[:77] + "…" if len(first_sentence) > 80 else first_sentence
        chapters.append({**item, "title": title or item["label"]})
    return chapters


ALLOWED_STATUS_TRANSITIONS = {
    READER_STATUS_UNREAD: {
        READER_STATUS_UNREAD,
        READER_STATUS_READING,
        READER_STATUS_LATER,
        READER_STATUS_FINISHED,
        READER_STATUS_ARCHIVED,
    },
    READER_STATUS_READING: {
        READER_STATUS_READING,
        READER_STATUS_LATER,
        READER_STATUS_FINISHED,
        READER_STATUS_ARCHIVED,
    },
    READER_STATUS_LATER: {
        READER_STATUS_LATER,
        READER_STATUS_READING,
        READER_STATUS_FINISHED,
        READER_STATUS_ARCHIVED,
    },
    READER_STATUS_FINISHED: {
        READER_STATUS_FINISHED,
        READER_STATUS_READING,
        READER_STATUS_ARCHIVED,
    },
    READER_STATUS_ARCHIVED: {
        READER_STATUS_ARCHIVED,
        READER_STATUS_READING,
        READER_STATUS_LATER,
    },
}


def apply_reader_state_update(
    state: ReaderState,
    *,
    status: str | None = None,
    progress_pct: float | None = None,
    last_block_anchor: str | None = None,
    last_timestamp_seconds: float | None = None,
    now: datetime | None = None,
) -> ReaderState:
    now = now or datetime.now(UTC)
    target_status = status or state.status
    if target_status not in ALLOWED_STATUS_TRANSITIONS.get(state.status, set()):
        raise ValueError(f"Invalid reader status transition: {state.status} -> {target_status}")
    if progress_pct is not None and not 0.0 <= float(progress_pct) <= 100.0:
        raise ValueError("progress_pct must be between 0 and 100")
    if last_timestamp_seconds is not None and float(last_timestamp_seconds) < 0:
        raise ValueError("last_timestamp_seconds must be non-negative")

    state.status = target_status
    if progress_pct is not None:
        state.progress_pct = float(progress_pct)
    if last_block_anchor is not None:
        state.last_block_anchor = last_block_anchor
    if last_timestamp_seconds is not None:
        state.last_timestamp_seconds = float(last_timestamp_seconds)

    if target_status == READER_STATUS_FINISHED:
        state.progress_pct = 100.0
        state.finished_at = state.finished_at or now
        state.started_at = state.started_at or now
    elif target_status == READER_STATUS_READING:
        state.started_at = state.started_at or now
        state.finished_at = None
    state.last_read_at = now
    state.updated_at = now
    return state


def reader_state_dict(state: ReaderState, blocks: Sequence[ReaderBlock]) -> dict:
    resume = resolve_resume_block(
        blocks,
        anchor=state.last_block_anchor,
        timestamp_seconds=state.last_timestamp_seconds,
    )
    return {
        "status": state.status,
        "progress_pct": float(state.progress_pct or 0.0),
        "last_block_anchor": state.last_block_anchor,
        "last_timestamp_seconds": state.last_timestamp_seconds,
        "resume_block_anchor": resume.anchor if resume else None,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "finished_at": state.finished_at.isoformat() if state.finished_at else None,
        "last_read_at": state.last_read_at.isoformat() if state.last_read_at else None,
    }
