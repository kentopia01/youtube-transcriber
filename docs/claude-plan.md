# QAClaw Phase 2 QA Round 2 — Chat Backend Review

## Goal
Thorough code review and QA testing of Phase 2 (Chat Backend): migration 006, models, chat service (RAG pipeline), chat router, schemas, config.

## Assumptions
- Phase 1 (toggle system) is complete and tested
- Phase 2 code was implemented by BuildClaw
- First QA pass already completed; this is a deeper review

## Steps
1. Read CHAT_FEATURE_PLAN.md Phase 2 section
2. Review all Phase 2 files against spec
3. Run existing tests to establish baseline (57 chat tests passed)
4. Identify bugs and gaps:
   - No input validation on `ChatMessageSend.content` (empty/very long allowed)
   - No input validation on `ChatSessionRename.title` (empty string allowed)
   - `asyncio.get_event_loop()` deprecated, should use `get_running_loop()`
   - No error handling around Anthropic API calls in `chat_with_context`
   - Sources list built after LLM call, unavailable in error path
5. Fix bugs: validation in schemas, error handling in service, deprecation fix
6. Add 14 new edge case tests to test_chat_backend.py
7. Run full suite: 532 passed, 0 failed
8. Create handoff docs, commit, push
