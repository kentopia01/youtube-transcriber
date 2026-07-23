# T078 - Local runtime hardening and recovery

## Status

Done

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

## Validation

- Live Docker services publish only on `127.0.0.1`; web starts without Uvicorn reload.
- Cross-site browser mutations are rejected while origin-less local clients remain
  supported, with accepted/rejected mutations written to sanitized durable JSONL.
- A CLI reconciliation preview produced a queryable audit record without body or
  credential data.
- Backup `data/backups/20260723T084401Z` passed portable SHA-256 checks for its
  database and report archive, then restored into isolated database
  `yt_restore_verify_20260723084501_39878`: `622` videos, Alembic `022`; the temporary
  database was dropped and the live database was untouched.
- Docker dependencies are healthy and `scripts/worker_health.sh` confirms all required
  queues are covered by three native workers.
- Cold embedding-model work runs in a threadpool, so the first semantic search no
  longer blocks Reader, Operations, or health requests on the async web event loop.
