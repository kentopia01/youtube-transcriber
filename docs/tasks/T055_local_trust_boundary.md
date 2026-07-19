# T055 - Local trust boundary

## Status

Done

## Objective

Match runtime exposure to the deployment contract: the web application is local-only, and Telegram is the only externally reachable user ingress with an explicit numeric allowlist.

## In Scope

- Bind the Docker web port to host loopback only.
- Fix the API-auth path classifier so a configured API key protects non-public routes.
- Make Telegram authorization fail closed when the allowlist is empty.
- Refuse to construct a Telegram polling app when a token is configured without allowed user IDs.
- Correct operator documentation to use the JSON-list format accepted by settings.
- Add focused regression tests and validate the live Docker/bot bindings.

## Out of Scope

- Public hosting, reverse proxies, TLS, SSO, or multi-tenant roles.
- Changing which of the two approved Telegram users receives automated notifications.
- Recipient-specific data lanes or scoped digests (T049).
- UI rendering/XSS hardening, which remains a separate remediation task.

## Acceptance

- Docker publishes web, Postgres, and Redis only on `127.0.0.1`.
- `/health`, `/`, and static assets remain exempt from optional API-key auth; other paths are protected when `API_KEY` is set.
- An empty Telegram allowlist authorizes nobody and prevents bot startup.
- The configured runtime allowlist contains exactly the two approved numeric IDs.
- Focused and full tests pass, and the restarted local services are healthy.

## Validation

- Docker now publishes web, Postgres, and Redis only on `127.0.0.1`; live `docker compose ps` confirmed the bindings.
- Added a lightweight `/health` endpoint and verified `{"status":"ok"}` through the host loopback binding.
- API-auth path and middleware tests prove public-route exemptions and protection of non-public routes when a key is configured.
- Telegram access fails closed for an empty allowlist, and application construction refuses a token without allowed IDs.
- Runtime `.env.native` resolves to exactly the two approved numeric user IDs; the restarted bot registered all 23 commands and started successfully.
- Focused trust-boundary tests passed: 56 tests.
- Final full suite passed: 1,223 passed, 12 skipped.
- Compile checks, shell syntax checks, and `git diff --check` passed.
