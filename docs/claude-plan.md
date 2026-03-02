# YouTube Transcriber — Implementation Plan

## Goal
Build a full-stack application that downloads YouTube audio (single video or entire channel), transcribes it locally with faster-whisper, summarises via Claude API, and provides a searchable web portal with semantic search via pgvector.

## Tech Stack
| Layer | Choice |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Frontend | Jinja2 + HTMX + daisyUI v5 + Tailwind CSS v4 (light theme, sidebar layout) |
| Transcription | faster-whisper (CTranslate2, CPU) |
| LLM | Claude API (sonnet) for summarisation |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 (384-dim) |
| Search | PostgreSQL + pgvector (HNSW index) |
| Task queue | Celery + Redis |
| Infra | Docker Compose (postgres, redis, web, worker) |

## Implementation Phases

### Phase 1-6: Foundation through Polish (DONE)
Full application built with all core features.

### Phase 7: UI Migration — Pico CSS → daisyUI + Tailwind CSS (DONE)
- Replaced Pico CSS with daisyUI v5 + Tailwind CSS v4
- Light-only theme with Inter font

### Phase 8: Bug Fix + UI Restructuring (DONE)
- [x] Fix transcription bug: `segment.avg_log_prob` → `segment.avg_logprob`
- [x] Fix search endpoint to accept form data (HTMX compatibility)
- [x] Replace top navbar with sidebar layout (Light Able dashboard aesthetic)
- [x] Merge Submit + Queue into Dashboard page
- [x] Merge Videos + Channels into Library page with tabs
- [x] Add sidebar navigation: Dashboard, Library, Search
- [x] Add stat cards with icons (Light Able style)
- [x] Add consistent card borders (`border border-base-200`)
- [x] Update breadcrumbs to point to Library/Dashboard
- [x] Legacy routes (/submit, /channels) redirect to new locations
- [x] Full pipeline validated end-to-end: download → transcribe → summarize → embed
- [x] All routes verified returning 200

## Navigation Structure (Current)
```
Sidebar:
  Dashboard (/)     — Stats, Submit forms, Queue, Recent Jobs
  Library (/library) — Videos tab | Channels tab
  Search (/search)  — Semantic search

Detail pages:
  /videos/{id}      — Video detail with transcript + summary
  /channels/{id}    — Channel detail with video list
  /jobs/{id}        — Job detail with pipeline steps
```
