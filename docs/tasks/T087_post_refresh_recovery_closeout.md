# T087 - Post-Refresh Recovery Closeout

## Status

Done as of the 2026-08-19 02:00 SGT verifier run.

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

## Closeout evidence

- Daily refresh cron `fc33488a-037c-4ad7-8707-61c5f6dd8a93` ran at
  `2026-08-19T01:45:00.043+08:00` and finished `status=ok`.
- `data/cookies/youtube-cookie-refresh-status.json` shows `status=ok`,
  `production_replaced=true`, `cookie_health.status=ok` with 19 auth-like
  cookies, `media_probe.ok=true`, and `finished_at=2026-08-18T17:45:11.258575+00:00`.
- Guarded retry jobs `6adc3d7e-088d-4272-98f6-7da628c19db9`,
  `2bbe0b26-6df1-4048-8079-1c0846999fea`, and
  `00052376-08a1-4fba-82b4-855861c0c4cb` are terminal `completed` at 100%.
- Manual-review job `23e01459-fdc7-4114-ab18-e488f59aa5ba` remains terminal
  `failed` with `manual_review_required=true`, `recovery_status=manual_review`,
  and no retry or bypass performed.
- Historical report warnings for videos `5bfa269c-30a0-4bee-8dec-f2154629ba1b`
  and `28a9607c-bce8-4fa5-821c-2842fb3c12f1` had valid artifacts and
  configured Telegram recipients, were redelivered once through
  `app.services.telegram_notify.notify("video.report_ready", ...)`, and now have
  `delivery_status=sent` with no `delivery_error`.
- `.venv/bin/ytctl --json status` reports service `ok`, queue `idle`, three
  workers covering `audio`, `celery`, `diarize`, and `post`,
  `report_delivery_warnings=0`, and no active, pending, or in-flight jobs.
- `.venv/bin/ytctl --json warnings` now reports one warning only: the preserved
  Aug 16 manual-review HTTP 403 job.
