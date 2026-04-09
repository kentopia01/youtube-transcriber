# T004 - Pipeline stabilization Phase 1: attempt model, one-active-attempt guard, and artifact-aware resume

## Status
In Progress

## Objective
Stabilize the ingestion pipeline so retries/resumes stop creating confusing superseding attempts and do not resume into stages whose required artifacts are missing.

## Why it matters
Current failures show that the pipeline can:
- create chains of superseded jobs for the same video
- resume from diarization when the required audio artifact is already gone
- represent job state unclearly enough that operators cannot trust the current attempt story

Phase 1 is meant to stop the most damaging behavior before deeper throughput work.

## Scope
- Add stronger attempt tracking for jobs.
- Enforce one active attempt per video.
- Make retry/resume planning artifact-aware, especially for audio existence before diarization.
- Stop immediate audio deletion from causing guaranteed retry failure.
- Keep changes surgical and focused on stability, not speed.

## Out of scope
- Parallel worker architecture
- Multi-queue throughput redesign
- Broad UI redesign
- Large refactors unrelated to retry/resume stability

## Constraints
- Preserve existing successful pipeline behavior where possible.
- Do not mix unrelated repo cleanup into this phase.
- Prefer recoverable changes and explicit lineage over clever implicit heuristics.

## Done criteria
- A video cannot accumulate multiple simultaneous active attempts.
- Retry/resume logic checks required artifacts before choosing a resume stage.
- Diarization is not resumed when audio is missing.
- Audio lifecycle is made safe for retryable execution.
- Tests cover the new attempt/resume rules.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.
- Report should call out any remaining edge cases deferred to later phases.
