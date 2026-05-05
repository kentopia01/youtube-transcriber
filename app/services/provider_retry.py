"""Retry taxonomy for transient LLM provider failures.

Cleanup and summarization are allowed to retry short-lived API/network
failures, but permanent provider/application errors should surface normally so
pipeline recovery can keep useful stage-aware failure signatures.
"""

from __future__ import annotations

from typing import Any

import anthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random_exponential

PROVIDER_RETRY_ATTEMPTS = 4
PROVIDER_RETRY_WAIT_MIN_SECONDS = 1
PROVIDER_RETRY_WAIT_MAX_SECONDS = 45

RETRYABLE_PROVIDER_EXCEPTION_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailableError",
        "APITimeout",
        "ReadTimeout",
        "ConnectTimeout",
        "TimeoutException",
        "TimeoutError",
        "ConnectError",
        "ConnectionError",
    }
)

_TRANSIENT_MESSAGE_MARKERS = (
    "connection error",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "rate limit",
    "too many requests",
    "server error",
    "internal server error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)


def _anthropic_exception_type(name: str) -> type[BaseException] | None:
    exc_type = getattr(anthropic, name, None)
    if isinstance(exc_type, type) and issubclass(exc_type, BaseException):
        return exc_type
    return None


def _retryable_anthropic_exception_types() -> tuple[type[BaseException], ...]:
    names = (
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
    )
    return tuple(exc for name in names if (exc := _anthropic_exception_type(name)) is not None)


def _response_status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status

    response: Any = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status

    return None


def is_retryable_provider_error(exc: BaseException) -> bool:
    """Return True for provider/network failures that are safe to retry.

    Covers Anthropic connection/timeouts, 429 rate limits, and 5xx provider
    responses. Keeps 4xx request/content errors non-retryable unless they are
    explicit 429s.
    """
    status = _response_status_code(exc)
    if status in {408, 429} or (status is not None and 500 <= status <= 599):
        return True
    if status is not None:
        return False

    retryable_types = _retryable_anthropic_exception_types()
    if retryable_types and isinstance(exc, retryable_types):
        return True

    if isinstance(exc, TimeoutError):
        return True

    exc_name = exc.__class__.__name__
    if exc_name in RETRYABLE_PROVIDER_EXCEPTION_NAMES:
        return True

    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_MESSAGE_MARKERS)


def provider_api_retry(
    *,
    attempts: int = PROVIDER_RETRY_ATTEMPTS,
    wait_min: float = PROVIDER_RETRY_WAIT_MIN_SECONDS,
    wait_max: float = PROVIDER_RETRY_WAIT_MAX_SECONDS,
):
    """Tenacity retry decorator for transient provider/API failures."""
    return retry(
        retry=retry_if_exception(is_retryable_provider_error),
        wait=wait_random_exponential(multiplier=1, min=wait_min, max=wait_max),
        stop=stop_after_attempt(attempts),
        reraise=True,
    )
