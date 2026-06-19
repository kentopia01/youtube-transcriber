# T029 - Controlled Download 403 Recovery

## Status
Done

## Objective
Retry the seven 2026-06-19 download-stage 403 failures under the patched downloader without creating unbounded retry churn.

## Scope
- Add a guarded operator script for failed download-stage 403 retries.
- Dry-run the exact failed YouTube IDs.
- Apply one retry first, verify it clears download, then release the rest.

## Out of scope
- Retrying unrelated failed jobs.
- Changing subscription polling behavior.
- Login or authenticated-cookie setup.

## Done criteria
- Retry script reuses normal attempt allocation and commit-before-publish enqueue.
- Dry-run shows exactly the intended failed jobs.
- Controlled retry is executed and monitored.

## Validation
- Dry-run planned the seven intended jobs.
- One job was applied first and reached `transcribe`, proving the patched download path cleared the failed stage.
- The remaining six jobs were queued under normal pipeline guardrails.
- Worker health passed after enqueue.
