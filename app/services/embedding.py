import structlog
import tiktoken

from app.config import settings

logger = structlog.get_logger()

_model_cache: dict = {}
SUMMARY_SPEAKER_LABEL = "__SUMMARY__"


def _get_embedding_model(model_cache_dir: str):
    """Get or create a sentence-transformers model (cached)."""
    if "embedding" not in _model_cache:
        from sentence_transformers import SentenceTransformer

        logger.info("loading_embedding_model", model=settings.embedding_model)
        _model_cache["embedding"] = SentenceTransformer(
            settings.embedding_model,
            cache_folder=model_cache_dir,
            trust_remote_code=True,
        )
    return _model_cache["embedding"]


def _count_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _split_at_sentence_boundaries(text: str, target_tokens: int, max_tokens: int) -> list[str]:
    """Split text at sentence boundaries, targeting target_tokens per chunk.

    Returns a list of text chunks, each ≤ max_tokens (best effort).
    """
    import re

    enc = tiktoken.get_encoding("cl100k_base")
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_sentences: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sent_tokens = len(enc.encode(sentence))

        if current_tokens + sent_tokens > max_tokens and current_sentences:
            chunks.append(" ".join(current_sentences))
            current_sentences = []
            current_tokens = 0

        current_sentences.append(sentence)
        current_tokens += sent_tokens

        if current_tokens >= target_tokens:
            chunks.append(" ".join(current_sentences))
            current_sentences = []
            current_tokens = 0

    if current_sentences:
        chunks.append(" ".join(current_sentences))

    return chunks if chunks else [text]


def _build_speaker_chunks(segments: list[dict], target_tokens: int, max_tokens: int) -> list[dict]:
    """Build chunks that respect speaker turn boundaries.

    Algorithm:
    1. Accumulate consecutive segments for the same speaker
    2. Flush when adding another segment would exceed max_tokens
    3. Flush once target_tokens is reached
    4. If a single segment exceeds max_tokens, split it into timed sentence chunks
    """
    if not segments:
        return []
    chunks: list[dict] = []
    current: dict | None = None

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return

        text = " ".join(current["texts"]).strip()
        chunks.append({
            "text": text,
            "start_time": current["start_time"],
            "end_time": current["end_time"],
            "token_count": current["token_count"],
            "speaker": current["speaker"],
        })
        current = None

    def split_oversized_segment(seg: dict, token_count: int) -> list[dict]:
        text = (seg.get("text") or "").strip()
        if not text:
            return [{
                "text": "",
                "start_time": seg["start"],
                "end_time": seg["end"],
                "token_count": token_count,
                "speaker": seg.get("speaker"),
            }]

        sub_texts = _split_at_sentence_boundaries(text, target_tokens, max_tokens)
        if len(sub_texts) == 1:
            return [{
                "text": text,
                "start_time": seg["start"],
                "end_time": seg["end"],
                "token_count": token_count,
                "speaker": seg.get("speaker"),
            }]

        sub_token_counts = [_count_tokens(sub_text) for sub_text in sub_texts]
        total_sub_tokens = sum(sub_token_counts) or len(sub_texts)
        total_duration = max(float(seg["end"]) - float(seg["start"]), 0.0)
        start_time = float(seg["start"])
        split_chunks: list[dict] = []

        for idx, (sub_text, sub_tokens) in enumerate(zip(sub_texts, sub_token_counts)):
            if idx == len(sub_texts) - 1:
                end_time = float(seg["end"])
            else:
                duration = total_duration * (sub_tokens / total_sub_tokens)
                end_time = min(float(seg["end"]), start_time + duration)

            split_chunks.append({
                "text": sub_text.strip(),
                "start_time": start_time,
                "end_time": end_time,
                "token_count": sub_tokens,
                "speaker": seg.get("speaker"),
            })
            start_time = end_time

        return split_chunks

    for seg in segments:
        speaker = seg.get("speaker")
        text = seg.get("text", "")
        token_count = _count_tokens(text)

        if token_count > max_tokens:
            flush_current()
            chunks.extend(split_oversized_segment(seg, token_count))
            continue

        if current is None:
            current = {
                "speaker": speaker,
                "texts": [text],
                "start_time": seg["start"],
                "end_time": seg["end"],
                "token_count": token_count,
            }
        elif speaker != current["speaker"] or current["token_count"] + token_count > max_tokens:
            flush_current()
            current = {
                "speaker": speaker,
                "texts": [text],
                "start_time": seg["start"],
                "end_time": seg["end"],
                "token_count": token_count,
            }
        else:
            current["texts"].append(text)
            current["end_time"] = seg["end"]
            current["token_count"] += token_count

        if current is not None and current["token_count"] >= target_tokens:
            flush_current()

    flush_current()
    return chunks if chunks else [{
        "text": " ".join(seg.get("text", "") for seg in segments).strip(),
        "start_time": segments[0]["start"],
        "end_time": segments[-1]["end"],
        "token_count": _count_tokens(" ".join(seg.get("text", "") for seg in segments)),
        "speaker": segments[0].get("speaker"),
    }]


def _build_text_chunks(
    text: str,
    target_tokens: int,
    max_tokens: int,
    *,
    speaker: str | None = None,
) -> list[dict]:
    """Split plain text into embedding chunks."""
    text = text.strip()
    if not text:
        return []

    sub_chunks = _split_at_sentence_boundaries(text, target_tokens, max_tokens)
    return [
        {
            "text": sub_text,
            "start_time": None,
            "end_time": None,
            "token_count": _count_tokens(sub_text),
            "speaker": speaker,
        }
        for sub_text in sub_chunks
        if sub_text.strip()
    ]


def _embed_chunks(chunks: list[dict], model_cache_dir: str) -> list[dict]:
    """Encode pre-built text chunks using the configured embedding model."""
    if not chunks:
        return []

    model = _get_embedding_model(model_cache_dir)

    # Batch encode with search_document: prefix for nomic model
    texts = [f"search_document: {c['text']}" for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

    logger.info("embeddings_generated", chunks=len(chunks), dimensions=settings.embedding_dimensions)

    results = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        results.append({
            "chunk_index": i,
            "chunk_text": chunk["text"],
            "start_time": chunk["start_time"],
            "end_time": chunk["end_time"],
            "embedding": emb.tolist(),
            "token_count": chunk["token_count"],
            "speaker": chunk.get("speaker"),
        })

    return results


def chunk_and_embed(
    segments: list[dict],
    model_cache_dir: str = "/data/models",
) -> list[dict]:
    """Split transcript segments into speaker-aware chunks and generate embeddings.

    Uses nomic-embed-text-v1.5 with search_document: prefix for asymmetric retrieval.

    Args:
        segments: List of dicts with keys: start, end, text, and optionally speaker
        model_cache_dir: Cache directory for the embedding model

    Returns:
        List of dicts with chunk_index, chunk_text, start_time, end_time,
        embedding, token_count, speaker
    """
    if not segments:
        return []

    chunks = _build_speaker_chunks(
        segments,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
    )

    return _embed_chunks(chunks, model_cache_dir)


def chunk_and_embed_summary(
    summary_text: str,
    model_cache_dir: str = "/data/models",
) -> list[dict]:
    """Split a summary into chunks and generate embeddings for chat/search retrieval."""
    chunks = _build_text_chunks(
        summary_text,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        speaker=SUMMARY_SPEAKER_LABEL,
    )
    return _embed_chunks(chunks, model_cache_dir)
