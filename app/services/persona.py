"""Persona derivation and retrieval.

A persona is an LLM-generated voice/style profile for some scope
(channel, advisor, speaker). v1 only generates ``scope_type='channel'``
personas, but the same derivation works for the future scope types.

Public entry points:
  - ``select_characteristic_chunks`` — pick the chunks that best represent a scope.
  - ``derive_persona`` — one LLM call: corpus → ``PersonaDerivation``.
  - ``upsert_persona`` — write the derivation to the ``personas`` table.
  - ``get_persona`` — lookup by scope.
  - ``channel_needs_persona`` — decides whether a channel should (re)generate.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import anthropic
import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.embedding_chunk import EmbeddingChunk
from app.models.persona import Persona
from app.models.video import Video
from app.services.embedding import SUMMARY_SPEAKER_LABEL

logger = structlog.get_logger()


SCOPE_CHANNEL = "channel"


DERIVATION_SYSTEM_PROMPT = """You design persona profiles for LLM agents.
You receive a corpus of excerpts from a creator's videos and return a compact JSON spec
that a downstream agent will use to answer questions *as* that creator / channel.

Be specific. Avoid generic adjectives. Prefer concrete patterns the reader can verify in the excerpts.
Never invent facts. Never reproduce the excerpts verbatim in the prompt — describe the patterns.

Return ONLY valid JSON with this shape (no prose before or after):

{
  "display_name": "string — usually the channel name, refined if the corpus reveals a better label",
  "persona_prompt": "string — the system prompt the downstream agent uses. Written in second person (\\"You are...\\"). Must tell the agent to ground answers in provided excerpts, match the voice described, and cite when appropriate.",
  "style_notes": {
    "tone": "short phrase",
    "rhythm": "sentence-length and pacing patterns",
    "vocab_tells": ["3-6 recurring words or phrases that signal this voice"],
    "frameworks": ["2-5 recurring mental models or argument structures this creator uses"],
    "topics": ["3-7 topics the corpus gravitates toward"]
  },
  "exemplar_chunk_ids": ["3-5 chunk UUIDs from the input that are the most representative — REAL ids from the input excerpts"],
  "confidence": "float 0..1 — your confidence that the persona captures the voice. Lower it for thin/ambiguous corpora."
}"""


@dataclass
class PersonaDerivation:
    display_name: str
    persona_prompt: str
    style_notes: dict
    exemplar_chunk_ids: list[uuid.UUID]
    source_chunk_count: int
    confidence: float
    model: str


async def select_characteristic_chunks(
    db: AsyncSession,
    channel_id: uuid.UUID,
    top_k: int | None = None,
) -> list[dict]:
    """Select the chunks most distinctive to this channel.

    Returns ``persona_characteristic_chunks`` transcript chunks plus all
    summary chunks for the channel. Distinctiveness is approximated by
    picking the chunks furthest (cosine distance) from the channel's own
    centroid — i.e. the chunks most different from the channel's average,
    which tend to be the most content-loaded and quotable.

    For v1 this is a simple heuristic; we can swap in a library-wide
    centroid later if persona quality needs it.
    """
    top_k = top_k or settings.persona_characteristic_chunks

    centroid_sql = """
        WITH chan_videos AS (
            SELECT id FROM videos WHERE channel_id = :channel_id
        ),
        chan_chunks AS (
            SELECT ec.embedding
            FROM embedding_chunks ec
            WHERE ec.video_id IN (SELECT id FROM chan_videos)
              AND (ec.speaker IS NULL OR ec.speaker <> :summary_label)
        )
        SELECT AVG(embedding) AS centroid FROM chan_chunks
    """

    characteristic_sql = """
        WITH chan_videos AS (
            SELECT id FROM videos WHERE channel_id = :channel_id
        ),
        chan_chunks AS (
            SELECT ec.id, ec.video_id, ec.chunk_text, ec.start_time, ec.end_time,
                   ec.speaker, ec.embedding
            FROM embedding_chunks ec
            WHERE ec.video_id IN (SELECT id FROM chan_videos)
              AND (ec.speaker IS NULL OR ec.speaker <> :summary_label)
        )
        SELECT id, video_id, chunk_text, start_time, end_time, speaker,
               (embedding <=> CAST(:centroid AS vector)) AS dist
        FROM chan_chunks
        ORDER BY dist DESC
        LIMIT :top_k
    """

    summary_sql = """
        SELECT ec.id, ec.video_id, ec.chunk_text, ec.start_time, ec.end_time, ec.speaker
        FROM embedding_chunks ec
        WHERE ec.video_id IN (SELECT id FROM videos WHERE channel_id = :channel_id)
          AND ec.speaker = :summary_label
    """

    from sqlalchemy import text as sa_text

    centroid_result = await db.execute(
        sa_text(centroid_sql),
        {"channel_id": str(channel_id), "summary_label": SUMMARY_SPEAKER_LABEL},
    )
    centroid_row = centroid_result.fetchone()
    if centroid_row is None or centroid_row[0] is None:
        return []

    centroid = centroid_row[0]
    # pgvector AVG returns the vector already; normalize to str for the next query.
    centroid_str = str(centroid) if not isinstance(centroid, str) else centroid

    characteristic_rows = (
        await db.execute(
            sa_text(characteristic_sql),
            {
                "channel_id": str(channel_id),
                "summary_label": SUMMARY_SPEAKER_LABEL,
                "centroid": centroid_str,
                "top_k": top_k,
            },
        )
    ).fetchall()

    summary_rows = (
        await db.execute(
            sa_text(summary_sql),
            {"channel_id": str(channel_id), "summary_label": SUMMARY_SPEAKER_LABEL},
        )
    ).fetchall()

    def row_to_chunk(row: Any, source_type: str) -> dict:
        return {
            "id": str(row.id),
            "video_id": str(row.video_id),
            "chunk_text": row.chunk_text,
            "start_time": getattr(row, "start_time", None),
            "end_time": getattr(row, "end_time", None),
            "speaker": getattr(row, "speaker", None),
            "source_type": source_type,
        }

    return [row_to_chunk(r, "transcript") for r in characteristic_rows] + [
        row_to_chunk(r, "summary") for r in summary_rows
    ]


def _format_corpus_for_derivation(chunks: list[dict]) -> str:
    lines = []
    for c in chunks:
        tag = "[Summary]" if c["source_type"] == "summary" else "[Transcript]"
        lines.append(f"id={c['id']} {tag}\n{c['chunk_text'].strip()}")
    return "\n\n---\n\n".join(lines)


def _build_derivation_user_message(channel_name: str, channel_description: str | None, chunks: list[dict]) -> str:
    desc_line = f"\nChannel description: {channel_description.strip()}" if channel_description else ""
    corpus = _format_corpus_for_derivation(chunks)
    return (
        f"Channel name: {channel_name}{desc_line}\n"
        f"Number of excerpts: {len(chunks)}\n\n"
        f"Excerpts (each starts with id=...):\n\n{corpus}\n\n"
        f"Return the JSON spec now."
    )


def _parse_derivation_json(raw: str, valid_chunk_ids: set[str]) -> dict:
    """Parse the LLM JSON, tolerating markdown fences if the model wraps them."""
    text = raw.strip()
    if text.startswith("```"):
        # strip a leading/trailing fenced block
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            # drop the language tag on the first line if present
            text = text.split("\n", 1)[1] if "\n" in text else text

    data = json.loads(text)

    for k in ("display_name", "persona_prompt", "style_notes", "exemplar_chunk_ids", "confidence"):
        if k not in data:
            raise ValueError(f"derivation missing key: {k}")

    # Filter exemplars to real ids from the corpus
    exemplars: list[str] = []
    for raw_id in data.get("exemplar_chunk_ids", []):
        candidate = str(raw_id).strip()
        if candidate in valid_chunk_ids:
            exemplars.append(candidate)
    data["exemplar_chunk_ids"] = exemplars[: settings.persona_exemplar_count]

    return data


def _call_derivation_llm(user_message: str, model: str, api_key: str) -> tuple[str, str]:
    """Call Anthropic for persona derivation. Returns (raw_text, model_actual)."""
    from app.services.cost_tracker import check_budget, record_usage

    check_budget()

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=DERIVATION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    record_usage(model, response.usage.input_tokens, response.usage.output_tokens)
    return response.content[0].text, response.model


def derive_persona(
    channel_name: str,
    channel_description: str | None,
    chunks: list[dict],
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> PersonaDerivation:
    """Run the LLM derivation step. Synchronous (runs in Celery worker)."""
    if not chunks:
        raise ValueError("derive_persona: empty corpus")

    model = model or settings.anthropic_persona_model
    api_key = api_key or settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    user_message = _build_derivation_user_message(channel_name, channel_description, chunks)
    raw, model_actual = _call_derivation_llm(user_message, model, api_key)

    valid_ids = {c["id"] for c in chunks}
    parsed = _parse_derivation_json(raw, valid_ids)

    try:
        confidence = float(parsed["confidence"])
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return PersonaDerivation(
        display_name=str(parsed["display_name"]).strip() or channel_name,
        persona_prompt=str(parsed["persona_prompt"]).strip(),
        style_notes=dict(parsed.get("style_notes") or {}),
        exemplar_chunk_ids=[uuid.UUID(x) for x in parsed["exemplar_chunk_ids"]],
        source_chunk_count=len(chunks),
        confidence=confidence,
        model=model_actual,
    )


async def upsert_persona(
    db: AsyncSession,
    derivation: PersonaDerivation,
    *,
    scope_type: str,
    scope_id: str,
    videos_at_generation: int,
    refresh_after_videos: int | None = None,
) -> Persona:
    """Upsert the persona row keyed on (scope_type, scope_id)."""
    stmt = pg_insert(Persona).values(
        scope_type=scope_type,
        scope_id=scope_id,
        display_name=derivation.display_name,
        persona_prompt=derivation.persona_prompt,
        style_notes=derivation.style_notes,
        exemplar_chunk_ids=derivation.exemplar_chunk_ids,
        source_chunk_count=derivation.source_chunk_count,
        confidence=derivation.confidence,
        generated_by_model=derivation.model,
        videos_at_generation=videos_at_generation,
        refresh_after_videos=refresh_after_videos or settings.persona_refresh_after_videos,
    ).on_conflict_do_update(
        constraint="uq_personas_scope",
        set_={
            "display_name": derivation.display_name,
            "persona_prompt": derivation.persona_prompt,
            "style_notes": derivation.style_notes,
            "exemplar_chunk_ids": derivation.exemplar_chunk_ids,
            "source_chunk_count": derivation.source_chunk_count,
            "confidence": derivation.confidence,
            "generated_by_model": derivation.model,
            "videos_at_generation": videos_at_generation,
            "refresh_after_videos": refresh_after_videos or settings.persona_refresh_after_videos,
            "generated_at": func.now(),
        },
    ).returning(Persona)

    result = await db.execute(stmt)
    persona = result.scalar_one()
    await db.commit()

    logger.info(
        "persona_upserted",
        scope_type=scope_type,
        scope_id=scope_id,
        display_name=persona.display_name,
        confidence=persona.confidence,
    )
    return persona


async def get_persona(db: AsyncSession, scope_type: str, scope_id: str) -> Persona | None:
    stmt = select(Persona).where(
        Persona.scope_type == scope_type, Persona.scope_id == scope_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


PERSONA_CITATION_SUFFIX = (
    "\n\n---\nFORMAT (strict):\n"
    "1. Lead with a short 2-3 sentence direct answer. No heading.\n"
    "2. Then 2-4 thematic sections with a bold heading each (`**Heading**`) "
    "and 1-3 sentences of prose. No bullet lists.\n"
    "3. Cite excerpts with chunk indices only: `[1]`, `[1, 3]`. NEVER write "
    "timestamp ranges like `[19:07 - 19:51]` yourself. A post-processor converts "
    "`[N]` citations into tappable YouTube links at the end of each paragraph. "
    "Avoid citing the same chunk more than once per paragraph.\n"
    "4. End with a line starting with `Related:` followed by one natural follow-up "
    "question the user might want to ask next.\n"
    "If the excerpts don't contain enough to answer, say so briefly in the lead "
    "paragraph and stop. Never invent facts.\n"
    "Stay in the voice described above at all times."
)


def compose_persona_system_prompt(persona: Persona) -> str:
    """Return the full system prompt to use at inference time."""
    return (persona.persona_prompt or "").strip() + PERSONA_CITATION_SUFFIX


async def get_exemplar_chunks(db: AsyncSession, persona: Persona) -> list[dict]:
    """Fetch the persona's exemplar chunks as context-ready dicts.

    Returns rows with ``chunk_text``, ``video_id``, ``video_title``,
    ``start_time``, ``end_time``, ``speaker``, and ``source_type`` keys —
    matching the shape expected by ``app.services.chat._format_chunks_for_context``.
    """
    if not persona.exemplar_chunk_ids:
        return []

    from sqlalchemy import text as sa_text

    sql = """
        SELECT ec.id, ec.video_id, v.title AS video_title, ec.chunk_text,
               ec.start_time, ec.end_time, ec.speaker
        FROM embedding_chunks ec
        JOIN videos v ON v.id = ec.video_id
        WHERE ec.id = ANY(CAST(:ids AS uuid[]))
        ORDER BY ec.start_time NULLS LAST
    """
    rows = (
        await db.execute(sa_text(sql), {"ids": [str(x) for x in persona.exemplar_chunk_ids]})
    ).fetchall()

    return [
        {
            "video_id": r.video_id,
            "video_title": r.video_title,
            "chunk_text": r.chunk_text,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "speaker": r.speaker,
            "source_type": "summary" if r.speaker == SUMMARY_SPEAKER_LABEL else "transcript",
        }
        for r in rows
    ]


async def count_completed_videos(db: AsyncSession, channel_id: uuid.UUID) -> int:
    stmt = select(func.count(Video.id)).where(
        Video.channel_id == channel_id, Video.status == "completed"
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def channel_needs_persona(db: AsyncSession, channel_id: uuid.UUID) -> tuple[bool, str]:
    """Return (should_generate, reason).

    Generates when:
      - No persona yet and channel has >= persona_min_videos completed videos.
      - Or persona exists and (completed_videos - videos_at_generation) >=
        persona.refresh_after_videos.
    """
    completed = await count_completed_videos(db, channel_id)
    min_videos = settings.persona_min_videos
    if completed < min_videos:
        return False, f"only {completed}/{min_videos} completed videos"

    persona = await get_persona(db, SCOPE_CHANNEL, str(channel_id))
    if persona is None:
        return True, f"no persona yet, channel has {completed} videos"

    since = completed - persona.videos_at_generation
    if since >= persona.refresh_after_videos:
        return True, f"{since} new videos since last persona (threshold {persona.refresh_after_videos})"

    return False, f"persona current ({since}/{persona.refresh_after_videos} new videos)"
