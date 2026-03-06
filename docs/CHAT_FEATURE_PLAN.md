# Chat with Transcripts — Feature Plan

**Project:** youtube-transcriber  
**Date:** 2026-03-06  
**Status:** Planning  

---

## Goal

Add a conversational chat interface that lets users ask questions grounded in their video transcript library. Users toggle videos on/off to control which content is searchable/chattable. Available via web dashboard (ChatGPT-style UI) and a dedicated Telegram bot.

---

## Architecture Overview

```
User question
    │
    ▼
┌──────────────────────┐
│  Chat API endpoint   │  POST /api/chat
│  (FastAPI)           │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  RAG Retrieval       │  Hybrid search (BM25 + vector)
│  Filter: chat_enabled│  across toggled-on videos only
│  Top K chunks        │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  LLM (Sonnet)        │  System prompt + retrieved chunks
│  Multi-turn context  │  + conversation history + question
└──────┬───────────────┘
       │
       ▼
    Answer (with source references)
```

---

## Phases

### Phase 1: Toggle System (DB + API + UI)

**Database changes:**
- Add `chat_enabled BOOLEAN DEFAULT true` column to `videos` table
- Add `chat_enabled BOOLEAN DEFAULT true` column to `channels` table
- Alembic migration for both columns

**API endpoints:**
- `PATCH /api/videos/{video_id}/chat-toggle` — body: `{"enabled": true/false}` → updates video
- `PATCH /api/channels/{channel_id}/chat-toggle` — body: `{"enabled": true/false}` → updates channel AND all its videos (bulk)
- `GET /api/videos?chat_enabled=true` — filter videos by toggle state

**UI changes (library page):**
- Add inline toggle switch on each video card (top-right corner)
- Add master toggle on channel cards
- Toggle sends HTMX PATCH, updates state without page reload
- Visual indicator: toggled-off videos appear dimmed/muted

**Search filter:**
- Update `semantic_search()` in `app/services/search.py` to add `WHERE v.chat_enabled = true` filter
- Make this the default for chat; existing search page keeps showing all videos

---

### Phase 2: Chat Backend (API + RAG + Sessions)

**Chat session model:**
- New table `chat_sessions`:
  - `id` UUID PK
  - `title` VARCHAR(255) — auto-generated from first message or user-set
  - `created_at`, `updated_at` TIMESTAMP
  - `platform` VARCHAR(20) — 'web' or 'telegram'
  - `telegram_chat_id` BIGINT NULLABLE — for telegram sessions
- New table `chat_messages`:
  - `id` UUID PK
  - `session_id` UUID FK → chat_sessions
  - `role` VARCHAR(10) — 'user' or 'assistant'
  - `content` TEXT
  - `sources` JSONB NULLABLE — list of `{video_id, video_title, chunk_text, start_time, end_time, similarity}`
  - `model` VARCHAR(64) — model used for generation
  - `prompt_tokens` INT, `completion_tokens` INT
  - `created_at` TIMESTAMP

**Chat API endpoints:**
- `POST /api/chat/sessions` — create new session, returns `session_id`
- `GET /api/chat/sessions` — list sessions (paginated, ordered by updated_at DESC)
- `GET /api/chat/sessions/{session_id}` — get session with messages
- `DELETE /api/chat/sessions/{session_id}` — delete session
- `PATCH /api/chat/sessions/{session_id}` — rename session
- `POST /api/chat/sessions/{session_id}/messages` — send message, get response
  - Body: `{"content": "user question"}`
  - Response: streamed or full `{"role": "assistant", "content": "...", "sources": [...]}`

**RAG pipeline (in `app/services/chat.py`):**
1. Take user question + conversation history (last N messages for context)
2. Generate search query from the question (use the question directly, or optionally rephrase with LLM for multi-turn context)
3. Run hybrid search with `chat_enabled=true` filter, retrieve top 10 chunks
4. Build prompt:
   ```
   System: You are a helpful assistant that answers questions based on 
   video transcript content. Ground your answers in the provided context.
   When referencing specific information, cite the source video and timestamp.
   If the context doesn't contain enough information to answer, say so.
   
   Context: [top 10 chunks with video title + timestamps]
   
   Conversation history: [last 5 message pairs]
   
   User: [current question]
   ```
5. Call Anthropic Sonnet, return response + sources

**Config:**
- `chat_model: str = "claude-sonnet-4-20250514"` — configurable in Settings
- `chat_max_history: int = 10` — max message pairs to include as context
- `chat_retrieval_top_k: int = 10` — chunks to retrieve per question

---

### Phase 3: Web Dashboard Chat UI

**Layout:**
```
┌─────────────────┬──────────────────────────────────────┐
│  Sidebar         │  Chat Area                          │
│                  │                                      │
│  [+ New Chat]    │  ┌────────────────────────────────┐  │
│                  │  │ Video context: 5 videos active │  │
│  Today           │  └────────────────────────────────┘  │
│  ├─ Game Theory  │                                      │
│  │  analysis     │  🤖 Based on the transcripts...     │
│  └─ Iran war     │                                      │
│    discussion    │  You: What about...                  │
│                  │                                      │
│  Yesterday       │  🤖 Looking at episode 9...         │
│  └─ ...          │                                      │
│                  │  ┌────────────────────────────────┐  │
│                  │  │ Ask about your videos...    ⏎  │  │
│                  │  └────────────────────────────────┘  │
└─────────────────┴──────────────────────────────────────┘
```

**Components:**
- Left sidebar: session list, grouped by date, "New Chat" button at top
- Chat area: messages with markdown rendering, source citations as expandable cards
- Source cards show: video title, timestamp range, relevance %, snippet
- Input bar at bottom with send button
- Header shows count of active (toggled-on) videos
- Session auto-titles from first message (via LLM or first 50 chars)

**Tech:**
- HTMX for sidebar interactions (create/delete/rename sessions)
- Fetch API + streaming for chat messages (SSE or chunked response)
- Messages render with markdown (use marked.js or similar lightweight lib)
- Auto-scroll to bottom on new messages

**New pages/routes:**
- `GET /chat` — main chat page
- `GET /chat/{session_id}` — load specific session
- Nav bar: add "Chat" link between "Library" and "Search"

---

### Phase 4: Telegram Bot

**Architecture:**
- Separate Telegram bot (new bot token via BotFather)
- Runs as a lightweight process alongside the existing stack
- Shares the same DB and RAG pipeline
- Implemented as `app/telegram_bot.py` using `python-telegram-bot` library

**Commands:**
- `/start` — welcome message + instructions
- `/new` — start a new chat session (clears context)
- `/sessions` — list recent sessions
- `/status` — show how many videos are toggled on, total library size
- `/videos` — list toggled-on videos

**Conversation flow:**
- Each Telegram chat maps to a `chat_session` (platform='telegram', telegram_chat_id=chat.id)
- `/new` creates a new session, archives the current one
- Regular messages → POST to the same chat API internally → return response
- Source citations formatted as inline text: `[📹 Video Title @ 12:34]`
- Long responses split at 4096 char Telegram limit

**Config:**
- `telegram_bot_token: str = ""` — separate bot token
- `telegram_allowed_users: list[int] = []` — allowlist of Telegram user IDs

**Process management:**
- Add to docker-compose as a new service, or run via launchd like the worker
- Shares the same `.env` for DB credentials and API keys

---

## Implementation Order

```
Phase 1 (toggles)  →  Phase 2 (chat backend)  →  Phase 3 (web UI)  →  Phase 4 (telegram bot)
```

- Phases 1-2 are backend-only, can be tested via API
- Phase 3 is frontend, depends on Phase 2
- Phase 4 is independent of Phase 3, depends on Phase 2

---

## Database Migrations

**Migration 005:** Add chat_enabled to videos and channels
```sql
ALTER TABLE videos ADD COLUMN chat_enabled BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE channels ADD COLUMN chat_enabled BOOLEAN NOT NULL DEFAULT true;
```

**Migration 006:** Create chat_sessions and chat_messages tables

---

## Dependencies

- `anthropic` (already installed) — for Sonnet chat
- `python-telegram-bot` (new) — for Phase 4 Telegram bot
- `marked.js` or `markdown-it` (CDN) — for Phase 3 markdown rendering in chat UI

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Context window overflow with many chunks + long history | Limit to top 10 chunks + last 5 message pairs; truncate if over 150k tokens |
| Slow response for complex multi-video questions | Stream responses (SSE); show "thinking" indicator |
| Telegram bot token management | Store in .env, document in README |
| Chat sessions growing indefinitely | Add auto-archive for sessions older than 30 days |
| Cost — Sonnet per chat message | Configurable model; can switch to Haiku for lighter use |

---

## Acceptance Criteria

- [ ] Videos have toggle switch in library UI; state persists in DB
- [ ] Channel toggle bulk-updates all its videos
- [ ] Search respects toggle filter
- [ ] Chat sessions with multi-turn conversation history
- [ ] RAG retrieval only from toggled-on videos
- [ ] Source citations with video title + timestamps
- [ ] ChatGPT-style web UI with sidebar session list
- [ ] Dedicated Telegram bot with /new, /sessions, conversational flow
- [ ] Configurable model (Sonnet default, Haiku option)
- [ ] All existing tests pass + new tests for chat + toggle features
