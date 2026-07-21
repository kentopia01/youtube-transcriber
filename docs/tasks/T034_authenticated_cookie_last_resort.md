# T034 - Authenticated Cookie Last Resort

## Status
Planned contingency — evidence gate not met

## Objective
Define the fallback path for videos that truly require authenticated YouTube access.

## Scope
- Prefer a dedicated service Google account over Ken's main Gmail.
- If Ken's account is used, Ken signs in locally; no password or 2FA is sent through chat.
- Export cookies locally from the browser profile and validate with the probe before enabling.

## Out of scope
- Implementing automatic login.
- Storing Google passwords or 2FA codes.
- Using authenticated cookies for public videos unless needed.

## Done criteria
- Authenticated-cookie use remains a deliberate operator action.
- Cookie health probe validates the session before production use.

## Validation
- Manual runbook only; implementation deferred until evidence requires it.
- 2026-07-21 T061 recovery validation passed every attempted public-video
  download; where cookie-backed requests returned 403, the existing one-time
  cookie-free fallback succeeded. There is no current evidence requiring
  authenticated cookies.
