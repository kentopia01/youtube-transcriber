# T063 - Reader and Operations Workspace Epic

## Status

Done — all child tasks completed and release-gated on 2026-07-21

## Objective

Split the web experience into a reading-first Reader product and an operational
Operations product while preserving one repository, backend, database,
authentication boundary, and deployment.

## Why it matters

The current dashboard mixes ingestion, monitoring, search, chat, and content
consumption. Returning readers need a calm place to continue and understand
transcripts, while operators need dense, truthful state and recovery controls.
Separate workspaces reduce cognitive load without prematurely duplicating the
platform.

## Target architecture

- Reader owns `/`, `/read`, `/read/{video_id}`, reader library state,
  annotations, and reader-facing Search/Ask.
- Operations owns `/ops`, queue/job health, submission, channels/subscriptions,
  report delivery, and usage.
- A workspace switcher connects the two products.
- Shared services continue to own videos, transcripts, summaries, embeddings,
  chat/RAG, jobs, workers, reports, and configuration.
- Reader and Operations use separate base templates and frontend entrypoints,
  with shared design tokens, accessible primitives, security utilities, and APIs.

## Execution sequence

1. T064 — Operations truth and dashboard contract.
2. T065 — Workspace route/layout boundary.
3. T066 — Reader state and transcript content contract.
4. T067 — Transcript Reader MVP.
5. T068 — Reader Home and reading library.
6. T069 — Reader annotations and notebook.
7. T070 — Document intelligence and Search/Ask consolidation.
8. T071 — Frontend production and accessibility release gate.

## Scope

- Define product ownership, route namespaces, navigation, and compatibility.
- Preserve one deployment while creating code boundaries that permit later
  extraction.
- Incorporate the dashboard QA findings into the Operations sequence.
- Incorporate Kindle/Kobo-style reading comfort, progress, navigation, and
  annotation patterns into the Reader sequence.
- Require responsive, keyboard, and accessibility acceptance per child task.

## Out of scope

- Separate Reader and Operations deployments.
- A new frontend framework solely for the split.
- Public or multi-tenant Reader access.
- Native mobile applications.
- Ebook/EPUB ingestion.
- Automatic deferred diarization or unrelated pipeline changes.

## Constraints

- Data contracts before dependent UI.
- Existing completed transcripts open without mandatory backfill or LLM calls.
- Reader actions never alter pipeline lifecycle state.
- Existing URLs remain compatible during the migration.
- Preserve the current local trust boundary; T049 governs future scoped users.
- Coordinate T066 reader ownership with T049 so reader state does not introduce
  a competing identity model.
- T061 remains the current in-progress runtime/recovery task until separately
  completed.

## Done criteria

- T064-T071 are completed and independently validated.
- Reader and Operations have distinct routes, layouts, navigation, and browser
  coverage within the shared application.
- Reader Home is the default daily-use entry point.
- Operations provides truthful health and recovery state.
- Existing completed transcripts support comfortable reading, progress, and
  knowledge-capture workflows.
- Compatibility routes and rollout steps are documented and tested.
- No separate deployment is required to operate the completed release.

## Validation

- T064-T071 are implemented and QA-validated against their task files.
- Final validation passed `1350 passed, 11 skipped`, `33/33` live HTTP checks,
  and `30/30` desktop/mobile browser checks.
- Live schema is at Alembic `021`; default release QA remained non-mutating.

## Notes

- Source context: `docs/PLAN.md` and `docs/CLARIFICATIONS.md`.
- This file is the parent contract; child task files are more specific when work
  is active.
