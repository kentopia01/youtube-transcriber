# T012 - Worker topology rollout and throughput validation

## Status
Planned

## Objective
Roll out the split worker topology safely on the current Mac mini and validate that it improves throughput without destabilizing the pipeline.

## Why it matters
Even with correct queue routing and dispatch, the actual worker topology and concurrency caps determine whether the box stays stable. This chunk is where the repo turns the new design into a controlled operational rollout.

## Scope
- Define launch/worker topology for `audio`, `diarize`, and `post` lanes.
- Set conservative initial concurrency caps appropriate for current hardware.
- Add operator-facing checks or validation steps for:
  - queue health
  - stage distribution
  - backlog movement
  - signs of starvation or resource contention
- Validate whether the split topology improves practical throughput for the target workload mix.
- Document rollback and safe fallback behavior.

## Out of scope
- Autoscaling or multi-machine scheduling.
- Aggressive concurrency tuning without evidence.
- New product features unrelated to throughput validation.

## Constraints
- Treat the current Apple M4 / 16 GB host as the deployment target.
- Default to single-concurrency for heavy queues unless evidence justifies more.
- Prefer reversible worker-topology changes.

## Done criteria
- Worker topology is documented and operational for the split queues.
- Initial concurrency caps are conservative and explicit.
- Validation shows throughput improvement without reliability regression.
- Rollback steps are documented and tested enough to be credible.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.
