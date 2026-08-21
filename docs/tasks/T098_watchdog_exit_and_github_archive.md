# T098 - Watchdog exit semantics and GitHub archive

## Status
In progress.

## Objective
Archive the full T088-T097 remediation in GitHub without making an observed
pipeline incident look like a watchdog execution failure.

## In scope
- Make stateful alert-output mode exit successfully after it evaluates and
  renders a degraded, suppressed, or recovered state.
- Preserve non-zero degraded exits for direct JSON/operator health checks.
- Add the missing test-only NumPy dependency required by GitHub Actions.
- Run focused, full, static, live, and public-repository credential checks.
- Commit and push the reviewed remediation to `origin/main`.

## Out of scope
- Cloak, proxies, browser-backed media downloading, PO-token deployment, or
  new retry behavior.
- A GitHub release, tag, pull request, or branch-history rewrite.

## Done criteria
- Degraded alert-output produces the actionable alert and exits `0`.
- Watchdog execution failures still exit non-zero and remain distinguishable.
- Local release gates pass and the live service stays healthy.
- The public-repository diff contains no credential or runtime-data files.
- `origin/main` contains the remediation commit and GitHub Actions completes
  successfully, or any external CI blocker is reported exactly.
