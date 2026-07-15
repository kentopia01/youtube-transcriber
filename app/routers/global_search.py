import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.services.global_search import (
    DEFAULT_CANDIDATE_LIMIT,
    DEFAULT_LIMIT,
    DEFAULT_PER_VIDEO_LIMIT,
    GlobalSearchOptions,
    global_search as run_global_search,
)

router = APIRouter(prefix="/api/global-search", tags=["global-search"])


def _parse_int(value, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_channel_id(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid channel_id") from exc


@router.post("")
async def global_search(
    request: Request,
    db: AsyncSession = Depends(get_db),
    query: str = Form(None),
    source_type: str = Form("all"),
    channel_id: str = Form(None),
    limit: str = Form(None),
    candidate_limit: str = Form(None),
    per_video_limit: str = Form(None),
):
    """Search every ingested transcript/summary chunk, independent of chat scope."""
    if query is None:
        try:
            body = await request.json()
        except Exception:
            body = {}
        query = body.get("query", "")
        source_type = body.get("source_type", source_type)
        channel_id = body.get("channel_id", channel_id)
        limit = body.get("limit", limit)
        candidate_limit = body.get("candidate_limit", candidate_limit)
        per_video_limit = body.get("per_video_limit", per_video_limit)

    query = (query or "").strip()
    if not query:
        empty_payload = {
            "query": "",
            "results": [],
            "candidate_count": 0,
            "lane_counts": {"vector": 0, "keyword": 0, "summary": 0},
        }
        if request.headers.get("HX-Request"):
            return request.app.state.templates.TemplateResponse(
                request,
                "partials/global_search_results.html",
                {"request": request, **empty_payload},
            )
        return empty_payload

    try:
        from app.services.search import encode_query

        query_embedding = encode_query(query, model_cache_dir=settings.model_cache_dir)
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Search requires sentence-transformers. Install with: pip install sentence-transformers",
        ) from exc

    options = GlobalSearchOptions(
        limit=_parse_int(limit, DEFAULT_LIMIT),
        candidate_limit=_parse_int(candidate_limit, DEFAULT_CANDIDATE_LIMIT),
        per_video_limit=_parse_int(per_video_limit, DEFAULT_PER_VIDEO_LIMIT),
        channel_id=_parse_channel_id(channel_id),
        source_type=source_type or "all",
    )
    payload = await run_global_search(
        db=db,
        query=query,
        query_embedding=query_embedding,
        options=options,
    )

    if request.headers.get("HX-Request"):
        return request.app.state.templates.TemplateResponse(
            request,
            "partials/global_search_results.html",
            {"request": request, **payload},
        )

    return payload
