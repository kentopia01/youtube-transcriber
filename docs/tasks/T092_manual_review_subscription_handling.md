# T092 - Manual-review subscription handling

## Status
Done (2026-08-21).

## Objective
Prevent a known manual-review video from disabling its source subscription.

## In scope
- Structured submit-result classification for HTTP 409 manual-review blocks.
- Mark the video handled/deferred without incrementing channel failures.
- Equivalent lane behavior where applicable.

## Out of scope
- Clearing manual review or retrying the video.

## Done criteria
- Repeated manual-review 409s cannot auto-disable a subscription.
- Genuine feed/channel failures retain existing containment.

## Validation
- Local submission failures now carry status/detail structurally.
- HTTP 409 with a manual-review reason is marked seen and reported as a
  per-video terminal disposition for global and lane subscriptions.
- The channel failure counter is reset through normal poll success and cannot
  auto-disable from the contained video.
- Focused subscription coverage: `41 passed`.
