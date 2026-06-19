from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import shutil
import tempfile
import uuid

import yt_dlp
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.video import Video
from app.services.job_visibility import hide_superseded_failed_jobs_sync
from app.services.pipeline_attempts import (
    ATTEMPT_RESULT_ALREADY_ACTIVE,
    ATTEMPT_RESULT_BLOCKED,
    ATTEMPT_RESULT_CREATED,
    allocate_pipeline_attempt_sync,
    create_pipeline_attempt_from_allocation_sync,
)
from app.services.pipeline_enqueue import enqueue_pipeline_job_after_commit
from app.services.pipeline_observability import ATTEMPT_REASON_OPERATOR_ACTION
from app.services.pipeline_recovery import get_retry_block_reason
from app.services.pipeline_resume import detect_resume_point_sync
from app.services.pipeline_state import PIPELINE_STAGE_QUEUED
from app.tasks.pipeline import run_pipeline_from

AUTH_COOKIE_NAMES = {
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
    "LOGIN_INFO",
}

DOWNLOAD_FORBIDDEN_SIGNATURE_MARKERS = (
    "download|downloaderror|error: unable to download video data: http error #: forbidden",
    "http error 403",
    "forbidden",
)


@dataclass(slots=True)
class CookieHealth:
    path: str
    exists: bool
    readable: bool
    cookie_count: int = 0
    auth_cookie_count: int = 0
    youtube_cookie_count: int = 0
    session_cookie_count: int = 0
    expired_cookie_count: int = 0
    age_seconds: float | None = None
    status: str = "missing"
    warnings: list[str] = field(default_factory=list)

    @property
    def has_auth_cookies(self) -> bool:
        return self.auth_cookie_count > 0


@dataclass(slots=True)
class YtdlpVersionHealth:
    version: str
    age_days: int | None
    status: str
    warning: str | None = None


@dataclass(slots=True)
class ProbeResult:
    label: str
    ok: bool
    error: str | None = None
    title: str | None = None
    duration: int | None = None
    downloaded_bytes: int | None = None


@dataclass(slots=True)
class DownloadFailureSummary:
    count: int
    since: datetime
    signature: str | None
    videos: list[dict]
    threshold_met: bool


@dataclass(slots=True)
class DownloadRetryDecision:
    job_id: str
    youtube_video_id: str | None
    status: str
    reason: str
    start_from: str | None = None
    new_job_id: str | None = None
    active_job_id: str | None = None


def inspect_cookie_file(path: str | os.PathLike[str] | None = None, *, now: datetime | None = None) -> CookieHealth:
    cookie_path = str(path or settings.ytdlp_cookies_file or "")
    if not cookie_path:
        return CookieHealth(path="", exists=False, readable=False, status="not_configured")

    p = Path(cookie_path)
    health = CookieHealth(path=str(p), exists=p.exists(), readable=False)
    if not p.exists():
        health.warnings.append("cookie_file_missing")
        return health

    try:
        stat = p.stat()
        health.age_seconds = max(0.0, datetime.now().timestamp() - stat.st_mtime)
        lines = p.read_text(errors="replace").splitlines()
        health.readable = True
    except OSError as exc:
        health.status = "unreadable"
        health.warnings.append(f"cookie_file_unreadable:{exc.__class__.__name__}")
        return health

    now_ts = int((now or datetime.now(UTC)).timestamp())
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _path, _secure, expiry, name, _value = parts[:7]
        health.cookie_count += 1
        if "youtube.com" in domain or "google.com" in domain:
            if "youtube.com" in domain:
                health.youtube_cookie_count += 1
            if name in AUTH_COOKIE_NAMES:
                health.auth_cookie_count += 1
        try:
            expiry_int = int(expiry)
        except ValueError:
            continue
        if expiry_int == 0:
            health.session_cookie_count += 1
        elif expiry_int < now_ts:
            health.expired_cookie_count += 1

    if health.cookie_count == 0:
        health.status = "empty"
        health.warnings.append("cookie_file_empty")
    elif health.auth_cookie_count == 0:
        health.status = "anonymous_only"
        health.warnings.append("no_auth_like_youtube_cookies")
    elif health.expired_cookie_count >= health.cookie_count:
        health.status = "expired"
        health.warnings.append("all_cookies_expired")
    else:
        health.status = "ok"

    return health


def get_ytdlp_version_health(*, warn_days: int = 75, now: datetime | None = None) -> YtdlpVersionHealth:
    version = yt_dlp.version.__version__
    age_days: int | None = None
    status = "unknown"
    warning = None
    try:
        released = datetime.strptime(version[:10], "%Y.%m.%d").replace(tzinfo=UTC)
        age_days = ((now or datetime.now(UTC)) - released).days
        status = "old" if age_days > warn_days else "ok"
        if status == "old":
            warning = f"yt-dlp {version} is {age_days} days old"
    except ValueError:
        warning = f"could not parse yt-dlp version {version}"
    return YtdlpVersionHealth(version=version, age_days=age_days, status=status, warning=warning)


def _probe_opts(*, cookie_path: str | None, output_dir: Path, test_download: bool) -> dict:
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if test_download:
        opts["test"] = True
    if cookie_path:
        opts["cookiefile"] = cookie_path
    return opts


def probe_youtube_media_download(
    url: str,
    *,
    use_cookies: bool,
    test_download: bool = False,
    cookie_path: str | None = None,
) -> ProbeResult:
    label = "with_cookies" if use_cookies else "without_cookies"
    tmp = Path(tempfile.mkdtemp(prefix=f"yt-probe-{label}-"))
    try:
        opts = _probe_opts(
            cookie_path=(cookie_path or settings.ytdlp_cookies_file) if use_cookies else None,
            output_dir=tmp,
            test_download=test_download,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        downloaded_bytes = sum(p.stat().st_size for p in tmp.glob("*") if p.is_file())
        return ProbeResult(
            label=label,
            ok=True,
            title=info.get("title"),
            duration=info.get("duration"),
            downloaded_bytes=downloaded_bytes,
        )
    except Exception as exc:  # noqa: BLE001 - probe reports external failure details
        return ProbeResult(label=label, ok=False, error=str(exc)[:500])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_download_403_failure(job: Job) -> bool:
    if job.job_type != "pipeline" or job.status != "failed":
        return False
    stage = (job.current_stage or "").lower()
    signature = (job.failure_signature or "").lower()
    error = (job.error_message or "").lower()
    if stage != "download":
        return False
    return any(marker in signature or marker in error for marker in DOWNLOAD_FORBIDDEN_SIGNATURE_MARKERS)


def summarize_recent_download_403_failures(
    db: Session,
    *,
    hours: float = 4.0,
    threshold: int = 3,
    limit: int = 25,
) -> DownloadFailureSummary:
    since = datetime.now(UTC) - timedelta(hours=hours)
    jobs = (
        db.query(Job)
        .filter(
            Job.job_type == "pipeline",
            Job.status == "failed",
            Job.current_stage == "download",
            Job.hidden_from_queue.is_(False),
        )
        .order_by(Job.completed_at.desc(), Job.created_at.desc())
        .limit(limit)
        .all()
    )
    matching = []
    for job in jobs:
        failed_at = _as_utc(job.completed_at or job.last_activity_at or job.created_at)
        if failed_at is not None and failed_at < since:
            continue
        if is_download_403_failure(job):
            matching.append(job)

    videos: list[dict] = []
    for job in matching:
        video = db.get(Video, job.video_id) if job.video_id else None
        videos.append(
            {
                "job_id": str(job.id),
                "video_id": str(job.video_id) if job.video_id else None,
                "youtube_video_id": getattr(video, "youtube_video_id", None),
                "title": getattr(video, "title", None),
                "failure_signature": job.failure_signature,
            }
        )
    signature = matching[0].failure_signature if matching else None
    return DownloadFailureSummary(
        count=len(matching),
        since=since,
        signature=signature,
        videos=videos,
        threshold_met=len(matching) >= threshold,
    )


def find_download_403_retry_candidates(
    db: Session,
    *,
    youtube_ids: list[str] | None = None,
    limit: int = 25,
) -> list[Job]:
    query = (
        db.query(Job)
        .join(Video, Video.id == Job.video_id)
        .filter(
            Job.job_type == "pipeline",
            Job.status == "failed",
            Job.current_stage == "download",
            Job.hidden_from_queue.is_(False),
        )
        .order_by(Job.created_at.asc())
    )
    if youtube_ids:
        query = query.filter(Video.youtube_video_id.in_(youtube_ids))
    jobs = query.limit(limit).all()
    return [job for job in jobs if is_download_403_failure(job)]


def retry_download_403_failures(
    db: Session,
    *,
    youtube_ids: list[str] | None = None,
    dry_run: bool = True,
    limit: int = 25,
    max_jobs: int | None = None,
) -> list[DownloadRetryDecision]:
    decisions: list[DownloadRetryDecision] = []
    jobs = find_download_403_retry_candidates(db, youtube_ids=youtube_ids, limit=limit)
    if max_jobs is not None:
        jobs = jobs[:max_jobs]

    for job in jobs:
        video = db.get(Video, job.video_id) if job.video_id else None
        youtube_id = getattr(video, "youtube_video_id", None)
        job_id = str(job.id)
        if not video:
            decisions.append(DownloadRetryDecision(job_id, youtube_id, "skipped", "missing_video"))
            continue
        if get_retry_block_reason(job):
            decisions.append(DownloadRetryDecision(job_id, youtube_id, "skipped", "manual_review"))
            continue

        allocation = allocate_pipeline_attempt_sync(db, job.video_id)
        if allocation.status == ATTEMPT_RESULT_ALREADY_ACTIVE:
            decisions.append(
                DownloadRetryDecision(
                    job_id,
                    youtube_id,
                    "skipped",
                    "active_attempt_exists",
                    active_job_id=str(allocation.active_job.id) if allocation.active_job else None,
                )
            )
            continue
        if allocation.status == ATTEMPT_RESULT_BLOCKED:
            decisions.append(DownloadRetryDecision(job_id, youtube_id, "skipped", allocation.reason or "blocked"))
            continue

        start_from, artifact_check_result = detect_resume_point_sync(db, video)
        if dry_run:
            decisions.append(DownloadRetryDecision(job_id, youtube_id, "planned", "dry_run", start_from=start_from))
            continue

        video.status = "pending"
        video.error_message = None
        video.dismissed_at = None
        video.dismissed_reason = None
        attempt = create_pipeline_attempt_from_allocation_sync(
            db,
            allocation,
            status="queued",
            current_stage=PIPELINE_STAGE_QUEUED,
            progress_message=lambda attempt_number: (
                f"Queued operator download retry attempt #{attempt_number} "
                f"(resuming from {start_from.split('.')[-1]})"
            ),
            channel_id=job.channel_id,
            batch_id=job.batch_id,
            supersedes_job_id=job.id,
            attempt_creation_reason=ATTEMPT_REASON_OPERATOR_ACTION,
            last_artifact_check_result=artifact_check_result,
        )
        if attempt.status != ATTEMPT_RESULT_CREATED or attempt.job is None:
            decisions.append(
                DownloadRetryDecision(job_id, youtube_id, "skipped", attempt.reason or attempt.status)
            )
            continue

        retry_job = attempt.job
        hide_superseded_failed_jobs_sync(db, video_id=job.video_id, superseded_by_job_id=retry_job.id)
        video_uuid = str(job.video_id)
        retry_job_id = str(retry_job.id)
        enqueue_pipeline_job_after_commit(
            db,
            retry_job,
            publish=lambda: run_pipeline_from(video_uuid, start_from=start_from, job_id=retry_job_id),
        )
        decisions.append(
            DownloadRetryDecision(
                job_id,
                youtube_id,
                "queued",
                "download_403_retry",
                start_from=start_from,
                new_job_id=retry_job_id,
            )
        )

    return decisions


def resolve_db_url_sync(project_root: Path) -> str:
    explicit = os.environ.get("DATABASE_URL_SYNC")
    if explicit:
        return explicit
    native_env = project_root / ".env.native"
    if native_env.exists():
        for line in native_env.read_text().splitlines():
            if line.startswith("DATABASE_URL_SYNC="):
                return line.split("=", 1)[1].strip()
    return settings.database_url_sync


def create_native_sync_engine(project_root: Path):
    return create_engine(resolve_db_url_sync(project_root))
