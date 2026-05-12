import anthropic
import structlog
import tiktoken

from app.services.provider_retry import provider_api_retry

logger = structlog.get_logger()


@provider_api_retry()
def _call_anthropic_with_retry(client: anthropic.Anthropic, **kwargs):
    return client.messages.create(**kwargs)

SUMMARY_SYSTEM_PROMPT = """You are Ken's executive video analyst. Your job is not to list topics; it is to make the transcript useful enough that Ken can scan it and understand the video's actual arguments, examples, caveats, and value without watching.

Write in this exact markdown structure:

## 30-second take
One dense paragraph with the video's thesis/verdict, the speaker's actual angle, and why it matters.

## Key takes
- 4-7 bullets. Each bullet must include a specific claim/take and its implication. Avoid generic topic labels.

## Useful details
- Specific examples, numbers, names, frameworks, tactics, or stories from the video.
- Preserve concrete facts over broad paraphrase.

## Caveats / counterpoints
- Important limitations, weak spots, disagreements, risks, or missing context. If the transcript gives none, say that.

## Ken relevance
- Explain why this matters for Ken's agent systems, AI ops, content/business opportunities, investing, GTM, or personal workflow when applicable.
- If relevance is low, say so plainly.

## Watch verdict
Choose one: Skip / Skim / Watch fully. Give a one-sentence reason.

Rules:
- Lead with the take, not a topic inventory.
- Capture what the speaker actually says or believes, including opinionated claims.
- Include numbers and examples when present.
- Do not invent facts beyond the transcript.
- If the transcript is mostly music, lyrics, ads, placeholders, repeated text, or too little substantive speech, clearly mark it as a low-content transcript in the 30-second take and explain what can/cannot be learned. Do not pad it into fake insight.
- Keep the whole summary concise but specific."""

CHUNK_SUMMARY_PROMPT = """Summarize this transcript portion for later consolidation. Preserve specific claims, examples, numbers, caveats, named people/products, and any watch-worthy moments. Do not reduce it to generic topics. If this chunk is low-content/music/placeholders/repetition, label that plainly:"""

CONSOLIDATION_PROMPT = """You are Ken's executive video analyst. You are given multiple partial summaries of a single video transcript titled "{title}". Combine them into one cohesive scan-first intelligence brief.

Use this exact markdown structure:

## 30-second take
One dense paragraph with the video's thesis/verdict, the speaker's actual angle, and why it matters.

## Key takes
- 4-7 bullets. Each bullet must include a specific claim/take and its implication.

## Useful details
- Specific examples, numbers, names, frameworks, tactics, or stories from the video.

## Caveats / counterpoints
- Important limitations, weak spots, disagreements, risks, or missing context. If none, say that.

## Ken relevance
- Explain why this matters for Ken's agent systems, AI ops, content/business opportunities, investing, GTM, or personal workflow when applicable.

## Watch verdict
Choose one: Skip / Skim / Watch fully. Give a one-sentence reason.

Rules: lead with the take, preserve concrete substance, do not invent beyond the transcript, and clearly flag low-content transcripts rather than padding them."""

MAX_TOKENS_PER_CHUNK = 80000  # Leave room for prompts within Claude's context


def _count_tokens(text: str) -> int:
    """Approximate token count using tiktoken cl100k_base."""
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def summarize_text(
    text: str,
    video_title: str = "",
    api_key: str = "",
    model: str = "",
    *,
    record_usage_enabled: bool = True,
) -> dict:
    """Summarize transcript text using Claude API.

    For long transcripts (>100k tokens), uses chunk-then-consolidate approach.
    Returns dict with summary, model, prompt_tokens, completion_tokens.
    """
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for summarization")

    client = anthropic.Anthropic(api_key=api_key)
    if not model:
        from app.config import settings
        model = settings.summary_model

    token_count = _count_tokens(text)
    logger.info("summarizing", token_count=token_count, title=video_title, model=model)

    if token_count <= MAX_TOKENS_PER_CHUNK:
        return _summarize_single(
            client,
            model,
            text,
            video_title,
            record_usage_enabled=record_usage_enabled,
        )
    else:
        return _summarize_chunked(
            client,
            model,
            text,
            video_title,
            token_count,
            record_usage_enabled=record_usage_enabled,
        )


def _summarize_single(
    client: anthropic.Anthropic,
    model: str,
    text: str,
    title: str,
    *,
    record_usage_enabled: bool = True,
) -> dict:
    """Summarize text in a single API call."""
    from app.services.cost_tracker import record_usage

    user_content = f"Video title: {title}\n\nTranscript:\n{text}" if title else text

    response = _call_anthropic_with_retry(
        client,
        model=model,
        max_tokens=4096,
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    if record_usage_enabled:
        record_usage(model, response.usage.input_tokens, response.usage.output_tokens)

    return {
        "summary": response.content[0].text,
        "model": model,
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
    }


def _summarize_chunked(
    client: anthropic.Anthropic,
    model: str,
    text: str,
    title: str,
    total_tokens: int,
    *,
    record_usage_enabled: bool = True,
) -> dict:
    """Summarize long text by chunking, summarizing each, then consolidating."""
    # Split into chunks
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)
    chunks = []
    for i in range(0, len(tokens), MAX_TOKENS_PER_CHUNK):
        chunk_tokens = tokens[i : i + MAX_TOKENS_PER_CHUNK]
        chunks.append(enc.decode(chunk_tokens))

    logger.info("chunked_summarization", chunks=len(chunks), total_tokens=total_tokens)

    # Summarize each chunk
    total_prompt = 0
    total_completion = 0
    partial_summaries = []

    from app.services.cost_tracker import record_usage

    for i, chunk in enumerate(chunks):
        response = _call_anthropic_with_retry(
            client,
            model=model,
            max_tokens=2048,
            system=CHUNK_SUMMARY_PROMPT,
            messages=[{"role": "user", "content": f"Part {i + 1}/{len(chunks)}:\n\n{chunk}"}],
        )
        partial_summaries.append(response.content[0].text)
        total_prompt += response.usage.input_tokens
        total_completion += response.usage.output_tokens
        if record_usage_enabled:
            record_usage(model, response.usage.input_tokens, response.usage.output_tokens)

    # Consolidate
    combined = "\n\n---\n\n".join(
        f"**Part {i + 1} Summary:**\n{s}" for i, s in enumerate(partial_summaries)
    )

    response = _call_anthropic_with_retry(
        client,
        model=model,
        max_tokens=4096,
        system=CONSOLIDATION_PROMPT.format(title=title),
        messages=[{"role": "user", "content": combined}],
    )
    total_prompt += response.usage.input_tokens
    total_completion += response.usage.output_tokens
    if record_usage_enabled:
        record_usage(model, response.usage.input_tokens, response.usage.output_tokens)

    return {
        "summary": response.content[0].text,
        "model": model,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
    }
