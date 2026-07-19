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
- T050 keeps the default YouTube LLM path Codex/OAuth-only, but uses workload-specific Smart Router profiles instead of generic `codex` everywhere.

### T048 subscription watchlist and long-form ingest clarifications
- Subscription auto-ingest is for long-form videos, not Shorts/reels/short clips.
- The default autonomous duration floor is 600 seconds; set `AUTO_INGEST_MIN_DURATION_SECONDS=0` only if short-form ingest is intentionally desired.
- Manual single-video submissions remain outside this filter so operators can still transcribe a short clip explicitly.
- Backlog seeding for newly followed channels should apply the same duration floor before queueing videos.

### T049 recipient lanes and scoped digest clarifications
- This is a lightweight shared-processing lane model, not full multi-tenant isolation and not a separate instance per user.
- Shared global videos, transcripts, summaries, jobs, embeddings, and reports are acceptable.
- Recipient-facing channel configuration and digest delivery must be scoped by lane.
- Do not reuse the existing global `channel_subscriptions` table for restricted-user subscribe/unsubscribe; add lane-scoped subscription state instead.
- Every user, including Ken, should have a personal digest lane.
- Ken's personal digest should include only Ken-lane items.
- Ken's Telegram identity should also have admin/operator capability across every lane for monitoring and troubleshooting.
- Restricted users should only see and use `/start`, `/help`, `/subscribe`, `/unsubscribe`, `/subscriptions`, and optionally `/digest`.
- Search/chat/RAG/job/report/notify/admin commands should remain admin-only and hidden from the simple restricted help/menu.
- Implementation is gated until the current catch-up pipeline has fully drained and Ken explicitly reopens this work.

### T051/T052 throughput clarifications
- The immediate throughput goal is faster completed intelligence, not perfect speaker labels on first pass.
- Catch-up release should continue through scheduled premieres, unavailable videos, and isolated submit failures, while still stopping for fresh real pipeline blockers.
- On Ken's local M4/16GB host, do not increase heavy-stage concurrency as the first speed lever.
- Default to summary-first ingest: transcribe, cleanup, summarize, embed, and report before diarization.
- Keep inline diarization available by config for videos where speaker labels are worth the extra runtime.
- Remote GPU or hosted diarization remains a later design spike after stage timing data.

### T053 diarization usefulness detector clarifications
- Keep summary-first as the default; speaker labeling must not block first-pass cleanup, summary, embedding, or report delivery.
- The detector should run after transcription and be much cheaper than full diarization.
- Use deterministic metadata/transcript heuristics for v1 rather than an LLM or full audio diarization probe.
- Store the decision structurally on the video so later workers/admin tools can inspect it without parsing progress messages.
- Do not automatically enqueue deferred diarization in T053; first collect decision quality and keep explicit/operator-triggered diarization available.
- Likely solo lectures, coding tutorials, demos, and monologues should default to skipping diarization.
- Interviews, podcasts, panels, debates, fireside chats, guest conversations, and Q&A-heavy formats should be marked as worth deferred diarization.
