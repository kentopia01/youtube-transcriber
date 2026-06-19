# T033 - yt-dlp Version Guardrail

## Status
Done

## Objective
Warn when the native yt-dlp install is old enough to deserve operator review.

## Scope
- Add a lightweight version freshness script.
- Parse date-based yt-dlp versions.
- Return non-zero when the installed version exceeds the warning threshold.

## Out of scope
- Silent auto-upgrades.
- Worker restarts after package updates.

## Done criteria
- Script reports installed version, age, and status.
- Old versions are test-covered.

## Validation
- Focused unit tests and local script run.
