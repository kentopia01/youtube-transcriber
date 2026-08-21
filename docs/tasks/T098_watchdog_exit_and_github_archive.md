# T098 - Watchdog exit semantics and GitHub archive

## Status
Done.

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

## Verification
- Alert-output mode exits `0` after a successful state evaluation; direct
  operator mode retains exit `1` for degradation and execution exceptions
  retain exit `2`.
- The 16:01 SGT scheduled watchdog run completed in `413 ms`, exited `0`, and
  correctly suppressed a healthy unchanged state as `NO_REPLY`.
- Local release gates passed: `1,449 passed, 11 skipped`, Python compilation,
  diff hygiene, Compose configuration, and native/runtime parity.
- The public staged diff contained `48` text files, no runtime-data paths, no
  binaries, and no detected credential formats.
- Remediation commit `7317441` is on `origin/main`. Follow-up commits make route
  contracts portable across supported FastAPI versions and update GitHub's
  official action runtimes.
- GitHub Actions run
  `https://github.com/kentopia01/youtube-transcriber/actions/runs/32462500099`
  passed every step without annotations at head `3ae65aa`.
- Final live state remains healthy and idle with three workers, zero visible
  failed jobs, and zero operational warnings.
