"""Tests for DigestService (FEATURE-002)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.digest_service import (
    DigestService,
    _ChatDigestItem,
    period_for_day,
    previous_trigger_day,
    seconds_until_next_digest,
    today_in_moscow,
    yesterday_in_moscow,
)

# ---------------------------------------------------------------------------
# Pure-time helpers
# ---------------------------------------------------------------------------


def test_period_for_day_covers_full_moscow_day_in_utc():
    day = date(2026, 5, 8)
    start, end = period_for_day(day)

    assert start.tzinfo == timezone.utc
    assert end.tzinfo == timezone.utc
    # Moscow is UTC+3 → 00:00 MSK == 21:00 UTC of the previous day.
    assert start == datetime(2026, 5, 7, 21, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 5, 8, 21, 0, tzinfo=timezone.utc)


def test_yesterday_in_moscow_handles_utc_late_night():
    # 23:00 UTC on May 8 → 02:00 MSK on May 9 → yesterday MSK = May 8.
    fixed_utc = datetime(2026, 5, 8, 23, 0, tzinfo=timezone.utc)
    assert yesterday_in_moscow(fixed_utc) == date(2026, 5, 8)


def test_today_in_moscow_handles_utc_morning():
    # 02:00 UTC → 05:00 MSK same day.
    fixed_utc = datetime(2026, 5, 8, 2, 0, tzinfo=timezone.utc)
    assert today_in_moscow(fixed_utc) == date(2026, 5, 8)


def test_seconds_until_next_digest_just_before_trigger():
    # 20:30 UTC = 23:30 MSK → 20 min before 23:50 trigger today.
    fixed = datetime(2026, 5, 8, 20, 30, tzinfo=timezone.utc)
    secs = seconds_until_next_digest(fixed)
    assert 1180 <= secs <= 1220  # ~20 minutes


def test_seconds_until_next_digest_just_after_trigger():
    # 21:00 UTC = 00:00 MSK → 23h 50m until next 23:50 today (same MSK day).
    # That's 85800 seconds (23*3600 + 50*60).
    fixed = datetime(2026, 5, 8, 21, 0, tzinfo=timezone.utc)
    secs = seconds_until_next_digest(fixed)
    assert 85700 <= secs <= 85900


def test_previous_trigger_day_before_2350_returns_yesterday_msk():
    # 12:00 UTC = 15:00 MSK on May 8 → today's 23:50 has not fired yet,
    # so the most recent fired trigger was yesterday's (May 7).
    fixed = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    assert previous_trigger_day(fixed) == date(2026, 5, 7)


def test_previous_trigger_day_just_past_2350_msk_returns_today_msk():
    # 20:55 UTC = 23:55 MSK on May 8 → 23:50 fired 5 min ago for May 8.
    fixed = datetime(2026, 5, 8, 20, 55, tzinfo=timezone.utc)
    assert previous_trigger_day(fixed) == date(2026, 5, 8)


def test_previous_trigger_day_after_midnight_msk_returns_yesterday_msk():
    # 21:00 UTC = 00:00 MSK on May 9 → most recent trigger was 23:50 of May 8.
    fixed = datetime(2026, 5, 8, 21, 0, tzinfo=timezone.utc)
    assert previous_trigger_day(fixed) == date(2026, 5, 8)


# ---------------------------------------------------------------------------
# DigestService.send_for_day
# ---------------------------------------------------------------------------


def _result_returning(scalar):
    """Tiny stub for `await session.execute(...)`."""
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=scalar)
    res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    return res


@pytest.mark.asyncio
async def test_send_for_day_skips_when_already_sent():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_returning(scalar=object()))
    bot = AsyncMock()

    svc = DigestService(session, bot)
    n = await svc.send_for_day(date(2026, 5, 8), record=True)

    assert n == -1
    bot.send_message.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_send_for_day_quiet_day_records_and_messages_owner():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_returning(scalar=None))
    session.add = MagicMock()
    bot = AsyncMock()

    svc = DigestService(session, bot)
    with patch.object(DigestService, "collect", AsyncMock(return_value=[])):
        n = await svc.send_for_day(date(2026, 5, 8), record=True)

    assert n == 0
    bot.send_message.assert_awaited_once()
    args, kwargs = bot.send_message.await_args
    assert "Тихий день" in args[1]
    session.add.assert_called_once()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_send_for_day_does_not_record_when_record_false():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_returning(scalar=None))
    session.add = MagicMock()
    bot = AsyncMock()

    svc = DigestService(session, bot)
    with patch.object(DigestService, "collect", AsyncMock(return_value=[])):
        await svc.send_for_day(date(2026, 5, 8), record=False)

    bot.send_message.assert_awaited()  # still sent
    session.add.assert_not_called()  # but NOT recorded


@pytest.mark.asyncio
async def test_send_for_day_sends_per_chat_summaries():
    chat = SimpleNamespace(telegram_id=-100123, name="My Chat")
    msg = SimpleNamespace(text="hello", user_id=42)
    items = [_ChatDigestItem(chat=chat, messages=[msg])]

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_returning(scalar=None))
    session.add = MagicMock()
    bot = AsyncMock()

    svc = DigestService(session, bot)
    with patch.object(DigestService, "collect", AsyncMock(return_value=items)):
        with patch.object(DigestService, "_summarize", AsyncMock(return_value="• summary")):
            n = await svc.send_for_day(date(2026, 5, 8), record=True)

    assert n == 1
    # 2 messages: header + 1 chat summary.
    assert bot.send_message.await_count == 2
    chat_msg_args = bot.send_message.await_args_list[1].args
    assert "My Chat" in chat_msg_args[1]
    assert "• summary" in chat_msg_args[1]
