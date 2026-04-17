"""Speaker diarization service using pyannote.audio.

Identifies who speaks when in an audio file. Uses Apple Metal (MPS) when
available, with graceful CPU fallback. The pyannote pipeline is cached
per-process so repeated invocations in a worker avoid the 5-10s reload cost.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.services.device import get_torch_device

logger = structlog.get_logger()

# Pipeline cache keyed by HF token. Workers are single-tenant in practice,
# so this is typically a single entry, but keying by token keeps behaviour
# correct if multiple credentials are ever used in one process.
_pipeline_cache: dict[str, Any] = {}


def _reset_caches() -> None:
    """Clear the pipeline cache. Intended for tests."""
    _pipeline_cache.clear()


def _load_audio_for_pyannote(audio_path: str) -> dict:
    """Load audio into-memory for pyannote when torchcodec decoding is unavailable."""
    import torchaudio

    waveform, sample_rate = torchaudio.load(audio_path)
    return {"waveform": waveform, "sample_rate": sample_rate}


def _iter_diarization_tracks(diarization_result):
    """Yield diarization tracks across pyannote output formats.

    pyannote<4 returns an Annotation directly (has ``itertracks``).
    pyannote>=4 returns a DiarizeOutput wrapper with annotation fields.
    """
    if hasattr(diarization_result, "itertracks"):
        return diarization_result.itertracks(yield_label=True)

    for attr in ("exclusive_speaker_diarization", "speaker_diarization"):
        annotation = getattr(diarization_result, attr, None)
        if annotation is not None and hasattr(annotation, "itertracks"):
            return annotation.itertracks(yield_label=True)

    raise TypeError(
        f"Unsupported diarization output type: {type(diarization_result)!r}"
    )


def _get_pipeline(hf_token: str):
    """Load (or return cached) pyannote diarization pipeline on the best device."""
    if hf_token in _pipeline_cache:
        return _pipeline_cache[hf_token]

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=hf_token,
    )

    device = get_torch_device()
    if device != "cpu":
        try:
            import torch

            pipeline = pipeline.to(torch.device(device))
            logger.info("diarization_device_set", device=device)
        except Exception as exc:
            logger.warning(
                "diarization_device_fallback",
                device=device,
                error=str(exc),
                msg="Falling back to CPU for diarization",
            )

    _pipeline_cache[hf_token] = pipeline
    return pipeline


def diarize(
    audio_path: str,
    hf_token: str,
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[dict]:
    """Run speaker diarization on an audio file.

    Args:
        audio_path: Path to the audio file (WAV recommended).
        hf_token: HuggingFace access token for pyannote models.
        num_speakers: Exact number of speakers (if known).
        min_speakers: Minimum expected speakers.
        max_speakers: Maximum expected speakers.

    Returns:
        List of dicts: [{"start": float, "end": float, "speaker": str}, ...]
    """
    logger.info("diarization_starting", audio=audio_path)

    pipeline = _get_pipeline(hf_token)

    # Build kwargs for speaker hints
    kwargs: dict = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers

    try:
        diarization = pipeline(audio_path, **kwargs)
    except Exception as exc:
        if "AudioDecoder" not in str(exc):
            raise

        logger.warning(
            "diarization_audio_decoder_missing",
            error=str(exc),
            msg="Falling back to in-memory torchaudio decode",
        )
        diarization = pipeline(_load_audio_for_pyannote(audio_path), **kwargs)

    segments = []
    for turn, _, speaker in _iter_diarization_tracks(diarization):
        segments.append({
            "start": turn.start,
            "end": turn.end,
            "speaker": speaker,
        })

    # Sort by start time
    segments.sort(key=lambda s: s["start"])

    # Collect unique speakers
    speakers = sorted(set(s["speaker"] for s in segments))

    logger.info(
        "diarization_complete",
        segments=len(segments),
        speakers=len(speakers),
        speaker_list=speakers,
    )

    return segments
