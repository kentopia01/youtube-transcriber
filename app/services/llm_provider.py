"""Small LLM provider helpers for non-Anthropic routes."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class LLMProviderError(RuntimeError):
    """Raised when a configured LLM provider call fails."""


@dataclass(frozen=True)
class LLMTextResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").rstrip("/")


def generate_openai_compatible(
    *,
    base_url: str,
    api_key: str = "",
    model: str,
    system: str | None,
    messages: list[dict],
    max_tokens: int,
    timeout_seconds: float = 180.0,
) -> LLMTextResponse:
    """Call an OpenAI-compatible chat-completions endpoint."""
    normalized_base = _normalize_base_url(base_url)
    if not normalized_base:
        raise LLMProviderError("OpenAI-compatible base URL is not configured")

    payload_messages = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(messages)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.post(
            f"{normalized_base}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": payload_messages,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMProviderError(f"OpenAI-compatible provider call failed: {exc}") from exc

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMProviderError("OpenAI-compatible provider returned malformed response") from exc

    usage = data.get("usage") or {}
    return LLMTextResponse(
        content=content,
        model=str(data.get("model") or model),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )
