from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.digest_lane import LANE_ROLE_ADMIN, LANE_ROLE_RESTRICTED
from app.services.recipient_lanes import (
    find_digest_lane,
    resolve_lane_access,
    slugify_lane_label,
)


def _db_with_lane(lane):
    result = MagicMock()
    result.scalar_one_or_none.return_value = lane
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def test_slugify_lane_label_is_stable_and_bounded():
    assert slugify_lane_label("  Ken Topia Dev  ") == "ken-topia-dev"
    assert len(slugify_lane_label("x" * 200)) == 128


@pytest.mark.asyncio
async def test_non_allowlisted_user_fails_before_lane_lookup():
    db = _db_with_lane(None)

    access = await resolve_lane_access(
        db,
        999,
        allowed_users=[123],
        admin_users=[123],
    )

    assert access.allowed is False
    assert access.reason == "not_allowlisted"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_restricted_lane_fails_closed():
    access = await resolve_lane_access(
        _db_with_lane(None),
        123,
        allowed_users=[123],
        admin_users=[],
    )

    assert access.allowed is False
    assert access.reason == "lane_not_provisioned"


@pytest.mark.asyncio
async def test_configured_admin_keeps_access_during_provisioning():
    access = await resolve_lane_access(
        _db_with_lane(None),
        123,
        allowed_users=[123],
        admin_users=[123],
    )

    assert access.allowed is True
    assert access.is_admin is True
    assert access.reason == "admin_lane_not_provisioned"


@pytest.mark.asyncio
async def test_lane_role_and_private_chat_are_resolved_and_persisted():
    lane = SimpleNamespace(
        role=LANE_ROLE_RESTRICTED,
        telegram_chat_id=None,
    )
    db = _db_with_lane(lane)

    access = await resolve_lane_access(
        db,
        123,
        telegram_chat_id=456,
        allowed_users=[123],
        admin_users=[],
    )

    assert access.is_restricted is True
    assert lane.telegram_chat_id == 456
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(lane)


@pytest.mark.asyncio
async def test_configured_admin_overrides_stale_restricted_lane_role():
    lane = SimpleNamespace(
        role=LANE_ROLE_RESTRICTED,
        telegram_chat_id=123,
    )

    access = await resolve_lane_access(
        _db_with_lane(lane),
        123,
        allowed_users=[123],
        admin_users=[123],
    )

    assert access.role == LANE_ROLE_ADMIN
    assert access.is_admin is True


@pytest.mark.asyncio
async def test_find_lane_accepts_slug_label_or_user_id():
    lane = SimpleNamespace(
        slug="kentopiadev",
        label="Ken Topia Dev",
        telegram_user_id=5815973193,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [lane]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    assert await find_digest_lane(db, "kentopiadev") is lane
    assert await find_digest_lane(db, "Ken Topia Dev") is lane
    assert await find_digest_lane(db, "5815973193") is lane
