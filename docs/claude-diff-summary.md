# QAClaw Round 1: Diff Summary

## What Changed

### Bug Fix: `app/services/embedding.py`
- **Lines 55-57**: `_split_at_sentence_boundaries` had a dead `pass` statement inside a `target_tokens` check. Chunks only flushed at `max_tokens` (400), ignoring `target_tokens` (300). Replaced with actual flush logic so chunks split near the target size.

### New Tests: `tests/test_embedding_service.py`
Added 4 new test classes (16 tests total):
- `TestTargetTokensSplitting` -- verifies chunks flush at target, not max; handles single long sentences
- `TestEdgeCases` -- single segment, empty text, missing speaker key, mixed speakers, all-empty segments
- `TestChunkAndEmbed` -- mocked model tests: 768d output, search_document prefix, empty input, multi-speaker

### New Tests: `tests/test_config.py`
Added 5 tests for new embedding config defaults:
- `embedding_model`, `embedding_dimensions`, `chunk_target_tokens`, `chunk_max_tokens`, overridability

## Why
- The target_tokens bug meant all chunks tended toward 400 tokens instead of the intended 200-400 range
- Test coverage for the new embedding pipeline was thin -- no mocked integration tests, no edge case coverage

## Risks
- The target_tokens fix changes chunking behavior -- existing re-embedded content would need re-embedding again (but since Phase 3 hasn't run in production yet, this is a no-op risk)
- No live database migration testing (reviewed by code inspection only)

## Plan Deviations
- None. All work follows QACLAW_TASK.md Round 1 scope.
