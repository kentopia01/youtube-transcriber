# T096 - YouTube remediation release QA

## Status
Done.

## Objective
Prove the remediation contract before mutating production job/subscription
state.

## In scope
- Focused tests, full default suite, compilation/static checks.
- Live non-mutating anonymous/auth/runtime/cookie/watchdog/service probes.
- Dirty-tree and deployment-drift review.

## Out of scope
- Job retries and subscription enablement.

## Done criteria
- All gates pass or every exception is explicitly reported before T097.

## Verification
- Pre-release full repository suite: `1,446 passed, 11 skipped`; final
  post-recovery/override suite: `1,447 passed, 11 skipped`.
- Python compilation, `git diff --check`, and `docker compose config --quiet`
  passed.
- Native, CLI/cron, and live web runtime parity checks passed.
- Web health is green; three restarted workers cover every required queue and
  report idle.
- All five recovery targets passed fresh anonymous 10 KiB media probes.
- A live authenticated canary probe used a disposable cookie snapshot; the
  canonical jar hash, size, and modification time remained byte-for-byte
  unchanged.
- The live watchdog reports the correct pre-recovery truth: two completed and
  four failed videos in 24 hours, with the latest failed attempts visible.
- AI Engineer remains disabled until T097; no job or subscription state was
  mutated during this QA gate.
