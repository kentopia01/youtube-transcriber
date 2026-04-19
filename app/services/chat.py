import asyncio
import uuid
from functools import partial

import anthropic
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.embedding import SUMMARY_SPEAKER_LABEL
from app.services.search import encode_query, semantic_search

logger = structlog.get_logger()

_anthropic_client: anthropic.Anthropic | None = None


def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


@retry(
    retry=retry_if_exception_type(anthropic.RateLimitError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_anthropic_with_retry(client: anthropic.Anthropic, **kwargs):
    return client.messages.create(**kwargs)


SYSTEM_PROMPT = """You answer questions using the provided video transcript excerpts.

**Format your response exactly like this:**

1. **Lead with the answer.** Open with one short paragraph (2-3 sentences) that directly answers the question. No heading above this paragraph.

2. **Then 2-4 thematic sections.** Each section has a short bold heading on its own line (e.g., ``**Why it matters**``). Under each heading write 1-3 sentences of grounded prose — NOT bullet lists.

3. **Cite sources with chunk indices only.** Use ``[1]``, ``[2]``, ``[1, 3]``. Do NOT write timestamp ranges like ``[19:07 - 19:51]`` manually — just cite the chunk number. A post-processor converts your ``[N]`` citations into tappable YouTube timestamp links at the end of each paragraph, so don't repeat the same citation multiple times per paragraph.

4. **End with ``Related:``** followed by one natural follow-up question the user might want to ask next.

**Rules:**
- If the excerpts lack evidence, say so briefly in the lead paragraph and stop. Don't invent facts.
- Never dump raw chunk text verbatim — summarize and cite.
- Never use numbered or bulleted lists. Prose only.
- If a source is marked [Summary], cite its chunk number as normal — the post-processor handles it."""


def _is_summary_chunk(chunk: dict) -> bool:
    return chunk.get("speaker") == SUMMARY_SPEAKER_LABEL


def _format_chunks_for_context(chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        if _is_summary_chunk(chunk):
            parts.append(f"[{i}] {chunk['video_title']} [Summary]\n{chunk['chunk_text']}")
            continue

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
    user_content = f"Context from video transcripts and summaries:\n\n{context_text}\n\nQuestion: {question}"
    messages.append({"role": "user", "content": user_content})
    return messages


def _call_anthropic(
    system: str,
    messages: list[dict],
    model: str,
) -> dict:
    from app.services.cost_tracker import BudgetExceededError, check_budget, record_usage

    check_budget()

    client = _get_anthropic_client()
    response = _call_anthropic_with_retry(
        client,
        model=model,
        max_tokens=4096,
        system=system,
        messages=messages,
    )

    record_usage(model, response.usage.input_tokens, response.usage.output_tokens)

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
    *,
    channel_id: uuid.UUID | None = None,
    system_prompt: str | None = None,
    exemplar_chunks: list[dict] | None = None,
) -> dict:
    """RAG chat: retrieve relevant chunks and generate a response.

    Args:
        question: The user's question.
        history: List of prior messages [{role, content}, ...].
        db: Async database session.
        channel_id: Optional channel to scope retrieval to. When set, only
            chunks from videos belonging to this channel are considered.
        system_prompt: Override the default system prompt (used for persona
            agents).
        exemplar_chunks: Optional list of persona exemplar chunk rows. Rendered
            as a ``[Persona Exemplars]`` block above the retrieved context so
            the agent can anchor on voice even if retrieval is thin.

    Returns:
        Dict with content, sources, model, prompt_tokens, completion_tokens.
    """
    try:
        query_embedding = encode_query(question)
        chunks = await semantic_search(
            db,
            query_embedding=query_embedding,
            limit=settings.chat_retrieval_top_k,
            query=question,
            channel_id=channel_id,
            chat_enabled_only=True,
        )
    except Exception as exc:
        logger.warning("search_failed", error=str(exc))
        chunks = []

    context_text = _format_chunks_for_context(chunks)
    if exemplar_chunks:
        exemplar_text = _format_chunks_for_context(exemplar_chunks)
        context_text = (
            f"[Persona Exemplars — representative excerpts from this channel]\n{exemplar_text}\n\n"
            f"[Retrieved for question]\n{context_text}"
        )

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

    sources = [
        {
            "video_id": str(chunk["video_id"]),
            "youtube_video_id": chunk.get("youtube_video_id"),
            "video_title": chunk["video_title"],
            "chunk_text": chunk["chunk_text"],
            "start_time": chunk.get("start_time"),
            "end_time": chunk.get("end_time"),
            "similarity": chunk.get("similarity"),
            "source_type": "summary" if _is_summary_chunk(chunk) else "transcript",
        }
        for chunk in chunks
    ]

    if not settings.anthropic_api_key:
        logger.warning("chat_missing_api_key")
        return {
            "content": "Chat is unavailable: Anthropic API key is not configured.",
            "sources": sources,
            "model": settings.chat_model,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    from app.services.cost_tracker import BudgetExceededError

    loop = asyncio.get_running_loop()
    model = settings.anthropic_chat_model
    active_system = system_prompt or SYSTEM_PROMPT
    try:
        llm_result = await loop.run_in_executor(
            None,
            partial(_call_anthropic, active_system, messages, model),
        )
    except BudgetExceededError as exc:
        logger.warning("chat_budget_exceeded", error=str(exc))
        return {
            "content": "Chat is temporarily unavailable: daily LLM budget exceeded. Try again tomorrow.",
            "sources": sources,
            "model": model,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
    except Exception as exc:
        logger.error("anthropic_api_error", error=str(exc))
        return {
            "content": "Sorry, an error occurred while generating the response. Please try again.",
            "sources": sources,
            "model": model,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    from app.services.response_formatter import format_response

    formatted = format_response(llm_result["content"], sources)

    return {
        "content": formatted,
        "sources": sources,
        "model": llm_result["model"],
        "prompt_tokens": llm_result["prompt_tokens"],
        "completion_tokens": llm_result["completion_tokens"],
    }

