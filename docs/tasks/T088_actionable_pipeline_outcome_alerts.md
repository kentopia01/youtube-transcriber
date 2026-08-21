# T088 - Actionable Pipeline Outcome Alerts

## Status

Done (2026-08-21).

## Objective

Replace the generic `command exited with code 1` watchdog notification with a
concise incident alert that explains which autonomous pipeline attempts are
affected, where they failed or stalled, what recovery state they are in, and
when the operator will be reminded.

## In scope

- Preserve the existing read-only 24-hour outcome and non-zero health contract.
- Add bounded structured details for failed and overdue attempts.
- Emit a first alert, a changed-incident alert, a periodic reminder, and one
  recovery notification.
- Suppress unchanged 30-minute repeats between reminders.
- Deliver deterministic command output through OpenClaw without a model turn.
- Rewire the existing production cron and verify its healthy path.

## Out of scope

- Changing retry, recovery, manual-review, or queue behavior.
- Changing the global OpenClaw cron failure-alert template.
- Alerting recipients other than the existing watchdog recipient.
- Operations UI changes.

## Drift guards and stop conditions

- The outcome collector remains read-only with respect to pipeline data.
- Existing checker output and JSON fields remain backward compatible.
- Alert state may record notification transitions only; it must never mutate a
  job or video.
- Error details are whitespace-normalized and bounded before delivery.
- Healthy runs must be silent except for a real recovery transition.

## Done criteria

- Alerts include the window counts and bounded affected-job details.
- New, changed, reminder, suppressed, and recovered decisions are tested.
- The checker still exits non-zero for degraded outcomes even when a repeat is
  suppressed.
- The production cron sends command output to the existing Telegram target and
  no longer emits the redundant generic failure alert.
- Focused tests and a live healthy cron run pass.

## Validation

- Focused alert and outcome tests passed: `6 passed`.
- Full default suite passed with explicit default-config environment values:
  `1421 passed, 11 skipped`.
- The production checker returned `degraded=false` with zero failed/overdue
  attempts and alert mode returned `NO_REPLY`.
- The existing 30-minute OpenClaw cron was rewired to deterministic Telegram
  command delivery, a two-hour unchanged-incident reminder, and no redundant
  generic failure alert.
- A forced live cron run completed `ok`, captured `NO_REPLY`, and reset
  `consecutiveErrors` to zero without sending a healthy notification.
