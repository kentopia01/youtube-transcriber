from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.digest_lane import DigestLane
from app.services.lane_digest import deliver_lane_digest
from app.tasks.celery_app import celery


async def _run_lane_digests(window_hours: int = 24) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    results: list[dict[str, object]] = []
    try:
        async with SessionLocal() as db:
            lanes = list(
                (
                    await db.execute(
                        select(DigestLane)
                        .where(DigestLane.digest_enabled.is_(True))
                        .order_by(DigestLane.slug)
                    )
                ).scalars().all()
            )
            for lane in lanes:
                results.append(
                    await deliver_lane_digest(
                        db,
                        lane,
                        window_hours=window_hours,
                    )
                )
    finally:
        await engine.dispose()
    return {"processed_lanes": len(results), "results": results}


@celery.task(name="tasks.lane_digests")
def lane_digests(window_hours: int = 24) -> dict[str, Any]:
    return asyncio.run(_run_lane_digests(window_hours=window_hours))
