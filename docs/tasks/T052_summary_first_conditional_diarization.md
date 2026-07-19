# T052 - Summary-First Conditional Diarization

## Status

done

## Objective

Shorten first-pass ingest by making diarization opt-in for the inline pipeline, so videos can reach cleanup, summary, embeddings, and report delivery before speaker labeling.

## In Scope

- Add a `DIARIZATION_MODE` config switch.
- Preserve the current full chain when `DIARIZATION_MODE=inline`, `DIARIZATION_ENABLED=true`, and `HF_TOKEN` is present.
- Default first-pass runs to summary-first behavior that skips `tasks.diarize_and_align`.
- Keep explicit resume from `tasks.diarize_and_align` available for operator-triggered speaker labeling.
- Update artifact-aware resume planning so transcript-only jobs resume at cleanup when inline diarization is not required.
- Update focused pipeline/config/retry tests.

## Out of Scope

- New database schema for diarization status.
- Automatic deferred diarization scheduler.
- Remote GPU or hosted diarization integration.
- UI changes for per-video speaker-label controls.

## Acceptance

- Default pipeline chain runs download -> transcribe -> cleanup -> summarize -> embeddings.
- Inline mode still runs download -> transcribe -> diarize -> cleanup -> summarize -> embeddings.
- Resume planning does not force audio re-download just for diarization unless inline mode is enabled.
- Focused pytest coverage passes.

## Validation

- `tests/test_pipeline_chain.py`, `tests/test_task_orchestration.py`, `tests/test_config.py`, `tests/test_jobs_retry.py`, and `tests/test_transient_auto_retry.py` passed: 70 passed.
- Web container and native worker topology were restarted after code changes.
- Native worker health check reports required queues covered.
