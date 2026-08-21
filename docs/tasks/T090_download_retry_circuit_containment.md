# T090 - Download retry and circuit containment

## Status
Done (2026-08-21).

## Objective
Stop deterministic YouTube failures from multiplying across task retries and
changing error strings.

## In scope
- Retryable error taxonomy for the download task.
- Total download-episode cap across pipeline attempts.
- Reload/unavailable-with-public-proof circuit classification.
- Circuit success semantics that do not erase unrelated failures.

## Out of scope
- Queue concurrency, account rotation, production job recovery.

## Done criteria
- Deterministic extractor failures do not receive blind Celery retries.
- Episode cap is independent of failure signature.
- Circuit tests cover the newly observed signatures.

## Validation
- Download Celery retries reduced from three to one and limited to transport/
  server failures; 403/reload/unavailable/player errors do not retry blindly.
- Manual review for downloads now counts the full per-video download episode,
  independent of changing failure signatures.
- Successful downloads remove only their own circuit failure; unrelated success
  cannot clear a clustered incident.
- Focused retry/circuit/recovery coverage: `35 passed`.
