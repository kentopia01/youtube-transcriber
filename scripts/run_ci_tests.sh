#!/usr/bin/env bash
# Run the test suite exactly as GitHub Actions does.
#
# CI installs only the [dev] extras — no torch, no mlx-whisper, no
# sentence-transformers — so tests that rely on those libraries must
# guard for their absence. Use this script before pushing to catch
# CI-only failures locally.
#
#   bash scripts/run_ci_tests.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv-ci"

echo "==> Ensuring CI-equivalent venv at $VENV"
if [[ ! -d "$VENV" ]]; then
  python3.12 -m venv "$VENV" || python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"

echo "==> Installing .[dev] (CI's exact pip line)"
python -m pip install --upgrade pip -q
python -m pip install "$ROOT[dev]" -q

echo "==> Running pytest with CI's env"
cd "$ROOT"
ANTHROPIC_API_KEY=test-key-for-ci python -m pytest -q "$@"
