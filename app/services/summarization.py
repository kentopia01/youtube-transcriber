import anthropic
import structlog
import tiktoken
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = structlog.get_logger()


@retry(
    retry=retry_if_exception_type(anthropic.RateLimitError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_anthropic_with_retry(client: anthropic.Anthropic, **kwargs):
    return client.messages.create(**kwargs)

SUMMARY_SYSTEM_PROMPT = """You are an expert content summarizer. Create a comprehensive yet concise summary of the following video transcript. Include:

1. **Main Topics**: Key subjects discussed
2. **Key Points**: Important arguments, facts, or insights
3. **Notable Quotes**: Any memorable or significant statements
4. **Takeaways**: Main conclusions or action items

Format with markdown headers and bullet points for readability."""

CHUNK_SUMMARY_PROMPT = """Summarize this portion of a video transcript concisely, preserving key points and notable quotes:"""

CONSOLIDATION_PROMPT = """You are given multiple partial summaries of a single video transcript titled "{title}". Combine them into one cohesive, comprehensive summary. Include:

1. **Main Topics**: Key subjects discussed
2. **Key Points**: Important arguments, facts, or insights
3. **Notable Quotes**: Any memorable or significant statements
4. **Takeaways**: Main conclusions or action items

Format with markdown headers and bullet points for readability."""

MAX_TOKENS_PER_CHUNK = 80000  # Leave room for prompts within Claude's context


def _count_tokens(text: str) -> int:
    """Approximate token count using tiktoken cl100k_base."""
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def summarize_text(text: str, video_title: str = "", api_key: str = "", model: str = "") -> dict:
    """Summarize transcript text using Claude API.

    For long transcripts (>100k tokens), uses chunk-then-consolidate approach.
    Returns dict with summary, model, prompt_tokens, completion_tokens.
    """
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for summarization")

    client = anthropic.Anthropic(api_key=api_key)
    if not model:
        from app.config import settings
        model = settings.anthropic_summary_model

    token_count = _count_tokens(text)
    logger.info("summarizing", token_count=token_count, title=video_title, model=model)

    if token_count <= MAX_TOKENS_PER_CHUNK:
        return _summarize_single(client, model, text, video_title)
    else:
        return _summarize_chunked(client, model, text, video_title, token_count)


def _summarize_single(client: anthropic.Anthropic, model: str, text: str, title: str) -> dict:
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

    record_usage(model, response.usage.input_tokens, response.usage.output_tokens)

    return {
        "summary": response.content[0].text,
        "model": model,
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
    }


def _summarize_chunked(
    client: anthropic.Anthropic, model: str, text: str, title: str, total_tokens: int
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
    record_usage(model, response.usage.input_tokens, response.usage.output_tokens)

    return {
        "summary": response.content[0].text,
        "model": model,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
    }
