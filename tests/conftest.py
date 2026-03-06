"""Shared test fixtures and configuration."""

import os

# Set a dummy Anthropic API key so chat service tests don't short-circuit
# on the "API key not configured" guard. Tests that need to verify
# the missing-key behavior should explicitly patch settings.anthropic_api_key = "".
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-ci")
