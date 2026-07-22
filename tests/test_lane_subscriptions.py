from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.lane_subscriptions import (
    create_or_enable_lane_subscription,
    disable_lane_subscription,
    list_lane_subscriptions,
)


def _result(*, scalar=None, scalars=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalars.return_value.all.return_value = list(scalars or [])
    return result


def _db(result):
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_create_lane_subscription_is_scoped_to_lane_and_channel():
    lane_id = uuid.uuid4()
    channel = SimpleNamespace(id=uuid.uuid4())
    db = _db(_result(scalar=None))

    subscription = await create_or_enable_lane_subscription(db, lane_id, channel)

    assert subscription.lane_id == lane_id
    assert subscription.channel_id == channel.id
    db.add.assert_called_once_with(subscription)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_lane_subscription_is_reenabled_without_cross_lane_mutation():
    existing = SimpleNamespace(
        enabled=False,
        disabled_reason="user_disabled",
        poll_frequency_hours=48,
        max_videos_per_poll=1,
    )
    db = _db(_result(scalar=existing))

    result = await create_or_enable_lane_subscription(
        db,
        uuid.uuid4(),
        SimpleNamespace(id=uuid.uuid4()),
        poll_frequency_hours=12,
        max_videos_per_poll=5,
    )

    assert result is existing
    assert existing.enabled is True
    assert existing.disabled_reason is None
    assert existing.poll_frequency_hours == 12
    assert existing.max_videos_per_poll == 5
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_disable_lane_subscription_only_changes_resolved_lane_row():
    existing = SimpleNamespace(enabled=True, disabled_reason=None)
    db = _db(_result(scalar=existing))

    result = await disable_lane_subscription(
        db,
        uuid.uuid4(),
        uuid.uuid4(),
    )

    assert result is existing
    assert existing.enabled is False
    assert existing.disabled_reason == "user_disabled"


@pytest.mark.asyncio
async def test_list_lane_subscriptions_returns_lane_query_results():
    subscriptions = [SimpleNamespace(id=uuid.uuid4())]
    db = _db(_result(scalars=subscriptions))

    result = await list_lane_subscriptions(db, uuid.uuid4())

    assert result == subscriptions


@pytest.mark.asyncio
async def test_telegram_subscriptions_uses_callers_lane(monkeypatch):
    from app import telegram_bot

    lane_id = uuid.uuid4()
    reply = AsyncMock()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        message=SimpleNamespace(reply_text=reply),
    )
    context = SimpleNamespace(
        args=[],
        user_data={
            "recipient_lane_access": SimpleNamespace(
                lane=SimpleNamespace(id=lane_id),
                role="restricted",
            )
        },
    )
    db = SimpleNamespace(close=AsyncMock())
    list_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(telegram_bot, "_is_user_allowed", lambda _: True)
    monkeypatch.setattr(telegram_bot, "_get_db", AsyncMock(return_value=db))
    monkeypatch.setattr(
        "app.services.lane_subscriptions.list_lane_subscriptions",
        list_mock,
    )

    await telegram_bot.subscriptions_command(update, context)

    list_mock.assert_awaited_once_with(db, lane_id)
    assert "No subscriptions" in reply.call_args.args[0]
