# T074 - Operations warning reconciliation

## Status

Done

## Objective

Make every Operations warning attributable and actionable, then reconcile stale
derived state without erasing genuine failure evidence.

## In scope

- Inspect visible failed jobs, channel batches, report deliveries, and subscriptions.
- Add structured warning totals/details where the dashboard contract is incomplete.
- Add a dry-run-first reconciliation path for stale batch state.
- Resolve deterministic state defects and document accepted/manual-review warnings.

## Out of scope

- Blind retries, automatic report redelivery, or hiding unresolved failures.

## Done criteria

- Warning count equals the sum of its typed warning groups.
- Reconciliation previews changes before applying them and is covered by tests.
- Live warnings are either corrected or retain an explicit reason and next action.

## Validation

- Reconciled four stale May channel batches through the dry-run-first endpoint.
- Dismissed one deterministic 609-minute policy rejection with its explicit reason.
- Fixed premiere/live-event polling so deferred videos no longer block later candidates.
- Reset the repaired subscription failure counter through the explicit API contract.
- Live Operations now reports two warnings, both retained report-delivery failures with
  reason and next-action fields; no batch, failed-job, or subscription warning remains.
- Focused Operations/subscription/classifier contracts pass.
