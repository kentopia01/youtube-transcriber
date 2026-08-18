# T084 - Brokered Authenticated YouTube Cookie Refresh

## Status

Done (2026-08-18).

## Objective

Keep unattended YouTube ingest able to use the dedicated Nora service session
without opening or reading the persistent Chrome profile from unleased cron or
worker processes.

## In scope

- Export YouTube cookies from the brokered `identity:nora-work` Chrome profile
  into the configured protected Netscape cookie jar.
- Require authenticated-cookie lint and a bounded real media probe before an
  export may replace the current production jar.
- Replace the jar atomically, retain one last-known-good rollback copy, and
  write structured non-secret refresh evidence.
- Schedule one daily refresh before the unattended overnight window.
- Enable yt-dlp's official EJS challenge solver for metadata, probes, and media
  download paths.
- Fix the `ytctl` service-URL/video-URL argument collision exposed by the live
  manual submission.
- Refresh the web runtime and validate the supported local API, worker queues,
  cookie health, and one live authenticated download path.

## Out of scope

- A second browser identity or cookie pool (Profile B).
- Automatic Google login, passwords, 2SV, CAPTCHA solving, proxies, or PO-token
  services.
- Rotating identities to bypass an active YouTube enforcement decision.
- Retrying the existing failed-job backlog.
- Increasing worker concurrency or changing queue topology.

## Drift guards and stop conditions

- Browser-profile access must run under a Browser Job Broker lease for
  `identity:nora-work`.
- Cookie values, browser lease tokens, and Google credentials must never appear
  in logs, task evidence, tests, or cron output.
- A missing profile, failed export, anonymous-only jar, stale/expired jar, or
  failed media probe must leave the current production jar untouched.
- The refresh must use same-filesystem atomic replacement and retain only one
  protected rollback jar.
- Stop for human action if Nora's session requires password, 2SV, or CAPTCHA.
- Profile B remains closed unless Profile A fails after this guarded refresh.

## Done criteria

- Focused CLI, downloader, cookie-refresh, and hardening tests pass.
- A live brokered canary reports authenticated cookie health and a successful
  test media download without exposing cookie values.
- The daily OpenClaw command cron is installed with no chat delivery and a
  bounded runtime.
- The web API is refreshed and `ytctl status` plus worker queue coverage are
  healthy.
- The requested `DFImJfJGXl0` ingest has passed the download stage, proving the
  authenticated jar and EJS solver path work in production.

## Validation evidence

- `44 passed` across cookie refresh, downloader hardening, YouTube download,
  CLI, download-circuit, and subscription-poll tests.
- Live brokered canary: `status=ok`, 42 scoped cookies, 12 authenticated
  cookies, 13 YouTube cookies, zero expired cookies, and a successful 10,241-
  byte media probe for `DFImJfJGXl0`.
- OpenClaw cron `fc33488a-037c-4ad7-8707-61c5f6dd8a93` is enabled for
  `45 1 * * *` in `Asia/Singapore`, with no chat delivery and a 900-second
  command timeout.
- The source-mounted web runtime was restarted after its remote image-metadata
  rebuild path stalled before changing the service. `ytctl status` then
  reported `status=ok`; three workers covered `audio`, `celery`, `diarize`, and
  `post` with no missing queues.
- An idempotent supported-API submission check returned the existing job rather
  than creating a duplicate, proving the metadata path now tolerates an
  authenticated response with no selectable media format.
- Requested job `6911bedc-96b9-4a18-a20e-f99010637547` completed at 100% with
  no error. Profile B remained out of scope because Profile A passed.
