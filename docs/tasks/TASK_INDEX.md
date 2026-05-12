# Task Index

Use this index for serious implementation work. Each execution chunk gets its own task file.

| Task | Title | Status | Owner | Notes |
|---|---|---:|---|---|
| T001 | Superseded failed jobs hidden by default + 14-day retention cleanup | done | BuildClaw / QAClaw | Implemented and QA-validated |
| T002 | Native ops path, cleanup scheduling, and README rollout notes | done | SentryClaw | Host-native maintenance and rollout hardening |
| T003 | Fix CI template failure and diarization runtime bug, then retry the 3 requested videos | done | BuildClaw / QAClaw | CI/test env fixed, diarization repaired, and 3 requested retries completed |
| T004 | Pipeline stabilization Phase 1: attempt model, one-active-attempt guard, and artifact-aware resume | done | BuildClaw / QAClaw | Stabilize retry/resume behavior before speed work |
| T005 | Pipeline stabilization Phase 1.5: DB-level one-active-attempt enforcement and concurrent test | done | BuildClaw / QAClaw | DB-level guard + concurrent race-closure test implemented |
| T006 | Pipeline stabilization Phase 2: separate execution status from stage/progress | done | BuildClaw / QAClaw | Lifecycle/stage contract hardened + tests updated |
| T007 | Pipeline stabilization Phase 3: recovery guardrails, stale-job behavior, and retry containment | done | BuildClaw / QAClaw | Recovery guardrails, stale classification, and manual-review containment implemented |
| T008 | Pipeline observability and attempt reasoning | done | BuildClaw / QAClaw | Structured attempt reasoning, artifact checks, stage timing, and worker health observability implemented |
| T009 | Throughput queues after stability | done | BuildClaw / QAClaw | Queue routing, channel backlog fairness, and split-worker rollout validated on the target host |
| T010 | Queue routing contract and stage gates | done | BuildClaw / QAClaw | Explicit queue routing, payload identity, and attempt-safe stage execution implemented |
| T011 | Channel backlog dispatcher and fairness | done | BuildClaw / QAClaw | Durable DB-backed channel backlog and dispatcher-based release path implemented and validated |
| T012 | Worker topology rollout and throughput validation | done | BuildClaw / QAClaw | Split native worker topology, queue coverage, health checks, and practical overlap validation completed |
| T013 | Provider resilience, worker health v2, and transient auto-retry | done | SentryClaw / BuildClaw | Provider retry taxonomy, worker health v2 degraded-busy signal, and dry-run auto-retry sweep implemented |
| T014 | Styled report delivery and overnight operations brief | done | SentryClaw / QAClaw | Parent epic split into T014A-C; report artifacts, Telegram document delivery, and overnight operations brief implemented locally |
| T014A | Report artifact MVP | done | SentryClaw | Persisted styled HTML report artifacts from existing transcript + summary data; focused tests pass |
| T014B | Telegram report document delivery | done | SentryClaw | Sends generated reports as Telegram documents with simplified buttonless completion messages; fallback preserved |
| T014C | Overnight brief operations status | done | SentryClaw | Morning brief now includes pending/retry/failure/manual-review/report-delivery/health/spend status |
| T014D | Summary-only report format | done | SentryClaw | Removed transcript appendix from delivered HTML reports by default and moved source into a top callout |
| T014E | Report cleanup and delivery path validation | done | BuildClaw | Removed dead transcript report plumbing, renamed summary report type, fixed failed-send dedupe, and validated real Telegram document delivery |
| T015 | Scan-first summary intelligence | done | SentryClaw / QAClaw | Scan-first prompt/report/caption, eval harness, guarded backfill tooling, and deterministic Phase 4 quality guardrails implemented locally |
| T016 | Full project engineering audit | done | SentryClaw + specialist agents | Read-only full-project architecture/code/reliability/data/test/ops audit and prioritized remediation roadmap completed in `docs/tasks/T016_full_project_engineering_audit.md` |
| T017 | Pipeline enqueue transaction boundary | done | BuildClaw / QAClaw | Shared commit-before-publish enqueue helper implemented for retry/channel/batch/manual pipeline starts; focused validation passed |
| T018 | Unified pipeline attempt factory | done | BuildClaw / QAClaw | Shared attempt factory/allocation contract implemented; QA passed after savepoint and channel batch consistency fixes |
| T019 | Test-suite smoke isolation | done | SentryClaw / QAClaw | Smoke/e2e tests are opt-in; default pytest/CI runs skip mutating localhost smoke tests |
| T020 | Alembic/model contract tests | done | BuildClaw / QAClaw | Static non-mutating Alembic/model contract tests added; QA passed |
| T021 | Config model-name consolidation | done | BuildClaw / QAClaw | Canonical model settings/aliases consolidated across config and LLM paths; QA passed |
| T022 | Channel dispatcher single source of truth | done | BuildClaw / QAClaw | Batch progress/dispatch centralized in channel dispatcher; QA passed |
| T023 | Broad exception audit and structured side-effect logging | done | BuildClaw / QAClaw | High-risk fail-open side-effect catches now emit structured logs; QA passed |
| T024 | Report schema intent cleanup | done | BuildClaw / QAClaw | One-current-summary-report-per-video intent explicit, tested, and QA-validated |
| T025 | Final full-suite release hygiene | done | SentryClaw | Static gates passed; default full pytest suite passed `1157 passed, 11 skipped` |

## Conventions
- Keep tasks narrowly scoped and testable.
- Update status as work moves from planned → in-progress → blocked → done.
- Link every task to the relevant plan and clarification context.
- QA validates against the same task file used for implementation.
