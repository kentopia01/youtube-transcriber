# T060 - yt-dlp Dependency Floor

## Status

Done

## Objective

Make the validated yt-dlp 2026.06.09 release the minimum project dependency so
new or secondary environments cannot silently satisfy the project contract with
the stale 2024-era floor.

## In Scope

- Raise the `pyproject.toml` yt-dlp lower bound to the T036 validated release.
- Keep the native-worker installation example aligned with the same floor.
- Add a small dependency-contract regression test.
- Refresh the local `.venv314` test environment to the validated baseline.

## Out of Scope

- Automatic runtime package upgrades.
- Worker restarts; production `.venv-native` already runs the validated release.
- Changing cookie or download retry behavior.

## Acceptance

- Project metadata requires `yt-dlp>=2026.6.9`.
- README native install instructions use the same minimum.
- The dependency-contract test passes.
- `.venv314` reports a non-stale validated version.

## Validation

- `pyproject.toml` and the README native install command now require `yt-dlp>=2026.6.9`.
- `.venv314` upgraded from 2026.02.21 to 2026.06.09 using the cached package artifact.
- `.venv314/bin/python scripts/check_ytdlp_version.py --warn-days 75` reports `status=ok`, age 42 days.
- Dependency-contract and download-hardening tests passed: 6 passed.
- Final default suite passed: 1,243 passed, 12 skipped.
- Production `.venv-native` was already on 2026.06.09; no worker restart was necessary.
