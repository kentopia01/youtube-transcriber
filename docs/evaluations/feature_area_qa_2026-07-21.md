# Feature-area QA Matrix — 2026-07-21

## Conclusion

The completed T063 Reader/Operations release passes all default gates:

- `1349 passed, 12 skipped` in the full isolated repository suite.
- `33/33` live loopback HTTP/API checks.
- `30/30` live Chromium checks across desktop and mobile.

The live schema is at Alembic `021`. Default QA remained non-mutating: it did
not submit or retry videos, change subscriptions, send chat prompts, create or
delete annotations, generate semantic chapters, or send Telegram messages.

## Coverage Matrix

| Feature area | Isolated coverage | Live coverage | Status |
|---|---|---|---|
| Reader Home | Shelves, durable progress, warnings, no queue controls | Desktop/mobile rendering and fit | Complete |
| Transcript Reader | Blocks, timestamps, search, appearance, progress | Desktop/mobile document interaction | Complete |
| Reader Library | Readable-only documents, filters, pagination, cards, tabs | Videos/channels tabs at both viewports | Complete |
| Highlights / Notebook | Annotation CRUD, anchors, reconciliation, export, XSS | Page and read-only annotation API | Complete |
| Research Search / Ask | Library/channel/video scope, fallback containment, citations | Search interaction and explicit current-video scope | Complete |
| Semantic chapters | Fingerprints, anchors, provenance, deterministic fallback | Stored chapter read API; generation not invoked | Complete |
| Operations dashboard | Structured health/count/batch/delivery contract | Desktop/mobile page and recent-jobs partial | Complete |
| Queue and job detail | Lifecycle, retry/cancel, routing, recovery affordances | Desktop/mobile pages, polling partial, read APIs | Complete |
| Submission/import | Validation, enqueue and batch contracts, shared frontend module | Forms render; live enqueue excluded | Complete within non-mutating boundary |
| Channel persona/chat | Persona generation, agent sessions and grounding | Page and read APIs; live message excluded | Complete within non-mutating boundary |
| Subscriptions/digests | CRUD, polling, isolation, delivery and failure handling | Read API; live mutation/delivery excluded | Complete within non-mutating boundary |
| Telegram recipient lanes | Allowlist, authorization, isolation, commands and fanout | Bot/process health; both approved lanes ready | Complete |
| Frontend/accessibility | WCAG token contrast, names/states, focus, live regions, static assets | JS errors, 4xx/5xx, overflow and 44px mobile targets | Complete |
| Compatibility | Route and template contracts | Submit, queue, library, channels, and Global Search redirects | Complete |

## Live HTTP Result

Run:

```bash
.venv314/bin/python scripts/qa_feature_areas.py
```

Final result: `33/33 passed`. Coverage includes Reader Home, Operations, Queue,
Library tabs, Chat, Research, Highlights, compatibility redirects, HTMX
partials, health/usage/subscription/session APIs, video/transcription/annotation/
chapter APIs, channel/persona/agent surfaces, job detail, Search, and Global
Search.

## Browser Result

Run with an environment containing Playwright and Chromium:

```bash
python scripts/qa_browser_feature_areas.py
```

Final result: `30/30 passed` at `1440x900` and `390x844`. The matrix covers
workspace pages, Library tab navigation, local HTMX JSON transport, Reader
blocks/annotations/search/appearance, current-transcript Research scope,
Operations job detail, mobile navigation, Chat sidebar, Search, and legacy
Global Search migration.

## Deliberate Live Boundaries

- Real ingestion, retry/cancel, subscription changes, persona generation,
  semantic chapter generation, chat sends, annotation mutation, and Telegram
  delivery require explicit opt-in.
- Provider failure and fallback behavior is covered with isolated tests instead
  of deliberately causing live spend or outage.
- Visual regression is enforced through deterministic structure/style
  contracts plus desktop/mobile overflow, responsive reflow, target-size, and
  JavaScript-error checks; pixel-diff baselines are not part of the default gate.
