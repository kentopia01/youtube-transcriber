# Feature-area QA Matrix — 2026-07-21

## Conclusion

All current navigation tabs and discoverable read-only feature surfaces pass against
the live loopback stack: 26/26 checks. This is not equivalent to complete browser
and production-mutation QA. Mutating actions are covered in isolated tests, while
live video submission, retry/cancel, subscription changes, chat sends, Telegram
delivery, and responsive/browser interaction remain deliberate opt-in checks.

## Coverage Matrix

| Feature area | Isolated automated coverage | Live read-only coverage | Live mutation/browser coverage | Status |
|---|---|---|---|---|
| Dashboard and submit forms | Template, API validation, attempt/enqueue tests | Page and recent-jobs partial pass | Real submit excluded from routine QA | Read path complete |
| Queue and job detail | Queue rendering, retry/cancel, state and routing tests | Full page, HTMX partial, job page/API pass | Retry/cancel live mutation not run | Read path complete |
| Library / Videos | Pagination, filters, toggle and rendering tests | Videos tab, video page/API, transcription API pass | Toggle/dismiss live mutation not run | Read path complete |
| Library / Channels | Discovery, filtering, batch/attempt and toggle tests | Channels tab and channel detail pass | Import/process/toggle live mutation not run | Read path complete |
| Chat | Session/message/RAG/security tests | Chat page and session-list API pass | Live model message send not run | Read path complete |
| Channel persona/chat | Persona generation and agent router tests | Persona API, channel chat page, agent sessions pass | Persona refresh and live message send not run | Read path complete |
| Search | Hybrid/vector/keyword and API tests | Page and read-only query pass | Browser debounce/chips not executed | Service path complete |
| Global Search | Fusion/diversity/benchmark and API tests | Page and read-only query pass | Browser filter interaction not executed | Service path complete |
| Subscriptions | CRUD, polling, long-form and Telegram-command tests | Subscription-list API passes | Live subscribe/unsubscribe not run | Read path complete |
| LLM usage/cost | Cost tracker, provider, retry and digest tests | Usage API passes | Live budget threshold not induced | Read path complete |
| Reports/digests | Rendering, quality, delivery-failure and digest tests | Current report state audited | No live Telegram resend | Automated complete |
| Telegram operator bot | Command, callback, Markdown, allowlist and fanout tests | Process/worker health only | No live message sent during QA | Automated complete |
| Pipeline/workers | Attempt, stage, recovery, queue and integration tests | Health and queue coverage pass | Real job smoke is opt-in | Automated/read health complete |
| Security boundaries | API auth, fail-closed allowlist and XSS tests | Loopback endpoints healthy | Browser CSP/visual inspection absent | Automated complete |
| Recipient lanes (T049) | Not implemented at audit start | Not available | Not available | Open task |

## Live Read-only Result

The command below passed 26/26 checks:

```bash
.venv314/bin/python scripts/qa_feature_areas.py
```

Covered live targets:

- Dashboard, Queue, Library videos, Library channels, Chat, Search, Global Search.
- Legacy `/submit` and `/channels` redirects.
- Recent-jobs and Queue HTMX partials.
- Health, chat sessions, subscriptions, and LLM usage APIs.
- Discovered video detail/API/transcription, channel detail/persona/chat/sessions, and job detail/API.
- Read-only Search and Global Search requests.

## Remaining QA Boundaries

- No browser automation runtime is installed, so JavaScript interaction, responsive layout, focus order, keyboard navigation, and visual regressions are not executed end-to-end.
- Routine QA must remain non-mutating. Existing smoke submission requires explicit opt-in and can enqueue real work.
- T049 requires its own schema, authorization, cross-lane isolation, digest, and Telegram acceptance suite before multi-user scoped QA can be called complete.
