# T087 - Post-Refresh Recovery Closeout

## Status

Ready; scheduled verification is pending for 2026-08-19 02:00 SGT.

## Objective

Close the authenticated-cookie recovery sequence after the first scheduled
refresh by verifying refresh evidence, retry outcomes, warning cleanup, and the
preserved manual-review boundary.

## In scope

- Verify the daily 01:45 SGT refresh and one-shot 02:00 SGT verifier definitions.
- Confirm the three guarded Aug 18 retry jobs completed successfully.
- Preserve the Aug 16 HTTP 403 job in manual review unless a separate reviewed
  investigation authorizes another attempt.
- Verify the scheduled refresh produces fresh authenticated-cookie and media
  probe evidence without exposing cookie values.
- Reconcile the two historical report-delivery warnings only when their
  artifacts and recipients remain valid.
- Update Task Board state and send the final operator result.

## Out of scope

- No Profile B activation, retry-limit bypass, concurrency change, schedule
  change, or broad historical retry.

## Done criteria

- Both scheduled jobs are enabled with the intended Asia/Singapore timing.
- Three Aug 18 recovery attempts are terminal and successful.
- The quarantined job remains explicit and explainable.
- The first unattended refresh evidence is fresh and healthy.
- The verifier reports a final success or the exact blocker and closes its
  one-shot lifecycle.

## Readiness evidence

- Daily refresh cron `fc33488a-037c-4ad7-8707-61c5f6dd8a93` is enabled for
  01:45 SGT with no stagger, a 900-second timeout, and no delivery side effect.
- One-shot verifier `40291cf3-b9d7-4452-a383-5f505d006955` is enabled for
  02:00 SGT, uses an isolated OpsClaw turn with `xhigh` thinking, deletes itself
  after success, and delivers its final result through the default SentryClaw
  Telegram account to Ken.
- The verifier payload names both task-board items, this task file, the three
  completed retry IDs, the quarantined retry ID, the two historical warning
  video IDs, and explicit no-duplicate/no-direct-database/no-extra-retry guards.
- The three Aug 18 recovery jobs are completed at 100% with no errors.
- The Aug 16 HTTP 403 job remains failed with two identical signatures,
  `manual_review_required=true`, and `recovery_status=manual_review`.
- `.venv/bin/ytctl` is present and its help command passes.
