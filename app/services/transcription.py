import time

import structlog

logger = structlog.get_logger()

# Singleton model cache
_model_cache: dict = {}


def _get_model(model_size: str, device: str, compute_type: str, model_cache_dir: str):
    """Get or create a faster-whisper model (cached as singleton)."""
    cache_key = f"{model_size}_{device}_{compute_type}"
    if cache_key not in _model_cache:
        from faster_whisper import WhisperModel

        logger.info("loading_whisper_model", model_size=model_size, device=device)
        _model_cache[cache_key] = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=model_cache_dir,
        )
    return _model_cache[cache_key]


def transcribe_audio(
    audio_path: str,
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
    model_cache_dir: str = "/data/models",
) -> dict:
    """Transcribe an audio file using faster-whisper.

    Returns dict with text, language, segments list, and processing_time.
    """
    model = _get_model(model_size, device, compute_type, model_cache_dir)

    start_time = time.time()
    segments_iter, info = model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,
    )

    segments = []
    full_text_parts = []

    for segment in segments_iter:
        segments.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip(),
            "confidence": segment.avg_logprob,
        })
        full_text_parts.append(segment.text.strip())

    processing_time = time.time() - start_time

    logger.info(
        "transcription_complete",
        language=info.language,
        duration=info.duration,
        segments=len(segments),
        processing_time=round(processing_time, 2),
    )

    return {
        "text": " ".join(full_text_parts),
        "language": info.language,
        "segments": segments,
        "processing_time": processing_time,
    }
