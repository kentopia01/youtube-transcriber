# T021 - Config model-name consolidation

## Status
Done — implementation and QA validation passed

## Objective
Consolidate model-name settings across app config and scripts so summary, cleanup, chat, persona, digest/report, and evaluation paths use documented canonical settings with safe deprecated aliases where needed.

## Why it matters
T016 identified model-setting drift: newer canonical fields such as `summary_model`, `cleanup_model`, and `chat_model` coexist with older `anthropic_*_model` fields, while different services/scripts read different names. That makes behavior hard to predict and easy to misconfigure.

## Source of truth
Read in order:
1. `AGENTS.md`
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. `docs/tasks/T016_full_project_engineering_audit.md`
6. this file

## In scope
- Define and document canonical model settings per use case.
- Preserve backward compatibility for existing/deployed `ANTHROPIC_*_MODEL` env vars where reasonable.
- Route app code to canonical settings or explicit compatibility properties.
- Cover these paths:
  - cleanup task
  - summarize task
  - chat / Telegram chat path
  - persona generation / refresh path
  - digest / overnight brief path
  - report/evaluation scripts that read model settings
- Add tests for defaults and env override behavior.
- Add/adjust docs/comments so operators know which env vars to use.
- Include a safe dry-run/command-level validation gate.

## Out of scope
- Do not change model vendors or model quality policy.
- Do not run live LLM calls.
- Do not mutate runtime DB, Redis, Celery, Telegram, reports, subscriptions, or videos.
- Do not remove backward-compatible aliases unless tests prove they are unused and docs are updated.
- Do not refactor unrelated pipeline logic.
- Do not clean up the broad dirty tree.

## Known starting points
- `app/config.py`
- `app/tasks/summarize.py`
- `app/tasks/cleanup.py`
- `app/services/chat.py`
- `app/telegram_bot.py`
- `app/services/digest.py`
- `app/tasks/generate_persona.py`
- report/eval/backfill scripts under `scripts/`
- config-related tests under `tests/`
- `.env.example` if present

## Required behavior
- Canonical fields should be clear, e.g. `summary_model`, `cleanup_model`, `chat_model`, `persona_model`, and optionally `digest_model`/`report_model` if those need to differ.
- Existing env vars like `ANTHROPIC_SUMMARY_MODEL`, `ANTHROPIC_CLEANUP_MODEL`, `ANTHROPIC_CHAT_MODEL`, and `ANTHROPIC_PERSONA_MODEL` should either remain supported as deprecated aliases or be documented as intentionally replaced with migration guidance.
- The same use case must not read two different model settings in different code paths unless explicitly documented.
- Tests must avoid network/LLM calls.

## Required dry-run / validation
Use safe commands only. Recommended minimum:

```bash
.venv/bin/python -m pytest <focused config/model tests> -q
.venv/bin/python -m pytest tests/test_chat.py tests/test_telegram_bot.py <focused config/model tests> -q
.venv/bin/python -m compileall -q app scripts tests
.venv/bin/python -m pytest --collect-only -q
# If a CLI supports dry-run/help, run it without live API calls and document output.
git diff --check -- <T021 touched files>
```

If a script cannot be dry-run safely, document why and cover it with unit/config tests instead.

## Acceptance criteria
- Canonical model settings are implemented/documented.
- Deprecated aliases are either supported safely or migration-documented.
- Summary/cleanup/chat/persona/digest/report paths read the intended settings consistently.
- Focused tests pass without live network calls.
- Safe dry-run/collect-only validation is recorded.
- QA validates before T021 is marked done.

## Implementation notes

Canonical model settings now live in `app.config.Settings` with per-use-case names:

| Use case | Canonical setting / env var | Default | Deprecated alias support |
|---|---|---|---|
| Transcript cleanup | `cleanup_model` / `CLEANUP_MODEL` | `codex` | `anthropic_cleanup_model` property + `ANTHROPIC_CLEANUP_MODEL` env |
| Pipeline summaries, report backfill, eval generation | `summary_model` / `SUMMARY_MODEL` | `codex` | `anthropic_summary_model` property + `ANTHROPIC_SUMMARY_MODEL` env |
| Web/Telegram chat | `chat_model` / `CHAT_MODEL` | `codex` | `anthropic_chat_model` property + `ANTHROPIC_CHAT_MODEL` env |
| Persona generation/refresh | `persona_model` / `PERSONA_MODEL` | `codex` | `anthropic_persona_model` property + `ANTHROPIC_PERSONA_MODEL` env |
| Morning digest | `digest_model` / `DIGEST_MODEL` | `codex` | `ANTHROPIC_SUMMARY_MODEL` env still feeds digest unless `DIGEST_MODEL` is set |

No separate `report_model` was added because report rendering does not make a fresh LLM call; report backfill/evaluation generation uses `summary_model`.

Routed paths:
- cleanup task → `settings.cleanup_model`
- summarize task and summarization service → `settings.summary_model`
- chat service and direct Telegram video Q&A → `settings.chat_model`
- persona derivation → `settings.persona_model`
- overnight digest → `settings.digest_model`
- scan-first backfill/eval scripts → `settings.summary_model`

Operator docs updated in `.env.example` and `README.md`; deprecated aliases remain supported but are documented as aliases, not preferred names.

## Validation evidence

Safe, non-live validation run locally:

- PASS: `.venv/bin/python -m pytest tests/test_config.py tests/test_model_config_paths.py tests/test_cleanup_task.py tests/test_chat.py tests/test_telegram_bot.py tests/test_scan_first_backfill_script.py tests/test_scan_first_eval_script.py -q` → `238 passed in 1.23s`
- PASS: `.venv/bin/python -m pytest tests/test_morning_digest.py tests/test_persona_service.py tests/test_persona_task_and_trigger.py tests/test_refresh_stale_personas.py tests/test_telegram_bot_channel_persona.py tests/test_telegram_callbacks.py tests/test_telegram_markdown.py tests/test_telegram_phase_a.py tests/test_weekly_digest.py -q` → `90 passed in 0.60s`
- PASS: `.venv/bin/python -m pytest tests/test_chat_toggle.py tests/test_telegram_notify.py -q` → `48 passed in 0.62s`
- PASS: `.venv/bin/python scripts/evaluate_scan_first_summaries.py --help` → help text printed; no Anthropic calls, DB writes, Redis/Celery/Telegram access, or file writes
- PASS: `.venv/bin/python scripts/backfill_scan_first_summaries.py --help` → help text printed; no Anthropic calls, DB writes, Redis/Celery/Telegram access, or file writes
- PASS: `.venv/bin/python -m compileall -q app scripts tests`
- PASS: `.venv/bin/python -m pytest --collect-only -q` → `1159 tests collected in 0.60s`
- PASS: `git diff --check -- .env.example README.md app/config.py app/services/chat.py app/services/digest.py app/services/persona.py app/services/summarization.py app/tasks/cleanup.py app/tasks/summarize.py app/telegram_bot.py tests/test_config.py tests/test_cleanup_task.py tests/test_chat.py docs/tasks/TASK_INDEX.md`
- PASS: explicit whitespace/final-newline check for untracked T021-touched files (`docs/tasks/T021_config_model_name_consolidation.md`, `tests/test_model_config_paths.py`, `scripts/backfill_scan_first_summaries.py`, `scripts/evaluate_scan_first_summaries.py`)

QA verdict: PASS.

QA confirmed no live LLM calls, DB writes, Redis/Celery, or Telegram mutations were observed in validation gates. Weekly digest has no LLM call.
