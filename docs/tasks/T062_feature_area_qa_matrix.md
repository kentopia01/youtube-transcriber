# T062 - Feature-area QA Matrix

## Status

Done — read-only/live and isolated matrix

## Objective

Prove the operator-facing tabs and feature areas with a repeatable combination of
read-only live checks and isolated automated tests, without allowing routine QA to
enqueue jobs or mutate production data.

## In Scope

- Dashboard, Queue, Library videos/channels, Chat, Search, and Global Search navigation surfaces.
- Legacy redirects and HTMX partials.
- Existing dynamic video, channel, persona/channel-chat, job, and transcription views.
- Read-only chat-session, subscription, LLM-usage, search, and global-search APIs.
- A coverage matrix separating live-read, isolated-mutating, Telegram, worker, and deferred browser-interaction evidence.

## Out of Scope

- Submitting a real video as part of routine smoke QA.
- Retrying/cancelling live jobs, editing subscriptions, toggling records, or sending live chat/Telegram messages.
- Pixel-perfect browser QA without a browser automation runtime.
- T049 lane implementation itself.

## Acceptance

- One command exercises every current navigation tab against the loopback service without writes.
- Dynamic detail/API checks use IDs discovered from current rendered pages.
- Failures identify their feature area and endpoint.
- The matrix states where mutating and browser-only behaviors are covered or still missing.
- Focused tests and the full default suite pass.

## Validation

- Live loopback matrix: 26/26 passed.
- Focused script, feature-smoke, and template suite: 78 passed.
- Dynamic checks discovered real video, channel/persona, and job IDs from rendered pages.
- Search and Global Search executed read-only live queries successfully.
- Coverage and intentional gaps are recorded in `docs/evaluations/feature_area_qa_2026-07-21.md`.
- Full-suite validation is part of the final combined release gate after the remaining tasks.
