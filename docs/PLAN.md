# Pipeline Stabilization and Execution Roadmap

## Current status

The YouTube Transcriber pipeline has completed the stabilization, delivery-quality, remediation, and final default full-suite validation arc through T025.

## Active follow-on: Global corpus search

Goal: add a first-class operator search path across every ingested video, transcript chunk, and summary chunk without replacing the current Postgres/pgvector storage layer.

The operator search surface remains separate from `/api/search`. Web chat now defaults to all embedded videos and can be narrowed to a specific YouTube channel/account; channel/persona chat can still pass its own channel scope.

Implementation posture:
- reuse existing Nomic query embeddings, pgvector, and PostgreSQL full-text search
- search all ingested videos by default, with optional channel/source filters
- fuse vector, keyword, and summary lanes with reciprocal rank fusion
- dedupe and diversify results so one video does not dominate every answer
- return compact evidence snippets with video IDs, timestamps, source type, and scores
- defer HyDE, API rerankers, RAPTOR, and GraphRAG until v1 search is measurable

Hardware posture:
- no heavy local reranker in the first release
- keep candidate pools bounded
- make advanced inference optional and off by default

Execution chunks:
- T037: global search source-of-truth docs and task contract
- T038: global search service with whole-corpus hybrid retrieval
- T039: diversity, dedupe, and evidence pack helpers
- T040: API endpoint and operator UI
- T041: web chat default all-corpus retrieval plus channel/account filter
- T042: reranker/query-expansion experiment
- T043: evaluation benchmark and tuning

Source of truth begins with `docs/tasks/T037_global_search_source_of_truth.md`.

Completed:
- T001: hide superseded failed jobs + retention cleanup
- T002: native ops cleanup and README rollout notes
- T003: CI/test env fix, diarization runtime fix, and 3 requested video retries
- T004: Phase 1, attempt model + one-active-attempt guard + artifact-aware resume
- T005: Phase 1.5, DB-level one-active-attempt enforcement
- T006: Phase 2, explicit lifecycle status vs stage/progress separation
- T007: Phase 3, recovery guardrails + stale-job behavior + retry containment
- T008: pipeline observability and attempt reasoning
- T009: throughput queues after stability
- T010: queue routing contract and stage gates
- T011: channel backlog dispatcher and fairness
- T012: worker topology rollout and throughput validation
- T013: stabilization/throughput completion baseline
- T014: styled report delivery, Telegram delivery, and overnight brief status
- T015: scan-first summary intelligence and guarded backfill/eval tooling
- T016: full engineering audit and remediation roadmap
- T017: pipeline enqueue transaction boundary
- T018: unified pipeline attempt factory
- T019: smoke/e2e test isolation
- T020: Alembic/model contract tests
- T021: config model-name consolidation
- T022: channel dispatcher single source of truth
- T023: broad exception audit + structured side-effect logging
- T024: report schema intent cleanup
- T025: final full-suite release hygiene
- T026: brief quality repair and report depth gate
- T027: summary quality gate hotfix

The prior full default validation baseline is green: `1157 passed, 11 skipped`; skipped tests are opt-in smoke/e2e tests. T026 added focused brief-quality validation after that baseline.

## Current verified reality

As of 2026-05-12, the repo is in a validated local default-test state after the T017-T025 remediation pass:
- queue routing exists in code and tasks are routed into `audio`, `diarize`, and `post`
- channel processing creates durable pending jobs and releases them through the dispatcher path
- launchd now runs a split native worker topology for `audio`, `diarize`, and `post,celery`
- Celery queue inspection confirms the intended queue coverage on the native workers
- focused T011 verification is green across dispatcher fairness, channel API, orchestration, retry/recovery, and worker-health packs
- launchd PATH handling was fixed so ffmpeg and ffprobe are available to the audio worker
- real routed-job smoke tests succeeded after the split-worker rollout
- practical overlap was observed with one job in `diarize` and another in `transcribe` on separate workers

This means the stabilization, dispatcher, worker-topology, report-delivery, remediation, and default full-suite roadmap through T025 is complete. A controlled live smoke remains an optional runtime-confidence step, not part of the default non-mutating suite.

## Roadmap goal

Keep the pipeline reliable first, then make it easier to triage, then improve throughput.

The ordering matters:
1. Stabilize retries, resume behavior, and stale-job recovery.
2. Add structured observability so operators can explain what is happening.
3. Split workloads with explicit routing and attempt-safe stage gates.
4. Only then complete durable channel dispatch and worker-topology rollout.

## Why this order

Past failures were not just single-stage bugs. They came from pipeline design weaknesses:
- retries were too loosely modeled
- resume logic was too optimistic
- artifact lifecycle was too aggressive
- state tracking was too muddy
- worker topology assumptions were implicit instead of verified

That is why the repo treats stability and observability as prerequisites for speed, and treats worker rollout as something that must be proven rather than assumed.

## Follow-on direction

### Goal
Roll out the split worker topology safely on the current Mac mini and validate that it improves throughput without destabilizing the pipeline.

### Architecture direction
Split workloads into three lanes:
- `audio`: download + transcribe
- `diarize`: diarize + align
- `post`: cleanup + summarize + embed

Use the DB as the durable source of truth for backlog and attempt ownership.
Channel jobs should share the same core pipeline, but they should enter execution through controlled DB-backed dispatch instead of flooding the queue transport directly.

Current verified gap that T012 must close:
- native worker startup still consumes only `celery`, while the routed pipeline lanes are `audio`, `diarize`, and `post`
- rollout is not complete until launch / launchd topology and queue consumption match the routing contract

### Hardware reality
Current target host is an Apple M4 Mac mini with 16 GB RAM.
Realistic safe overlap target:
- 1 active transcribe/audio job
- 1 active diarize job
- 1 lightweight post-processing job

Not a safe target:
- multiple simultaneous diarize jobs
- multiple simultaneous transcribe jobs
- blind queue-wide concurrency increases

### Execution chunks
T009 is being implemented through:
- T010: queue routing contract and stage gates
- T011: channel backlog dispatcher and fairness
- T012: worker topology rollout and throughput validation

### Guardrail
Do not blindly increase concurrency on the current single queue.
That would make a flaky system fail faster, not better.

## Validation posture going forward

Keep these checks in place as future work builds on the completed T012 baseline:
- keep plan docs and task index synced to the actual repo state
- preserve the green focused T011 and T012 validation packs
- keep verifying worker topology against queue routing via Celery queue inspection
- rerun routed-job smoke tests after worker-topology or launchd changes
- prefer conservative queue and concurrency changes over blunt expansion

## Execution rule

All serious implementation should use:
- `AGENTS.md`
- this `docs/PLAN.md`
- `docs/CLARIFICATIONS.md`
- `docs/tasks/TASK_INDEX.md`
- the specific task file for the current chunk

For future chunks, use the specific follow-on task file as the source of truth.

## Completed follow-on: T014 report delivery

Goal: turn completed transcripts into finished, styled intelligence artifacts delivered directly in Telegram.

Implementation posture:
- reuse existing transcript, summary, segment, job, and LLM usage data from Postgres
- add report artifacts and document delivery without destabilizing the core pipeline
- keep pushed Telegram messages concise and remove chat/channel redirect buttons by default
- make the morning brief explain overnight activity, pending/retrying work, failures/manual-review items, health, and spend
- keep HTML as the MVP artifact format; defer PDF export

Source of truth: `docs/tasks/T014_styled-report-delivery-and-overnight-brief.md`.

## Completed follow-on: T015 scan-first summary intelligence

Goal: make completed video summaries useful as executive intelligence, not generic topic lists.

Implementation posture:
- improve future summary generation first, before any backfill
- preserve report generation/delivery as non-fatal post-processing
- keep Telegram report captions short and useful, with no “try it” buttons and no “Attached:” filler
- make the report renderer extract actual key takes from the `Key takes` section rather than blindly using the first bullets
- flag low-content transcripts honestly instead of manufacturing confident takeaways
- backfill only after prompt/report changes are validated on representative samples

Phase order:
1. Phase 1: summary output contract, report extraction, and Telegram caption.
2. Phase 2: evaluation harness and sample QA.
3. Phase 3: controlled dry-run/live backfill.
4. Phase 4: optional personalization/ranking.

Source of truth: `docs/tasks/T015_scan_first_summary_intelligence.md`.

## Completed follow-on: T016 full project engineering audit

T016 completed a read-only engineering audit and produced a prioritized remediation roadmap.

Top P1 finding: retry/channel/batch paths can publish Celery work before the DB job state they depend on is committed, which can strand queued jobs if a worker consumes the task first.

Source of truth: `docs/tasks/T016_full_project_engineering_audit.md`.

## Completed follow-on: T017 pipeline enqueue transaction boundary

T017 closed T016's top P1 reliability finding by adding a shared commit-before-publish enqueue contract for pipeline starts and resumes.

Implemented posture:
- committed queued/active job state before Celery workers can depend on it
- covered manual video submit, job retry, channel dispatcher promotion, transient auto-retry, and task-layer batch advancement
- preserved active-attempt, stage-gate, resume, and queue-routing behavior
- added focused regression tests for enqueue ordering, publish-failure handling, and non-fatal next-batch dispatch failure
- left active-attempt factory/semantics redesign for T018, now completed separately

Source of truth: `docs/tasks/T017_pipeline_enqueue_transaction_boundary.md`.

## Completed follow-on: T018 unified pipeline attempt factory

T018 unified manual submit, user retry, transient auto-retry, and channel process attempt-creation semantics through a shared attempt allocation/factory contract.

Implemented posture:
- shared active-attempt guard, manual-review block, attempt-number allocation, creation reason, and lineage handling
- channel process per-video results for created, already-active, blocked, skipped duplicate, and error outcomes
- channel-created attempts now preserve failed-attempt superseding/visibility behavior
- T017 commit-before-publish enqueue boundary remains intact

Source of truth: `docs/tasks/T018_unified_pipeline_attempt_factory.md`.

## Completed follow-on: T019 test-suite smoke isolation

T019 keeps default focused/unit test runs non-mutating by making smoke/e2e tests explicitly opt-in.

Implemented posture:
- `smoke` and `e2e` pytest markers are registered
- smoke/e2e tests are skipped unless `--run-smoke` / `YT_RUN_SMOKE=1` or `--run-e2e` / `YT_RUN_E2E=1` is used
- `tests/test_v2_smoke.py` remains discoverable but default-runs skip all live localhost tests
- CI/local script messaging clarifies the non-mutating default

Source of truth: `docs/tasks/T019_test_suite_smoke_isolation.md`.

## Completed follow-on: T020 Alembic/model contract tests

T020 added static, non-mutating schema-contract coverage so migration/model drift, key constraints, and required pipeline columns/indexes are caught before runtime.

Implemented posture:
- Alembic revision chain must be a single linear chain to head
- model metadata must include critical T014-T018 tables/columns
- jobs attempt/stage/recovery/visibility columns and indexes are covered
- active partial unique pipeline-attempt index is covered
- video dismiss fields and video report uniqueness/delivery contracts are covered
- default tests do not run live migrations or mutate runtime services

Source of truth: `docs/tasks/T020_alembic_model_contract_tests.md`.

## Completed follow-on: T021 config model-name consolidation

T021 consolidated model-name settings across app config and scripts so summary, cleanup, chat, persona, digest/report, and evaluation paths use documented canonical settings with safe deprecated aliases.

Implemented posture:
- canonical fields: `cleanup_model`, `summary_model`, `chat_model`, `persona_model`, `digest_model`
- deprecated `ANTHROPIC_*_MODEL` env aliases remain supported through explicit alias handling
- deprecated compatibility properties remain usable for older code/tests
- cleanup, summary, chat, Telegram direct Q&A, persona, digest, and scan-first scripts read canonical settings consistently
- safe dry-run/help gates were used for scripts; no live LLM/runtime mutations in validation

Source of truth: `docs/tasks/T021_config_model_name_consolidation.md`.

## Completed follow-on: T022 channel dispatcher single source of truth

T022 centralized channel batch progress/state-transition and next-job dispatch semantics in `app/services/channel_dispatcher.py`, leaving `app/tasks/batch_progress.py` as a thin compatibility wrapper.

Implemented posture:
- dispatcher owns batch refresh, terminal status, next-batch lookup, first pending-job dispatch, and enqueue-failure handling
- T017 commit-before-publish enqueue boundary remains intact
- direct backlog enqueue failure remains fatal where intended
- next-batch enqueue failure is logged/suppressed so it does not poison the just-completed current pipeline job
- all-failed channel batches consistently resolve to `completed_with_errors`

Source of truth: `docs/tasks/T022_channel_dispatcher_single_source_of_truth.md`.

## Completed follow-on: T023 broad exception audit and structured side-effect logging

T023 audited high-risk broad exception handlers at fail-open side-effect boundaries and added structured logs/classification without breaking intentional fail-open behavior.

Implemented posture:
- report delivery fallback, Telegram notify, morning/weekly digest notify, persona notify/enqueue, pipeline recovery notifier, and next-batch enqueue suppression remain fail-open
- audited logs include event name, category, safe entity context, exception type/message where applicable, and outcome
- bug-mask candidates are documented rather than behavior-changed unsafely
- no secrets, API keys, full transcripts, or private message bodies are logged in audited paths

Source of truth: `docs/tasks/T023_exception_audit_structured_side_effect_logging.md`.

## Completed follow-on: T024 report schema intent cleanup

T024 resolved the `video_reports.report_type` vs one-report-per-video uniqueness ambiguity by making the chosen one-current-summary-report-per-video intent explicit in code, docs, and tests.

Implemented posture:
- `SUMMARY_REPORT_TYPE = "summary_report"` is the canonical report type label
- `video_reports` intentionally stores exactly one current summary report per video
- `report_type` is a label, not a variant dimension
- `Video.report` remains `uselist=False`
- reporting upserts by `video_id` only and normalizes existing report type labels
- model/migration contract tests assert uniqueness on `video_id` only and reject `(video_id, report_type)` uniqueness

Source of truth: `docs/tasks/T024_report_schema_intent_cleanup.md`.

## Completed follow-on: T025 final full-suite release hygiene

T025 completed the final non-mutating validation pass after T017-T024.

Validation posture:
- compileall passed for `app`, `scripts`, and `tests`
- collect-only found `1168` tests
- `git diff --check` passed
- default full pytest suite passed: `1157 passed, 11 skipped`
- skipped tests are the opt-in smoke/e2e tests isolated by T019
- no live smoke, runtime mutation, commit, or push was performed

Source of truth: `docs/tasks/T025_final_full_suite_release_hygiene.md`.

## Implemented pilot: T044 Codex-auth batch LLM migration

T044 prepared the high-value unattended LLM path for Codex-auth routing before the summary and digest defaults were promoted in follow-up tasks.

Implemented posture:
- Smart Router was recovered as a launchd-backed local OpenAI-compatible service on `127.0.0.1:8400`
- the router `codex` profile passed live Codex-auth smoke tests
- summary and digest generation now have per-workload provider/base-url/fallback settings
- Anthropic remains the rollback path
- the transcriber calls only the local OpenAI-compatible endpoint and does not read Codex OAuth tokens
- production switch remains gated by existing transcript comparisons and one controlled live batch/video smoke

Source of truth: `docs/tasks/T044_codex_auth_batch_llm_migration.md`.

## Completed follow-on: T045 summary delivery polish and Codex default

T045 promoted the summary workload to Codex primary with Anthropic fallback after tightening the report delivery surface.

Implemented posture:
- Telegram report-ready delivery now starts with a compact decision brief and keeps the full report as the attached appendix
- Watch Map was removed from the summary/report contract
- Detailed Brief is treated as extra detail and de-duped against Key Takeaways
- summary defaults use Smart Router Codex with Anthropic fallback

Source of truth: `docs/tasks/T045_summary_delivery_codex_default.md`.

## Completed follow-on: T046 digest Codex default

T046 promoted digest generation to Codex primary with Anthropic fallback after a fresh non-delivering 24h digest eval.

Implemented posture:
- digest defaults use Smart Router Codex with Anthropic fallback
- rollback stays one config flip: `DIGEST_LLM_PROVIDER=anthropic`
- validation did not send a live digest notification

Source of truth: `docs/tasks/T046_digest_codex_default.md`.

## Completed follow-on: T047 chat and persona Codex default

T047 promoted interactive intelligence paths to Codex primary with Anthropic fallback.

Implemented posture:
- web chat, Telegram chat, and direct video Q&A use the shared chat provider setting
- channel persona generation and refresh use the shared persona provider setting
- both paths call the local Smart Router OpenAI-compatible endpoint
- Anthropic remains the rollback/fallback path per workflow

Source of truth: `docs/tasks/T047_chat_persona_codex_default.md`.

## Completed follow-on: cleanup Codex default

Transcript cleanup now follows the same Codex-primary posture as the rest of the LLM pipeline.

Implemented posture:
- cleanup defaults use Smart Router Codex with Anthropic fallback
- rollback stays one config flip: `CLEANUP_LLM_PROVIDER=anthropic`
- native post worker and Docker web both load cleanup provider settings

Source of truth: live config and focused cleanup/config tests.

## Follow-on: T048 subscription watchlist and long-form ingest

T048 keeps the followed-channel list focused on long-form signal and prevents autonomous polling from downloading Shorts/reels/short clips.

Target posture:
- re-enable or add Ken-requested channels as subscriptions
- subscription auto-ingest rejects videos shorter than the configured long-form floor
- manual single-video submissions are unaffected
- Andrej Karpathy is backfilled with the 30 most recent long-form videos

Source of truth: `docs/tasks/T048_subscription_watchlist_longform.md`.

## Current throughput work: T051/T052

The next speed-up pass keeps the local M4/16GB topology conservative and focuses on removing avoidable stalls.

Target posture:
- the catch-up runner skips bad submit candidates and continues releasing the rest of the batch
- runner state records skipped candidates for later review
- first-pass ingest skips inline diarization by default so transcript cleanup, summaries, embeddings, and reports finish sooner
- explicit inline/operator diarization remains available when speaker labels matter

Source of truth: `docs/tasks/T051_catchup_runner_hardening.md` and `docs/tasks/T052_summary_first_conditional_diarization.md`.

## Current release hygiene: T054 native audio dependency baseline

T054 resolves the native worker's declared-but-missing TorchCodec dependency while preserving the current Torch 2.8 / Python 3.13 stack and the host's default FFmpeg 8 CLI.

Target posture:
- pin TorchCodec to the release family compatible with Torch 2.8
- supply versioned FFmpeg shared libraries for TorchCodec without replacing the default FFmpeg binary
- keep the torchaudio fallback and existing diarization behavior intact
- require clean dependency metadata, successful imports, focused tests, and healthy queue coverage

Source of truth: `docs/tasks/T054_native_audio_dependency_baseline.md`.

## Current security remediation: T055 local trust boundary

T055 aligns service exposure with the actual operating model: web access is local to the Mac mini, while Telegram is the only external user ingress and is restricted to an explicit numeric allowlist.

Target posture:
- publish web, Postgres, and Redis only on host loopback
- keep optional API-key enforcement correct for every non-public route
- fail closed when the Telegram allowlist is empty
- require both the bot token and at least one allowed numeric user before polling starts

Source of truth: `docs/tasks/T055_local_trust_boundary.md`.

## Current security remediation: T056 rendering safety

T056 closes executable HTML injection paths in the local operator UI while preserving Markdown presentation and the existing report pipeline.

Target posture:
- route persisted summary content through an escaping-first renderer
- treat model chat output as untrusted before and after Markdown parsing
- build API status and channel discovery content from text nodes or escaped values
- allow only HTTP(S) links in dynamically rendered external metadata

Source of truth: `docs/tasks/T056_rendering_safety.md`.

## Current Telegram delivery work: T057 allowlisted notification fanout

T057 matches the current two-user trust model without prematurely building the
scoped-recipient architecture in T049.

Target posture:
- all unique numeric allowlist entries receive shared operator notifications
- one recipient failure does not block delivery to the other recipient
- dedupe is tracked per recipient so partial retries do not duplicate successes
- notification controls remain global while both users have the same access

Source of truth: `docs/tasks/T057_allowlisted_notification_fanout.md`.
