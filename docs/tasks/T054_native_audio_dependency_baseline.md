# T054 - Native audio dependency baseline

## Status

Done

## Objective

Make the native diarization worker dependency set internally consistent and reproducible for the host's existing Torch 2.8 / Python 3.13 runtime.

## In Scope

- Install the TorchCodec release compatible with Torch 2.8 and Python 3.13.
- Provide a supported FFmpeg shared-library runtime for that TorchCodec release without replacing the host's default FFmpeg 8 CLI.
- Export the versioned FFmpeg library path from the native worker startup script.
- Document the native compatibility pins and validate imports, dependency metadata, focused diarization tests, and worker health.

## Out of Scope

- Upgrading Torch, pyannote, WhisperX, or the host's default FFmpeg.
- Changing diarization policy, models, queue topology, or pipeline behavior.
- Removing the existing in-memory torchaudio fallback.

## Acceptance

- `pip check` reports no broken native requirements.
- TorchCodec imports with Torch 2.8 and can construct its decoder API.
- The existing FFmpeg 8 command remains the default CLI.
- Native workers receive the compatible FFmpeg shared-library path.
- Focused diarization tests pass and worker queue coverage remains healthy after a quiet-queue restart.

## Validation

- Installed `torchcodec==0.7.0`, the supported line for the existing `torch==2.8.0` and Python 3.13 runtime.
- Installed keg-only Homebrew FFmpeg 7 shared libraries; the default `ffmpeg` command remains FFmpeg 8.1.2.
- TorchCodec and `AudioDecoder` import successfully when using `/opt/homebrew/opt/ffmpeg@7/lib`.
- `pip check` reports no broken requirements.
- Focused diarization validation passed: 23 tests.
- `bash -n scripts/start_worker.sh` and `git diff --check` passed.
- The queue was empty before restart, and post-restart worker health confirmed coverage for `audio`, `diarize`, `post`, and `celery`.
