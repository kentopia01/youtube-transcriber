import structlog
import tiktoken

from app.config import settings

logger = structlog.get_logger()

_model_cache: dict = {}


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

        if current_tokens >= target_tokens and sent_tokens <= max_tokens:
            # We've hit our target; save this chunk if next sentence would exceed max
            pass  # Let the max_tokens check handle it on next iteration

    if current_sentences:
        chunks.append(" ".join(current_sentences))

    return chunks if chunks else [text]


def _build_speaker_chunks(segments: list[dict], target_tokens: int, max_tokens: int) -> list[dict]:
    """Build chunks that respect speaker turn boundaries.

    Algorithm:
    1. Group consecutive segments by speaker label
    2. For each speaker group:
       - If ≤ max_tokens → one chunk
       - If > max_tokens → split at sentence boundaries
    3. Merge short same-speaker groups that fit within target
    """
    enc = tiktoken.get_encoding("cl100k_base")

    if not segments:
        return []

    # Step 1: Group consecutive segments by speaker
    groups: list[dict] = []
    current_group: dict | None = None

    for seg in segments:
        speaker = seg.get("speaker")
        if current_group is None or speaker != current_group["speaker"]:
            if current_group is not None:
                groups.append(current_group)
            current_group = {
                "speaker": speaker,
                "texts": [seg["text"]],
                "start_time": seg["start"],
                "end_time": seg["end"],
            }
        else:
            current_group["texts"].append(seg["text"])
            current_group["end_time"] = seg["end"]

    if current_group is not None:
        groups.append(current_group)

    # Step 2: Merge short consecutive same-speaker groups
    merged: list[dict] = []
    for group in groups:
        if (
            merged
            and merged[-1]["speaker"] == group["speaker"]
            and len(enc.encode(" ".join(merged[-1]["texts"])))
            + len(enc.encode(" ".join(group["texts"])))
            <= target_tokens
        ):
            merged[-1]["texts"].extend(group["texts"])
            merged[-1]["end_time"] = group["end_time"]
        else:
            merged.append(group)

    # Step 3: Build chunks, splitting long groups at sentence boundaries
    chunks = []
    for group in merged:
        full_text = " ".join(group["texts"])
        token_count = len(enc.encode(full_text))

        if token_count <= max_tokens:
            chunks.append({
                "text": full_text,
                "start_time": group["start_time"],
                "end_time": group["end_time"],
                "token_count": token_count,
                "speaker": group["speaker"],
            })
        else:
            sub_chunks = _split_at_sentence_boundaries(full_text, target_tokens, max_tokens)
            for sub_text in sub_chunks:
                chunks.append({
                    "text": sub_text,
                    "start_time": group["start_time"],
                    "end_time": group["end_time"],
                    "token_count": len(enc.encode(sub_text)),
                    "speaker": group["speaker"],
                })

    return chunks


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

    model = _get_embedding_model(model_cache_dir)

    chunks = _build_speaker_chunks(
        segments,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
    )

    if not chunks:
        return []

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
