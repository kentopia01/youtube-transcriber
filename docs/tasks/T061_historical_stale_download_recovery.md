# T061 - Historical Stale Download Recovery

## Status

Done

## Objective

Resolve the 22 visible April pipeline failures that were reaped as stale during
the earlier download-worker incident, without flooding the now-healthy queue or
retrying videos that are no longer available or useful.

## Current Evidence

- All 22 jobs failed in the download stage with `recovery_status=stale_reaped`.
- None has a newer pipeline attempt.
- None is in manual review.
- A separate visible failure is an intentional 609-minute duration-limit rejection and is not part of this recovery set.
- The current queue is empty and recent unattended pipeline jobs complete cleanly.
- Metadata probing categorized 11 items as short-form and 11 as available
  long-form. One long-form item is an older duplicate of a fixed-audio re-upload.
- All ten approved long-form retries passed download and completed successfully.
- The active pipeline count returned to zero after the bounded release.

## Proposed Sequence

1. Export the exact 22 YouTube IDs and titles for operator review.
2. Probe availability and duration without downloading full media.
3. Exclude private, unavailable, short-form, duplicate, or no-longer-useful items.
4. Dry-run attempt allocation and artifact-aware resume for approved items.
5. Enqueue a bounded batch, observe completion/failure, then decide whether to release the remainder.

## Guardrails

- Do not bulk retry all 22 without explicit operator approval.
- Preserve the configured duration limit and long-form subscription policy.
- Use the shared pipeline attempt factory and commit-before-publish boundary.
- Stop on a recurring download/provider failure pattern.
- Do not use authenticated cookies unless T034's evidence gate is separately met.

## Done Criteria

- Every stale item is explicitly categorized as recovered, unavailable, intentionally skipped, or still failed with a current reason.
- Retried items use new attempts; historical failures remain preserved for audit.
- Queue and worker health remain green throughout bounded release.
