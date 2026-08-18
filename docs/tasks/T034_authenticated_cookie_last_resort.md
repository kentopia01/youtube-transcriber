# T034 - Authenticated Cookie Last Resort

## Status
Done — evidence gate opened and implementation moved to T084 on 2026-08-18

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
- The dedicated Nora service profile was used; no password or 2FA was handled
  by the transcriber or placed in chat.
- The exported jar passed authenticated-cookie lint and a real media probe for
  `DFImJfJGXl0`; that production ingest then passed the download stage.
- The guarded scheduled refresh and runtime rollout are tracked in T084.
- 2026-07-21 T061 recovery validation passed every attempted public-video
  download; where cookie-backed requests returned 403, the existing one-time
  cookie-free fallback succeeded. There is no current evidence requiring
  authenticated cookies.
