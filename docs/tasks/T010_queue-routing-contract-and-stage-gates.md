# T010 - Queue routing contract and stage gates

## Status
Done

## Objective
Introduce explicit queue routing and attempt-safe stage gates so each pipeline stage runs in the correct workload lane and only against the intended active attempt.

## Why it matters
Queue splitting is dangerous if tasks still infer ownership from "latest job" behavior or ambiguous artifact paths. Before channel dispatch or fairness work, the pipeline needs a routing contract that proves the right task is acting on the right attempt.

## Scope
- Define explicit queue mapping for pipeline stages:
  - `audio`: download + transcribe
  - `diarize`: diarize + align
  - `post`: cleanup + summarize + embed
- Ensure stage dispatch carries explicit attempt/job identity.
- Add stage gate checks before execution so a task exits safely when:
  - the attempt is no longer active
  - the attempt was superseded
  - the stage no longer matches expected ownership
  - required attempt inputs are missing or belong to another attempt
- Add the minimum routing/config updates needed so tasks land in the intended queue.
- Add tests for routing and stage-gate behavior.

## Out of scope
- Channel backlog release logic.
- Fairness policies between channel and manual jobs.
- Throughput tuning based on measurements.

## Constraints
- Preserve one-active-attempt semantics.
- Prefer explicit attempt/job identity over any "latest job for video" inference.
- Keep compatibility with the current stabilized recovery model.

## Done criteria
- Each pipeline stage routes to the intended queue.
- Stage execution can prove it belongs to the current active attempt.
- Wrong-attempt / superseded-attempt execution paths fail safe.
- Tests cover the routing contract and stage-gate checks.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.
