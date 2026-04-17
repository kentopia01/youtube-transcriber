"""LLM-powered transcript cleanup service.

Replaces the regex-based filler word removal with Anthropic Haiku API calls.
Speaker-aware cleanup that preserves meaning while improving readability.
Chunked processing for long transcripts.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import anthropic
import structlog
import tiktoken
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = structlog.get_logger()

# Concurrency cap for LLM cleanup chunks. Haiku rate limits are generous,
# and _call_anthropic_with_retry already backs off on 429, so 4 is conservative.
MAX_CONCURRENT_CHUNKS = 4


@retry(
    retry=retry_if_exception_type(anthropic.RateLimitError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_anthropic_with_retry(client: anthropic.Anthropic, **kwargs):
    return client.messages.create(**kwargs)

# Chunking parameters
MAX_TOKENS_SINGLE = 4000  # Below this, send as single request
CHUNK_SIZE = 2000  # Target chunk size in tokens
CHUNK_OVERLAP = 200  # Overlap between chunks in tokens

CLEANUP_PROMPT = """Clean this transcript for readability. Rules:
- Remove filler words (um, uh, like, you know, I mean, basically, sort of, kind of)
- Fix obvious grammar and punctuation errors
- Preserve speaker labels exactly (e.g., [SPEAKER_00])
- Do NOT change meaning, rephrase, or add content
- Do NOT remove technical terms, proper nouns, or intentional repetition
- Return the cleaned text only, no commentary"""


def clean_transcript(
    segments: list[dict],
    api_key: str,
    model: str = "claude-haiku-4-5",
) -> list[dict]:
    """Clean transcript segments using an LLM.

    Args:
        segments: List of dicts with at least {"text": str, "speaker": str | None}
        api_key: Anthropic API key.
        model: Model to use for cleanup.

    Returns:
        Updated segments with cleaned text.
    """
    if not segments:
        return segments

    if not api_key:
        logger.warn("transcript_cleanup_skipped", reason="No API key provided")
        return segments

    # Build the full transcript text with speaker labels
    labeled_lines = []
    for seg in segments:
        speaker = seg.get("speaker")
        text = seg.get("text", "")
        if speaker:
            labeled_lines.append(f"[{speaker}] {text}")
        else:
            labeled_lines.append(text)

    full_text = "\n".join(labeled_lines)

    # Count tokens to decide chunking strategy
    enc = tiktoken.get_encoding("cl100k_base")
    token_count = len(enc.encode(full_text))

    logger.info(
        "transcript_cleanup_starting",
        model=model,
        segments=len(segments),
        tokens=token_count,
    )

    if token_count <= MAX_TOKENS_SINGLE:
        # Single request
        cleaned_text = _call_llm(full_text, api_key, model)
    else:
        # Chunked processing
        cleaned_text = _chunked_cleanup(labeled_lines, api_key, model, enc)

    # Map cleaned text back to segments
    cleaned_segments = _map_cleaned_to_segments(cleaned_text, segments)

    logger.info("transcript_cleanup_complete", segments=len(cleaned_segments))
    return cleaned_segments


def _call_llm(text: str, api_key: str, model: str) -> str:
    """Send text to Anthropic API for cleanup."""
    from app.services.cost_tracker import BudgetExceededError, check_budget, record_usage

    check_budget()

    client = anthropic.Anthropic(api_key=api_key)

    response = _call_anthropic_with_retry(
        client,
        model=model,
        max_tokens=8192,
        system=CLEANUP_PROMPT,
        messages=[{"role": "user", "content": text}],
    )

    record_usage(model, response.usage.input_tokens, response.usage.output_tokens)

    return response.content[0].text


def _chunked_cleanup(
    lines: list[str],
    api_key: str,
    model: str,
    enc,
) -> str:
    """Process transcript in chunks with overlap, running chunks in parallel."""
    chunks = _build_chunks(lines, enc)

    logger.info("chunked_cleanup", chunks=len(chunks), max_concurrency=MAX_CONCURRENT_CHUNKS)

    workers = min(MAX_CONCURRENT_CHUNKS, max(len(chunks), 1))

    def _clean_one(idx_chunk: tuple[int, list[str]]) -> tuple[int, str]:
        idx, chunk = idx_chunk
        logger.info("cleaning_chunk", chunk=idx + 1, total=len(chunks))
        return idx, _call_llm("\n".join(chunk), api_key, model)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_clean_one, enumerate(chunks)))

    # Restore original chunk order; pool.map preserves order but we sort defensively
    # in case the implementation ever changes.
    results.sort(key=lambda r: r[0])

    # Simple concatenation — overlap ensures context continuity
    # but we don't deduplicate overlap since the LLM may rephrase slightly
    return "\n".join(part for _, part in results)


def _build_chunks(lines: list[str], enc) -> list[list[str]]:
    """Split lines into token-budget-aware chunks with overlap."""
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_tokens = 0

    for line in lines:
        line_tokens = len(enc.encode(line))

        if current_tokens + line_tokens > CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk)

            # Build overlap from end of current chunk
            overlap_lines: list[str] = []
            overlap_tokens = 0
            for prev_line in reversed(current_chunk):
                t = len(enc.encode(prev_line))
                if overlap_tokens + t > CHUNK_OVERLAP:
                    break
                overlap_lines.insert(0, prev_line)
                overlap_tokens += t

            current_chunk = overlap_lines
            current_tokens = overlap_tokens

        current_chunk.append(line)
        current_tokens += line_tokens

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _map_cleaned_to_segments(cleaned_text: str, original_segments: list[dict]) -> list[dict]:
    """Map cleaned text back to the original segment structure.

    Strategy: Split the cleaned text into lines and try to match each line
    back to the original segment by position. Preserves timestamps and metadata.
    """
    cleaned_lines = [line.strip() for line in cleaned_text.strip().split("\n") if line.strip()]

    result = []
    cleaned_idx = 0

    for seg in original_segments:
        new_seg = dict(seg)  # copy

        if cleaned_idx < len(cleaned_lines):
            cleaned_line = cleaned_lines[cleaned_idx]

            # Strip speaker label if present (we already have it in the segment)
            speaker = seg.get("speaker")
            if speaker and cleaned_line.startswith(f"[{speaker}]"):
                cleaned_line = cleaned_line[len(f"[{speaker}]"):].strip()

            new_seg["text"] = cleaned_line
            cleaned_idx += 1
        # else: keep original text if we ran out of cleaned lines

        result.append(new_seg)

    return result
