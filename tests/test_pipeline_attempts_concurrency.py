import asyncio
import os
import socket
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.job import Job
from app.models.video import Video
from app.routers import videos as videos_router
from app.schemas.video import VideoSubmit
from app.services.pipeline_attempts import ACTIVE_PIPELINE_ATTEMPT_STATUSES


class _AsyncBarrier:
    def __init__(self, size: int):
        self.size = size
        self._count = 0
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()

    async def wait(self) -> None:
        async with self._lock:
            self._count += 1
            if self._count >= self.size:
                self._ready.set()
        await self._ready.wait()


def _integration_db_url() -> str:
    return (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL_NATIVE")
        or settings.database_url_native
    )


def _db_reachable(db_url: str) -> bool:
    parsed = make_url(db_url)
    host = parsed.host or "localhost"
    port = parsed.port or 5432

    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.asyncio
async def test_concurrent_submit_only_creates_one_active_attempt(monkeypatch):
    db_url = _integration_db_url()
    if not _db_reachable(db_url):
        pytest.skip(f"Postgres not reachable for integration test: {db_url}")

    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.connect() as conn:
        has_attempt_number = await conn.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'jobs' AND column_name = 'attempt_number'
                )
                """
            )
        )
        has_active_attempt_index = await conn.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE tablename = 'jobs'
                      AND indexname = 'uq_jobs_pipeline_one_active_attempt'
                )
                """
            )
        )
        has_current_stage = await conn.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'jobs' AND column_name = 'current_stage'
                )
                """
            )
        )

    if not has_attempt_number or not has_active_attempt_index or not has_current_stage:
        await engine.dispose()
        pytest.skip("Integration DB is not migrated to Phase 2 pipeline schema yet")

    youtube_video_id = f"race{uuid.uuid4().hex[:20]}"
    video_url = f"https://www.youtube.com/watch?v={youtube_video_id}"
    video_uuid = None

    try:
        async with session_factory() as setup_db:
            seeded_video = Video(
                youtube_video_id=youtube_video_id,
                title="Race Seed",
                url=video_url,
                status="failed",
                error_message="seed failure",
            )
            setup_db.add(seeded_video)
            await setup_db.flush()
            video_uuid = seeded_video.id

            setup_db.add(
                Job(
                    video_id=video_uuid,
                    job_type="pipeline",
                    status="failed",
                    attempt_number=1,
                    error_message="seed failure",
                )
            )
            await setup_db.commit()

        monkeypatch.setattr(videos_router, "extract_video_id", lambda _: youtube_video_id)
        monkeypatch.setattr(
            videos_router,
            "get_video_info",
            lambda _: {
                "video_id": youtube_video_id,
                "title": "Race Test",
                "description": "Race test metadata",
                "duration": 33,
                "thumbnail": "https://example.com/thumb.jpg",
                "channel_id": None,
                "channel_name": None,
                "channel_url": None,
                "published_at": "20260401",
                "url": video_url,
            },
        )

        async def _fake_get_or_create_channel(*args, **kwargs):
            return None

        monkeypatch.setattr(videos_router, "get_or_create_channel", _fake_get_or_create_channel)

        pipeline_runs: list[str] = []
        monkeypatch.setattr(
            videos_router,
            "run_pipeline",
            lambda video_id: pipeline_runs.append(video_id) or f"celery-{len(pipeline_runs)}",
        )

        real_get_active_attempt = videos_router.get_active_pipeline_attempt
        barrier = _AsyncBarrier(2)
        guarded_calls = 0

        async def _guarded_get_active_attempt(db, video_id):
            nonlocal guarded_calls
            guarded_calls += 1
            if guarded_calls <= 2:
                await barrier.wait()
                return None
            return await real_get_active_attempt(db, video_id)

        monkeypatch.setattr(videos_router, "get_active_pipeline_attempt", _guarded_get_active_attempt)

        async def _submit_once():
            async with session_factory() as db:
                return await videos_router.submit_video(
                    SimpleNamespace(headers={}),
                    VideoSubmit(url=video_url),
                    db,
                )

        response_one, response_two = await asyncio.gather(_submit_once(), _submit_once())

        assert sorted((response_one["status"], response_two["status"])) == ["existing", "queued"]
        assert len({response_one["job_id"], response_two["job_id"]}) == 1
        assert len(pipeline_runs) == 1

        async with session_factory() as verify_db:
            jobs_result = await verify_db.execute(
                select(Job)
                .where(Job.video_id == video_uuid, Job.job_type == "pipeline")
                .order_by(Job.attempt_number.asc())
            )
            jobs = jobs_result.scalars().all()

            active_jobs = [job for job in jobs if job.status in ACTIVE_PIPELINE_ATTEMPT_STATUSES]
            assert len(active_jobs) == 1
            assert active_jobs[0].attempt_number == 2

    finally:
        async with session_factory() as cleanup_db:
            if video_uuid:
                await cleanup_db.execute(delete(Job).where(Job.video_id == video_uuid))
                await cleanup_db.execute(delete(Video).where(Video.id == video_uuid))
                await cleanup_db.commit()

        await engine.dispose()
