# T089 - Anonymous-first YouTube access

## Status
Done (2026-08-21).

## Objective
Restore anonymous extraction for public discovery, metadata, classification,
and media, with authentication used only when the anonymous response proves it
is required.

## In scope
- Anonymous defaults for public yt-dlp calls.
- Explicit authenticated retry for classified login/age/member/private errors.
- One exact-video anonymous fallback after authenticated 403/reload/unavailable.
- Focused tests for client-selection and terminal outcomes.

## Out of scope
- PO-token installation, proxies, Cloak, account rotation, production retries.

## Done criteria
- Public paths do not receive cookies.
- Auth is bounded and does not mask deleted/private/geo/live outcomes.
- Focused tests pass.

## Validation
- Public media, metadata, and channel discovery omit configured cookies.
- Explicit age/private/login responses may use the active cookie profile once.
- A degraded authenticated response gets one exact-URL anonymous retry.
- Focused service tests: `46 passed`.
