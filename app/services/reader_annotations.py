from __future__ import annotations

import re
from html import escape
from dataclasses import dataclass
from typing import Sequence

from app.models.reader_annotation import ReaderAnnotation
from app.services.reader import ReaderBlock


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


@dataclass(frozen=True)
class ReconciledAnchor:
    block_anchor: str | None
    start_offset: int
    end_offset: int
    status: str


def reconcile_annotation(annotation: ReaderAnnotation, blocks: Sequence[ReaderBlock]) -> ReconciledAnchor:
    exact = next((block for block in blocks if block.anchor == annotation.block_anchor), None)
    if exact:
        return ReconciledAnchor(exact.anchor, annotation.start_offset, annotation.end_offset, "attached")
    snapshot = _normalized(annotation.selected_text_snapshot or "")
    if snapshot:
        for block in blocks:
            # Preserve character offsets whenever the text survives verbatim.
            # Whitespace-normalized matching is only an attachment signal; its
            # offsets do not map safely back to the original block.
            offset = block.text.casefold().find(
                (annotation.selected_text_snapshot or "").strip().casefold()
            )
            if offset >= 0:
                return ReconciledAnchor(
                    block.anchor,
                    offset,
                    offset + len((annotation.selected_text_snapshot or "").strip()),
                    "reattached",
                )
            if snapshot in _normalized(block.text):
                return ReconciledAnchor(block.anchor, 0, 0, "reattached")
    if blocks:
        nearest = min(blocks, key=lambda block: abs(block.start_time - annotation.start_timestamp_seconds))
        return ReconciledAnchor(nearest.anchor, 0, 0, "reattached")
    return ReconciledAnchor(None, 0, 0, "orphaned")


def annotation_dict(annotation: ReaderAnnotation, reconciled: ReconciledAnchor | None = None) -> dict:
    anchor = reconciled or ReconciledAnchor(annotation.block_anchor, annotation.start_offset, annotation.end_offset, annotation.reconciliation_status)
    return {
        "id": str(annotation.id),
        "video_id": str(annotation.video_id),
        "annotation_type": annotation.annotation_type,
        "block_anchor": anchor.block_anchor,
        "start_timestamp_seconds": annotation.start_timestamp_seconds,
        "end_timestamp_seconds": annotation.end_timestamp_seconds,
        "start_offset": anchor.start_offset,
        "end_offset": anchor.end_offset,
        "selected_text_snapshot": annotation.selected_text_snapshot,
        "note_text": annotation.note_text,
        "reconciliation_status": anchor.status,
        "created_at": annotation.created_at.isoformat() if annotation.created_at else None,
        "updated_at": annotation.updated_at.isoformat() if annotation.updated_at else None,
    }


def export_annotations_markdown(title: str, annotations: Sequence[ReaderAnnotation]) -> str:
    safe_title = escape(title.replace("\n", " ").strip())
    lines = [f"# {safe_title}", ""]
    for annotation in sorted(annotations, key=lambda item: (item.start_timestamp_seconds, str(item.id))):
        minutes, seconds = divmod(int(annotation.start_timestamp_seconds), 60)
        lines.append(f"## {annotation.annotation_type.capitalize()} — {minutes}:{seconds:02d}")
        if annotation.selected_text_snapshot:
            quote = escape(annotation.selected_text_snapshot.replace("\n", " ").strip())
            lines.append(f"> {quote}")
        if annotation.note_text:
            lines.extend(["", escape(annotation.note_text.strip())])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
