import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.schemas.video import SearchQuery
from app.services.search import semantic_search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("")
async def search(
    request: Request,
    data: SearchQuery,
    db: AsyncSession = Depends(get_db),
):
    """Semantic search across all transcripts."""
    query = data.query.strip()
    if not query:
        return {"results": []}

    try:
        from app.services.search import encode_query

        query_embedding = encode_query(query, model_cache_dir=settings.model_cache_dir)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Search requires sentence-transformers. Install with: pip install sentence-transformers",
        )

    results = await semantic_search(
        db=db,
        query_embedding=query_embedding,
        limit=data.limit,
    )

    # For HTMX, return HTML partial
    if request.headers.get("HX-Request"):
        return request.app.state.templates.TemplateResponse(
            "partials/search_results.html",
            {"request": request, "results": results, "query": query},
        )

    return {"results": results, "query": query}
