# BuildClaw Phase 2: Chat Backend — Error Handling Hardening

## Goal
Add graceful error handling to the Phase 2 chat backend for missing dependencies and missing API keys.

## Assumptions
- Phase 2 was already fully implemented in commit ee872d2
- `encode_query()` imports sentence_transformers which may fail in some environments
- Anthropic API key may be unconfigured

## Steps
1. Wrap `encode_query()` + `semantic_search()` in try/except — fallback to empty chunks on failure
2. Add early return when `anthropic_api_key` is empty — return informative error message
3. Add 2 new tests for the error handling paths
4. Run full test suite: 507 passed
5. Update handoff docs, commit, push
