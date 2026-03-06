---
name: yt-chat
description: Chat with transcribed YouTube video content — ask questions about a video's transcript and get grounded answers. Use when asked to chat with a video, ask questions about a YouTube video's content, query transcript content, or discuss what was said in a video. Requires the youtube-transcriber Docker stack on localhost:8000 and a previously transcribed video (use yt-transcribe skill first if needed).
---

# yt-chat

Ask questions about transcribed YouTube videos and get answers grounded in the transcript.

## Prerequisites

1. The youtube-transcriber Docker stack must be running on `localhost:8000`
2. The video must already be transcribed (use the `yt-transcribe` skill to transcribe first)
3. Either `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` must be set for the LLM chat

## Commands

### List available videos

```bash
python3 scripts/chat.py --list
```

Shows transcribed videos with their UUIDs (needed for chatting).

### Get raw transcript

```bash
python3 scripts/chat.py --video-id <uuid>
```

Returns the full transcript JSON without sending to an LLM.

### Ask a question about a video

```bash
python3 scripts/chat.py --video-id <uuid> -q "What were the main points discussed?"
```

Retrieves the transcript, sends it with the question to an LLM, and returns a grounded answer.

### Search across all transcripts and ask

```bash
python3 scripts/chat.py --search "machine learning" -q "What approaches were recommended?"
```

Uses semantic search to find relevant transcript chunks across all videos, then answers the question using those chunks as context.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | Primary LLM provider |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Custom endpoint |
| `CHAT_MODEL` | `gpt-4o-mini` | Model for chat |
| `ANTHROPIC_API_KEY` | — | Fallback LLM provider |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Anthropic model |

## Workflow

1. Use `--list` to find the video UUID
2. Optionally use `--video-id <uuid>` (no question) to preview the transcript
3. Use `--video-id <uuid> -q "your question"` to chat
4. Or use `--search "topic" -q "question"` to query across all transcripts

## Notes

- Semantic search requires sentence-transformers installed in the web container (may not be available)
- For long transcripts, the full text is sent as context — be mindful of token limits
- The script uses `urllib` only (no pip dependencies needed on the host)
