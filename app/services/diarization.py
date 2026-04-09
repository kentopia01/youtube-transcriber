"""Speaker diarization service using pyannote.audio.

Identifies who speaks when in an audio file. Runs on CPU
(pyannote supports CPU, no CUDA required).
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


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
    from pyannote.audio import Pipeline

    logger.info("diarization_starting", audio=audio_path)

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=hf_token,
    )

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
