# AGENTS.md - youtube-transcriber repo rules

This repo has already burned time on worker drift, vague implementation, and UI-first detours.
Treat this file as the repo-specific execution contract.

## Source of truth

For any serious implementation, read and follow these in order:
1. `AGENTS.md` (this file)
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. the active task file in `docs/tasks/`

If they conflict, prefer the more specific file closest to the active task.

## Core rule

Do not widen scope.
Do not "improve" adjacent areas unless the task explicitly requires it.
Do not substitute polish for the core objective.

## Repo execution doctrine

### 1. Data contract before UI
For this repo, operator-facing UI is downstream of pipeline state.
If the task is about execution, retry, recovery, observability, or worker health:
- implement the structured fields first
- add tests second
- only then add minimal UI exposure

Do not spend major time polishing templates before the underlying contract exists.

### 2. Stability before throughput
Never use concurrency or queue changes as a shortcut for correctness.
For this repo:
- stabilize retry/resume/recovery first
- add observability next
- only then do queue splitting / throughput work

### 3. Resume must be artifact-aware
Never resume into a stage whose required inputs are missing.
If upstream artifacts are missing, step back to the earliest safe stage.

### 4. Recovery must be bounded
No endless retry churn.
Repeated identical failures must converge toward containment, quarantine, or manual review.

### 5. Health must distinguish busy from dead
Long diarization/alignment work is normal.
Do not classify a worker as unhealthy just because it is busy on a long stage.

## Required implementation behavior

### Before editing
- restate the exact task objective privately in your working notes
- identify what is explicitly out of scope
- inspect the current code path before changing it

### During implementation
- keep changes narrow
- prefer structured fields over freeform progress-message inference
- preserve existing working behavior unless the task explicitly replaces it
- avoid drive-by refactors

### Before claiming done
You are not done until all of these are true:
- the task file done criteria are satisfied
- relevant tests pass
- obvious runtime/migration steps are identified
- docs are updated if the source of truth changed

## Stop conditions

Stop and report instead of drifting when:
- the task is underspecified
- the repo docs conflict
- a new direction would require widening scope
- you find yourself mostly editing templates/CSS for a backend or observability task

## T008-specific rule

T008 is not a queue UI task.
Priority order is:
1. attempt creation reason
2. worker / host identity
3. last artifact-check result
4. stage timing that helps triage
5. busy-vs-unhealthy worker health logic
6. minimal operator-facing exposure only after 1-5 exist

## Doc drift policy

Stale docs are dangerous.
If a file is no longer current, do one of these:
1. archive it under `docs/archive/YYYY-MM-DD/`
2. replace the live file with a short superseded stub that points to the real source of truth

Do not leave ambiguous historical docs in active paths.

## What good looks like in this repo

A good change in `youtube-transcriber`:
- fixes one pipeline risk at a time
- leaves behind structured evidence
- improves operator clarity
- reduces retry/recovery ambiguity
- makes the next phase safer instead of noisier
