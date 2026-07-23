---
name: yt-chat
description: Search or ask grounded questions across local YouTube transcripts through ytctl and the service's scoped RAG chat.
---

# yt-chat

Use `/Users/sentryclaw/Projects/youtube-transcriber/.venv/bin/ytctl`. Do not call
OpenAI or Anthropic directly and do not load transcript data from PostgreSQL.
The service owns retrieval scope, routing, budgets, and citations.

Use `ytctl search QUERY` for evidence. Use `ytctl ask QUESTION`, optionally with
`--video-id` or `--channel-id`, for server-side RAG. Report returned sources and
timestamps. Continue with `--session-id` only when requested. Fetch a full raw
transcript only when the user explicitly asks for it.
