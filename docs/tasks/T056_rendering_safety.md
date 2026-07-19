# T056 - Rendering safety

## Status

Done

## Objective

Remove executable HTML injection paths from persisted summaries, chat Markdown, API error messages, and channel discovery metadata while preserving the local operator experience.

## In Scope

- Render persisted video summaries through the existing escaping-first Markdown renderer.
- Escape model/user HTML before Marked parses chat Markdown and strip unsafe links/attributes from rendered output.
- Use text nodes or escaped values for API error/status messages and discovered-video metadata.
- Reject non-HTTP(S) thumbnail/video links in dynamically rendered channel results.
- Add focused regression coverage for server-rendered and client-rendered injection sinks.

## Out of Scope

- Replacing Marked or redesigning chat.
- Content Security Policy, vendoring all CDN assets, or removing every benign `innerHTML` use.
- Public hosting or reverse-proxy security.
- Report layout changes; its current renderer already escapes input before emitting trusted HTML.

## Acceptance

- Persisted summary HTML is escaped before trusted rendering.
- Raw chat HTML and `javascript:` Markdown links cannot become executable DOM.
- API-provided error text, channel names, video titles, and URLs cannot inject markup or executable links.
- Focused template/reporting tests and the full default suite pass.
- Runtime web health remains green after the mounted templates/code reload.

## Validation

- Persisted video summaries now use the escaping-first report Markdown renderer; malicious tag regression coverage confirms formatting remains while raw tags are encoded.
- Dynamic and server-rendered chat messages share an escape-before-Markdown and allowlist-after-Markdown path.
- Markdown links are limited to HTTP(S), and generated attributes are stripped except safe anchor metadata.
- Dashboard and legacy submit templates escape API errors, IDs, channel names, and video titles; dashboard external media links are protocol-checked.
- Focused rendering/report validation passed: 83 tests.
- Final full suite passed: 1,228 passed, 12 skipped.
- Compile checks and `git diff --check` passed.
- Mounted web code reloaded successfully and live `/health` returned `{"status":"ok"}`.
