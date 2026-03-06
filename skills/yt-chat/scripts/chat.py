#!/usr/bin/env python3
"""Chat with a transcribed YouTube video's content.

Usage:
  chat.py --video-id <uuid> --question "What was the main point?"
  chat.py --search "topic keywords" --question "What do experts say about this?"
  chat.py --video-id <uuid>   (no question = return full transcript)

Retrieves transcript from the local youtube-transcriber API and uses
the OpenAI-compatible API (or Anthropic) to answer questions grounded
in the transcript content.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

API = "http://localhost:8000"


def fetch_transcription(video_id: str) -> dict | None:
    """Fetch transcription for a video by UUID."""
    try:
        req = urllib.request.Request(f"{API}/api/transcriptions/{video_id}")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def search_videos(query: str) -> list[dict]:
    """Search transcripts via the semantic search endpoint."""
    data = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(f"{API}/api/search", data=data)
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            return result.get("results", [])
    except Exception as e:
        print(f"Search failed: {e}", file=sys.stderr)
        return []


def list_videos_from_db(limit: int = 10) -> str:
    """List videos from Postgres for discovery."""
    try:
        result = subprocess.run(
            [
                "docker", "exec", "youtube-transcriber-postgres-1",
                "psql", "-U", "transcriber", "-d", "transcriber",
                "-t", "-A", "-F", "|",
                "-c", f"""
                SELECT v.id, v.title, v.status
                FROM videos v
                WHERE v.status = 'completed'
                ORDER BY v.created_at DESC
                LIMIT {limit};
                """
            ],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Could not list videos: {e}"


def build_context(transcript: dict, video_title: str = "") -> str:
    """Build context string from transcript data.

    If speaker diarization is available, formats the transcript with speaker
    labels and timestamps for rich context.
    """
    parts = []
    if video_title:
        parts.append(f"Video title: {video_title}")
    parts.append(f"Language: {transcript.get('language_detected', transcript.get('language', 'unknown'))}")
    parts.append(f"Word count: {transcript.get('word_count', 'unknown')}")

    speakers = transcript.get("speakers", [])
    if speakers:
        parts.append(f"Speakers: {', '.join(speakers)} ({len(speakers)} total)")

    parts.append("")
    parts.append("--- TRANSCRIPT ---")

    # Use speaker-labeled segments if available
    segments = transcript.get("segments", [])
    has_speakers = any(s.get("speaker") for s in segments)

    if has_speakers and segments:
        for seg in segments:
            speaker = seg.get("speaker", "")
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = seg.get("text", "")
            # Format: [SPEAKER_00] 0:00 - 0:15: Welcome to the show...
            start_fmt = f"{int(start // 60)}:{int(start % 60):02d}"
            end_fmt = f"{int(end // 60)}:{int(end % 60):02d}"
            if speaker:
                parts.append(f"[{speaker}] {start_fmt} - {end_fmt}: {text}")
            else:
                parts.append(f"{start_fmt} - {end_fmt}: {text}")
    else:
        parts.append(transcript.get("full_text", ""))

    return "\n".join(parts)


def chat_with_transcript(context: str, question: str) -> str:
    """Send question + transcript context to LLM and return the answer."""
    # Try OpenAI-compatible API first (works with most providers)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    api_base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("CHAT_MODEL", "gpt-4o-mini")

    if not api_key:
        # Fallback: try Anthropic
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            return _chat_anthropic(context, question, anthropic_key)
        print("Error: Set OPENAI_API_KEY or ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    payload = json.dumps({
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that answers questions based on "
                    "YouTube video transcripts. Ground your answers in the transcript "
                    "content provided. If the transcript doesn't contain enough "
                    "information to answer, say so. Reference specific parts of the "
                    "transcript when relevant."
                )
            },
            {
                "role": "user",
                "content": f"{context}\n\n--- QUESTION ---\n{question}"
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.3
    }).encode()

    req = urllib.request.Request(
        f"{api_base}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )

    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]


def _chat_anthropic(context: str, question: str, api_key: str) -> str:
    """Fallback: use Anthropic API."""
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    payload = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "system": (
            "You are a helpful assistant that answers questions based on "
            "YouTube video transcripts. Ground your answers in the transcript "
            "content provided. If the transcript doesn't contain enough "
            "information to answer, say so."
        ),
        "messages": [
            {
                "role": "user",
                "content": f"{context}\n\n--- QUESTION ---\n{question}"
            }
        ]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    )

    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        return result["content"][0]["text"]


def main():
    parser = argparse.ArgumentParser(description="Chat with transcribed YouTube content")
    parser.add_argument("--video-id", help="Video UUID to chat about")
    parser.add_argument("--search", help="Search query to find relevant transcript chunks")
    parser.add_argument("--question", "-q", help="Question to ask about the content")
    parser.add_argument("--list", action="store_true", help="List available transcribed videos")
    parser.add_argument("--raw", action="store_true", help="Return raw transcript (no LLM)")
    args = parser.parse_args()

    if args.list:
        videos = list_videos_from_db()
        if not videos:
            print("No transcribed videos found.")
        else:
            print("Transcribed videos (id | title | status):")
            print(videos)
        return

    if not args.video_id and not args.search:
        parser.error("Provide --video-id or --search (or --list to browse)")

    # Build context
    context = ""
    video_title = ""

    if args.video_id:
        transcript = fetch_transcription(args.video_id)
        if not transcript:
            print(f"No transcription found for video {args.video_id}", file=sys.stderr)
            sys.exit(1)

        # Get video title from DB
        try:
            result = subprocess.run(
                [
                    "docker", "exec", "youtube-transcriber-postgres-1",
                    "psql", "-U", "transcriber", "-d", "transcriber",
                    "-t", "-A",
                    "-c", f"SELECT title FROM videos WHERE id = '{args.video_id}';"
                ],
                capture_output=True, text=True, timeout=10
            )
            video_title = result.stdout.strip()
        except Exception:
            pass

        context = build_context(transcript, video_title)

        if args.raw or not args.question:
            print(json.dumps({
                "video_id": args.video_id,
                "title": video_title,
                "transcript": transcript.get("full_text", ""),
                "word_count": transcript.get("word_count"),
                "language": transcript.get("language"),
                "segments": len(transcript.get("segments", []))
            }, indent=2))
            return

    elif args.search:
        results = search_videos(args.search)
        if not results:
            print(f"No results found for: {args.search}", file=sys.stderr)
            sys.exit(1)

        # Build context from search results
        parts = [f"Search results for: {args.search}\n"]
        for r in results:
            parts.append(f"[Video: {r.get('video_title', 'unknown')} | "
                        f"Similarity: {r.get('similarity', 0):.2%}]")
            parts.append(r.get("chunk_text", ""))
            parts.append("")
        context = "\n".join(parts)

        if not args.question:
            print(context)
            return

    # Chat
    answer = chat_with_transcript(context, args.question)
    print(answer)


if __name__ == "__main__":
    main()
