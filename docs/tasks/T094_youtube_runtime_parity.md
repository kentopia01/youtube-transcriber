# T094 - YouTube extraction runtime parity

## Status
Done.

## Objective
Use one tested yt-dlp and JavaScript-runtime capability contract everywhere
YouTube extraction runs.

## In scope
- Exact yt-dlp pin across project/native/web/CLI/cron environments.
- Supported JS runtime in the web image.
- Runtime contract tests/diagnostics.

## Out of scope
- Worker concurrency or transcription dependency changes.

## Done criteria
- Version/runtime checks report parity for supported extraction paths.

## Verification
- Exact `yt-dlp 2026.08.19` contract passes in `.venv`, `.venv-native`, and the
  live web container.
- Deno is available in every supported extraction environment.
- The web cookie mount is read-only and the web health endpoint is healthy.
- Docker Hub metadata stalled during deployment, so the release used the
  secret-free local-image overlay in `Dockerfile.runtime-overlay`; `Dockerfile`
  remains the canonical clean-build path.
