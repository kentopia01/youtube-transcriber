# T040: Global Search API and Operator UI

## Status
Done

## Goal
Expose global corpus search through a separate API and a simple operator page.

## In scope
- Add `POST /api/global-search`.
- Add `GET /global-search`.
- Add an HTMX results partial for global search.
- Add navigation access without removing the existing search page.
- Return JSON for API callers and HTML partials for the UI.

## Out of scope
- Replacing the current search page.
- Chat answer generation from selected results.
- Complex dashboard redesign.

## Guardrails
- Keep UI functional and compact.
- Make filters obvious but not noisy.
- Preserve API-key behavior inherited from the app.

## Validation
- Endpoint tests cover JSON and HTMX responses.
- Template rendering works with representative result rows.
