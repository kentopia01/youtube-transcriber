# Pipeline Reliability Fixes -- Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/tasks/helpers.py` | **New** — shared `get_latest_pipeline_job()` helper that queries `ORDER BY created_at DESC` |
| `app/tasks/download.py` | Use `get_latest_pipeline_job()` instead of `.first()` |
| `app/tasks/transcribe.py` | Use latest job helper; upsert transcription (update if exists, delete old segments) |
| `app/tasks/diarize.py` | Use `get_latest_pipeline_job()` |
| `app/tasks/cleanup.py` | Use `get_latest_pipeline_job()` |
| `app/tasks/summarize.py` | Use latest job helper; upsert summary; add `max_retries=2` with exponential backoff |
| `app/tasks/embed.py` | Use latest job helper; DELETE old chunks before insert; add `max_retries=2` with exponential backoff |
| `app/tasks/pipeline.py` | Extract `PIPELINE_STEPS` list; add `run_pipeline_from(video_id, start_from)` for partial chains; `run_pipeline()` delegates to it |
| `app/routers/jobs.py` | Smart retry: `_detect_resume_point()` checks existing transcription/summary/embeddings; calls `run_pipeline_from()` |
| `app/routers/videos.py` | Allow resubmission of failed videos (reset status, create new job) |
| `tests/test_jobs_retry.py` | Updated for smart retry (mock `run_pipeline_from`, handle extra DB queries) |
| `tests/test_pipeline_chain.py` | Added `TestPipelineFromPartialChain` (3 tests: resume from diarize, embed-only, invalid step) |
| `README.md` | Added "Pipeline Retry Behavior" section documenting smart retry and idempotency |

## Why
- Retry was restarting the full pipeline, wasting time and crashing on UniqueViolation
- Tasks updated the wrong (first) job instead of the latest retry job
- No idempotency guards on transcription, summary, or embedding inserts
- Failed videos couldn't be resubmitted
- Summarization and embedding had no transient-failure retry

## Risks
- `_detect_resume_point` uses async queries; the retry endpoint now makes 3 extra SELECT queries (one each for embeddings, summary, transcription). Minimal performance impact since these are indexed lookups by video_id.
- `DELETE` before insert in embed.py means a crash mid-insert loses old embeddings. Acceptable since the task will retry.
- Exponential backoff on summarize/embed means a truly broken API key will take ~30s longer to fail permanently.

## Plan Deviations
- None. All planned steps completed.
