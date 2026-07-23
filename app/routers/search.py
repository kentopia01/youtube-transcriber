import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.dependencies import get_db
from app.schemas.video import SearchQuery
from app.services.search import semantic_search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("")
async def search(
    request: Request,
    db: AsyncSession = Depends(get_db),
    query: str = Form(None),
    channel_id: str = Form(None),
    video_id: str = Form(None),
):
    """Semantic search across all transcripts. Accepts form data (HTMX) or JSON."""
    # Handle both form-encoded (HTMX) and JSON requests
    if query is None:
        try:
            body = await request.json()
            query = body.get("query", "")
            channel_id = body.get("channel_id", channel_id)
            video_id = body.get("video_id", video_id)
        except Exception:
            query = ""

    query = query.strip()
    if not query:
        if request.headers.get("HX-Request"):
            return request.app.state.templates.TemplateResponse(
                request,
                "partials/search_results.html",
                {"request": request, "results": [], "query": ""},
            )
        return {"results": []}

    try:
        from app.services.search import encode_query

        query_embedding = await run_in_threadpool(
            encode_query,
            query,
            model_cache_dir=settings.model_cache_dir,
        )
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Search requires sentence-transformers. Install with: pip install sentence-transformers",
        )

    try:
        parsed_channel_id = uuid.UUID(channel_id) if channel_id else None
        parsed_video_id = uuid.UUID(video_id) if video_id else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid retrieval scope") from exc

    results = await semantic_search(
        db=db,
        query_embedding=query_embedding,
        limit=10,
        query=query,
        channel_id=parsed_channel_id,
        video_id=parsed_video_id,
        chat_enabled_only=True,
    )

    # For HTMX, return HTML partial
    if request.headers.get("HX-Request"):
        return request.app.state.templates.TemplateResponse(
            request,
            "partials/search_results.html",
            {"request": request, "results": results, "query": query},
        )

    return {"results": results, "query": query}
