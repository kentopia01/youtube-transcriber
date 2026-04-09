# T008 - Pipeline observability and attempt reasoning

## Status
Planned

## Objective
Make pipeline triage easy by recording enough structured state to explain what is running, why a retry exists, what artifacts were checked, and whether a worker is healthy or just busy.

## Why it matters
Phases 1 to 3 made the pipeline safer, but debugging still depends too much on inference. Without stronger observability, future failures will be harder to diagnose and throughput changes will be riskier.

## Scope
- Add per-stage start/end timestamps where they are still missing.
- Record why an attempt was created, for example user retry, stale recovery, manual resubmit, or operator action.
- Record worker id / host id for active attempts when available.
- Record the last artifact-check result used by resume/recovery logic.
- Improve worker health reporting so long-running diarization can be recognized as busy-but-healthy instead of simply dead.
- Expose the new observability fields in operator-facing views or APIs where they materially help triage.

## Out of scope
- Queue splitting or concurrency changes.
- Broad UI redesign beyond targeted operator-facing exposure.
- Reworking the core retry model from Phases 1 to 3.

## Constraints
- Build on the current attempt/stage model instead of replacing it.
- Prefer structured fields over parsing freeform progress messages.
- Keep storage and UI additions narrow and purposeful.

## Done criteria
- Operators can explain why a given attempt exists without reconstructing history from logs.
- Active attempts expose enough structured worker/activity metadata to distinguish busy vs unhealthy in common cases.
- Resume/recovery decisions leave behind an inspectable artifact-check trail.
- Tests cover the new observability fields and worker-health behavior.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.

## Notes
- This is the next phase after T007.
- Throughput work should not start until this observability layer is in place.
- Read `AGENTS.md` before implementing. T008 must not drift into queue UI polish before the structured observability contract exists.
