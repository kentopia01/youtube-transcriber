import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = structlog.get_logger()

_search_model_cache: dict = {}


def encode_query(query: str, model_cache_dir: str = "/data/models") -> list[float]:
    """Encode a search query into an embedding vector.

    Uses nomic-embed-text-v1.5 with search_query: prefix for asymmetric retrieval.
    """
    if "model" not in _search_model_cache:
        from sentence_transformers import SentenceTransformer

        _search_model_cache["model"] = SentenceTransformer(
            settings.embedding_model,
            cache_folder=model_cache_dir,
            trust_remote_code=True,
        )

    model = _search_model_cache["model"]
    prefixed_query = f"search_query: {query}"
    embedding = model.encode([prefixed_query], normalize_embeddings=True)
    return embedding[0].tolist()


async def semantic_search(
    db: AsyncSession,
    query_embedding: list[float],
    limit: int = 10,
    channel_id: uuid.UUID | None = None,
) -> list[dict]:
    """Search for similar transcript chunks using pgvector cosine similarity."""
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    sql = """
        SELECT
            ec.id,
            ec.video_id,
            v.title as video_title,
            ec.chunk_text,
            ec.start_time,
            ec.end_time,
            ec.speaker,
            1 - (ec.embedding <=> :embedding::vector) as similarity
        FROM embedding_chunks ec
        JOIN videos v ON v.id = ec.video_id
    """
    params: dict = {"embedding": embedding_str, "limit": limit}

    if channel_id:
        sql += " WHERE v.channel_id = :channel_id"
        params["channel_id"] = str(channel_id)

    sql += " ORDER BY ec.embedding <=> :embedding::vector LIMIT :limit"

    result = await db.execute(text(sql), params)
    rows = result.fetchall()

    return [
        {
            "id": row.id,
            "video_id": row.video_id,
            "video_title": row.video_title,
            "chunk_text": row.chunk_text,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "speaker": row.speaker,
            "similarity": round(float(row.similarity), 4),
        }
        for row in rows
    ]
