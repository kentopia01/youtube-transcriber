# T077 - OpenClaw local-control modernization

## Status

Done

## Objective

Make OpenClaw use the supported local API/CLI boundary for YouTube operations and
research instead of direct database or model-provider access.

## In scope

- Version-controlled `yt-transcribe`, `yt-chat`, and `yt-status` skill sources.
- Read-only defaults through `ytctl`; explicit confirmation for mutations.
- Install/sync instructions and static contract tests.
- Sync and smoke-test the installed local OpenClaw workspace skills.

## Out of scope

- Telegram identity as API auth, public network access, or direct OpenAI/Anthropic calls.

## Done criteria

- Skills contain no Docker/Postgres SQL or provider bypass.
- OpenClaw status and transcript/search reads work against the live local service.
- Installed copies match the version-controlled source.

## Validation

- Added canonical `yt-status`, `yt-chat`, and `yt-transcribe` skill sources under
  `openclaw/skills` and synced byte-identical copies into the active workspace.
- Removed the installed legacy scripts that queried Docker/PostgreSQL or called model
  providers directly.
- `openclaw skills info` reports all three skills ready, visible to the model, and
  available as commands.
- Live `ytctl` status, transcript, and semantic-search reads pass; static boundary
  tests confirm no SQL/provider bypass remains.
