#!/usr/bin/env python3
"""Re-embed all existing videos with the new embedding model and chunking logic.

Usage:
    python scripts/reembed_all.py                  # re-embed all completed videos
    python scripts/reembed_all.py --dry-run         # preview without writing
    python scripts/reembed_all.py --video-id UUID   # re-embed a single video
"""
import argparse
import sys
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Ensure the project root is importable
sys.path.insert(0, ".")

from app.config import settings
from app.models.embedding_chunk import EmbeddingChunk
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.video import Video
from app.services.embedding import chunk_and_embed, chunk_and_embed_summary


BATCH_SIZE = 10


def reembed_video(db: Session, video: Video, transcription: Transcription, dry_run: bool = False) -> int:
    """Re-embed a single video. Returns the number of new chunks created."""
    segments = [
        {
            "start": s.start_time,
            "end": s.end_time,
            "text": s.text,
            "speaker": getattr(s, "speaker", None),
        }
        for s in transcription.segments
    ]

    if not segments:
        return 0

    if dry_run:
        print(f"  [DRY RUN] Would delete existing chunks and re-embed {len(segments)} segments")
        return 0

    # Delete existing chunks for this video
    db.query(EmbeddingChunk).filter(EmbeddingChunk.video_id == video.id).delete()

    # Generate new embeddings with new model + chunking
    transcript_chunks = chunk_and_embed(
        segments,
        model_cache_dir=settings.model_cache_dir,
    )
    summary = db.query(Summary).filter(Summary.video_id == video.id).first()
    summary_chunks = []
    if summary and summary.content.strip():
        summary_chunks = chunk_and_embed_summary(
            summary.content,
            model_cache_dir=settings.model_cache_dir,
        )

    chunks = transcript_chunks + summary_chunks

    for index, chunk in enumerate(chunks):
        ec = EmbeddingChunk(
            transcription_id=transcription.id,
            video_id=video.id,
            chunk_index=index,
            chunk_text=chunk["chunk_text"],
            start_time=chunk.get("start_time"),
            end_time=chunk.get("end_time"),
            embedding=chunk["embedding"],
            token_count=chunk.get("token_count"),
            speaker=chunk.get("speaker"),
        )
        db.add(ec)

    return len(chunks)


def main():
    parser = argparse.ArgumentParser(description="Re-embed all videos with new model and chunking")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing changes")
    parser.add_argument("--video-id", type=str, help="Re-embed a single video by UUID")
    args = parser.parse_args()

    engine = create_engine(settings.database_url_sync)

    with Session(engine) as db:
        if args.video_id:
            vid = uuid.UUID(args.video_id)
            video = db.get(Video, vid)
            if not video:
                print(f"Video {args.video_id} not found")
                sys.exit(1)
            transcription = db.query(Transcription).filter(Transcription.video_id == vid).first()
            if not transcription:
                print(f"No transcription found for video {args.video_id}")
                sys.exit(1)

            print(f"Re-embedding: {video.title}")
            count = reembed_video(db, video, transcription, dry_run=args.dry_run)
            if not args.dry_run:
                db.commit()
                print(f"  Created {count} chunks")
            print("Done.")
            return

        # All completed videos
        videos = db.query(Video).filter(Video.status == "completed").all()
        total = len(videos)
        print(f"Found {total} completed videos to re-embed")

        if total == 0:
            print("Nothing to do.")
            return

        processed = 0
        total_chunks = 0

        for i, video in enumerate(videos, 1):
            transcription = db.query(Transcription).filter(Transcription.video_id == video.id).first()
            if not transcription:
                print(f"  [{i}/{total}] SKIP {video.title} (no transcription)")
                continue

            print(f"  [{i}/{total}] {video.title}")
            count = reembed_video(db, video, transcription, dry_run=args.dry_run)
            total_chunks += count
            processed += 1

            # Batch commit every BATCH_SIZE videos
            if not args.dry_run and processed % BATCH_SIZE == 0:
                db.commit()
                print(f"  Committed batch ({processed}/{total})")

        # Final commit for remaining
        if not args.dry_run and processed % BATCH_SIZE != 0:
            db.commit()

        print(f"\nDone. Processed {processed}/{total} videos, created {total_chunks} chunks total.")


if __name__ == "__main__":
    main()
