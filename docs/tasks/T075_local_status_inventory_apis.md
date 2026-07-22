# T075 - Local status and inventory APIs

## Status

Planned

## Objective

Provide stable loopback API contracts so the web UI, CLI, and OpenClaw inspect the
same service truth rather than scraping HTML or querying PostgreSQL directly.

## In scope

- Paginated read endpoints for jobs and videos.
- Reader-state inventory and a compact system-status endpoint.
- Typed filters, deterministic ordering, bounded limits, and API tests.

## Out of scope

- Remote/public API exposure, user auth, or replacing existing detail endpoints.

## Done criteria

- Each collection response includes `items`, `total`, `limit`, and `offset`.
- Status output is composed from existing structured services.
- Invalid filters and excessive limits fail or clamp predictably.

