# Pipeline Stabilization and Execution Roadmap

## Current status

The YouTube Transcriber pipeline has completed the core stabilization arc through T007.

Completed:
- T001: hide superseded failed jobs + retention cleanup
- T002: native ops cleanup and README rollout notes
- T003: CI/test env fix, diarization runtime fix, and 3 requested video retries
- T004: Phase 1, attempt model + one-active-attempt guard + artifact-aware resume
- T005: Phase 1.5, DB-level one-active-attempt enforcement
- T006: Phase 2, explicit lifecycle status vs stage/progress separation
- T007: Phase 3, recovery guardrails + stale-job behavior + retry containment

Planned next:
- T008: pipeline observability and attempt reasoning
- T009: throughput queues after stability

## Roadmap goal

Keep the pipeline reliable first, then make it easier to triage, then improve throughput.

The ordering matters:
1. Stabilize retries, resume behavior, and stale-job recovery.
2. Add structured observability so operators can explain what is happening.
3. Only then split workloads and tune throughput.

## Why this order

Past failures were not just single-stage bugs. They came from pipeline design weaknesses:
- retries were too loosely modeled
- resume logic was too optimistic
- artifact lifecycle was too aggressive
- state tracking was too muddy

That is why the repo now treats stability and observability as prerequisites for speed.

## Next implementation target: T008

### Goal
Make pipeline triage easy by recording enough structured state to explain:
- what is running
- why an attempt exists
- what artifacts were checked
- whether a worker is actually unhealthy or simply busy

### Scope
- add structured attempt-creation reasons
- add worker id / host id where available
- record last artifact-check result used by resume/recovery logic
- add missing per-stage timing where it materially helps triage
- improve worker health reporting for long-running stages like diarization
- expose the new observability data in targeted operator-facing surfaces

### Out of scope
- queue splitting
- broad UI redesign
- throughput tuning by turning up concurrency on the existing single queue

## Future implementation target: T009

### Goal
Improve throughput only after T008 is done.

### Strategy
Split workloads by stage/resource profile, for example:
- download/transcribe queue
- diarize/align queue
- summarize/embed queue

### Guardrail
Do not blindly increase concurrency on the current single queue.
That would make a flaky system fail faster, not better.

## Execution rule

All serious implementation should use:
- `AGENTS.md`
- this `docs/PLAN.md`
- `docs/CLARIFICATIONS.md`
- `docs/tasks/TASK_INDEX.md`
- the specific task file for the current chunk

For the next chunk, that means T008 is the source of truth.
