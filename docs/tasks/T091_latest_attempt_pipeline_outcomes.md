# T091 - Latest-attempt pipeline outcomes

## Status
Done (2026-08-21).

## Objective
Make the watchdog report each video's actual latest pipeline outcome.

## In scope
- Group attempts by video within the reporting cohort.
- Include retries, hidden/superseded jobs, and all attempt reasons.
- Preserve T088 alert rendering/state behavior.

## Out of scope
- Job mutation or automatic retry.

## Done criteria
- A hidden auto-ingest failure followed by a failed user retry remains failed.
- Recovery is emitted only when the latest attempt is genuinely resolved.

## Validation
- Collector cohorts autonomous videos, then selects each video's latest recent
  pipeline attempt regardless of retry reason, hidden state, or supersession.
- Alert copy now reports videos/latest outcomes rather than raw attempts.
- Focused tests: `8 passed`.
- Live read-only 24-hour check: `6 videos`, `2 completed`, `4 failed`, `0
  overdue`, `degraded=true`, matching the audit ground truth.
