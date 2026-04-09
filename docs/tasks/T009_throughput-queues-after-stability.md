# T009 - Throughput queues after stability

## Status
Planned

## Objective
Improve throughput only after the stabilized pipeline is observable enough to support safe queue separation and resource-aware parallelism.

## Why it matters
Blindly increasing concurrency on the current single queue would make failures faster and harder to untangle. Throughput gains should come from workload separation, not brute-force parallelism.

## Scope
- Design and implement queue separation by workload class.
- Split heavy and light stages into distinct execution lanes, for example download/transcribe, diarize/align, and summarize/embed.
- Add the minimum routing needed so tasks land on the correct queue.
- Validate that resource contention is controlled on the current box.
- Measure whether the new topology improves throughput without regressing reliability.

## Out of scope
- New product features unrelated to pipeline execution.
- Aggressive horizontal scaling or distributed orchestration.
- Any change that depends on guessing worker health instead of using structured observability.

## Constraints
- Do not begin implementation until T008 observability is done.
- Preserve one-active-attempt semantics and Phase 3 recovery containment.
- Prefer reversible queue/routing changes over a full execution rewrite.

## Done criteria
- Queue routing is separated by workload class.
- Long heavy stages no longer block lightweight stages unnecessarily.
- Reliability remains at least as good as pre-split behavior.
- Tests and operator checks prove the queue split works as intended.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.

## Notes
- This is intentionally sequenced after T008.
- Do not solve throughput by simply turning up concurrency on the existing single queue.
