# T031 - Cookie Lint And Safe Refresh Policy

## Status
Done

## Objective
Prevent anonymous or stale cookie files from silently poisoning public-video downloads.

## Scope
- Inspect configured YouTube cookie file.
- Classify missing, unreadable, empty, anonymous-only, expired, and healthy states.
- Surface warnings to probes and alerts.

## Out of scope
- Storing Google credentials.
- Automatic browser login.
- Automatic cookie refresh from Ken's personal account.

## Done criteria
- Anonymous-only cookies are detectable.
- Auth-like YouTube cookies are detectable.
- Cookie lint never prints secret cookie values.

## Validation
- Unit tests with synthetic cookie files.
