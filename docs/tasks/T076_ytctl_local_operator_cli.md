# T076 - `ytctl` local operator CLI

## Status

Done

## Objective

Give local humans and agents one supported command-line client for service status,
inventory, transcripts, search, and bounded operations.

## In scope

- A packaged `ytctl` command with human-readable and JSON output.
- Read commands for status, warnings, jobs, videos, transcripts, Reader state,
  search, and subscriptions.
- Mutation commands for submit/retry/cancel/reconcile that require explicit confirmation.
- Configurable base URL defaulting to `http://127.0.0.1:8000`.

## Out of scope

- Direct database access, remote credentials, or implicit destructive actions.

## Done criteria

- Read commands work without auth on the loopback deployment.
- Mutations refuse to run without `--confirm`.
- Transport, output, exit codes, and command contracts have automated tests.

## Validation

- Installed the packaged `ytctl` entry point and live-tested status, warnings, jobs,
  videos, Reader state, transcript, semantic search, and reconciliation preview.
- Submit/retry/cancel and reconciliation apply refuse to run without `--confirm`.
- Transport errors, including a cold-model socket timeout, produce exit code `2` and
  a stable message; request timeout is configurable with `--timeout` or
  `YT_TRANSCRIBER_TIMEOUT`.
- CLI contract tests pass.
