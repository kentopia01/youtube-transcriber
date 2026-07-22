from __future__ import annotations

import uuid

from app.models import DigestLane, LaneSubscription, LaneVideoItem
from app.models.digest_lane import LANE_ROLE_ADMIN, LANE_ROLE_RESTRICTED


def test_digest_lane_constructs_for_admin_and_restricted_roles():
    admin = DigestLane(
        label="Ken",
        slug="ken",
        telegram_user_id=5815973193,
        role=LANE_ROLE_ADMIN,
    )
    restricted = DigestLane(
        label="Future recipient",
        slug="future-recipient",
        telegram_user_id=123,
        role=LANE_ROLE_RESTRICTED,
    )

    assert admin.is_admin is True
    assert restricted.is_admin is False
    assert admin.telegram_chat_id is None


def test_lane_subscription_and_item_reference_recipient_scope():
    lane_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    video_id = uuid.uuid4()
    subscription_id = uuid.uuid4()

    subscription = LaneSubscription(
        id=subscription_id,
        lane_id=lane_id,
        channel_id=channel_id,
        last_seen_video_ids=["abc123def45"],
    )
    item = LaneVideoItem(
        lane_id=lane_id,
        video_id=video_id,
        lane_subscription_id=subscription_id,
        source="lane_poll",
    )

    assert subscription.lane_id == lane_id
    assert subscription.channel_id == channel_id
    assert item.lane_id == lane_id
    assert item.video_id == video_id
    assert item.lane_subscription_id == subscription_id
