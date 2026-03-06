# QAClaw Task: Post-Implementation Testing & Bug Fixes

**Trigger:** Run after BuildClaw completes Phases 1-3, then again after Phase 4.

---

## Round 1: After Phases 1-3 (Embedding Model + Chunking + Re-embed)

### Scope
Review, test, and fix the code changes from Phases 1-3 of the Embedding & Chunking Upgrade Plan.

### Tasks

**1. Code Review**
- Read ALL changed files and verify they match the plan in `docs/EMBEDDING_UPGRADE_PLAN.md`
- Check for bugs, edge cases, missing error handling
- Verify Alembic migrations are correct and reversible
- Ensure config settings are properly wired through

**2. Unit Tests** (add to `tests/`)
- Embedding model outputs 768d vectors
- Task prefixes (`search_document:` / `search_query:`) are correctly applied
- Speaker-aware chunking:
  - Diarized segments → chunks respect speaker boundaries
  - Non-diarized segments → falls back to sentence-boundary splitting  
  - Long single-speaker monologue → splits at sentence boundaries
  - Very short turns merge with adjacent same-speaker turns
  - Edge cases: single segment, empty segments, no text
- Chunk sizes stay within configured target/max bounds
- Re-embed script handles --dry-run correctly

**3. Smoke Tests**
- Import `chunk_and_embed` and run against sample segments
- Import `encode_query` and verify it returns 768d vector
- Verify `embedding_chunks` table has `speaker` column and `vector(768)`

**4. Fix Any Bugs Found**
- Fix and commit with clear messages
- Re-run full test suite after fixes

### Run Tests
```bash
cd ~/Projects/youtube-transcriber
.venv/bin/pytest -v
```

---

## Round 2: After Phase 4 (Hybrid Search)

### Additional Tasks
- Verify hybrid search combines BM25 + vector scores correctly
- Test `search_mode` config toggle (vector / hybrid / keyword)
- Test tsvector column + GIN index creation
- Verify search still works in vector-only mode
- Edge cases: queries with special characters, empty results, single-word queries
- Fix any bugs, commit, push

---

## Acceptance Criteria
- [ ] All existing tests pass
- [ ] New unit tests cover embedding model, chunking logic, and search
- [ ] No obvious bugs in code review
- [ ] Test suite runs clean with 0 failures
