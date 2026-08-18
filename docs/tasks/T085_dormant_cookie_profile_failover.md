# T085 - Dormant Cookie Profile Failover Readiness

## Status

Done (2026-08-18).

## Objective

Make a second authenticated-cookie profile implementation-ready without
creating credentials, enabling automatic account rotation, or changing the
active production profile.

## In scope

- Represent `profile_a` and optional `profile_b` as named cookie slots.
- Preserve the current `YTDLP_COOKIES_FILE` behavior as `profile_a` when no
  profile state or Profile B configuration exists.
- Resolve the active named slot at each yt-dlp operation so a confirmed manual
  switch persists across service and worker restarts.
- Store only non-secret active-profile, probe, and cooldown state in a protected
  atomic JSON file guarded by a process lock.
- Add explicit local operator commands for status, live probe, confirmed
  activation, and confirmed failback.
- Require a healthy authenticated jar and successful live media probe before a
  profile may become active.
- Put a profile with a failed probe on a bounded cooldown and reject activation
  while that cooldown remains active.
- Cover absent Profile B, unhealthy Profile B, switching, cooldown, failback,
  persistence, and legacy single-file behavior with focused tests.

## Out of scope

- Creating, launching, or signing into a Profile B browser identity.
- Exporting or scheduling Profile B cookies before the evidence gate opens.
- Automatic failover, round-robin selection, load balancing, or concurrent use
  of two authenticated jars.
- Password, 2SV, CAPTCHA, proxy, PO-token, or IP-rotation automation.
- Retrying failed production jobs or changing worker concurrency.

## Drift guards and stop conditions

- `profile_a` remains active after implementation and runtime validation.
- A missing, malformed, stale, anonymous-only, expired, or failed-probe Profile
  B must be rejected without changing active state.
- Cookie values and browser credentials must never enter state, logs, tests, or
  task evidence.
- State replacement must be atomic and same-filesystem; concurrent operator
  mutations must serialize through one lock.
- Profile selection is explicit and manual. No download error may trigger a
  profile change.
- Stop for human action if activation requires browser login, password, 2SV, or
  CAPTCHA.

## Activation gate

Profile B credentials remain absent until Profile A has two consecutive guarded
refresh or media-probe failures, or evidence proves an account-specific block.
If both profiles later fail from the same Mac and IP, stop instead of rotating.

## Activation runbook

1. Create a separate broker identity and browser profile only after the
   activation gate opens; a human performs any required Google login locally.
2. Configure a distinct Profile B cookie path. Use
   `refresh_youtube_cookies.py` with Profile B's broker resource, browser root,
   cookie path, and evidence path. Its per-jar lock, authenticated-cookie lint,
   real media probe, atomic replacement, and last-good backup apply unchanged.
3. Run `manage_youtube_cookie_profiles.py probe profile_b`.
4. Run `manage_youtube_cookie_profiles.py activate profile_b --confirm` only
   after the successful probe.
5. Verify status and one bounded ingest. Do not retry a backlog automatically.
6. Before failback, probe Profile A, then run
   `manage_youtube_cookie_profiles.py failback --confirm`.

## Done criteria

- The current production configuration behaves exactly as `profile_a` when
  Profile B is absent.
- Status reports both named slots without exposing cookie values.
- Probe failure records a cooldown and activation rejects the profile.
- A successful isolated fixture probe permits confirmed activation; confirmed
  failback restores Profile A.
- Active selection survives a new resolver/process instance.
- Focused tests and the full default suite pass.
- Runtime status remains healthy and active production state remains
  `profile_a`.

## Validation evidence

- The full suite passed with `1417 passed, 11 skipped`; the local production
  `.env` values were neutralized only for four default-contract assertions.
- Focused profile, refresh, download, hardening, and configuration tests passed.
- Python compilation and `git diff --check` passed.
- A live Profile A operator probe reported 42 scoped cookies, 12 authenticated
  cookies, 13 YouTube cookies, zero expired cookies, and a successful 10,241-
  byte media download for `DFImJfJGXl0`.
- Confirmed activation persisted `profile_a`; the state file mode is `0600`.
  Profile B remains unconfigured with no probe or cooldown state.
- The web, post, and audio runtimes were reloaded. `ytctl status` reported
  `status=ok`; three workers covered `audio`, `celery`, `diarize`, and `post`
  with no missing queues.
- No Profile B browser identity, cookies, login, automatic failover, job retry,
  or concurrency change was created.
