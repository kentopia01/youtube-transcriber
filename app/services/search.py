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


def _build_where_clause(channel_id: uuid.UUID | None) -> tuple[str, dict]:
    """Build optional WHERE clause for channel filtering."""
    if channel_id:
        return " WHERE v.channel_id = :channel_id", {"channel_id": str(channel_id)}
    return "", {}


async def _vector_search(
    db: AsyncSession,
    query_embedding: list[float],
    limit: int,
    channel_id: uuid.UUID | None,
) -> list[dict]:
    """Pure vector cosine similarity search."""
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    where, params = _build_where_clause(channel_id)
    params.update({"embedding": embedding_str, "limit": limit})

    sql = f"""
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
        {where}
        ORDER BY ec.embedding <=> :embedding::vector
        LIMIT :limit
    """

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


async def _keyword_search(
    db: AsyncSession,
    query: str,
    limit: int,
    channel_id: uuid.UUID | None,
) -> list[dict]:
    """Pure keyword (tsvector) search using PostgreSQL full-text search."""
    where, params = _build_where_clause(channel_id)
    params.update({"query": query, "limit": limit})

    # Add tsquery match condition
    ts_condition = "ec.search_vector @@ plainto_tsquery('english', :query)"
    if where:
        where += f" AND {ts_condition}"
    else:
        where = f" WHERE {ts_condition}"

    sql = f"""
        SELECT
            ec.id,
            ec.video_id,
            v.title as video_title,
            ec.chunk_text,
            ec.start_time,
            ec.end_time,
            ec.speaker,
            ts_rank(ec.search_vector, plainto_tsquery('english', :query)) as similarity
        FROM embedding_chunks ec
        JOIN videos v ON v.id = ec.video_id
        {where}
        ORDER BY similarity DESC
        LIMIT :limit
    """

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


async def _hybrid_search(
    db: AsyncSession,
    query: str,
    query_embedding: list[float],
    limit: int,
    channel_id: uuid.UUID | None,
    rrf_k: int = 60,
) -> list[dict]:
    """Hybrid search using reciprocal rank fusion (RRF) of BM25 + vector scores.

    RRF formula: score = 1/(k + rank_bm25) + 1/(k + rank_vector)
    where k=60 (standard RRF constant).
    """
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    where, params = _build_where_clause(channel_id)
    params.update({
        "embedding": embedding_str,
        "query": query,
        "limit": limit,
        "rrf_k": rrf_k,
    })

    # Fetch a larger candidate pool for ranking (3x limit from each method)
    candidate_limit = limit * 3

    sql = f"""
        WITH vector_ranked AS (
            SELECT
                ec.id,
                ec.video_id,
                v.title as video_title,
                ec.chunk_text,
                ec.start_time,
                ec.end_time,
                ec.speaker,
                ROW_NUMBER() OVER (ORDER BY ec.embedding <=> :embedding::vector) as vector_rank
            FROM embedding_chunks ec
            JOIN videos v ON v.id = ec.video_id
            {where}
            ORDER BY ec.embedding <=> :embedding::vector
            LIMIT {candidate_limit}
        ),
        keyword_ranked AS (
            SELECT
                ec.id,
                ec.video_id,
                v.title as video_title,
                ec.chunk_text,
                ec.start_time,
                ec.end_time,
                ec.speaker,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank(ec.search_vector, plainto_tsquery('english', :query)) DESC
                ) as keyword_rank
            FROM embedding_chunks ec
            JOIN videos v ON v.id = ec.video_id
            {where}
            {"AND" if where else "WHERE"} ec.search_vector @@ plainto_tsquery('english', :query)
            ORDER BY ts_rank(ec.search_vector, plainto_tsquery('english', :query)) DESC
            LIMIT {candidate_limit}
        )
        SELECT
            COALESCE(vr.id, kr.id) as id,
            COALESCE(vr.video_id, kr.video_id) as video_id,
            COALESCE(vr.video_title, kr.video_title) as video_title,
            COALESCE(vr.chunk_text, kr.chunk_text) as chunk_text,
            COALESCE(vr.start_time, kr.start_time) as start_time,
            COALESCE(vr.end_time, kr.end_time) as end_time,
            COALESCE(vr.speaker, kr.speaker) as speaker,
            COALESCE(1.0 / (:rrf_k + vr.vector_rank), 0)
                + COALESCE(1.0 / (:rrf_k + kr.keyword_rank), 0) as rrf_score
        FROM vector_ranked vr
        FULL OUTER JOIN keyword_ranked kr ON vr.id = kr.id
        ORDER BY rrf_score DESC
        LIMIT :limit
    """

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
            "similarity": round(float(row.rrf_score), 4),
        }
        for row in rows
    ]


async def semantic_search(
    db: AsyncSession,
    query_embedding: list[float],
    limit: int = 10,
    channel_id: uuid.UUID | None = None,
    query: str | None = None,
    search_mode: str | None = None,
) -> list[dict]:
    """Search for similar transcript chunks.

    Supports three modes (configured via settings.search_mode or override):
    - "vector": pure cosine similarity search
    - "keyword": pure PostgreSQL full-text search
    - "hybrid": reciprocal rank fusion of BM25 + vector (default)

    Args:
        db: Database session
        query_embedding: The query embedding vector
        limit: Maximum results to return
        channel_id: Optional channel filter
        query: Original query text (required for hybrid/keyword modes)
        search_mode: Override for settings.search_mode
    """
    mode = search_mode or settings.search_mode

    if mode == "keyword":
        if not query:
            logger.warning("keyword_search_requires_query_text, falling back to vector")
            mode = "vector"
        else:
            return await _keyword_search(db, query, limit, channel_id)

    if mode == "hybrid":
        if not query:
            logger.warning("hybrid_search_requires_query_text, falling back to vector")
            mode = "vector"
        else:
            return await _hybrid_search(db, query, query_embedding, limit, channel_id)

    # Default: vector-only
    return await _vector_search(db, query_embedding, limit, channel_id)
