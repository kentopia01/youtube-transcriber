# T011 - Channel backlog dispatcher and fairness

## Status
Planned

## Objective
Make channel processing durable over long durations by using a DB-backed backlog and controlled dispatcher, while preserving responsiveness for manual jobs.

## Why it matters
Channel ingestion should use the same pipeline as manual jobs, but it should not dump an uncontrolled flood of work into the queue transport. Without a dispatcher, jobs can become harder to reason about and manual work can get starved.

## Scope
- Represent channel backlog durably in DB-backed pending work.
- Add a dispatcher loop or dispatcher mechanism that promotes only a safe number of channel attempts into runnable queued state.
- Add fairness rules so manual/ad hoc jobs continue to move even when channel backlogs are large.
- Keep channel processing on the same core pipeline model and attempt semantics as manual jobs.
- Add tests for backlog release and fairness behavior.

## Out of scope
- Queue topology redesign beyond using the lanes created in T010.
- Throughput tuning or benchmark work.
- New channel product features unrelated to dispatch durability.

## Constraints
- DB backlog is authoritative; queue transport should not be the only place work lives.
- Do not let channel jobs starve manual jobs.
- Do not compromise one-active-attempt semantics.

## Done criteria
- Channel jobs can remain pending durably over long durations.
- Dispatcher promotes backlog gradually instead of flooding runnable queues.
- Manual jobs retain a protected path to progress.
- Tests prove channel backlog durability and fairness behavior.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.
