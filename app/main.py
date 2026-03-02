from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routers import channels, jobs, pages, search, transcriptions, videos

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
)


def create_app() -> FastAPI:
    application = FastAPI(title="YouTube Transcriber", version="0.1.0")

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
