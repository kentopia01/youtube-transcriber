from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services.operations_dashboard import build_operations_summary


router = APIRouter(prefix="/api/operations", tags=["operations"])


@router.get("/summary")
async def operations_summary(request: Request, db: AsyncSession = Depends(get_db)):
    queue_probe = getattr(request.app.state, "operations_queue_probe", None)
    summary = await build_operations_summary(db, queue_probe=queue_probe)
    return summary.to_dict()
