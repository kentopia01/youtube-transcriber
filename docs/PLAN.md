# Pipeline Stabilization and Execution Roadmap

## Current status

The YouTube Transcriber pipeline has completed the core stabilization arc and the first observability and routing follow-on work.

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

The current development arc is complete through T012.

## Current verified reality

As of 2026-04-09, the repo and runtime are in a validated split-topology state:
- queue routing exists in code and tasks are routed into `audio`, `diarize`, and `post`
- channel processing creates durable pending jobs and releases them through the dispatcher path
- launchd now runs a split native worker topology for `audio`, `diarize`, and `post,celery`
- Celery queue inspection confirms the intended queue coverage on the native workers
- focused T011 verification is green across dispatcher fairness, channel API, orchestration, retry/recovery, and worker-health packs
- launchd PATH handling was fixed so ffmpeg and ffprobe are available to the audio worker
- real routed-job smoke tests succeeded after the split-worker rollout
- practical overlap was observed with one job in `diarize` and another in `transcribe` on separate workers

This means the stabilization, dispatcher, and worker-topology roadmap through T012 is complete.

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
