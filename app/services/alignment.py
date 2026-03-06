"""Forced alignment and speaker merge service.

Uses whisperX for word-level alignment, then maps each transcript segment
to the speaker who covers the most time in that segment (majority vote).
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


def align_and_merge(
    audio_path: str,
    transcript_segments: list[dict],
    diarization_segments: list[dict],
    language: str,
) -> list[dict]:
    """Align transcript segments with diarization and assign speakers.

    Uses whisperX forced alignment for word-level timestamps, then maps
    each word/segment to the overlapping diarization speaker via majority vote.

    Args:
        audio_path: Path to the audio file.
        transcript_segments: From whisper: [{"start", "end", "text", "confidence"}, ...]
        diarization_segments: From pyannote: [{"start", "end", "speaker"}, ...]
        language: Detected language code (e.g., "en").

    Returns:
        Updated segments with speaker labels:
        [{"start", "end", "text", "confidence", "speaker"}, ...]
    """
    if not diarization_segments:
        logger.warn("no_diarization_segments", msg="No diarization data, skipping alignment")
        return [
            {**seg, "speaker": None}
            for seg in transcript_segments
        ]

    # Try whisperX forced alignment for better word-level timestamps
    aligned_segments = _try_whisperx_alignment(audio_path, transcript_segments, language)

    # Map each segment to the most likely speaker
    result = []
    for seg in aligned_segments:
        speaker = _find_speaker(seg["start"], seg["end"], diarization_segments)
        result.append({
            **seg,
            "speaker": speaker,
        })

    # Log summary
    speakers_found = set(s["speaker"] for s in result if s["speaker"])
    logger.info(
        "alignment_complete",
        segments=len(result),
        speakers_assigned=len(speakers_found),
    )

    return result


def _try_whisperx_alignment(
    audio_path: str,
    segments: list[dict],
    language: str,
) -> list[dict]:
    """Try to use whisperX for forced alignment. Falls back to original segments."""
    try:
        import whisperx
        import torch

        device = "cpu"
        audio = whisperx.load_audio(audio_path)

        # whisperX expects segments in a specific format
        whisperx_segments = [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in segments
        ]

        model_a, metadata = whisperx.load_align_model(
            language_code=language,
            device=device,
        )

        result = whisperx.align(
            whisperx_segments,
            model_a,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )

        # Map back to our format
        aligned = []
        for seg in result.get("segments", []):
            aligned.append({
                "start": seg.get("start", 0.0),
                "end": seg.get("end", 0.0),
                "text": seg.get("text", "").strip(),
                "confidence": seg.get("avg_logprob", 0.0),
            })

        if aligned:
            logger.info("whisperx_alignment_success", segments=len(aligned))
            return aligned

    except Exception as exc:
        logger.warn(
            "whisperx_alignment_failed",
            error=str(exc),
            msg="Falling back to original segment timestamps",
        )

    return segments


def _find_speaker(
    start: float,
    end: float,
    diarization_segments: list[dict],
) -> str | None:
    """Find the speaker with the most overlap for a given time range.

    Uses majority-vote: the speaker who covers the most time in the
    [start, end] interval wins.
    """
    speaker_overlap: dict[str, float] = {}

    for dseg in diarization_segments:
        # Calculate overlap
        overlap_start = max(start, dseg["start"])
        overlap_end = min(end, dseg["end"])
        overlap = max(0.0, overlap_end - overlap_start)

        if overlap > 0:
            speaker = dseg["speaker"]
            speaker_overlap[speaker] = speaker_overlap.get(speaker, 0.0) + overlap

    if not speaker_overlap:
        return None

    # Return speaker with maximum overlap
    return max(speaker_overlap, key=speaker_overlap.get)
