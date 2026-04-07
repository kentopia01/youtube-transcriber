# T002 - Native ops path, cleanup scheduling, and README rollout notes

## Status
Done

## Objective
Make native maintenance commands work cleanly on the host, repair the broader local test environment, enable scheduled cleanup for hidden superseded failed jobs, and document the workflow in the repo README.

## Why it matters
The feature is implemented, but the operational path still has sharp edges: host-native Alembic needed manual DB overrides, broader tests were missing dependencies, scheduled cleanup was not yet enabled, and rollout knowledge was still living in chat.

## Scope
- Add a clean native wrapper for Alembic migrations.
- Add a clean native wrapper for hidden superseded failed job cleanup.
- Repair the local venv verification path so broader tests run.
- Enable a scheduled cleanup job.
- Document rollout and maintenance commands in `README.md`.

## Out of scope
- Broad refactors unrelated to this workflow.
- Replacing the existing stale-job reaper.
- Reworking Docker DB host conventions for containerized paths.

## Constraints
- Preserve existing container behavior.
- Do not perform real cleanup deletions during validation unless explicitly intended.
- Keep the implementation minimal and operator-friendly.

## Done criteria
- Native Alembic path works without manual localhost override.
- Hidden superseded failed jobs cleanup has a native wrapper and scheduled job.
- Broader local tests run after venv repair.
- README documents rollout, dry-run, real cleanup, and scheduled cleanup.
- Changes are verified before commit.

## Validation
- Run targeted and broader tests.
- Verify wrapper scripts execute.
- Verify cron job is created with the expected command payload.
