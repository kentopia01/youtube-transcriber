# T072 - Runtime dependency refresh

## Status

Done

## Objective

Refresh the approved Anthropic and yt-dlp runtime baselines, and make the ARM64
web image install the embedding stack with the official CPU-only PyTorch wheel.

## In scope

- Raise the Anthropic baseline to `0.117.0` and yt-dlp to `2026.7.4`.
- Add a web-specific embedding extra so the web image does not install the
  unrelated transcription engine.
- Install PyTorch 2.11 from the official CPU wheel index in Docker images.
- Rebuild and validate the web image, run the default test suite, and verify
  native worker health after the quiet-queue restart.

## Out of scope

- Upgrading the native Torch 2.8, Torchaudio 2.8, TorchCodec 0.7, Pyannote,
  WhisperX, or host FFmpeg compatibility set.
- Upgrading Starlette beyond the project `<1.0.0` constraint.
- Queue topology, model, pipeline, or product behavior changes.

## Acceptance

- Development and native environments satisfy the new dependency floors.
- The web image has CPU-only Torch and no NVIDIA/CUDA packages.
- `pip check`, focused dependency tests, the default suite, and live service
  health checks pass.
- Existing native worker queue coverage remains healthy after restart.

## Validation

- Development, Python 3.14, and native environments pass `pip check` with
  Anthropic 0.117.0 and yt-dlp 2026.7.4.
- The rebuilt ARM64 web image passes `pip check`, imports the embedding stack,
  reports Torch 2.11.0+cpu, and contains no NVIDIA/CUDA packages.
- The default suite passes with `1263 passed, 12 skipped`.
- Web health passed after replacement, and all three native Celery workers used
  warm shutdown to finish active tasks before restarting successfully.
