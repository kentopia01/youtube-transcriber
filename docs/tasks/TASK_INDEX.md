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

## Conventions
- Keep tasks narrowly scoped and testable.
- Update status as work moves from planned → in-progress → blocked → done.
- Link every task to the relevant plan and clarification context.
- QA validates against the same task file used for implementation.
