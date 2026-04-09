# T012 - Worker topology rollout and throughput validation

## Status
Done

## Objective
Roll out the split worker topology safely on the current Mac mini and validate that it improves throughput without destabilizing the pipeline.

## Why it matters
Even with correct queue routing and dispatch, the actual worker topology and concurrency caps determine whether the box stays stable. This chunk is where the repo turns the new design into a controlled operational rollout.

Verified rollout as of 2026-04-09:
- queue routing targets `audio`, `diarize`, and `post`
- worker startup is parameterized and launchd now runs a split topology:
  - `native-audio-worker@%h` on `audio`
  - `native-diarize-worker@%h` on `diarize`
  - `native-post-worker@%h` on `post,celery`
- launchd worker restart + Celery queue inspection proved the intended queues are covered directly by the native split workers
- launchd PATH handling was fixed so ffmpeg/ffprobe are available to the audio worker
- real manual submissions completed successfully on the routed worker path
- practical overlap was verified: one job reached `diarize` on `native-diarize-worker@mac.lan` while another simultaneously ran `transcribe` on `native-audio-worker@mac.lan`

## Scope
- Fix and document launch / worker topology for `audio`, `diarize`, and `post` lanes.
- Set conservative initial concurrency caps appropriate for current hardware.
- Add operator-facing checks or validation steps for:
  - queue health
  - stage distribution
  - backlog movement
  - signs of starvation or resource contention
  - actual queue consumption by the launched workers
- Validate whether the split topology improves practical throughput for the target workload mix.
- Document rollback and safe fallback behavior.

## Out of scope
- Autoscaling or multi-machine scheduling.
- Aggressive concurrency tuning without evidence.
- New product features unrelated to throughput validation.

## Constraints
- Treat the current Apple M4 / 16 GB host as the deployment target.
- Default to single-concurrency for heavy queues unless evidence justifies more.
- Prefer reversible worker-topology changes.
- Do not claim rollout complete until queue inspection proves the workers are consuming the intended lanes.

## Done criteria
- Worker topology is documented and operational for the split queues.
- Initial concurrency caps are conservative and explicit.
- `celery inspect active_queues` or equivalent operator proof shows the launched workers are consuming the intended queues.
- Validation shows throughput improvement without reliability regression.
- Rollback steps are documented and credible.
+
+## Rollback
+If the split topology regresses in production, fall back to the single-worker topology:
+1. Boot out `com.sentryclaw.yt-worker-audio` and `com.sentryclaw.yt-worker-diarize`.
+2. Change `com.sentryclaw.yt-worker.plist` so `CELERY_QUEUES=audio,diarize,post,celery` and set a single hostname.
+3. Bootstrap or kickstart `com.sentryclaw.yt-worker`.
+4. Verify queue coverage with `python -c 'from app.tasks.celery_app import celery; print(celery.control.inspect(timeout=5).active_queues())'`.
+5. Confirm health with `bash scripts/worker_health.sh --quiet`.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.
- Operational proof completed on 2026-04-09:
  - `active_queues` confirmation for `native-audio-worker@mac.lan`, `native-diarize-worker@mac.lan`, and `native-post-worker@mac.lan`
  - worker health script updated and passing against required queue coverage
  - real manual routed-job smoke tests succeeded after launchd rollout
  - concurrent stage overlap observed with one job in `diarize` and another in `transcribe` on separate workers
