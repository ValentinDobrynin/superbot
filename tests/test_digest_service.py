"""Tests for DigestService (FEATURE-002 + FEATURE-007/008/009/010)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.digest_service import (
    DigestService,
    _ChatDigestItem,
    _format_messages,
    _partner_label_for,
    is_within_24h,
    parse_deadline,
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
    assert start == datetime(2026, 5, 7, 21, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 5, 8, 21, 0, tzinfo=timezone.utc)


def test_yesterday_in_moscow_handles_utc_late_night():
    fixed_utc = datetime(2026, 5, 8, 23, 0, tzinfo=timezone.utc)
    assert yesterday_in_moscow(fixed_utc) == date(2026, 5, 8)


def test_today_in_moscow_handles_utc_morning():
    fixed_utc = datetime(2026, 5, 8, 2, 0, tzinfo=timezone.utc)
    assert today_in_moscow(fixed_utc) == date(2026, 5, 8)


def test_seconds_until_next_digest_just_before_trigger():
    fixed = datetime(2026, 5, 8, 20, 30, tzinfo=timezone.utc)
    secs = seconds_until_next_digest(fixed)
    assert 1180 <= secs <= 1220


def test_seconds_until_next_digest_just_after_trigger():
    fixed = datetime(2026, 5, 8, 21, 0, tzinfo=timezone.utc)
    secs = seconds_until_next_digest(fixed)
    assert 85700 <= secs <= 85900


def test_previous_trigger_day_before_2350_returns_yesterday_msk():
    fixed = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    assert previous_trigger_day(fixed) == date(2026, 5, 7)


def test_previous_trigger_day_just_past_2350_msk_returns_today_msk():
    fixed = datetime(2026, 5, 8, 20, 55, tzinfo=timezone.utc)
    assert previous_trigger_day(fixed) == date(2026, 5, 8)


def test_previous_trigger_day_after_midnight_msk_returns_yesterday_msk():
    fixed = datetime(2026, 5, 8, 21, 0, tzinfo=timezone.utc)
    assert previous_trigger_day(fixed) == date(2026, 5, 8)


# ---------------------------------------------------------------------------
# Deadline parsing & urgency
# ---------------------------------------------------------------------------


def test_parse_deadline_returns_none_for_empty():
    assert parse_deadline("") is None
    assert parse_deadline(None) is None


def test_parse_deadline_handles_iso_date():
    parsed = parse_deadline("2026-05-15")
    assert parsed is not None
    assert parsed.tzinfo is not None
    # Date alone → midnight Moscow → 21:00 UTC of the previous day.
    assert parsed.date() in (date(2026, 5, 14), date(2026, 5, 15))


def test_is_within_24h_true_for_near_future():
    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    soon = now + timedelta(hours=10)
    assert is_within_24h(soon, now_utc=now) is True


def test_is_within_24h_false_for_far_future():
    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    later = now + timedelta(days=3)
    assert is_within_24h(later, now_utc=now) is False


def test_is_within_24h_false_for_past():
    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    earlier = now - timedelta(hours=1)
    assert is_within_24h(earlier, now_utc=now) is False


def test_is_within_24h_handles_none():
    assert is_within_24h(None) is False


# ---------------------------------------------------------------------------
# Author normalisation in messages
# ---------------------------------------------------------------------------


def test_format_messages_owner_is_normalised_to_ya():
    msgs = [
        SimpleNamespace(text="привет", user_id=42),
        SimpleNamespace(text="как дела?", user_id=999),
    ]
    out = _format_messages(msgs, owner_id=42, partner_label="Маша", is_group=False)
    assert "Я: привет" in out
    assert "Маша: как дела?" in out


def test_format_messages_group_uses_anonymous_short_label():
    msgs = [
        SimpleNamespace(text="hi", user_id=42),
        SimpleNamespace(text="hello", user_id=12345),
    ]
    out = _format_messages(msgs, owner_id=42, partner_label="ignored", is_group=True)
    assert "Я: hi" in out
    assert "user_12345: hello" in out


def test_format_messages_skips_empty_text():
    msgs = [
        SimpleNamespace(text="", user_id=42),
        SimpleNamespace(text=None, user_id=42),
        SimpleNamespace(text="real", user_id=42),
    ]
    out = _format_messages(msgs, owner_id=42, partner_label="x", is_group=False)
    assert out == "Я: real"


def test_partner_label_strips_username_and_keeps_first_name():
    chat = SimpleNamespace(name="Мария Иванова (@maria_iv)", telegram_id=12345)
    assert _partner_label_for(chat) == "Мария"


def test_partner_label_falls_back_to_telegram_id_when_name_missing():
    chat = SimpleNamespace(name=None, telegram_id=99)
    assert _partner_label_for(chat) == "Контакт_99"


# ---------------------------------------------------------------------------
# DigestService.send_for_day
# ---------------------------------------------------------------------------


def _result_returning(scalar):
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

    bot.send_message.assert_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_send_for_day_processes_each_chat():
    """One header + one message per chat (+ no classification suggestions when classified)."""
    chat = SimpleNamespace(
        id="chat-uuid",
        telegram_id=-100123,
        name="My Chat",
        tg_type="supergroup",
        business_connection_id=None,
        classification="business",
    )
    msg = SimpleNamespace(text="hello", user_id=42)
    items = [_ChatDigestItem(chat=chat, messages=[msg])]

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_returning(scalar=None))
    session.add = MagicMock()
    bot = AsyncMock()

    svc = DigestService(session, bot)
    with patch.object(DigestService, "collect", AsyncMock(return_value=items)):
        with patch.object(
            DigestService,
            "_extract",
            AsyncMock(return_value={"summary_md": "Sample.", "commitments": []}),
        ):
            with patch.object(DigestService, "_persist", AsyncMock()):
                n = await svc.send_for_day(date(2026, 5, 8), record=True)

    assert n == 1
    # Header + one chat block.
    assert bot.send_message.await_count == 2
    second_call = bot.send_message.await_args_list[1]
    assert "My Chat" in second_call.args[1]


# ---------------------------------------------------------------------------
# Render block — MarkdownV2 output structure
# ---------------------------------------------------------------------------


@pytest.fixture
def _render_chat():
    return SimpleNamespace(
        id="abc",
        telegram_id=12345,
        name="Маша",
        tg_type="private",
        business_connection_id="conn-1",
        classification="private",
    )


def _new_svc() -> DigestService:
    return DigestService(MagicMock(), MagicMock())


def test_render_block_full_payload(_render_chat):
    item = _ChatDigestItem(
        chat=_render_chat,
        messages=[
            SimpleNamespace(text="hi", user_id=1),
            SimpleNamespace(text="привет", user_id=2),
        ],
    )
    extracted = {
        "summary_md": "Сегодня обсудили проект.",
        "commitments": [
            {
                "direction": "from_me",
                "text": "отправлю отчёт",
                "deadline_raw": "до пятницы",
                "is_urgent": True,
            },
            {
                "direction": "to_me",
                "text": "позвонит",
                "deadline_raw": None,
                "is_urgent": False,
            },
        ],
        "events": [
            {
                "description": "ужин",
                "when_raw": "12.05 в 19:00",
                "is_urgent": False,
            }
        ],
        "open_questions": [
            {"direction": "to_partner", "text": "когда созвон?"},
            {"direction": "to_me", "text": "что с фрилансером?"},
        ],
    }

    block = _new_svc()._render_block(item, extracted)

    # Header has chat name + message counts.
    assert "Маша" in block
    assert "*Коммиты*" in block
    assert "от меня: отправлю отчёт" in block
    assert "← мне: позвонит" in block
    assert "*Даты и события*" in block
    assert "*Открытые вопросы*" in block
    assert "*Срочное*" in block
    # Plain dots are escaped for MarkdownV2.
    assert "сообщ\\." in block


def test_render_block_skips_empty_sections(_render_chat):
    item = _ChatDigestItem(chat=_render_chat, messages=[SimpleNamespace(text="x", user_id=1)])
    extracted = {"summary_md": "Тихо.", "commitments": [], "events": [], "open_questions": []}

    block = _new_svc()._render_block(item, extracted)

    assert "Тихо\\." in block
    assert "Коммиты" not in block
    assert "Открытые вопросы" not in block
    assert "Срочное" not in block


def test_render_block_uses_classification_badge():
    chat = SimpleNamespace(
        id="abc",
        telegram_id=1,
        name="Босс",
        tg_type="private",
        business_connection_id="c",
        classification="business",
    )
    item = _ChatDigestItem(chat=chat, messages=[SimpleNamespace(text="x", user_id=1)])
    extracted = {"summary_md": ""}

    block = _new_svc()._render_block(item, extracted)

    assert block.startswith("💼 ")


def test_render_block_unclassified_uses_question_badge():
    chat = SimpleNamespace(
        id="abc",
        telegram_id=1,
        name="Кто-то",
        tg_type="private",
        business_connection_id="c",
        classification=None,
    )
    item = _ChatDigestItem(chat=chat, messages=[SimpleNamespace(text="x", user_id=1)])

    block = _new_svc()._render_block(item, {"summary_md": ""})

    assert block.startswith("❓ ")
