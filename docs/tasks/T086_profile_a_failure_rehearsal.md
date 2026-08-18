# T086 - Profile A Guarded Failure Rehearsal

## Status

Done (2026-08-18).

## Objective

Prove that a failed Profile A cookie refresh or probe preserves the production
jar and active selection, records bounded failure evidence, and does not activate
Profile B.

## In scope

- Run the refresh and profile-control paths against disposable cookie, state,
  evidence, lock, and backup paths.
- Simulate an invalid or failed candidate refresh without reading or replacing
  the production cookie jar.
- Prove last-known-good preservation, atomic state behavior, cooldown evidence,
  unsafe activation rejection, and unchanged `profile_a` selection.
- Record a redacted rehearsal artifact suitable for operator review.

## Out of scope

- No production cookie replacement, browser lease, Google login, Profile B
  creation, automatic failover, job retry, schedule change, or worker restart.
- No cookie values or browser credentials in output or test artifacts.

## Drift guards and stop conditions

- All mutable paths must resolve inside a disposable rehearsal directory.
- Stop before any browser or network operation not supplied by a deterministic
  fixture.
- Production Profile A must remain active before and after the rehearsal.

## Done criteria

- The failed refresh leaves the disposable last-known-good jar byte-identical.
- Failure and cooldown evidence are recorded without secret values.
- Profile B activation is rejected and remains unconfigured.
- The production active-profile state and production cookie hash are unchanged.
- Focused tests and static checks pass.

## Validation evidence

- The disposable refresh raised the intended synthetic export failure and wrote
  failed evidence with `production_replaced=false`.
- The disposable last-known-good jar remained byte-identical.
- Profile A remained active, its failed probe recorded a cooldown, and a new
  activation was rejected during cooldown.
- Profile B remained unconfigured and activation was rejected.
- Production Profile A cookie and profile-state hashes were identical before
  and after the rehearsal.
- The rehearsal performed no browser, network, production-cookie, schedule, or
  worker mutation.
- Focused validation passed: 17 tests, Python compilation, and
  `git diff --check`.
- Redacted evidence:
  `outputs/operations/T086_profile_a_failure_rehearsal_2026-08-18.json`.
