# T036 - Recovered jobs and yt-dlp update

## Status
Done

## Objective
Close the 2026-06-19 YouTube download incident follow-up by confirming the seven recovered videos completed and updating the runtime yt-dlp installation after the cookie-backed 403 hardening.

## Scope
- Confirm all seven download-403 recovery jobs reached completed state.
- Update yt-dlp in both the dev/test virtualenv and native worker virtualenv.
- Run the YouTube download probe after the update.
- Restart native workers only after active pipeline work drains so the running Celery processes load the updated package.
- Validate that the update did not break the default test suite or YouTube download hardening tests.

## Out of scope
- Authenticated Google login or cookie refresh.
- Queue topology changes.
- Summary-quality impact analysis.
- Remote push.

## Results
- All seven recovered videos completed:
  - `OCEVqy8kl7Q`
  - `P0ju8XGsYwA`
  - `pX-AdubYXgk`
  - `kQn3GQBZ0Cs`
  - `3tV4wdtZBuk`
  - `ObTPqBGsEbA`
  - `btxGmN8RvNU`
- Updated yt-dlp:
  - `.venv`: `2026.02.21` -> `2026.06.09`
  - `.venv-native`: `2026.03.03` -> `2026.06.09`
- `scripts/check_ytdlp_version.py` now reports `status=ok`.
- `scripts/probe_youtube_download.py --test-download` passes both cookie and no-cookie paths.
- `scripts/check_youtube_download_failures.py --hours 24 --threshold 1` reports `download_403_failures=0`.
- Native workers were restarted after `active_pipeline_jobs=0`.

## Verification
- PASS: `.venv/bin/python -m pytest tests/test_youtube_download.py tests/test_youtube_download_hardening.py -q` -> `8 passed`.
- PASS: `.venv/bin/python -m pytest -q` -> `1172 passed, 11 skipped`.
- PASS: `bash scripts/worker_health.sh --quiet`.

## Follow-up
- Schedule the probe/checker scripts as a proactive ops guard before the subscription ingest window.
- Keep T034 as the last-resort authenticated-cookie runbook only if public-video fallback stops being sufficient.
