# YouTube Transcriber

A web app that lets you submit YouTube videos (or channels), transcribe audio, generate summaries, and search transcript content.

## Documentation Map

Use this section to quickly find the right document.

- **Start here (nontechnical):** [`docs/user-guide.md`](docs/user-guide.md)
- **Project implementation plan:** [`docs/claude-plan.md`](docs/claude-plan.md)
- **What changed in the implementation:** [`docs/claude-diff-summary.md`](docs/claude-diff-summary.md)
- **Prior test verification notes:** [`docs/claude-test-results.txt`](docs/claude-test-results.txt)

## Quick Start (Technical)

1. Copy environment file:
   ```bash
   cp .env.example .env
   ```
2. Fill in required values in `.env` (especially API keys).
3. Start services:
   ```bash
   docker compose up --build
   ```
4. Open the app:
   - `http://localhost:8000`

## What the App Does

- Submit a **single video URL** for full processing.
- Submit a **channel URL**, choose videos, and process in batches.
- View **job queue** and status updates.
- Read **transcript + summary** for each processed video.
- Run **semantic search** across transcript chunks.

## Main Areas in the UI

- `/` Dashboard
- `/submit` Submit videos/channels
- `/videos` Video library
- `/channels` Channel library
- `/search` Semantic search
- `/queue` Active and completed jobs

## Who Should Read What

- Nontechnical operators: `docs/user-guide.md`
- Developers setting up or modifying the system: this `README.md` + docs in `docs/`
