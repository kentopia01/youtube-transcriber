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
| T026 | Brief quality repair and report depth gate | done | OpsClaw | Structured JSON brief contract, report depth gate, and bounded thin-report regeneration |
| T027 | Summary quality gate hotfix | done | SentryClaw | Structured brief repair pass now falls back to direct markdown contract before current summarize-stage retries |
| T028 | yt-dlp cookie 403 fallback | done | SentryClaw | Cookie-backed media 403 retries once without cookies |
| T029 | Controlled download 403 recovery | done | SentryClaw | Guarded retry script added; seven failed jobs queued under patched downloader |
| T030 | YouTube download health probe | done | SentryClaw | Cookie/no-cookie probe with JSON output and native env loading |
| T031 | Cookie lint and safe refresh policy | done | SentryClaw | Cookie file lint classifies anonymous-only and auth-like sessions without exposing values |
| T032 | Batch download failure alerting | done | SentryClaw | Threshold checker and Telegram diagnostic renderer added |
| T033 | yt-dlp version guardrail | done | SentryClaw | Version freshness checker added |
| T034 | Authenticated cookie last resort | planned | SentryClaw | Runbook-only fallback; no login automation or credential storage |
| T035 | Repo cleanup after download hardening | done | SentryClaw | T026/T027 summary-quality work committed separately; generated OpenClaw workspace files ignored |
| T036 | Recovered jobs and yt-dlp update | done | SentryClaw | Seven 403 recovery jobs completed; yt-dlp updated to 2026.06.09 in dev/native envs and validated |
| T037 | Global search source-of-truth docs and task contract | done | SentryClaw | Establish rollout docs for whole-corpus retrieval |
| T038 | Global search core service | done | SentryClaw | Whole-corpus vector, keyword, and summary-lane retrieval with RRF |
| T039 | Global search diversity and evidence packing | done | SentryClaw | Dedupe, per-video diversity, and compact evidence snippets |
| T040 | Global search API and operator UI | done | SentryClaw | Separate `/api/global-search` and `/global-search` surfaces |
| T041 | Global search chat mode switch | done | SentryClaw | Web chat now defaults to all embedded videos and supports channel/account scoping |
| T042 | Reranker and query-expansion experiment | deferred-evidence | SentryClaw | Reopen at 30 real queries, sub-90% hit rate, or three recurring miss patterns |
| T043 | Global search evaluation benchmark | done | SentryClaw | Read-only 12-query seed baseline; enrich manually with anonymized real operator queries |
| T044 | Codex-auth batch LLM migration | done | SentryClaw | Production-proven Codex-primary workloads with Smart Router and Anthropic fallback |
| T045 | Summary delivery polish and Codex default | done | SentryClaw | Telegram-first report caption, Watch Map removal, report de-dupe, Codex-primary summary default with Anthropic fallback validated on five-video dry run |
| T046 | Digest Codex default | done | SentryClaw | Codex-primary digest default with Anthropic fallback validated on a non-delivering 24h digest eval |
| T047 | Chat and persona Codex default | done | SentryClaw | Web/Telegram chat, direct video Q&A, and channel persona generation now use Smart Router Codex with Anthropic fallback |
| T048 | Subscription watchlist and long-form ingest | done | SentryClaw | Requested channels enabled, long-form auto-ingest floor added, and Andrej Karpathy backlog seeded |
| T049 | Recipient lanes and scoped digests | planned-gated | SentryClaw / BuildClaw / QAClaw | Lightweight shared-processing lanes; implementation blocked until current catch-up pipeline fully drains and Ken reopens build |
| T050 | Codex workload router profiles | done | SentryClaw | Keep YouTube LLM workloads on Codex/OAuth while splitting cleanup/summary/digest/chat/persona across workload-specific Smart Router profiles; live profiles and both model-name forms validated |
| T051 | Catch-up runner hardening | done | SentryClaw | Keep unattended backlog release moving through future premieres/unavailable candidates |
| T052 | Summary-first conditional diarization | done | SentryClaw | Skip expensive inline diarization by default; preserve explicit inline/operator diarization path |
| T053 | Diarization usefulness detector | done | SentryClaw | Records cheap post-ASR speaker-label usefulness decisions without re-adding diarization to the critical path; quiet-queue worker rollout validated |
| T054 | Native audio dependency baseline | done | SentryClaw | TorchCodec/Torch/Python compatibility pinned, keg-only FFmpeg 7 libraries supplied, and healthy worker rollout validated |
| T055 | Local trust boundary | done | SentryClaw | Loopback-only Docker bindings, fail-closed Telegram allowlist enforcement, and live service health validated |
| T056 | Rendering safety | done | SentryClaw | Persisted summaries, chat Markdown, API messages, and discovered metadata now render through escaping and protocol guardrails |
| T057 | Allowlisted Telegram notification fanout | done | SentryClaw | Shared trusted-operator notifications fan out with per-recipient failure isolation and dedupe |
| T058 | Runtime bootstrap consolidation | done | SentryClaw | Centralized copied native env loading and sync database URL precedence |
| T059 | Post-roadmap operational closeout | done | SentryClaw | Reconciled live production evidence, roadmap status, and gated residual work |
| T060 | yt-dlp dependency floor | done | SentryClaw | Project/test environments aligned to the T036 validated 2026.06.09 baseline |
| T061 | Historical stale download recovery | planned-approval | SentryClaw | Review and recover 22 April stale-download failures in bounded batches only after approval |
| T062 | Feature-area QA matrix | done | SentryClaw | 26/26 read-only live checks plus explicit isolated/mutating/browser coverage boundaries |

## Conventions
- Keep tasks narrowly scoped and testable.
- Update status as work moves from planned → in-progress → blocked → done.
- Link every task to the relevant plan and clarification context.
- QA validates against the same task file used for implementation.
