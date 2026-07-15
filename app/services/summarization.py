import json
import re
from typing import Any

import anthropic
import structlog
import tiktoken

from app.config import settings
from app.services.llm_provider import LLMProviderError, LLMTextResponse, generate_openai_compatible
from app.services.provider_retry import provider_api_retry

logger = structlog.get_logger()


@provider_api_retry()
def _call_anthropic_with_retry(client: anthropic.Anthropic, **kwargs):
    return client.messages.create(**kwargs)

BRIEF_JSON_CONTRACT = """Return only valid JSON, with no markdown fences and no extra prose.

Required object shape:
{
  "at_a_glance": {
    "verdict": "Skip | Skim | Watch fully",
    "core_thesis": "specific thesis/verdict in one sentence",
    "why_it_matters": "specific reason this matters",
    "best_use": "how Ken should use the video"
  },
  "executive_summary": ["2-4 concise paragraphs, not bullets"],
  "key_takeaways": [
    {
      "claim": "specific claim or take from the speaker",
      "evidence": "supporting example, number, named reference, or transcript detail",
      "caveat": "only include when a limitation materially changes how Ken should interpret or use the takeaway; otherwise null",
      "implication": "what follows from the claim, especially for Ken",
      "timestamp": "MM:SS/HH:MM:SS if present, otherwise null"
    }
  ],
  "detailed_brief": [
    {
      "heading": "specific section heading",
      "claims": ["extra claims or detail not already covered in Key Takeaways"],
      "evidence": ["extra examples, numbers, names, tactics, or stories not already used above"],
      "caveats": ["only material risks, limits, or missing context not already covered above"],
      "implications": ["additional so-what / what Ken should infer, not repeated operator actions"]
    }
  ],
  "notable_concepts_terms": [
    {"term": "term/name/framework", "meaning": "why it matters in this video"}
  ],
  "operator_notes": ["new action, decision, risk, or watch item for Ken; do not restate summary points"],
  "source_metadata": {
    "title": "video title",
    "transcript_word_count": 0,
    "timestamp_note": "whether timestamps/chapters were present or unavailable"
  },
  "low_content": false
}

Depth rules:
- For transcripts around 1,500+ words or videos over 10 minutes, provide 5-7 key_takeaways, 1-3 detailed_brief appendix sections only when they add non-repeated detail, and 4-8 notable concepts/terms.
- For shorter substantive transcripts, provide at least 4 key_takeaways and omit detailed_brief unless there is genuinely extra non-repeated material.
- For low-content/music/placeholders/repetition/extraction failures, set low_content=true and explain what can/cannot be learned instead of padding fake insight.

Quality rules:
- Section jobs and deduplication:
  - At-a-Glance gives the decision, thesis, relevance, and best use only.
  - Executive Summary gives the narrative once in 3-5 short paragraphs, with no bullets.
  - Key Takeaways are the top claims only: Claim, Evidence, Implication, and a Caveat only when the caveat materially changes the takeaway.
  - Detailed Brief is an appendix for extra detail that was not already covered in Key Takeaways; never repeat the same claim/evidence/caveat/implication structure for the same point.
  - Operator Notes must be action-only: what Ken should do, decide, monitor, or avoid. Do not restate content already summarized.
  - Do not include a Watch Map section.
  - Once a point has been made, later sections should add new utility or omit it.
- Choose exactly one watch verdict: Skip / Skim / Watch fully.
- Verdict calibration:
  - Use Watch fully when the transcript contains high-signal material directly relevant to Ken's agent systems, OpenClaw, AI ops, orchestration/control planes, security/auth, model routing, workflow design, GTM systems, or investment thesis work, especially when the video has reusable architecture patterns, implementation checklists, failure modes, or strategic operating lessons.
  - Use Skim when the transcript is useful but repetitive, mostly conceptual, shallow, or has only a few segments Ken needs.
  - Use Skip when the transcript is low-content, mostly promotional, off-topic for Ken, or does not contain enough concrete claims to justify attention.
  - Do not default to Skim just because the brief itself is complete; judge whether Ken should actually watch the source.
- Forbid vague bullets like "the video discusses X" unless the claim, evidence/example, caveat, and implication are explicit.
- Every key_takeaway must include claim, evidence, and implication. Include caveat only when material.
- Preserve numbers, examples, named people/products, frameworks, tactics, and caveats when present.
- Do not create timestamp navigation. If timestamps or chapters are unavailable, note that only in source_metadata.timestamp_note.
- Do not invent facts beyond the transcript."""

SUMMARY_SYSTEM_PROMPT = f"""You are Ken's executive video analyst. Your job is not to list topics; it is to make the transcript useful enough that Ken can scan it and understand the video's actual arguments, examples, caveats, implications, and watch value without watching.

Think in structured fields first, then return the structured JSON object.

{BRIEF_JSON_CONTRACT}"""

MARKDOWN_BRIEF_CONTRACT = """Return only markdown with this heading set and order. Omit Detailed Brief only when there is no non-repeated extra detail:

## At-a-Glance
- Verdict: Skip | Skim | Watch fully
- Core thesis: ...
- Why it matters: ...
- Best use: ...

## Executive Summary
2-4 concise paragraphs with the actual argument, examples, caveats, and value.

## Key Takeaways
- Claim: ... | Evidence: ... | Implication: ... | Caveat: ... only if material

## Detailed Brief
### Specific section heading
- Claims: extra detail not already covered in Key Takeaways
- Evidence: extra examples/numbers/names not already used above
- Caveats: only material risks/limits not already covered above
- Implications: additional inference, not repeated operator actions

## Notable Concepts & Terms
- Term: why it matters in this video

## Operator Notes / Why Ken Should Care
- Only new actions, decisions, risks, or watch items for Ken. Do not restate summary points. If relevance is low, say so plainly.

## Source/Metadata
- Title: video title
- Transcript words: count
- Timestamp note: whether timestamps/chapters were available

Section jobs and deduplication:
- At-a-Glance gives the decision, thesis, relevance, and best use only.
- Executive Summary gives the narrative once in 3-5 short paragraphs, with no bullets.
- Key Takeaways are the top claims only: Claim, Evidence, Implication, and a Caveat only when it materially changes the takeaway.
- Detailed Brief is an appendix for extra details not already covered in Key Takeaways; omit it for short/simple videos when there is no extra detail.
- Operator Notes are action-only: what Ken should do, decide, monitor, or avoid.
- Do not include Watch Map.
- Once a point has been made, later sections should add new utility or omit it.

Verdict calibration:
- Use Watch fully when the source is directly relevant to Ken's agent systems, OpenClaw, AI ops, orchestration/control planes, security/auth, model routing, workflow design, GTM systems, or investment thesis work, and contains reusable architecture patterns, implementation checklists, failure modes, or strategic operating lessons.
- Use Skim when the source is useful but repetitive, mostly conceptual, shallow, or has only a few segments Ken needs.
- Use Skip when the source is low-content, mostly promotional, off-topic for Ken, or lacks concrete claims.
- Do not default to Skim just because the brief is complete; judge whether Ken should actually watch the source.

For substantive transcripts over roughly 1,500 words or videos over 10 minutes, include at least 5 Key Takeaways, 1-3 non-redundant Detailed Brief sections, 4 Notable Concepts & Terms, and enough detail that the brief is not a teaser. If the transcript is low-content, say that plainly instead of inventing substance."""

SUMMARY_MARKDOWN_FALLBACK_PROMPT = f"""You are Ken's executive video analyst. A prior structured JSON attempt did not pass the deterministic report quality gate. Produce the final operator brief directly as markdown.

{MARKDOWN_BRIEF_CONTRACT}"""

CHUNK_SUMMARY_PROMPT = """Summarize this transcript portion for later consolidation. Preserve specific claims, examples, numbers, caveats, named people/products, and any watch-worthy moments. Do not reduce it to generic topics. If this chunk is low-content/music/placeholders/repetition, label that plainly:"""

CONSOLIDATION_PROMPT = f"""You are Ken's executive video analyst. You are given multiple partial summaries of a single video transcript titled "{{title}}". Combine them into one cohesive scan-first intelligence brief.

Think in structured fields first, then return the structured JSON object.

{BRIEF_JSON_CONTRACT}"""

CONSOLIDATION_MARKDOWN_FALLBACK_PROMPT = f"""You are Ken's executive video analyst. You are given multiple partial summaries of a single video transcript titled "{{title}}". A prior structured JSON attempt did not pass the deterministic report quality gate. Produce the final operator brief directly as markdown.

{MARKDOWN_BRIEF_CONTRACT}"""

MAX_TOKENS_PER_CHUNK = 80000  # Leave room for prompts within Claude's context


def _count_tokens(text: str) -> int:
    """Approximate token count using tiktoken cl100k_base."""
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _count_words(text: str | None) -> int:
    return len(re.findall(r"[\w']+", text or ""))


def _extract_json_object(text: str | None) -> dict[str, Any] | None:
    """Extract a JSON object from the model response if it followed the contract."""
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
    candidates = [raw]
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _stringify(item)
            if text:
                parts.append(f"{str(key).replace('_', ' ').title()}: {text}")
        return "; ".join(parts)
    return str(value).strip()


def _append_bullets(lines: list[str], values: Any) -> None:
    for value in _listify(values):
        text = _stringify(value)
        if text:
            lines.append(f"- {text}")


def _material_caveat(value: Any) -> str:
    caveat = _stringify(value)
    normalized = re.sub(r"[^a-z0-9]+", " ", caveat.lower()).strip()
    if normalized in {
        "",
        "none",
        "na",
        "n a",
        "null",
        "no caveat",
        "no caveat stated",
        "none stated",
        "not stated",
        "no material caveat",
        "no material caveat stated",
        "no caveat stated in the transcript",
    }:
        return ""
    return caveat


def _normalize_for_overlap(value: str) -> str:
    value = re.sub(r"^\s*(?:claims?|evidence|caveats?|implications?)\s*:\s*", "", value, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _non_redundant_detail_values(values: Any, key_takeaway_reference: str) -> list[str]:
    reference = _normalize_for_overlap(key_takeaway_reference)
    kept: list[str] = []
    for value in _listify(values):
        text = _stringify(value)
        if not text:
            continue
        normalized = _normalize_for_overlap(text)
        if normalized and len(normalized.split()) >= 5 and normalized in reference:
            continue
        kept.append(text)
    return kept


def structured_brief_to_markdown(
    payload: dict[str, Any],
    *,
    title: str = "",
    transcript_word_count: int | None = None,
    duration_seconds: float | None = None,
) -> str:
    """Render model JSON into the markdown shape stored in ``summaries``."""
    lines: list[str] = []

    at_a_glance = payload.get("at_a_glance") if isinstance(payload.get("at_a_glance"), dict) else {}
    lines.append("## At-a-Glance")
    if at_a_glance:
        for label, key in (
            ("Verdict", "verdict"),
            ("Core thesis", "core_thesis"),
            ("Why it matters", "why_it_matters"),
            ("Best use", "best_use"),
        ):
            value = _stringify(at_a_glance.get(key))
            if value:
                lines.append(f"- {label}: {value}")
    else:
        _append_bullets(lines, payload.get("at_a_glance"))
    lines.append("")

    lines.append("## Executive Summary")
    executive_summary = _listify(payload.get("executive_summary"))
    if executive_summary:
        for paragraph in executive_summary:
            text = _stringify(paragraph)
            if text:
                lines.extend([text, ""])
    lines.append("")

    lines.append("## Key Takeaways")
    for item in _listify(payload.get("key_takeaways")):
        if isinstance(item, dict):
            claim = _stringify(item.get("claim"))
            evidence = _stringify(item.get("evidence"))
            caveat = _material_caveat(item.get("caveat"))
            implication = _stringify(item.get("implication"))
            parts = [
                f"Claim: {claim}" if claim else "",
                f"Evidence: {evidence}" if evidence else "",
                f"Implication: {implication}" if implication else "",
                f"Caveat: {caveat}" if caveat else "",
            ]
            bullet = " | ".join(part for part in parts if part)
            if bullet:
                lines.append(f"- {bullet}")
        else:
            text = _stringify(item)
            if text:
                lines.append(f"- {text}")
    lines.append("")

    key_takeaway_reference = " ".join(_stringify(item) for item in _listify(payload.get("key_takeaways")))
    detailed_items = _listify(payload.get("detailed_brief"))
    rendered_detailed: list[str] = []
    for index, item in enumerate(detailed_items, start=1):
        if isinstance(item, dict):
            item_lines: list[str] = []
            heading = _stringify(item.get("heading")) or f"Brief Section {index}"
            item_lines.append(f"### {heading}")
            for label, key in (
                ("Claims", "claims"),
                ("Evidence", "evidence"),
                ("Caveats", "caveats"),
                ("Implications", "implications"),
            ):
                values = _non_redundant_detail_values(item.get(key), key_takeaway_reference)
                if values:
                    item_lines.append(f"- {label}: " + "; ".join(values))
            if len(item_lines) > 1:
                rendered_detailed.extend(item_lines)
                rendered_detailed.append("")
        else:
            text = _stringify(item)
            if text:
                rendered_detailed.append(f"- {text}")
    if rendered_detailed:
        lines.append("## Detailed Brief")
        lines.extend(rendered_detailed)
        lines.append("")

    lines.append("## Notable Concepts & Terms")
    for item in _listify(payload.get("notable_concepts_terms")):
        if isinstance(item, dict):
            term = _stringify(item.get("term"))
            meaning = _stringify(item.get("meaning"))
            if term or meaning:
                lines.append(f"- {term}: {meaning}" if term and meaning else f"- {term or meaning}")
        else:
            text = _stringify(item)
            if text:
                lines.append(f"- {text}")
    lines.append("")

    lines.append("## Operator Notes / Why Ken Should Care")
    _append_bullets(lines, payload.get("operator_notes"))
    lines.append("")

    source_metadata = payload.get("source_metadata") if isinstance(payload.get("source_metadata"), dict) else {}
    lines.append("## Source/Metadata")
    metadata_title = _stringify(source_metadata.get("title")) or title
    if metadata_title:
        lines.append(f"- Title: {metadata_title}")
    metadata_word_count = _stringify(source_metadata.get("transcript_word_count")) or (
        str(transcript_word_count) if transcript_word_count is not None else ""
    )
    if metadata_word_count:
        lines.append(f"- Transcript words: {metadata_word_count}")
    if duration_seconds is not None:
        lines.append(f"- Duration seconds: {int(duration_seconds)}")
    timestamp_note = _stringify(source_metadata.get("timestamp_note"))
    if timestamp_note:
        lines.append(f"- Timestamp note: {timestamp_note}")
    elif not any(re.search(r"\b\d{1,2}:\d{2}\b", line) for line in lines):
        lines.append("- Timestamp note: Timestamps or chapters were unavailable in the transcript.")

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def normalize_summary_response(
    response_text: str,
    *,
    title: str = "",
    transcript_word_count: int | None = None,
    duration_seconds: float | None = None,
) -> str:
    """Convert structured JSON responses to stored markdown, preserving fallback behavior."""
    payload = _extract_json_object(response_text)
    if payload is None:
        return response_text
    return structured_brief_to_markdown(
        payload,
        title=title,
        transcript_word_count=transcript_word_count,
        duration_seconds=duration_seconds,
    )


def summarize_text(
    text: str,
    video_title: str = "",
    api_key: str = "",
    model: str = "",
    *,
    record_usage_enabled: bool = True,
    video_duration_seconds: float | None = None,
    quality_feedback: list[str] | None = None,
    output_format: str = "structured",
) -> dict:
    """Summarize transcript text using Claude API.

    For long transcripts (>100k tokens), uses chunk-then-consolidate approach.
    Returns dict with summary, model, prompt_tokens, completion_tokens.
    """
    provider = settings.summary_llm_provider.strip().lower()
    if provider == "anthropic" and not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for summarization")

    client = anthropic.Anthropic(api_key=api_key) if api_key else None
    if not model:
        model = settings.summary_model

    token_count = _count_tokens(text)
    logger.info("summarizing", token_count=token_count, title=video_title, model=model)

    if token_count <= MAX_TOKENS_PER_CHUNK:
        return _summarize_single(
            client,
            provider,
            api_key,
            model,
            text,
            video_title,
            record_usage_enabled=record_usage_enabled,
            duration_seconds=video_duration_seconds,
            quality_feedback=quality_feedback,
            output_format=output_format,
        )
    else:
        return _summarize_chunked(
            client,
            provider,
            api_key,
            model,
            text,
            video_title,
            token_count,
            record_usage_enabled=record_usage_enabled,
            duration_seconds=video_duration_seconds,
            quality_feedback=quality_feedback,
            output_format=output_format,
        )


def _anthropic_text_response(
    client: anthropic.Anthropic,
    *,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
) -> LLMTextResponse:
    response = _call_anthropic_with_retry(
        client,
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return LLMTextResponse(
        content=response.content[0].text,
        model=response.model,
        prompt_tokens=response.usage.input_tokens,
        completion_tokens=response.usage.output_tokens,
    )


def _call_summary_llm(
    client: anthropic.Anthropic | None,
    *,
    provider: str,
    api_key: str,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
) -> LLMTextResponse:
    if provider == "anthropic":
        if client is None:
            raise ValueError("ANTHROPIC_API_KEY is required for summarization")
        return _anthropic_text_response(
            client,
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )

    if provider in {"openai_compatible", "openai-compatible", "openai"}:
        try:
            return generate_openai_compatible(
                base_url=settings.summary_llm_base_url,
                api_key=settings.summary_llm_api_key,
                model=model,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
            )
        except LLMProviderError as exc:
            fallback_provider = settings.summary_llm_fallback_provider.strip().lower()
            if fallback_provider != "anthropic" or not api_key:
                raise
            logger.warning(
                "summary_llm_fallback_to_anthropic",
                provider=provider,
                model=model,
                error=str(exc),
            )
            fallback_client = client or anthropic.Anthropic(api_key=api_key)
            return _anthropic_text_response(
                fallback_client,
                model=settings.summary_llm_fallback_model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )

    raise ValueError(f"Unsupported summary LLM provider: {provider}")


def _summarize_single(
    client: anthropic.Anthropic | None,
    provider: str,
    api_key: str,
    model: str,
    text: str,
    title: str,
    *,
    record_usage_enabled: bool = True,
    duration_seconds: float | None = None,
    quality_feedback: list[str] | None = None,
    output_format: str = "structured",
) -> dict:
    """Summarize text in a single API call."""
    from app.services.cost_tracker import record_usage

    word_count = _count_words(text)
    metadata_lines = [
        f"Video title: {title or 'unknown'}",
        f"Transcript word count: {word_count}",
    ]
    if duration_seconds is not None:
        metadata_lines.append(f"Video duration seconds: {int(duration_seconds)}")
    if quality_feedback:
        metadata_lines.extend(
            [
                "",
                "The previous generated brief failed deterministic quality checks.",
                "Fix these issues in the regenerated JSON:",
                *[f"- {line}" for line in quality_feedback],
            ]
        )
    user_content = "\n".join(metadata_lines) + f"\n\nTranscript:\n{text}"

    response = _call_summary_llm(
        client,
        provider=provider,
        api_key=api_key,
        model=model,
        max_tokens=12000,
        system=SUMMARY_MARKDOWN_FALLBACK_PROMPT if output_format == "markdown" else SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    if record_usage_enabled:
        record_usage(response.model, response.prompt_tokens, response.completion_tokens)

    response_text = response.content
    summary = (
        response_text
        if output_format == "markdown"
        else normalize_summary_response(
            response_text,
            title=title,
            transcript_word_count=word_count,
            duration_seconds=duration_seconds,
        )
    )

    return {
        "summary": summary,
        "model": response.model,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
    }


def _summarize_chunked(
    client: anthropic.Anthropic | None,
    provider: str,
    api_key: str,
    model: str,
    text: str,
    title: str,
    total_tokens: int,
    *,
    record_usage_enabled: bool = True,
    duration_seconds: float | None = None,
    quality_feedback: list[str] | None = None,
    output_format: str = "structured",
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
        response = _call_summary_llm(
            client,
            provider=provider,
            api_key=api_key,
            model=model,
            max_tokens=2048,
            system=CHUNK_SUMMARY_PROMPT,
            messages=[{"role": "user", "content": f"Part {i + 1}/{len(chunks)}:\n\n{chunk}"}],
        )
        partial_summaries.append(response.content)
        total_prompt += response.prompt_tokens
        total_completion += response.completion_tokens
        if record_usage_enabled:
            record_usage(response.model, response.prompt_tokens, response.completion_tokens)

    # Consolidate
    combined = "\n\n---\n\n".join(
        f"**Part {i + 1} Summary:**\n{s}" for i, s in enumerate(partial_summaries)
    )

    feedback_block = ""
    if quality_feedback:
        feedback_block = "\n\nQuality gate feedback to fix:\n" + "\n".join(
            f"- {line}" for line in quality_feedback
        )
    word_count = _count_words(text)
    system_prompt = CONSOLIDATION_PROMPT if output_format != "markdown" else CONSOLIDATION_MARKDOWN_FALLBACK_PROMPT
    response = _call_summary_llm(
        client,
        provider=provider,
        api_key=api_key,
        model=model,
        max_tokens=12000,
        system=system_prompt.replace("{title}", title),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Video title: {title or 'unknown'}\n"
                    f"Transcript word count: {word_count}\n"
                    f"Video duration seconds: {int(duration_seconds) if duration_seconds is not None else 'unknown'}"
                    f"{feedback_block}\n\nPartial summaries:\n{combined}"
                ),
            }
        ],
    )
    total_prompt += response.prompt_tokens
    total_completion += response.completion_tokens
    if record_usage_enabled:
        record_usage(response.model, response.prompt_tokens, response.completion_tokens)

    response_text = response.content
    summary = (
        response_text
        if output_format == "markdown"
        else normalize_summary_response(
            response_text,
            title=title,
            transcript_word_count=word_count,
            duration_seconds=duration_seconds,
        )
    )

    return {
        "summary": summary,
        "model": response.model,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
    }
