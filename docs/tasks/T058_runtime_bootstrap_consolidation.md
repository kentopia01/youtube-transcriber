# T058 - Runtime Bootstrap Consolidation

## Status

Done

## Objective

Remove copied native environment loading and synchronous database URL resolution
from operator scripts without changing their command behavior.

## In Scope

- One dependency-light helper for `.env.native` parsing/loading.
- One precedence contract for explicit, process, native-file, and fallback database URLs.
- Preserve the public helper used by YouTube download hardening and the scan-first scripts.
- Focused precedence and non-overwrite tests.

## Out of Scope

- Broad LLM provider or retrieval-service redesign.
- Changing secrets, native launch agents, or runtime process topology.
- Rewriting unrelated scripts merely for stylistic consistency.

## Acceptance

- Four copied environment loaders are removed.
- Database URL resolution delegates to one implementation.
- Callers can still import settings only after `.env.native` is loaded.
- Async PostgreSQL URLs are consistently converted to the sync psycopg2 driver.
- Focused script/config tests and the full suite pass.

## Validation

- Four copied native environment loader functions were removed.
- Duplicate synchronous database resolver bodies now delegate to `app.services.runtime_config`.
- Focused runtime, scan-first evaluation, YouTube hardening, retry, and recovery tests: 31 passed.
- Native yt-dlp operator check imported successfully; production `.venv-native` remains on yt-dlp 2026.06.09.
