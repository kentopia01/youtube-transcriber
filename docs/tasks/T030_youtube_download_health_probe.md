# T030 - YouTube Download Health Probe

## Status
Done

## Objective
Detect cookie-backed YouTube media-download degradation before the subscription auto-ingest batch runs.

## Scope
- Add a probe script for cookie and no-cookie media download paths.
- Report yt-dlp version freshness.
- Report cookie-file health alongside media probe results.

## Out of scope
- Automatic yt-dlp upgrades.
- Automatic Google login.
- PO-token generation.

## Done criteria
- Probe exits non-zero when cookie path fails while no-cookie path works.
- Probe output is human-readable and JSON-capable.
- Probe can run from the native repo environment.

## Validation
- Focused unit tests plus a real probe run.
