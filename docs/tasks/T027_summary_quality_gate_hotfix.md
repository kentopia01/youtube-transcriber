# T027 - Summary quality gate hotfix

## Status
Done

## Objective
Stop recent substantive YouTube videos from failing permanently at the summarize stage when the structured JSON brief response cannot be normalized into the markdown report contract.

## Scope
- Keep the T026 quality gate in place.
- Change the repair pass after a failed structured brief so it asks Claude for the final markdown report contract directly.
- Preserve the required report headings and depth requirements.
- Fix the chunked consolidation prompt formatting hazard caused by JSON braces in the structured prompt contract.
- Rerun only the current failed summarize-stage jobs after the worker is restarted.

## Out of scope
- Download/transcription/diarization changes.
- Queue topology changes.
- Bulk historical backfill.
- Relaxing the report quality bar into teaser summaries.

## Verification
- Focused tests for summarization prompt/config paths.
- Runtime retry of the 3 current failed summarize-stage jobs.
