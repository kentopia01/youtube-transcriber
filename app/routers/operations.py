from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services.operations_dashboard import build_operations_summary
from app.services.batch_reconciliation import reconcile_stale_batches
from app.services.mutation_audit import list_mutations


router = APIRouter(prefix="/api/operations", tags=["operations"])


class ReconcileBatchesRequest(BaseModel):
    apply: bool = False


@router.get("/summary")
async def operations_summary(request: Request, db: AsyncSession = Depends(get_db)):
    queue_probe = getattr(request.app.state, "operations_queue_probe", None)
    summary = await build_operations_summary(db, queue_probe=queue_probe)
    return summary.to_dict()


@router.post("/reconcile-batches")
async def reconcile_batches(
    data: ReconcileBatchesRequest,
    db: AsyncSession = Depends(get_db),
):
    changes = await reconcile_stale_batches(db, apply=data.apply)
    return {
        "mode": "apply" if data.apply else "dry_run",
        "changed": len(changes),
        "items": [change.to_dict() for change in changes],
    }


@router.get("/audit")
async def mutation_audit(
    limit: int = Query(default=100, ge=1, le=500),
    actor: str | None = Query(default=None, max_length=64),
):
    items = list_mutations(limit=limit, actor=actor)
    return {"items": items, "total_returned": len(items), "limit": limit}
