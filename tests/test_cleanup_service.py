"""Tests for CleanupService and the schedule helper (TECH-009)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import settings
from src.services.cleanup_service import CleanupService, seconds_until_next_cleanup


def test_seconds_until_next_cleanup_morning_msk():
    # 23:00 UTC May 8 == 02:00 MSK May 9 → 2 hours until 04:00 MSK.
    fixed = datetime(2026, 5, 8, 23, 0, tzinfo=timezone.utc)
    secs = seconds_until_next_cleanup(fixed)
    assert 7100 <= secs <= 7300  # ~2 hours


def test_seconds_until_next_cleanup_after_trigger_msk():
    # 02:00 UTC May 8 == 05:00 MSK May 8 → trigger fired 1h ago, next is 23h away.
    fixed = datetime(2026, 5, 8, 2, 0, tzinfo=timezone.utc)
    secs = seconds_until_next_cleanup(fixed)
    assert 82700 <= secs <= 83000  # ~23 hours


@pytest.mark.asyncio
async def test_purge_old_messages_uses_ttl(monkeypatch):
    monkeypatch.setattr(settings, "MESSAGE_TTL_DAYS", 30)

    captured = {}

    async def fake_execute(stmt):
        captured["stmt"] = stmt
        result = MagicMock()
        result.rowcount = 7
        return result

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=fake_execute)

    svc = CleanupService(session)
    fixed = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    deleted = await svc.purge_old_messages(now_utc=fixed)

    assert deleted == 7
    session.commit.assert_awaited()
    # The compiled SQL must reference the ``messages`` table and the cutoff
    # parameter must be ``fixed - 30 days``.
    sql = str(captured["stmt"]).lower()
    assert "delete" in sql and "messages" in sql
    expected_threshold = fixed - timedelta(days=30)
    bound = captured["stmt"].compile().params  # type: ignore[attr-defined]
    cutoff_value = next(iter(bound.values()))
    assert cutoff_value == expected_threshold


@pytest.mark.asyncio
async def test_purge_old_messages_clamps_ttl_to_at_least_one_day(monkeypatch):
    monkeypatch.setattr(settings, "MESSAGE_TTL_DAYS", 0)
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 0
    session.execute = AsyncMock(return_value=result)

    svc = CleanupService(session)
    fixed = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    await svc.purge_old_messages(now_utc=fixed)

    bound = session.execute.call_args.args[0].compile().params  # type: ignore[attr-defined]
    cutoff_value = next(iter(bound.values()))
    # The clamp ensures 0 → 1 day (we never want to drop everything).
    assert cutoff_value == fixed - timedelta(days=1)


@pytest.mark.asyncio
async def test_mark_past_events_emits_update_against_events_table():
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 3
    session.execute = AsyncMock(return_value=result)

    svc = CleanupService(session)
    fixed = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    marked = await svc.mark_past_events(now_utc=fixed)

    assert marked == 3
    session.commit.assert_awaited()

    stmt = session.execute.call_args.args[0]
    sql = str(stmt).lower()
    assert "update" in sql and "events" in sql
    # The cutoff bound parameter must equal ``fixed`` (status='upcoming' AND when_at < cutoff).
    bound = stmt.compile().params  # type: ignore[attr-defined]
    assert fixed in bound.values()
