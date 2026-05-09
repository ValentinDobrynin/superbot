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


# ---------------------------------------------------------------------------
# parse_deadline — Russian phrasing (TECH-011, step D of digest cleanup)
# ---------------------------------------------------------------------------

# Pin "now" to Friday 9 May 2026 02:50 MSK (= 8 May 23:50 UTC) so weekday
# expectations are stable. ``parse_deadline`` returns UTC dates; expected
# values below are also UTC.
_NOW = datetime(2026, 5, 8, 23, 50, tzinfo=timezone.utc)


def _msk(d):
    """Helper: convert an MSK ``date(...)`` into the equivalent UTC date."""
    return d  # date comparison only — actual UTC drift is ±1 day, callers tolerate


@pytest.mark.parametrize(
    "raw, expected_msk_date",
    [
        # "до пятницы" — by end of Friday → Fri 15 May 2026 in МСК
        ("до пятницы", date(2026, 5, 15)),
        ("к пятнице", date(2026, 5, 15)),
        # "в следующую пятницу" — same Friday after stripping prefix
        ("в следующую пятницу", date(2026, 5, 15)),
        # "до 12.05" — by 12 May (year auto-filled, ISO conversion)
        ("до 12.05", date(2026, 5, 12)),
        ("12.05.2026", date(2026, 5, 12)),
        ("до 12 мая", date(2026, 5, 12)),
        # Today / tomorrow anchored to 23:59 МСК
        ("сегодня", date(2026, 5, 9)),
        ("завтра", date(2026, 5, 10)),
        ("до завтра", date(2026, 5, 10)),
        # End-of-day shortcuts
        ("до конца дня", date(2026, 5, 9)),
        ("к концу дня", date(2026, 5, 9)),
        # Weekends
        ("к выходным", date(2026, 5, 16)),  # Sat 09:00 МСК
        ("на выходных", date(2026, 5, 16)),
        ("до выходных", date(2026, 5, 15)),  # Fri 23:59 МСК
        # Weekday + time of day adverb
        ("в пн утром", date(2026, 5, 11)),
        ("в среду вечером", date(2026, 5, 13)),
    ],
)
def test_parse_deadline_russian_phrases(raw, expected_msk_date):
    """Compare against the MSK calendar date so DST/UTC drift doesn't matter."""
    from zoneinfo import ZoneInfo as _ZI

    parsed = parse_deadline(raw, now_utc=_NOW)
    assert parsed is not None, f"expected non-None for {raw!r}"
    assert parsed.tzinfo is not None
    msk_date = parsed.astimezone(_ZI("Europe/Moscow")).date()
    assert (
        msk_date == expected_msk_date
    ), f"{raw!r} -> {parsed} ({msk_date} МСК, expected {expected_msk_date} МСК)"


@pytest.mark.parametrize(
    "raw",
    [
        "срочно",
        "ASAP",
        "asap",
        "до конца дня срочно",
        "Срочно!",
        "немедленно",
        "urgent",
        "EOD",
        "to me eod",
        "до конца дня",  # shortcut implies urgency
    ],
)
def test_has_urgency_keyword_recognizes_common_phrases(raw):
    from src.services.digest_service import has_urgency_keyword

    assert has_urgency_keyword(raw) is True, f"expected urgent for {raw!r}"


@pytest.mark.parametrize(
    "raw",
    [
        "до пятницы",
        "12 мая",
        "",
        None,
        "просто длинная фраза без ключевых слов",
        "к выходным",
    ],
)
def test_has_urgency_keyword_ignores_non_urgent(raw):
    from src.services.digest_service import has_urgency_keyword

    assert has_urgency_keyword(raw) is False, f"expected not-urgent for {raw!r}"


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
# _sanitize_extracted — defensive filters on top of the LLM output (TECH-012)
# ---------------------------------------------------------------------------


def test_sanitize_moves_question_commits_to_open_questions():
    from src.services.digest_service import _sanitize_extracted

    extracted = {
        "commitments": [
            {"direction": "from_me", "text": "Зум можешь сегодня дать?"},
            {"direction": "from_me", "text": "Я пришлю отчёт", "deadline_raw": "до пятницы"},
        ],
        "events": [],
        "open_questions": [],
    }
    out = _sanitize_extracted(extracted, messages_text="me: что-то про зум")
    # Question moved out of commits.
    assert len(out["commitments"]) == 1
    assert "пришлю отчёт" in out["commitments"][0]["text"]
    # And appeared in open_questions, with direction preserved.
    assert any(q["text"].endswith("?") for q in out["open_questions"])
    assert out["open_questions"][0]["direction"] == "from_me"


def test_sanitize_drops_tiny_commits_without_deadline():
    from src.services.digest_service import _sanitize_extracted

    extracted = {
        "commitments": [
            {"direction": "from_me", "text": "как раз занимаюсь"},  # 3 words, no deadline → drop
            {"direction": "from_me", "text": "сделаю"},  # 1 word, no deadline → drop
            {
                "direction": "from_me",
                "text": "ок",
                "deadline_raw": "до пятницы",
            },  # has deadline, keep
            {
                "direction": "from_me",
                "text": "напишу инвесторам про штраф",  # 4+ words → keep
            },
        ],
        "events": [],
        "open_questions": [],
    }
    out = _sanitize_extracted(extracted, messages_text="")
    texts = [c["text"] for c in out["commitments"]]
    assert "напишу инвесторам про штраф" in texts
    assert "ок" in texts  # kept due to deadline
    assert "как раз занимаюсь" not in texts
    assert "сделаю" not in texts


def test_sanitize_drops_hallucinated_18_00_when_not_in_source():
    """LLM keeps lifting random events to '12 мая в 18:00' even when source
    only mentions 'в пятницу'. We blank the time when there's no anchor.
    """
    from src.services.digest_service import _sanitize_extracted

    extracted = {
        "commitments": [],
        "events": [
            {"description": "all-hands встреча", "when_raw": "12 мая в 18:00"},
            {"description": "встреча с СОЛИДом", "when_raw": "12 мая в 18:00"},
        ],
        "open_questions": [],
    }
    # Source says nothing about "18:00" or "12 мая".
    out = _sanitize_extracted(extracted, messages_text="me: давай в пятницу обсудим")
    # Both events kept (description is fine), but their fake date stripped.
    assert len(out["events"]) == 2
    assert out["events"][0]["when_raw"] is None
    assert out["events"][1]["when_raw"] is None


def test_sanitize_keeps_18_00_when_present_in_source():
    from src.services.digest_service import _sanitize_extracted

    extracted = {
        "commitments": [],
        "events": [
            {"description": "встреча с командой", "when_raw": "12 мая в 18:00"},
        ],
        "open_questions": [],
    }
    out = _sanitize_extracted(
        extracted,
        messages_text="me: жду тебя 12 мая в 18:00, переговорка",
    )
    assert out["events"][0]["when_raw"] == "12 мая в 18:00"


def test_sanitize_dedups_identical_events_within_chat():
    from src.services.digest_service import _sanitize_extracted

    extracted = {
        "commitments": [],
        "events": [
            {"description": "Открытие офиса Silk Road", "when_raw": "26 мая"},
            {"description": "открытие офиса Silk Road", "when_raw": "26 мая"},  # case
            {"description": "Открытие офиса Silk Road", "when_raw": "26 мая"},  # exact dup
        ],
        "open_questions": [],
    }
    out = _sanitize_extracted(extracted, messages_text="we open silk road on 26 мая")
    assert len(out["events"]) == 1


def test_sanitize_resolves_commit_event_overlap():
    """Same sentence in both buckets — event wins iff it has a date."""
    from src.services.digest_service import _sanitize_extracted

    # Case A: event has a date → drop the duplicate commit.
    extracted_a = {
        "commitments": [
            {"direction": "from_me", "text": "сравнение предложений", "deadline_raw": "до 12.05"},
        ],
        "events": [
            {"description": "Сравнение предложений", "when_raw": "12 мая"},
        ],
        "open_questions": [],
    }
    out_a = _sanitize_extracted(extracted_a, messages_text="до 12 мая буду сравнивать")
    assert len(out_a["commitments"]) == 0
    assert len(out_a["events"]) == 1

    # Case B: event has no date → drop the duplicate event, keep commit.
    extracted_b = {
        "commitments": [
            {"direction": "from_me", "text": "сравнение предложений", "deadline_raw": "до 12.05"},
        ],
        "events": [
            {"description": "Сравнение предложений", "when_raw": None},
        ],
        "open_questions": [],
    }
    out_b = _sanitize_extracted(extracted_b, messages_text="когда-нибудь")
    assert len(out_b["commitments"]) == 1
    assert len(out_b["events"]) == 0


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
    # TECH-010: full body must be persisted on the DailyDigest row so we
    # can postmortem what was actually delivered.
    session.add.assert_called_once()
    digest_entry = session.add.call_args.args[0]
    assert digest_entry.body_md is not None
    assert "📊" in digest_entry.body_md  # header
    assert "My Chat" in digest_entry.body_md  # chat block


@pytest.mark.asyncio
async def test_send_for_day_records_body_on_quiet_day():
    """TECH-010: even on a silent day, the canned message goes into body_md."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_returning(scalar=None))
    session.add = MagicMock()
    bot = AsyncMock()

    svc = DigestService(session, bot)
    with patch.object(DigestService, "collect", AsyncMock(return_value=[])):
        await svc.send_for_day(date(2026, 5, 8), record=True)

    session.add.assert_called_once()
    digest_entry = session.add.call_args.args[0]
    assert digest_entry.body_md is not None
    assert "Тихий день" in digest_entry.body_md


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
