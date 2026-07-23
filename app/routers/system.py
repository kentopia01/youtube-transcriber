from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services.operations_dashboard import build_operations_summary


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
async def system_status(request: Request, db: AsyncSession = Depends(get_db)):
    queue_probe = getattr(request.app.state, "operations_queue_probe", None)
    summary = await build_operations_summary(db, queue_probe=queue_probe)
    return {
        "service": "youtube-transcriber",
        "status": "ok" if summary.queue_health.state in {"idle", "healthy", "busy"} else "degraded",
        "generated_at": summary.generated_at.isoformat(),
        "queue_health": summary.queue_health.to_dict(),
        "warning_count": summary.warning_count,
        "counts": summary.counts.to_dict(),
        "runtime": summary.runtime.to_dict(),
    }
