# T081 - YouTube Access-Degradation Circuit and Bounded Autonomous Release

## Status

Done (2026-08-06).

## Objective

Prevent a transient YouTube/IP/session challenge from turning one autonomous poll
into a large cluster of failed download jobs.

## In scope

- One classifier for cookie-backed 403, 429, bot-confirmation, login challenge,
  and equivalent YouTube access-degradation errors.
- Self-expiring Redis circuit state based on distinct-video failures.
- Download-task recording of degradation failures and successful recovery.
- Subscription polling that respects an open circuit.
- A configurable poll-wide cap on newly submitted pipeline jobs.
- Focused unit tests for classification, thresholding, expiry/fail-open behavior,
  and bounded polling.

## Out of scope

- Authenticated Google cookies, automatic login, proxies, or PO-token services.
- Production failed-job retries.
- Worker concurrency or queue-topology changes.
- UI redesign.

## Drift guards and stop conditions

- One isolated unavailable video must not open the circuit.
- Redis/circuit-observability failure must not crash manual submissions.
- Circuit deferral must not allow a Celery chain to advance to transcription.
- Stop if a safe bounded task-deferral contract cannot be proven in tests.

## Done criteria

- The four observed anti-bot failures classify as access degradation.
- Two distinct failures inside the configured window open the circuit.
- Polling does not create new jobs while the circuit is open.
- One poll cannot exceed the configured global submission cap.
- Existing focused download and subscription tests remain green.

## Validation

- Anti-bot and HTTP access signatures share one classifier across the circuit,
  checker, and guarded retry candidate path.
- Focused circuit, subscription polling, and download-hardening tests passed.
- A read-only 48-hour production check correctly identified all four observed
  anti-bot failures; no failed jobs were retried.
