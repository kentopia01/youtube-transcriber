# T078 - Local runtime hardening and recovery

## Status

Planned

## Objective

Harden the trusted-local deployment without inventing remote-user authentication.

## In scope

- Remove development reload behavior from the deployed web command.
- Preserve loopback-only publication and reject cross-site browser mutations.
- Record mutation provenance without storing request bodies or secrets.
- Add reproducible local backup plus isolated restore-verification tooling.
- Validate health and worker coverage after rollout.

## Out of scope

- Public ingress, Telegram-as-web-auth, OAuth, or opening database/Redis ports.

## Done criteria

- Unsafe cross-site browser requests fail while CLI requests remain supported.
- Mutations create queryable, sanitized audit records.
- A fresh backup passes an isolated restore drill without touching the live database.
- The production-like web service and all workers are healthy after restart.

