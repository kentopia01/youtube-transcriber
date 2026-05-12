"""Shared test fixtures and configuration."""

import importlib
import os

import pytest

# Set a dummy Anthropic API key so chat service tests don't short-circuit
# on the "API key not configured" guard. Tests that need to verify
# the missing-key behavior should explicitly patch settings.anthropic_api_key = "".
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-ci")

# Skip test files that require optional dependencies not present in this venv.
# This avoids ImportError collection failures for lightweight/CI environments.
_OPTIONAL_DEPS = {
    "test_telegram_bot.py": "telegram",
}

collect_ignore = []
for _filename, _module in _OPTIONAL_DEPS.items():
    try:
        importlib.import_module(_module)
    except ImportError:
        collect_ignore.append(_filename)


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def pytest_addoption(parser):
    parser.addoption(
        "--run-smoke",
        action="store_true",
        default=False,
        help="Run smoke tests that may hit local services. Equivalent env: YT_RUN_SMOKE=1.",
    )
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run e2e tests that may hit local services. Equivalent env: YT_RUN_E2E=1.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "smoke: service-dependent smoke tests; skipped unless --run-smoke or YT_RUN_SMOKE=1",
    )
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end tests; skipped unless --run-e2e or YT_RUN_E2E=1",
    )


def pytest_collection_modifyitems(config, items):
    run_smoke = config.getoption("--run-smoke") or _env_truthy("YT_RUN_SMOKE")
    run_e2e = config.getoption("--run-e2e") or _env_truthy("YT_RUN_E2E")

    skip_smoke = pytest.mark.skip(
        reason="smoke test requires explicit opt-in: --run-smoke or YT_RUN_SMOKE=1"
    )
    skip_e2e = pytest.mark.skip(
        reason="e2e test requires explicit opt-in: --run-e2e or YT_RUN_E2E=1"
    )

    for item in items:
        if item.get_closest_marker("smoke") and not run_smoke:
            item.add_marker(skip_smoke)
        if item.get_closest_marker("e2e") and not run_e2e:
            item.add_marker(skip_e2e)
