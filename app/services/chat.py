import asyncio
import uuid
from functools import partial

import anthropic
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.search import encode_query, semantic_search

logger = structlog.get_logger()

_anthropic_client: anthropic.Anthropic | None = None


def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on video transcript content. \
Ground your answers in the provided context. When referencing specific information, cite the source video and timestamp. \
If the context doesn't contain enough information to answer, say so."""


def _format_chunks_for_context(chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        start = chunk.get("start_time")
        end = chunk.get("end_time")
        ts = ""
        if start is not None:
            ts = f" [{_fmt_ts(start)}"
            if end is not None:
                ts += f" - {_fmt_ts(end)}"
            ts += "]"
        parts.append(f"[{i}] {chunk['video_title']}{ts}\n{chunk['chunk_text']}")
    return "\n\n".join(parts)


def _fmt_ts(seconds: float) -> str:
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _build_messages(
    history: list[dict],
    question: str,
    context_text: str,
) -> list[dict]:
    messages = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    user_content = f"Context from video transcripts:\n\n{context_text}\n\nQuestion: {question}"
    messages.append({"role": "user", "content": user_content})
    return messages


def _call_anthropic(
    system: str,
    messages: list[dict],
    model: str,
) -> dict:
    client = _get_anthropic_client()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=messages,
    )
    return {
        "content": response.content[0].text,
        "model": response.model,
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
    }


async def chat_with_context(
    question: str,
    history: list[dict],
    db: AsyncSession,
) -> dict:
    """RAG chat: retrieve relevant chunks and generate a response.

    Args:
        question: The user's question.
        history: List of prior messages [{role, content}, ...].
        db: Async database session.

    Returns:
        Dict with content, sources, model, prompt_tokens, completion_tokens.
    """
    query_embedding = encode_query(question)

    chunks = await semantic_search(
        db,
        query_embedding=query_embedding,
        limit=settings.chat_retrieval_top_k,
        query=question,
        chat_enabled_only=True,
    )

    context_text = _format_chunks_for_context(chunks)

    trimmed_history = history[-(settings.chat_max_history * 2) :]

    messages = _build_messages(trimmed_history, question, context_text)

    # Rough token estimate: ~4 chars per token. Truncate context if over 150k tokens.
    total_chars = sum(len(m["content"]) for m in messages) + len(SYSTEM_PROMPT)
    estimated_tokens = total_chars // 4
    if estimated_tokens > 150_000:
        # Drop oldest history pairs until under limit
        while len(messages) > 1 and estimated_tokens > 150_000:
            removed = messages.pop(0)
            estimated_tokens -= len(removed["content"]) // 4

    loop = asyncio.get_event_loop()
    llm_result = await loop.run_in_executor(
        None,
        partial(_call_anthropic, SYSTEM_PROMPT, messages, settings.chat_model),
    )

    sources = [
        {
            "video_id": str(chunk["video_id"]),
            "video_title": chunk["video_title"],
            "chunk_text": chunk["chunk_text"],
            "start_time": chunk.get("start_time"),
            "end_time": chunk.get("end_time"),
            "similarity": chunk.get("similarity"),
        }
        for chunk in chunks
    ]

    return {
        "content": llm_result["content"],
        "sources": sources,
        "model": llm_result["model"],
        "prompt_tokens": llm_result["prompt_tokens"],
        "completion_tokens": llm_result["completion_tokens"],
    }
