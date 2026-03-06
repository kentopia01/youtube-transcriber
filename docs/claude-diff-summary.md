# BuildClaw Phase 2: Chat Backend — Error Handling Hardening

## What Changed

| File | Change |
|---|---|
| `app/services/chat.py` | Wrapped search (encode_query + semantic_search) in try/except — on failure, logs warning and continues with empty chunks. Added early return when `anthropic_api_key` is empty. |
| `tests/test_chat_backend.py` | Added 2 tests: `test_chat_graceful_when_search_fails` (ImportError from sentence_transformers), `test_chat_returns_error_when_api_key_missing` |

## Why
- `encode_query()` imports `sentence_transformers` which may not be available in test/web environments
- Missing API key should produce a clear error message, not an exception

## Risks
- None — purely additive error handling; all 507 tests pass

## Plan Deviations
- None
