"""Whole-corpus retrieval for operator/global video search."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from math import ceil
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.embedding import SUMMARY_SPEAKER_LABEL

DEFAULT_LIMIT = 12
DEFAULT_CANDIDATE_LIMIT = 100
DEFAULT_SUMMARY_LIMIT = 50
DEFAULT_RRF_K = 60
DEFAULT_PER_VIDEO_LIMIT = 3
DEFAULT_MIN_TRANSCRIPT_RATIO = 0.33
MAX_LIMIT = 50
MAX_CANDIDATE_LIMIT = 250
VALID_SOURCE_TYPES = {"all", "transcript", "summary"}


@dataclass(frozen=True)
class GlobalSearchOptions:
    """Bounded knobs for whole-corpus retrieval."""

    limit: int = DEFAULT_LIMIT
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT
    summary_limit: int = DEFAULT_SUMMARY_LIMIT
    per_video_limit: int = DEFAULT_PER_VIDEO_LIMIT
    channel_id: uuid.UUID | None = None
    video_id: uuid.UUID | None = None
    source_type: str = "all"
    rrf_k: int = DEFAULT_RRF_K

    def normalized(self) -> "GlobalSearchOptions":
        source_type = self.source_type if self.source_type in VALID_SOURCE_TYPES else "all"
        return GlobalSearchOptions(
            limit=max(1, min(self.limit, MAX_LIMIT)),
            candidate_limit=max(1, min(self.candidate_limit, MAX_CANDIDATE_LIMIT)),
            summary_limit=max(0, min(self.summary_limit, MAX_CANDIDATE_LIMIT)),
            per_video_limit=max(1, min(self.per_video_limit, MAX_LIMIT)),
            channel_id=self.channel_id,
            video_id=self.video_id,
            source_type=source_type,
            rrf_k=max(1, self.rrf_k),
        )


def _embedding_literal(query_embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in query_embedding) + "]"


def _source_type_for_speaker(speaker: str | None) -> str:
    return "summary" if speaker == SUMMARY_SPEAKER_LABEL else "transcript"


def _build_global_where_clause(
    channel_id: uuid.UUID | None = None,
    source_type: str = "all",
    video_id: uuid.UUID | None = None,
) -> tuple[str, dict[str, Any]]:
    conditions = []
    params: dict[str, Any] = {"summary_label": SUMMARY_SPEAKER_LABEL}

    if channel_id:
        conditions.append("v.channel_id = :channel_id")
        params["channel_id"] = str(channel_id)
    if video_id:
        conditions.append("v.id = :video_id")
        params["video_id"] = str(video_id)

    if source_type == "summary":
        conditions.append("ec.speaker = :summary_label")
    elif source_type == "transcript":
        conditions.append("(ec.speaker IS NULL OR ec.speaker <> :summary_label)")

    if not conditions:
        return "", params
    return " WHERE " + " AND ".join(conditions), params


def _row_to_candidate(row: Any, lane: str, rank: int) -> dict[str, Any]:
    speaker = getattr(row, "speaker", None)
    source_type = _source_type_for_speaker(speaker)
    start_time = getattr(row, "start_time", None)
    youtube_video_id = getattr(row, "youtube_video_id", None)

    candidate = {
        "id": str(getattr(row, "id")),
        "video_id": str(getattr(row, "video_id")),
        "video_title": getattr(row, "video_title", ""),
        "youtube_video_id": youtube_video_id,
        "channel_id": str(getattr(row, "channel_id")) if getattr(row, "channel_id", None) else None,
        "channel_name": getattr(row, "channel_name", None),
        "chunk_text": getattr(row, "chunk_text", "") or "",
        "start_time": start_time,
        "end_time": getattr(row, "end_time", None),
        "speaker": speaker,
        "source_type": source_type,
        "lane_ranks": {lane: rank},
        "score_components": {},
        "similarity": round(float(getattr(row, "similarity", 0.0) or 0.0), 4),
    }
    candidate["youtube_url"] = build_youtube_url(youtube_video_id, start_time)
    return candidate


async def _global_vector_search(
    db: AsyncSession,
    query_embedding: list[float],
    limit: int,
    channel_id: uuid.UUID | None = None,
    source_type: str = "all",
    video_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    embedding = _embedding_literal(query_embedding)
    where, params = _build_global_where_clause(channel_id, source_type, video_id)
    params.update({"embedding": embedding, "limit": limit})

    sql = f"""
        SELECT
            ec.id,
            ec.video_id,
            v.title as video_title,
            v.youtube_video_id,
            v.channel_id,
            c.name as channel_name,
            ec.chunk_text,
            ec.start_time,
            ec.end_time,
            ec.speaker,
            1 - (ec.embedding <=> CAST(:embedding AS vector)) as similarity
        FROM embedding_chunks ec
        JOIN videos v ON v.id = ec.video_id
        LEFT JOIN channels c ON c.id = v.channel_id
        {where}
        ORDER BY ec.embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """

    result = await db.execute(text(sql), params)
    return [
        _row_to_candidate(row, "vector", rank)
        for rank, row in enumerate(result.fetchall(), start=1)
    ]


async def _global_keyword_search(
    db: AsyncSession,
    query: str,
    limit: int,
    channel_id: uuid.UUID | None = None,
    source_type: str = "all",
    video_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    where, params = _build_global_where_clause(channel_id, source_type, video_id)
    params.update({"query": query, "limit": limit})

    ts_condition = "ec.search_vector @@ plainto_tsquery('english', :query)"
    if where:
        where = f"{where} AND {ts_condition}"
    else:
        where = f" WHERE {ts_condition}"

    sql = f"""
        SELECT
            ec.id,
            ec.video_id,
            v.title as video_title,
            v.youtube_video_id,
            v.channel_id,
            c.name as channel_name,
            ec.chunk_text,
            ec.start_time,
            ec.end_time,
            ec.speaker,
            ts_rank(ec.search_vector, plainto_tsquery('english', :query)) as similarity
        FROM embedding_chunks ec
        JOIN videos v ON v.id = ec.video_id
        LEFT JOIN channels c ON c.id = v.channel_id
        {where}
        ORDER BY similarity DESC
        LIMIT :limit
    """

    result = await db.execute(text(sql), params)
    return [
        _row_to_candidate(row, "keyword", rank)
        for rank, row in enumerate(result.fetchall(), start=1)
    ]


async def _summary_vector_search(
    db: AsyncSession,
    query_embedding: list[float],
    limit: int,
    channel_id: uuid.UUID | None = None,
    video_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    embedding = _embedding_literal(query_embedding)
    where, params = _build_global_where_clause(channel_id, "summary", video_id)
    params.update({"embedding": embedding, "limit": limit})

    sql = f"""
        SELECT
            ec.id,
            ec.video_id,
            v.title as video_title,
            v.youtube_video_id,
            v.channel_id,
            c.name as channel_name,
            ec.chunk_text,
            ec.start_time,
            ec.end_time,
            ec.speaker,
            1 - (ec.embedding <=> CAST(:embedding AS vector)) as similarity
        FROM embedding_chunks ec
        JOIN videos v ON v.id = ec.video_id
        LEFT JOIN channels c ON c.id = v.channel_id
        {where}
        ORDER BY ec.embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """

    result = await db.execute(text(sql), params)
    return [
        _row_to_candidate(row, "summary", rank)
        for rank, row in enumerate(result.fetchall(), start=1)
    ]


def reciprocal_rank_fuse(
    lanes: dict[str, list[dict[str, Any]]],
    rrf_k: int = DEFAULT_RRF_K,
) -> list[dict[str, Any]]:
    """Fuse ranked candidate lanes with reciprocal rank fusion."""
    fused: dict[str, dict[str, Any]] = {}

    for lane, candidates in lanes.items():
        for rank, candidate in enumerate(candidates, start=1):
            candidate_id = str(candidate["id"])
            score = 1.0 / (rrf_k + rank)

            if candidate_id not in fused:
                fused[candidate_id] = dict(candidate)
                fused[candidate_id]["lane_ranks"] = {}
                fused[candidate_id]["score_components"] = {}

            fused[candidate_id]["lane_ranks"][lane] = rank
            fused[candidate_id]["score_components"][lane] = round(score, 6)

    results = []
    for candidate in fused.values():
        fused_score = sum(candidate["score_components"].values())
        candidate["fused_score"] = round(fused_score, 6)
        candidate["similarity"] = round(fused_score, 4)
        results.append(candidate)

    return sorted(results, key=lambda item: item["fused_score"], reverse=True)


def _text_fingerprint(text_value: str) -> str:
    words = re.findall(r"[a-z0-9]+", text_value.lower())
    return " ".join(words[:80])


def select_diverse_results(
    candidates: list[dict[str, Any]],
    limit: int,
    per_video_limit: int = DEFAULT_PER_VIDEO_LIMIT,
) -> list[dict[str, Any]]:
    """Dedupe and apply a soft per-video cap to fused candidates."""
    if not candidates or limit <= 0:
        return []

    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    video_counts: dict[str, int] = defaultdict(int)

    for candidate in candidates:
        candidate_id = str(candidate["id"])
        fingerprint = _text_fingerprint(candidate.get("chunk_text", ""))
        if candidate_id in seen_ids or (fingerprint and fingerprint in seen_text):
            continue

        seen_ids.add(candidate_id)
        if fingerprint:
            seen_text.add(fingerprint)

        video_id = str(candidate.get("video_id"))
        if video_counts[video_id] >= per_video_limit:
            deferred.append(candidate)
            continue

        selected.append(candidate)
        video_counts[video_id] += 1
        if len(selected) >= limit:
            return selected

    for candidate in deferred:
        selected.append(candidate)
        if len(selected) >= limit:
            break

    return selected


def balance_source_types(
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    per_video_limit: int = DEFAULT_PER_VIDEO_LIMIT,
    min_transcript_ratio: float = DEFAULT_MIN_TRANSCRIPT_RATIO,
) -> list[dict[str, Any]]:
    """Keep default all-source search from collapsing into summaries only.

    Summary chunks are excellent for broad questions, but default search should
    expose some raw transcript evidence when transcript candidates exist.
    Source-specific filters bypass this helper.
    """
    if not selected or limit <= 0:
        return selected

    transcript_candidates = [
        item for item in candidates if item.get("source_type") == "transcript"
    ]
    if not transcript_candidates:
        return selected

    min_transcripts = max(1, ceil(limit * min_transcript_ratio))
    current_transcripts = sum(
        1 for item in selected if item.get("source_type") == "transcript"
    )
    if current_transcripts >= min_transcripts:
        return selected

    selected_ids = {str(item["id"]) for item in selected}
    video_counts: dict[str, int] = defaultdict(int)
    for item in selected:
        video_counts[str(item.get("video_id"))] += 1

    needed = min_transcripts - current_transcripts
    replacements = []
    fallback_replacements = []
    for item in transcript_candidates:
        if str(item["id"]) in selected_ids:
            continue
        video_id = str(item.get("video_id"))
        if video_counts[video_id] < per_video_limit:
            replacements.append(item)
            video_counts[video_id] += 1
        else:
            fallback_replacements.append(item)
        if len(replacements) >= needed:
            break
    if len(replacements) < needed:
        replacements.extend(fallback_replacements[: needed - len(replacements)])
    if not replacements:
        return selected

    balanced = list(selected)
    for replacement in replacements:
        for idx in range(len(balanced) - 1, -1, -1):
            if balanced[idx].get("source_type") == "summary":
                balanced[idx] = replacement
                selected_ids.add(str(replacement["id"]))
                break

    return sorted(
        balanced[:limit],
        key=lambda item: item.get("fused_score", 0.0),
        reverse=True,
    )


def build_youtube_url(youtube_video_id: str | None, start_time: float | None = None) -> str | None:
    if not youtube_video_id:
        return None
    url = f"https://www.youtube.com/watch?v={youtube_video_id}"
    if start_time is not None:
        url = f"{url}&t={max(0, int(start_time))}s"
    return url


def _query_terms(query: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) >= 3}


def build_evidence_text(query: str, chunk_text: str, max_chars: int = 700) -> str:
    """Return a concise deterministic evidence snippet for a chunk."""
    text_value = " ".join((chunk_text or "").split())
    if len(text_value) <= max_chars:
        return text_value

    terms = _query_terms(query)
    sentences = re.split(r"(?<=[.!?])\s+", text_value)
    matching = [
        sentence for sentence in sentences
        if terms and terms.intersection(_query_terms(sentence))
    ]
    snippet = " ".join(matching[:3]) if matching else text_value[:max_chars]
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3].rstrip()
    return f"{snippet}..."


def build_evidence_pack(
    query: str,
    candidates: list[dict[str, Any]],
    max_chars: int = 700,
) -> list[dict[str, Any]]:
    packed = []
    for index, candidate in enumerate(candidates, start=1):
        item = dict(candidate)
        item["rank"] = index
        item["evidence_text"] = build_evidence_text(
            query=query,
            chunk_text=item.get("chunk_text", ""),
            max_chars=max_chars,
        )
        packed.append(item)
    return packed


async def global_search(
    db: AsyncSession,
    query: str,
    query_embedding: list[float],
    options: GlobalSearchOptions | None = None,
) -> dict[str, Any]:
    """Run whole-corpus retrieval and return citation-ready results."""
    opts = (options or GlobalSearchOptions()).normalized()

    vector_results = await _global_vector_search(
        db=db,
        query_embedding=query_embedding,
        limit=opts.candidate_limit,
        channel_id=opts.channel_id,
        source_type=opts.source_type,
        video_id=opts.video_id,
    )
    keyword_results = await _global_keyword_search(
        db=db,
        query=query,
        limit=opts.candidate_limit,
        channel_id=opts.channel_id,
        source_type=opts.source_type,
        video_id=opts.video_id,
    )
    summary_results = []
    if opts.source_type in {"all", "summary"}:
        summary_results = await _summary_vector_search(
            db=db,
            query_embedding=query_embedding,
            limit=opts.summary_limit,
            channel_id=opts.channel_id,
            video_id=opts.video_id,
        )

    lanes = {
        "vector": vector_results,
        "keyword": keyword_results,
        "summary": summary_results,
    }
    fused = reciprocal_rank_fuse(lanes, rrf_k=opts.rrf_k)
    diverse = select_diverse_results(
        fused,
        limit=opts.limit,
        per_video_limit=opts.per_video_limit,
    )
    if opts.source_type == "all":
        diverse = balance_source_types(
            diverse,
            fused,
            limit=opts.limit,
            per_video_limit=opts.per_video_limit,
        )
    results = build_evidence_pack(query, diverse)

    return {
        "query": query,
        "results": results,
        "candidate_count": len(fused),
        "lane_counts": {lane: len(items) for lane, items in lanes.items()},
        "options": {
            "limit": opts.limit,
            "candidate_limit": opts.candidate_limit,
            "summary_limit": opts.summary_limit,
            "per_video_limit": opts.per_video_limit,
            "channel_id": str(opts.channel_id) if opts.channel_id else None,
            "video_id": str(opts.video_id) if opts.video_id else None,
            "source_type": opts.source_type,
            "rrf_k": opts.rrf_k,
        },
    }
