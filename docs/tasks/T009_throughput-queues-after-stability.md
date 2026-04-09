# T009 - Throughput queues after stability

## Status
Planned

## Objective
Increase practical throughput on the current Mac mini without regressing stability by separating workloads into resource-aware queues, enforcing attempt-safe routing, and adding durable dispatch for long-running channel backlogs.

## Why it matters
The current single-queue model is reliable enough to operate, but it is not the right shape for long-running channel ingestion and mixed manual workloads. Throughput improvements should come from queue separation and controlled dispatch, not from blindly increasing concurrency.

## Workload assumptions
- Primary workload: podcast-style videos, usually 15 to 45 minutes.
- Host: Apple M4 Mac mini with 16 GB RAM.
- Realistic safe overlap target:
  - 1 active audio/transcribe job
  - 1 active diarize job
  - 1 lightweight post-processing job
- Not a safe target:
  - multiple diarize jobs at once
  - multiple transcribe jobs at once
  - uncontrolled queue flood from channel jobs

## Proposed architecture
Create three workload queues:
- `audio` for download + transcribe
- `diarize` for diarize + align
- `post` for cleanup + summarize + embed

Initial worker policy:
- `audio`: concurrency 1
- `diarize`: concurrency 1
- `post`: concurrency 1

Queue splitting alone is not enough. Routing and dispatch must remain attempt-safe and durable.

## Scope
- Define queue topology by stage/workload class.
- Route tasks by explicit attempt/job identity, not by guessing latest state.
- Add attempt-safe stage gate checks so the wrong attempt cannot consume the wrong artifact.
- Add durable DB-backed dispatch for channel backlogs so channel jobs can run over long durations without getting lost.
- Add fairness rules so manual jobs are not starved by channel floods.
- Add operator-visible checks/metrics needed to validate the new queue topology.

## Out of scope
- Broad infrastructure scaling or distributed cluster design.
- Blind concurrency increases on the current single queue.
- New product features unrelated to execution throughput.
- Replacing the stabilized retry/recovery model from T004 to T008.

## Guardrails
- DB remains the execution source of truth. Redis/Celery transports work, but DB state is authoritative.
- Channel discovery should create durable DB backlog entries, not flood Redis directly.
- Every stage must run against the exact intended attempt/job identity.
- Attempt-safe routing should be compatible with future attempt-scoped artifact storage.
- Manual jobs must retain a path to progress even while long channel jobs are queued.

## Done criteria
- Workloads are separated into `audio`, `diarize`, and `post` execution lanes.
- Channel jobs use durable DB-backed dispatch instead of fire-and-forget queue flooding.
- Manual jobs are protected from starvation by channel backlogs.
- Stage routing is explicit enough that tasks can prove they belong to the current active attempt.
- Operator checks can show whether the split topology is improving throughput without destabilizing the pipeline.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.

## Chunk plan
T009 is too large for a single implementation pass. Execute it through these chunks:
- T010: queue routing contract + stage/attempt-safe dispatch metadata
- T011: channel backlog dispatcher + fairness rules
- T012: worker topology rollout + throughput validation
