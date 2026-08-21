# T093 - Immutable scoped YouTube cookies

## Status
Done (2026-08-21).

## Objective
Make canonical authentication state narrow, atomic, and immutable to routine
metadata/download calls.

## In scope
- YouTube-only export domain allowlist.
- Per-run protected snapshots with no writeback to the canonical jar.
- Read-only web mount.
- Refresh/profile-state synchronization and multiple canaries.

## Out of scope
- Password automation, account rotation, Profile B creation.

## Done criteria
- Routine extraction cannot change canonical cookie bytes/mtime.
- Failed canaries do not replace production state.
- Evidence remains non-secret and state agrees with refresh outcome.

## Validation
- Routine authenticated extraction and media probes consume protected
  disposable snapshots; tests prove yt-dlp writeback cannot alter canonical
  bytes or mtime.
- Browser/live-profile cookie extraction is no longer a worker fallback.
- Refresh allowlist excludes broad `google.com` account state.
- Default refresh uses two canaries; every configured canary must pass before
  atomic replacement.
- Successful configured refresh updates named-profile probe evidence.
- Docker web cookie mount is read-only.
- Focused cookie/access tests: `32 passed`; Compose config validates.
