# T003 - Fix CI template failure and diarization runtime bug, then retry the 3 requested videos

## Status
Done

## Objective
Repair the current GitHub Actions unit-test failure, fix the diarization runtime bugs causing `AudioDecoder` failures and `DiarizeOutput.itertracks` compatibility failures, and retry the 3 previously requested YouTube transcription jobs.

## Why it matters
The repo is currently red on GitHub CI and the three user-requested video ingests did not complete. We need the code path healthy in both CI and runtime before calling the workflow fixed.

## Scope
- Identify and fix the current GitHub Actions failure on `main`.
- Identify and fix the diarization/runtime error `name 'AudioDecoder' is not defined`.
- Identify and fix the follow-on diarization compatibility error `'DiarizeOutput' object has no attribute 'itertracks'`.
- Re-run verification locally.
- Retry the three previously failed video jobs after the fix.
- Confirm the jobs move to successful completion or surface any remaining exact blocker.

## Out of scope
- Unrelated repo cleanup.
- Broad refactors outside the failing CI/runtime paths.
- New feature work unrelated to search/templates or diarization runtime.

## Constraints
- Keep changes surgical.
- Work against the current repo state without scooping unrelated dirty changes into the fix.
- Do not claim success until GitHub CI is green or the remaining exact blocker is known.

## Done criteria
- GitHub CI failure root cause is fixed locally and pushed in a clean surgical commit.
- Diarization path no longer fails with `AudioDecoder` undefined.
- Diarization path no longer fails with `DiarizeOutput.itertracks` compatibility mismatch.
- Relevant tests pass locally.
- The three requested video jobs are retried.
- Result reports whether all three ultimately completed.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.
- Final report must include the three video URLs or IDs and their resulting job states.

## Outcome
- GitHub/local test environment issue was resolved, including the missing `.venv314` dependency drift that was blocking broad pytest collection.
- The diarization path no longer fails on `AudioDecoder` or `DiarizeOutput.itertracks` for the three originally requested retries.
- All three requested failed videos were retried and completed successfully.
