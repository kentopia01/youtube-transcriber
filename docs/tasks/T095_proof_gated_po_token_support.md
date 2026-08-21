# T095 - Proof-gated PO-token support

## Status
Done.

## Objective
Support authenticated-only YouTube content without making a token provider a
silent global dependency.

## In scope
- Optional provider configuration and readiness diagnostics.
- Authenticated-only gating and fail-closed provider selection.
- Non-secret tests/documentation.

## Out of scope
- Browser-service media downloading, Cloak, bypassing enforcement decisions.

## Done criteria
- Public extraction never depends on the provider.
- Authenticated use is refused or explicitly degraded when required provider
  readiness is absent.

## Verification
- Public mode reports ready with authenticated access disabled.
- Enabling authenticated extraction without a configured, discovered provider
  fails closed before a cookie-bearing request is made.
- Provider/client configuration is explicit and diagnostic output contains no
  token or cookie material.
- `14` focused access/provider tests pass in the release environment and the
  live web container reports the same readiness state.
