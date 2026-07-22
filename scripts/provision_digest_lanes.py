#!/usr/bin/env python3
"""Explicitly provision or update recipient lanes in the local database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.channel_subscription import ChannelSubscription  # noqa: E402
from app.models.digest_lane import DigestLane  # noqa: E402
from app.models.lane_subscription import LaneSubscription  # noqa: E402
from app.services.recipient_lanes import provision_digest_lane  # noqa: E402
from app.services.runtime_config import load_native_env, resolve_sync_database_url  # noqa: E402


def _parse_lane(value: str) -> tuple[str, int, str, int | None]:
    parts = value.split(":")
    if len(parts) not in {3, 4}:
        raise argparse.ArgumentTypeError(
            "lane must be LABEL:TELEGRAM_USER_ID:ROLE[:TELEGRAM_CHAT_ID]"
        )
    label, user_id_text, role = parts[:3]
    try:
        user_id = int(user_id_text)
        chat_id = int(parts[3]) if len(parts) == 4 and parts[3] else None
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Telegram IDs must be integers") from exc
    return label, user_id, role, chat_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lane",
        action="append",
        required=True,
        type=_parse_lane,
        metavar="LABEL:USER_ID:ROLE[:CHAT_ID]",
    )
    parser.add_argument(
        "--copy-global-subscriptions-to",
        type=int,
        metavar="TELEGRAM_USER_ID",
        help="Idempotently copy the existing global watchlist into one lane.",
    )
    args = parser.parse_args()

    load_native_env(PROJECT_ROOT)
    engine = create_engine(resolve_sync_database_url(PROJECT_ROOT), pool_pre_ping=True)
    try:
        with Session(engine) as db:
            for label, user_id, role, chat_id in args.lane:
                lane = provision_digest_lane(
                    db,
                    label=label,
                    telegram_user_id=user_id,
                    role=role,
                    telegram_chat_id=chat_id,
                )
                delivery = "ready" if lane.telegram_chat_id is not None else "awaiting /start"
                print(f"{lane.slug}: {lane.role}, delivery {delivery}")
            if args.copy_global_subscriptions_to is not None:
                lane = db.scalar(
                    select(DigestLane).where(
                        DigestLane.telegram_user_id == args.copy_global_subscriptions_to
                    )
                )
                if lane is None:
                    parser.error("copy target lane must be provisioned first")
                copied = 0
                for source in db.scalars(select(ChannelSubscription)).all():
                    existing = db.scalar(
                        select(LaneSubscription).where(
                            LaneSubscription.lane_id == lane.id,
                            LaneSubscription.channel_id == source.channel_id,
                        )
                    )
                    if existing is not None:
                        continue
                    db.add(
                        LaneSubscription(
                            lane_id=lane.id,
                            channel_id=source.channel_id,
                            enabled=source.enabled,
                            poll_frequency_hours=source.poll_frequency_hours,
                            max_videos_per_poll=source.max_videos_per_poll,
                            last_polled_at=source.last_polled_at,
                            last_seen_video_ids=list(source.last_seen_video_ids or []),
                            videos_ingested_today=source.videos_ingested_today,
                            daily_counter_reset_at=source.daily_counter_reset_at,
                            consecutive_failure_count=source.consecutive_failure_count,
                            disabled_reason=source.disabled_reason,
                        )
                    )
                    copied += 1
                db.commit()
                print(f"copied {copied} global subscription(s) to {lane.slug}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
