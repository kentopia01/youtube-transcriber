# T057 - Allowlisted Telegram Notification Fanout

## Status

Done

## Objective

Deliver existing operational and report notifications to every explicitly
allowlisted Telegram user while both current users share the same trusted operator
role.

## In Scope

- Resolve every unique configured numeric allowlist entry as a notification recipient.
- Send message and report-document events to each recipient in stable configured order.
- Isolate recipient failures so one Telegram error does not block other recipients.
- Track dedupe per recipient so retrying a partial failure does not duplicate successful deliveries.
- Preserve the existing global notification enable/mute state.

## Out of Scope

- T049 recipient lanes, per-user subscriptions, role restrictions, or scoped digests.
- Per-user notification preferences.
- Sending test notifications to live Telegram accounts during automated validation.

## Acceptance

- Both allowlisted IDs receive the same trusted-operator notifications.
- Duplicate IDs are sent once.
- If one recipient fails and another succeeds, the call remains best-effort successful and a repeat attempts only the failed recipient.
- Message and document fanout have focused regression coverage.
- T049 remains gated until users need different permissions or digest scopes.

## Validation

- Focused notifier, report delivery, digest, recovery, and persona tests: 65 passed.
- Tests cover duplicate allowlist entries, message fanout, document fanout, partial failure, and recipient-specific retry.
- Active queue check returned zero pending, queued, or running jobs before restart.
- All three native workers restarted cleanly; `scripts/worker_health.sh` returned `HEALTH_OK`.
- No live Telegram test notification was sent.
