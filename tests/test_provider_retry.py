from types import SimpleNamespace

from app.services.provider_retry import is_retryable_provider_error


class CustomConnectionError(Exception):
    pass


class BadRequestLike(Exception):
    status_code = 400


class RateLimitLike(Exception):
    status_code = 429


class ServerErrorViaResponse(Exception):
    response = SimpleNamespace(status_code=503)


def test_connection_error_message_is_retryable():
    assert is_retryable_provider_error(CustomConnectionError("Connection error.")) is True


def test_429_and_5xx_are_retryable():
    assert is_retryable_provider_error(RateLimitLike("too many requests")) is True
    assert is_retryable_provider_error(ServerErrorViaResponse("service unavailable")) is True


def test_non_429_4xx_is_not_retryable():
    assert is_retryable_provider_error(BadRequestLike("invalid request")) is False
