from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.routers import agents, channels, chat, jobs, pages, search, transcriptions, videos
from app.routers import llm_usage

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
)

logger = structlog.get_logger()


def _warm_embedding_model() -> None:
    """Preload the shared sentence-transformers model so the first search
    doesn't pay a multi-second cold-start. Best-effort: if the optional
    dependency is missing we log and continue.
    """
    try:
        from app.services.embedding import _get_embedding_model

        _get_embedding_model(settings.model_cache_dir)
        logger.info("embedding_model_warm", model=settings.embedding_model)
    except ImportError as exc:
        logger.warning("embedding_model_warm_skipped", reason=str(exc))
    except Exception as exc:  # noqa: BLE001 — best-effort warm; never block boot
        logger.warning("embedding_model_warm_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warm_embedding_model()
    yield

# Paths that skip API key auth
_AUTH_SKIP_PREFIXES = ("/health", "/static/", "/")


def _auth_required(path: str) -> bool:
    """Return True if this path requires API key authentication."""
    if path == "/":
        return False
    for prefix in _AUTH_SKIP_PREFIXES:
        if path == prefix or (prefix.endswith("/") and path.startswith(prefix)):
            return False
    return True


def create_app() -> FastAPI:
    application = FastAPI(title="YouTube Transcriber", version="0.1.0", lifespan=lifespan)

    # API key middleware
    @application.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        if settings.api_key and _auth_required(request.url.path):
            key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            if key != settings.api_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key. Provide X-API-Key header or api_key query param."},
                )
        return await call_next(request)

    if not settings.api_key:
        logger.warning("api_auth_disabled", reason="API_KEY not set — running in open dev mode")

    # Static files
    static_dir = Path(__file__).parent / "static"
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Templates
    templates_dir = Path(__file__).parent / "templates"
    application.state.templates = Jinja2Templates(directory=str(templates_dir))

    # Register template filters
    application.state.templates.env.filters["format_duration"] = format_duration
    application.state.templates.env.filters["format_timestamp"] = format_timestamp

    # Routers
    application.include_router(pages.router)
    application.include_router(videos.router)
    application.include_router(channels.router)
    application.include_router(search.router)
    application.include_router(jobs.router)
    application.include_router(transcriptions.router)
    application.include_router(chat.router)
    application.include_router(agents.router)
    application.include_router(llm_usage.router)

    return application


def format_duration(seconds: float | None) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_timestamp(seconds: float | None) -> str:
    """Format seconds into a timestamp string for transcript segments."""
    if seconds is None:
        return "0:00"
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


app = create_app()
