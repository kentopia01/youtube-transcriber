# T097 - Bounded YouTube production recovery

## Status
Done.

## Objective
After T089-T096 pass and deployment is verified, recover the five blocked
videos and safely restore the AI Engineer subscription.

## In scope
- Explicitly clear/retry only the audited five latest manual-review failures.
- Bounded release with observed download outcomes.
- Re-enable AI Engineer and verify its failure state is reset.
- Confirm watchdog and worker truth after recovery.

## Out of scope
- Historical dismissed failures or bulk backlog release.

## Done criteria
- Each target has a verified latest outcome.
- AI Engineer is enabled only after the 409 handling fix is live.
- Final service/watchdog state is truthful.

## Verification
- Added an explicit, confirmation-gated operator override for one audited
  manual-review job; ordinary retry paths remain blocked.
- Released two jobs first and observed both pass download before releasing the
  remaining three.
- All five exact recovery attempts completed successfully.
- AI Engineer is enabled with `consecutive_failure_count=0`, `last_error=null`,
  and `disabled_reason=null`.
- Six `t097-recovery` mutations are present in the service audit: five exact
  retries and one subscription patch.
- Final service state is healthy and idle with three workers, all queues
  covered, zero visible failed jobs, and zero operational warnings.
- Final 24-hour watchdog state is `6 completed / 0 failed / 0 overdue`.
- Final repository suite: `1,447 passed, 11 skipped`; compilation, diff, and
  Compose configuration gates also pass.
