# T037: Global Search Source of Truth

## Status
Done

## Goal
Create the rollout contract for a first-class global corpus search feature across all ingested videos.

## In scope
- Update `docs/PLAN.md` with the global search direction.
- Update `docs/CLARIFICATIONS.md` with scope and guardrails.
- Update `docs/tasks/TASK_INDEX.md` with global search tasks.
- Add task files for implementation and follow-on chunks.

## Out of scope
- Replacing pgvector/Postgres.
- Changing existing chat retrieval behavior.
- Adding heavy local inference or reranker dependencies.

## Guardrails
- Keep global search separate from existing `/api/search`.
- Treat advanced retrieval features as follow-ons until v1 is measurable.

## Validation
- Docs and task index describe the intended sequence clearly.
- Implementation tasks have specific source-of-truth files.
