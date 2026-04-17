"""Transcription service with pluggable engine support.

Supports two backends:
  - "mlx": Apple Silicon Metal-accelerated via mlx-whisper (native macOS only)
  - "faster-whisper": CPU-based via faster-whisper (Docker or any platform)

Engine selection is controlled by the TRANSCRIPTION_ENGINE env var.
"""

from __future__ import annotations

import re
import time
from typing import Protocol

import structlog

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Transcript result type
# ---------------------------------------------------------------------------

class TranscriptResult:
    """Standard result from any transcription engine."""

    def __init__(self, text: str, language: str, segments: list[dict], processing_time: float):
        self.text = text
        self.language = language
        self.segments = segments
        self.processing_time = processing_time

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "segments": self.segments,
            "processing_time": self.processing_time,
        }


# ---------------------------------------------------------------------------
# Engine protocol
# ---------------------------------------------------------------------------

class TranscriptionEngine(Protocol):
    """Protocol for pluggable transcription engines."""

    def detect_language(self, audio_path: str) -> str:
        """Detect the language of an audio file."""
        ...

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptResult:
        """Transcribe an audio file, returning structured result."""
        ...


# ---------------------------------------------------------------------------
# MLX Whisper Engine (Apple Silicon / Metal)
# ---------------------------------------------------------------------------

class MLXWhisperEngine:
    """Transcription engine using mlx-whisper on Apple Silicon."""

    def __init__(self, model: str, detect_model: str):
        self.model = model
        self.detect_model = detect_model

    def detect_language(self, audio_path: str) -> str:
        """Detect language using the tiny model on the first 30s."""
        import mlx_whisper

        logger.info("detecting_language", model=self.detect_model, audio=audio_path)
        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=self.detect_model,
            word_timestamps=False,
        )
        language = result.get("language", "en")
        logger.info("language_detected", language=language)
        return language

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptResult:
        """Transcribe audio using MLX Whisper with Metal acceleration."""
        import mlx_whisper

        logger.info(
            "transcribing_mlx",
            model=self.model,
            language=language,
            audio=audio_path,
        )

        start_time = time.time()

        kwargs: dict = {
            "path_or_hf_repo": self.model,
            "word_timestamps": True,
        }
        if language and language != "auto":
            kwargs["language"] = language

        result = mlx_whisper.transcribe(audio_path, **kwargs)

        segments = []
        full_text_parts = []

        for seg in result.get("segments", []):
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
                "confidence": seg.get("avg_logprob", 0.0),
            })
            full_text_parts.append(seg["text"].strip())

        processing_time = time.time() - start_time
        detected_lang = result.get("language", language or "en")

        logger.info(
            "transcription_complete",
            engine="mlx",
            language=detected_lang,
            segments=len(segments),
            processing_time=round(processing_time, 2),
        )

        return TranscriptResult(
            text=" ".join(full_text_parts),
            language=detected_lang,
            segments=segments,
            processing_time=processing_time,
        )


# ---------------------------------------------------------------------------
# Faster-Whisper Engine (CPU / Docker)
# ---------------------------------------------------------------------------

class FasterWhisperEngine:
    """Transcription engine using faster-whisper on CPU."""

    def __init__(self, model_size: str, device: str, compute_type: str, model_cache_dir: str):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model_cache_dir = model_cache_dir
        self._model = None

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            logger.info("loading_whisper_model", model_size=self.model_size, device=self.device)
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root=self.model_cache_dir,
            )
        return self._model

    def detect_language(self, audio_path: str) -> str:
        """Detect language using faster-whisper."""
        model = self._get_model()
        _, info = model.transcribe(audio_path, beam_size=1)
        return info.language

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptResult:
        """Transcribe audio using faster-whisper on CPU."""
        model = self._get_model()

        start_time = time.time()
        kwargs: dict = {"beam_size": 5, "vad_filter": True}
        if language and language != "auto":
            kwargs["language"] = language

        segments_iter, info = model.transcribe(audio_path, **kwargs)

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
            engine="faster-whisper",
            language=info.language,
            duration=info.duration,
            segments=len(segments),
            processing_time=round(processing_time, 2),
        )

        return TranscriptResult(
            text=" ".join(full_text_parts),
            language=info.language,
            segments=segments,
            processing_time=processing_time,
        )


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------

# Cache engines per worker process so we don't pay reload cost for faster-whisper
# weights on every task (~10-30s per video). Keyed by the full engine spec so a
# config change produces a fresh instance.
_engine_cache: dict[tuple, TranscriptionEngine] = {}


def _reset_caches() -> None:
    """Clear the engine cache. Intended for tests."""
    _engine_cache.clear()


def get_engine(
    engine_type: str = "faster-whisper",
    *,
    # MLX options
    whisper_model: str = "mlx-community/whisper-large-v3-turbo",
    whisper_detect_model: str = "mlx-community/whisper-tiny",
    # Faster-whisper options
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
    model_cache_dir: str = "/data/models",
) -> TranscriptionEngine:
    """Create (or return cached) the appropriate transcription engine."""
    if engine_type == "mlx":
        key = ("mlx", whisper_model, whisper_detect_model)
    elif engine_type == "faster-whisper":
        key = ("faster-whisper", model_size, device, compute_type, model_cache_dir)
    else:
        raise ValueError(f"Unknown transcription engine: {engine_type}")

    cached = _engine_cache.get(key)
    if cached is not None:
        return cached

    if engine_type == "mlx":
        engine: TranscriptionEngine = MLXWhisperEngine(
            model=whisper_model, detect_model=whisper_detect_model
        )
    else:
        engine = FasterWhisperEngine(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            model_cache_dir=model_cache_dir,
        )

    _engine_cache[key] = engine
    return engine


# ---------------------------------------------------------------------------
# Legacy helper — kept for backward compatibility with existing filler tests
# ---------------------------------------------------------------------------

def clean_filler_words(text: str) -> str:
    """Remove common filler words and phrases from transcribed text.

    NOTE: This is the legacy regex approach. Phase 3 replaces this with LLM cleanup.
    Kept for backward compatibility and as a fallback.
    """
    standalone = [
        r"\bum\b", r"\buh\b", r"\buhm\b", r"\bumm\b",
        r"\byou know\b", r"\bI mean\b", r"\bbasically\b",
        r"\bkind of\b", r"\bsort of\b",
    ]
    for pattern in standalone:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    text = re.sub(r"\blike,\s", ", ", text, flags=re.IGNORECASE)
    text = re.sub(r"\blike\s+(I|you|he|she|it|we|they)\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\bright[,?]\s", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bso,\s", ", ", text, flags=re.IGNORECASE)

    text = re.sub(r"  +", " ", text)
    text = re.sub(r"\s+([,.])", r"\1", text)
    text = re.sub(r"^[,\s]+", "", text)
    text = re.sub(r"[,\s]+$", "", text)

    return text.strip()


# ---------------------------------------------------------------------------
# High-level convenience function (used by transcribe task)
# ---------------------------------------------------------------------------

def transcribe_audio(
    audio_path: str,
    # Engine selection
    engine_type: str = "faster-whisper",
    # MLX options
    whisper_model: str = "mlx-community/whisper-large-v3-turbo",
    whisper_detect_model: str = "mlx-community/whisper-tiny",
    whisper_language: str = "auto",
    # Faster-whisper options
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
    model_cache_dir: str = "/data/models",
) -> dict:
    """Transcribe an audio file using the configured engine.

    Returns dict with text, language, segments list, and processing_time.
    """
    engine = get_engine(
        engine_type,
        whisper_model=whisper_model,
        whisper_detect_model=whisper_detect_model,
        model_size=model_size,
        device=device,
        compute_type=compute_type,
        model_cache_dir=model_cache_dir,
    )

    # Language detection for MLX engine
    language = None
    if engine_type == "mlx" and whisper_language == "auto":
        language = engine.detect_language(audio_path)
    elif whisper_language != "auto":
        language = whisper_language

    result = engine.transcribe(audio_path, language=language)

    # Apply legacy filler word cleanup (will be replaced by LLM cleanup in Phase 3)
    cleaned_text = clean_filler_words(result.text)

    return {
        "text": cleaned_text,
        "language": result.language,
        "segments": result.segments,
        "processing_time": result.processing_time,
    }
