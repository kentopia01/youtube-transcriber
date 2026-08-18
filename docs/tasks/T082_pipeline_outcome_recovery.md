# T082 - Pipeline Outcome Watchdog and Artifact-Aware Handoff Recovery

## Status

Done (2026-08-06).

## Objective

Close the false-green gap between successful discovery/enqueue and actual terminal
pipeline outcomes, while recovering one proven lost stage handoff safely.

## In scope

- Read-only outcome summary/checker for recent autonomous attempts.
- Counts for completed, failed, active, overdue, and clustered failures.
- Stale-reaper planning that inspects durable audio/transcript/summary artifacts.
- One bounded same-attempt requeue from the earliest safe next stage.
- Structured recovery evidence in the existing artifact-check JSON field.
- Focused tests for forward progress, no-progress failure, publish failure, and the
  recovery limit.

## Out of scope

- Retrying the nine current production failures.
- Indefinite retry loops or automatic manual-review bypass.
- New database tables/migrations unless the existing structured field proves
  insufficient.
- Operations UI redesign.

## Drift guards and stop conditions

- Resume only when required inputs exist.
- Never create a second active attempt for the same video.
- At most one automatic stale-handoff recovery per attempt by default.
- If recovery publish fails, preserve a visible terminal failure.

## Done criteria

- The July artifact patterns map to safe next stages.
- One stale handoff can resume on the same attempt and records why.
- A second stale event follows the existing terminal failure path.
- The watchdog exits nonzero on an overdue/failure cluster and remains read-only.
- Focused recovery/state tests pass.

## Validation

- Focused stale-reaper, artifact recovery, resume-point, and outcome tests passed.
- The native production dry-run found no currently stale jobs.
- The 24-hour read-only outcome watchdog returned healthy and made no mutations.
