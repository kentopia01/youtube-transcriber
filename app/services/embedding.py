import structlog
import tiktoken

logger = structlog.get_logger()

CHUNK_SIZE = 500  # tokens
CHUNK_OVERLAP = 50  # tokens

_model_cache: dict = {}


def _get_embedding_model(model_cache_dir: str):
    """Get or create a sentence-transformers model (cached)."""
    if "embedding" not in _model_cache:
        from sentence_transformers import SentenceTransformer

        logger.info("loading_embedding_model")
        _model_cache["embedding"] = SentenceTransformer(
            "all-MiniLM-L6-v2",
            cache_folder=model_cache_dir,
        )
    return _model_cache["embedding"]


def _count_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def chunk_and_embed(
    segments: list[dict],
    model_cache_dir: str = "/data/models",
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """Split transcript segments into overlapping chunks and generate embeddings.

    Args:
        segments: List of dicts with keys: start, end, text
        model_cache_dir: Cache directory for the embedding model
        chunk_size: Target chunk size in tokens
        chunk_overlap: Overlap between chunks in tokens

    Returns:
        List of dicts with chunk_index, chunk_text, start_time, end_time, embedding, token_count
    """
    model = _get_embedding_model(model_cache_dir)
    enc = tiktoken.get_encoding("cl100k_base")

    # Build chunks from segments
    chunks = []
    current_texts: list[str] = []
    current_tokens = 0
    current_start = segments[0]["start"] if segments else 0.0
    current_end = 0.0

    for seg in segments:
        seg_tokens = len(enc.encode(seg["text"]))

        if current_tokens + seg_tokens > chunk_size and current_texts:
            # Save current chunk
            chunks.append({
                "text": " ".join(current_texts),
                "start_time": current_start,
                "end_time": current_end,
                "token_count": current_tokens,
            })

            # Overlap: keep last segments that fit within overlap budget
            overlap_texts: list[str] = []
            overlap_tokens = 0
            overlap_start = current_end
            for prev_text in reversed(current_texts):
                t = len(enc.encode(prev_text))
                if overlap_tokens + t > chunk_overlap:
                    break
                overlap_texts.insert(0, prev_text)
                overlap_tokens += t
                overlap_start = current_start  # approximate

            current_texts = overlap_texts
            current_tokens = overlap_tokens
            current_start = seg["start"]

        current_texts.append(seg["text"])
        current_tokens += seg_tokens
        current_end = seg["end"]

    # Don't forget the last chunk
    if current_texts:
        chunks.append({
            "text": " ".join(current_texts),
            "start_time": current_start,
            "end_time": current_end,
            "token_count": current_tokens,
        })

    if not chunks:
        return []

    # Batch encode
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

    logger.info("embeddings_generated", chunks=len(chunks))

    results = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        results.append({
            "chunk_index": i,
            "chunk_text": chunk["text"],
            "start_time": chunk["start_time"],
            "end_time": chunk["end_time"],
            "embedding": emb.tolist(),
            "token_count": chunk["token_count"],
        })

    return results
