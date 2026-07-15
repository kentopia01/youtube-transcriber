from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.services.llm_provider import LLMProviderError, generate_openai_compatible


def test_generate_openai_compatible_normalizes_chat_completion(monkeypatch):
    observed: dict[str, object] = {}

    def fake_post(url, *, headers, json, timeout):
        observed["url"] = url
        observed["headers"] = headers
        observed["json"] = json
        observed["timeout"] = timeout

        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "model": "actual-model",
                "choices": [{"message": {"content": "done"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    result = generate_openai_compatible(
        base_url="http://127.0.0.1:8400/v1/",
        api_key="local-key",
        model="codex",
        system="system prompt",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=99,
        timeout_seconds=7,
    )

    assert observed["url"] == "http://127.0.0.1:8400/v1/chat/completions"
    assert observed["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer local-key",
    }
    assert observed["json"] == {
        "model": "codex",
        "messages": [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
        ],
        "max_tokens": 99,
        "stream": False,
    }
    assert observed["timeout"] == 7
    assert result.content == "done"
    assert result.model == "actual-model"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 3


def test_generate_openai_compatible_raises_on_malformed_response(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": []},
        ),
    )

    with pytest.raises(LLMProviderError, match="malformed"):
        generate_openai_compatible(
            base_url="http://127.0.0.1:8400/v1",
            model="codex",
            system=None,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=10,
        )


def test_generate_openai_compatible_requires_base_url():
    with pytest.raises(LLMProviderError, match="base URL"):
        generate_openai_compatible(
            base_url="",
            model="codex",
            system=None,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=10,
        )
