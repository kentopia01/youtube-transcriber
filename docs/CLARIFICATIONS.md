# Clarifications

## Workflow rule
For serious implementation work in this repo, the execution source of truth is:
- `AGENTS.md`
- `docs/PLAN.md`
- `docs/CLARIFICATIONS.md`
- `docs/tasks/TASK_INDEX.md`
- task files under `docs/tasks/`

BuildClaw should implement against these files, not a chat brief alone. QAClaw should validate against the same files.

## Current clarifications

### Global corpus search clarifications
- The goal is whole-corpus search over every ingested video, not persona prompt expansion.
- Web chat should default to all embedded YouTube videos, with an explicit channel/account filter for scoped retrieval.
- Channel/persona-specific chat can still pass a channel scope explicitly.
- Keep `/api/search` behavior stable; add a separate global search route and UI.
- Use existing pgvector and PostgreSQL full-text search first. Do not introduce FAISS, Qdrant, Weaviate, GraphRAG, or a local heavy reranker for v1.
- Search should include summary chunks as a separate retrieval lane because summary chunks are useful for broad/thematic queries.
- Retrieval should return source metadata: video ID, title, YouTube ID, channel name when available, timestamp, source type, and score components.
- Result packing should favor concise evidence snippets over dumping whole chunks into downstream prompts.
- Advanced techniques are follow-ons after evaluation: query fusion/HyDE, API rerankers, RAPTOR-style hierarchy, and GraphRAG-style graph summaries.
- The target hardware is basic local hardware, so local inference must stay bounded and optional.

### Superseded failed jobs and retention
- Superseded failed jobs should be hidden from the default failed-job UI.
- A failed job is superseded when a newer job for the same video is created through retry or failed-video re-submit.
- Hidden superseded failed jobs should be retained for 14 days, then deleted by cleanup.
- Cleanup should delete only hidden, superseded, failed jobs, not active, visible, or completed jobs.
- Dry-run must be available before enabling automated cleanup.

### Rollout safety
- Do a dry-run cleanup before enabling scheduled deletion.
- Keep ingestion dedupe behavior unchanged for non-failed existing videos.
- Use targeted tests plus QA validation before rollout.

### Current hotfix scope
- Fixes for the current GitHub Actions red build and the diarization `AudioDecoder` runtime error should be kept surgical.
- The 3 earlier user-requested videos should be retried only after the runtime fix is applied.
- Do not claim the transcription workflow is healthy until those retried jobs are verified.

### Phase 1 stabilization scope
- The current superseding-job churn is treated as a pipeline design problem, not just an operator problem.
- Phase 1 should prioritize attempt lineage, one-active-attempt enforcement, artifact-aware resume planning, and safe audio retention for retryable execution.
- Speed/parallelism changes are intentionally deferred until the retry/resume model is trustworthy.

### Phase 1.5 stabilization scope
- The one-active-attempt rule should be enforced at the database level, not just in application code.
- Submit/retry conflict paths should fail predictably and return the active attempt instead of creating duplicate active attempts.
- Add at least one concurrent integration test that proves the race window is closed.

### Phase 2 stabilization scope
- Separate lifecycle status from stage/progress semantics so active, terminal, and superseded attempts are unambiguous.
- Current stage should be explicitly tracked for active pipeline jobs.
- Recovery/retry logic should rely on explicit state rather than parsing ambiguous progress messages.

### Phase 3 stabilization scope
- Recovery should be bounded, stage-aware, and predictable.
- Repeated identical failures should not create indefinite attempt churn.
- Slow-but-active jobs should be distinguished from truly stale jobs before automatic recovery or reaping occurs.
- Quarantine/manual-review paths are acceptable when repeated failure signatures persist.

### Post-Phase-3 sequencing
- After T007, prioritize observability before throughput work.
- Record structured attempt-creation reasons, worker identity/activity, and artifact-check results before splitting queues.
- Worker health should distinguish busy-but-healthy from unhealthy before any throughput/concurrency tuning.
- Do not increase concurrency on the existing single queue as a substitute for proper workload separation.

### T009 throughput clarifications
- Throughput work should target podcast-style videos, usually 15 to 45 minutes.
- Channel jobs should use the same core pipeline semantics as manual jobs.
- Channel jobs should be represented durably in DB-backed backlog state and released gradually into runnable queues.
- Manual jobs should retain a protected path to progress even while channel backlog exists.
- Queue routing must be explicit and attempt-safe; tasks should not guess ownership from "latest job for video" behavior.
- Prefer conservative heavy-stage concurrency on current hardware: start with one active `audio`, one active `diarize`, and one active `post` lane.

### T014 report-delivery clarifications
- Telegram push delivery should send finished intelligence directly, not primarily redirect users into chat/channel views.
- Per-video completion messages should be concise and should not include Chat/Channel buttons by default.
- The styled HTML report is the MVP delivery artifact; PDF export is explicitly later.
- Report generation and document delivery are post-processing concerns. They must not cause a successfully transcribed/summarized/embedded video to become a failed transcription pipeline job.
- The daily morning brief should include overnight activity plus operational status: queued/pending work, retries, failed/manual-review items, worker/system health, and LLM spend.
- Existing manual bot commands for chat/channel navigation should remain available; only pushed delivery notifications are simplified.

### T015 scan-first summary intelligence clarifications
- Summary quality should be judged by whether Ken can understand the video’s actual contents/takes without watching, not by summary length.
- Summaries should lead with thesis/verdict and key claims, then include supporting examples, numbers, caveats, implications, and watch recommendation.
- “Main Topics” as the leading section is no longer sufficient; topic lists may exist only if they support the scan-first contract.
- Telegram report captions should provide a quick useful summary of the video/report. Do not say “Attached: summary report” and do not add “try it” buttons to pushed report delivery.
- Low-content transcripts, music-only videos, placeholders, or extraction failures should be flagged plainly as low-content/invalid transcript instead of padded into fake insight.

### T044 Codex-auth batch LLM migration clarifications
- Prioritize daily/nightly transcription follow-on intelligence: summary generation, report/caption intelligence, and morning/daily digest.
- Chat and persona generation were secondary to the initial batch path, then promoted in T047 after summary/digest validation.
- Smart Router is not assumed maintained infrastructure; it must be triaged, launched, health-checked, and Codex-auth smoke-tested before transcriber routing depends on it.
- The transcriber must not read or store Codex OAuth tokens. It should call a local OpenAI-compatible endpoint.
- Anthropic remains the explicit fallback/rollback path for migrated workflows.
- Per-workload provider flags are preferred over switching the whole application at once.
