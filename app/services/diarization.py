"""Speaker diarization service using pyannote.audio.

Identifies who speaks when in an audio file. Runs on CPU
(pyannote supports CPU, no CUDA required).
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


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
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )

    # Build kwargs for speaker hints
    kwargs: dict = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers

    diarization = pipeline(audio_path, **kwargs)

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
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
