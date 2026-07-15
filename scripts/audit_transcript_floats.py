#!/usr/bin/env python3
"""Audit transcript float fields for non-JSON-safe values."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine, text

from app.config import settings


BAD_FLOAT_SQL = "('NaN','Infinity','-Infinity')"


def scalar(conn, sql: str) -> int:
    return int(conn.execute(text(sql)).scalar_one())


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit transcript float fields for NaN/Infinity values")
    parser.add_argument(
        "--database-url",
        default="",
        help="SQLAlchemy sync database URL. Defaults to app settings DATABASE_URL_SYNC.",
    )
    parser.add_argument(
        "--native-db",
        action="store_true",
        help="Use the local host PostgreSQL URL from .env.native.",
    )
    parser.add_argument(
        "--fix-confidence",
        action="store_true",
        help="Set non-finite optional segment confidence values to NULL.",
    )
    args = parser.parse_args()

    database_url = args.database_url
    if args.native_db and not database_url:
        database_url = settings.database_url_sync.replace("@postgres:", "@localhost:")
    engine = create_engine(database_url or settings.database_url_sync)
    with engine.begin() as conn:
        if args.fix_confidence:
            result = conn.execute(
                text(
                    f"""
                UPDATE transcription_segments
                SET confidence = NULL
                WHERE confidence::text IN {BAD_FLOAT_SQL}
                """
                )
            )
            fixed = int(result.rowcount or 0)
        else:
            fixed = 0

        counts = {
            "bad_processing_time": scalar(
                conn,
                f"SELECT COUNT(*) FROM transcriptions WHERE processing_time_seconds::text IN {BAD_FLOAT_SQL}",
            ),
            "bad_segment_confidence": scalar(
                conn,
                f"SELECT COUNT(*) FROM transcription_segments WHERE confidence::text IN {BAD_FLOAT_SQL}",
            ),
            "bad_segment_start": scalar(
                conn,
                f"SELECT COUNT(*) FROM transcription_segments WHERE start_time::text IN {BAD_FLOAT_SQL}",
            ),
            "bad_segment_end": scalar(
                conn,
                f"SELECT COUNT(*) FROM transcription_segments WHERE end_time::text IN {BAD_FLOAT_SQL}",
            ),
            "fixed_confidence": fixed,
        }

    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0 if not any(counts[key] for key in counts if key != "fixed_confidence") else 1


if __name__ == "__main__":
    raise SystemExit(main())
