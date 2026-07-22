from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence

from app.services.reader import ReaderBlock

GENERATOR_VERSION = "reader-chapters-v1"


def chapter_source_fingerprint(blocks: Sequence[ReaderBlock]) -> str:
    digest = hashlib.sha256()
    for block in blocks:
        digest.update(f"{block.anchor}\0{block.start_time}\0{block.end_time}\0{block.text}\n".encode())
    return digest.hexdigest()


def deterministic_chapters(
    blocks: Sequence[ReaderBlock], *, interval_seconds: float = 600
) -> list[dict]:
    if not blocks:
        return []
    selected = [blocks[0]]
    next_boundary = blocks[0].start_time + interval_seconds
    for block in blocks[1:]:
        if block.start_time >= next_boundary:
            selected.append(block)
            next_boundary = block.start_time + interval_seconds

    chapters = []
    for index, block in enumerate(selected):
        text = " ".join(block.text.split())
        title = text[:72].rstrip(" ,.;:-") or f"Section {index + 1}"
        end_time = (
            selected[index + 1].start_time
            if index + 1 < len(selected)
            else blocks[-1].end_time
        )
        chapters.append(
            {
                "title": title,
                "anchor": block.anchor,
                "start_time": block.start_time,
                "end_time": end_time,
            }
        )
    return chapters


def validate_semantic_chapters(raw: object, blocks: Sequence[ReaderBlock]) -> list[dict]:
    if not isinstance(raw, list) or not raw or len(raw) > 30:
        raise ValueError("chapters must be a non-empty list of at most 30 items")
    by_anchor = {block.anchor: block for block in blocks}
    chapters = []
    previous_start = -1.0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("chapter item must be an object")
        title = " ".join(str(item.get("title", "")).split())[:120]
        anchor = str(item.get("anchor", ""))
        block = by_anchor.get(anchor)
        if not title or block is None or block.start_time < previous_start:
            raise ValueError("chapter title, anchor, or order is invalid")
        chapters.append(
            {
                "title": title,
                "anchor": anchor,
                "start_time": block.start_time,
                "end_time": block.end_time,
            }
        )
        previous_start = block.start_time
    for index in range(len(chapters) - 1):
        chapters[index]["end_time"] = chapters[index + 1]["start_time"]
    chapters[-1]["end_time"] = blocks[-1].end_time
    return chapters


def parse_semantic_chapter_response(content: str, blocks: Sequence[ReaderBlock]) -> list[dict]:
    candidate = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    return validate_semantic_chapters(json.loads(candidate), blocks)


def semantic_chapter_prompt(blocks: Sequence[ReaderBlock], max_chars: int = 80_000) -> str:
    lines = []
    used = 0
    for block in blocks:
        line = f"ANCHOR={block.anchor} TIME={block.start_time:.1f}\n{block.text}\n"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    return (
        "Create 3-12 concise semantic chapters for this transcript. Return only a JSON "
        "array of objects with title and anchor. Use only anchors shown below, keep source "
        "order, and do not invent topics.\n\n" + "\n".join(lines)
    )
