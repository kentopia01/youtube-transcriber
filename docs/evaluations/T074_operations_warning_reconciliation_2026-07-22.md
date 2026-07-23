# T074 Operations warning reconciliation — 2026-07-22

## Outcome

The live warning total fell from eight to two by repairing or explicitly resolving
deterministic state defects. The two remaining warnings are genuine Telegram report-
delivery failures and retain their evidence; no blind redelivery was attempted.

| Warning group | Before | After | Disposition |
|---|---:|---:|---|
| Stale channel batches | 4 | 0 | Dry-run preview, then reconciled missing/failed child outcomes |
| Visible failed jobs | 1 | 0 | Dismissed with the 609-minute versus 150-minute policy reason |
| Subscription polling | 1 | 0 | Upcoming live events now defer and polling continues; counter reset explicitly |
| Report delivery | 2 | 2 | Preserved with Telegram failure reason and explicit verification/redelivery action |

The structured Operations contract now provides a title, detail, reason, timestamp,
next action, and resource metadata for each warning. Its displayed count is derived
from the same warning collection.

## Root cause evidence

The subscription poll had encountered upcoming premieres/live events. The classifier
failed open after `yt-dlp` reported that the event had not begun, and submission then
failed, preventing later candidates from being considered. The classifier now emits a
`retry_later` result for live/upcoming metadata and known premiere errors; pollers leave
those IDs unseen, continue the scan, and clear failure state after an otherwise
successful poll.

The four stale channel batches predated reliable child-job accounting. Reconciliation
is intentionally dry-run-first and only changes stale batches: missing planned children
count as failures, empty batches become failed, and mixed outcomes become
`completed_with_errors`.
