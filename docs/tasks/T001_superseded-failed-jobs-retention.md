# T001 - Superseded failed jobs hidden by default + 14-day retention cleanup

## Status
Done

## Objective
Hide superseded failed jobs from the default failed-job UI and add cleanup for hidden superseded failed jobs older than 14 days.

## Why it matters
Retry and re-submit flows were cluttering the queue with stale failed attempts. Operators should see actionable failures, not historical noise.

## Scope
- Add explicit job visibility metadata for superseded failed jobs.
- Hide superseded failed jobs in dashboard and queue failed-job views.
- Mark older failed attempts as superseded when a new retry or failed-video re-submit creates a replacement job.
- Add a dry-run-friendly cleanup script for hidden superseded failed jobs older than 14 days.
- Preserve non-failed ingestion dedupe behavior.

## Constraints
- No unrelated repo cleanup.
- Keep the implementation production-safe and minimal in scope.
- Do not change non-failed existing-video dedupe behavior.
- Validate with focused tests and QA review.

## Done criteria
- Retry path hides prior failed jobs for the same video.
- Failed-video re-submit hides prior failed jobs for the same video.
- Default failed-job UI excludes hidden superseded failed jobs.
- Cleanup targets only hidden superseded failed jobs older than 14 days.
- Dry-run is supported.
- QA confirms no regression in non-failed existing-video dedupe.

## Evidence summary
- Build implementation added explicit visibility fields, helper logic, migration, cleanup script, and focused tests.
- QA validated behavior and fixed one operational defect in cleanup script exit codes.

## Rollout notes
1. Run migration.
2. Run cleanup script in dry-run mode.
3. Review output.
4. Run real cleanup.
5. Enable scheduled cleanup only after dry-run review.
