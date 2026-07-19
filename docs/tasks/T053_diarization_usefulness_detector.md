# T053 - Diarization Usefulness Detector

## Status

done

## Objective

Add a cheap first-pass detector that records whether speaker labels are likely useful for a video, without putting full diarization back into the critical summary/report path.

## In Scope

- Add structured storage for the detector result on the pipeline job attempt.
- Add a deterministic v1 detector using title, channel, description, and transcript snippets.
- Run the detector after ASR has produced transcript text and segments.
- Preserve summary-first processing and explicit/operator-triggered diarization behavior.
- Add focused tests for the detector policy and transcribe persistence hook.

## Out of Scope

- Automatic background enqueue of deferred diarization.
- Full audio speaker-count probing.
- LLM-based diarization classification.
- UI controls for reviewing or overriding the decision.
- Remote GPU or hosted diarization integration.
- Video-level schema promotion; keep that for a quiet migration window after decision quality is proven.

## Acceptance

- Completed transcribe tasks persist a `diarization_decision` JSON blob and timestamp inside the pipeline job's structured metadata.
- Likely solo/tutorial/lecture videos classify as low-value speaker labels and skip diarization.
- Interview/podcast/panel/debate/guest/Q&A videos classify as high-value speaker labels and defer diarization.
- Ambiguous videos classify as review/uncertain rather than forcing full diarization.
- The default pipeline remains download -> transcribe -> cleanup -> summarize -> embeddings.
- Focused detector, transcribe-hook, and pipeline-regression tests pass.

## Validation

- Detector and transcribe persistence tests passed: `tests/test_diarization_decision.py`.
- Static model/migration contract remained green: `tests/test_migrations_contract.py`.
- Pipeline regression checks passed: `tests/test_pipeline_chain.py`, `tests/test_task_orchestration.py`, `tests/test_config.py`, `tests/test_jobs_retry.py`, and `tests/test_transient_auto_retry.py`.
- Focused validation total: 95 passed.
- Compile checks passed for changed Python files.
- `git diff --check` passed.
- Alembic still has a single head at `017`; T053 intentionally does not require a migration.
- Live rollout completed after the active queue drained: all three native workers were restarted and `scripts/worker_health.sh` confirmed coverage for `audio`, `diarize`, `post`, and `celery`.
