"""Shared test fixtures and configuration."""

import importlib
import os

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
