"""Smoke tests for ``command_handler.update_chat_title`` and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramForbiddenError

from src.database.models import Chat
from src.handlers.command_handler import _format_chat_name, update_chat_title


def _make_message_with_bot(get_chat_return=None, get_chat_side_effect=None):
    bot = AsyncMock()
    if get_chat_side_effect is not None:
        bot.get_chat = AsyncMock(side_effect=get_chat_side_effect)
    else:
        bot.get_chat = AsyncMock(return_value=get_chat_return)
    message = MagicMock()
    message.bot = bot
    return message


def _make_chat(name="Old Name", telegram_id=42) -> Chat:
    chat = Chat(name=name, telegram_id=telegram_id, type="MIXED", tg_type="group", description="x")
    chat.id = uuid4()
    return chat


@pytest.mark.asyncio
async def test_update_chat_title_skips_when_chat_not_in_db():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    message = _make_message_with_bot()

    await update_chat_title(message, uuid4(), session)

    message.bot.get_chat.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_chat_title_updates_when_title_changed():
    chat = _make_chat(name="Old")
    new_info = MagicMock()
    new_info.title = "New"

    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)
    message = _make_message_with_bot(get_chat_return=new_info)

    await update_chat_title(message, chat.id, session)

    assert chat.name == "New"
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_update_chat_title_removes_chat_on_forbidden_error():
    chat = _make_chat()
    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)
    session.delete = AsyncMock()
    message = _make_message_with_bot(
        get_chat_side_effect=TelegramForbiddenError(method=None, message="kicked")
    )

    await update_chat_title(message, chat.id, session)

    session.delete.assert_awaited_once_with(chat)
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_update_chat_title_keeps_chat_on_chat_not_found():
    chat = _make_chat()
    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)
    session.delete = AsyncMock()
    message = _make_message_with_bot(get_chat_side_effect=Exception("Chat not found"))

    await update_chat_title(message, chat.id, session)

    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_format_chat_name_falls_back_to_telegram_id():
    chat = _make_chat(name=None, telegram_id=777)
    assert _format_chat_name(chat) == "Chat 777"

    chat.name = "Pretty"
    assert _format_chat_name(chat) == "Pretty"


# ---------------------------------------------------------------------------
# /business toggle (FEATURE-004)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_business_command_off_pauses_observer(monkeypatch):
    from src.config import settings as app_settings
    from src.handlers.command_handler import business_command

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)
    monkeypatch.setattr(app_settings, "business_paused", False)

    msg = MagicMock()
    msg.from_user.id = 1
    msg.chat.type = "private"
    msg.answer = AsyncMock()
    command = MagicMock()
    command.args = "off"

    session = AsyncMock()

    await business_command(msg, command, session)

    assert app_settings.business_paused is True
    msg.answer.assert_awaited()


@pytest.mark.asyncio
async def test_business_command_on_resumes_observer(monkeypatch):
    from src.config import settings as app_settings
    from src.handlers.command_handler import business_command

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)
    monkeypatch.setattr(app_settings, "business_paused", True)

    msg = MagicMock()
    msg.from_user.id = 1
    msg.chat.type = "private"
    msg.answer = AsyncMock()
    command = MagicMock()
    command.args = "on"

    session = AsyncMock()
    await business_command(msg, command, session)

    assert app_settings.business_paused is False
    msg.answer.assert_awaited()


@pytest.mark.asyncio
async def test_business_command_rejects_non_owner(monkeypatch):
    from src.config import settings as app_settings
    from src.handlers.command_handler import business_command

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)
    monkeypatch.setattr(app_settings, "business_paused", False)

    msg = MagicMock()
    msg.from_user.id = 999  # not the owner
    msg.chat.type = "private"
    msg.answer = AsyncMock()
    command = MagicMock()
    command.args = "off"

    session = AsyncMock()
    await business_command(msg, command, session)

    assert app_settings.business_paused is False
    msg.answer.assert_not_awaited()


# ---------------------------------------------------------------------------
# /glossary, /commits, /events callbacks (FEATURE-007/008/009)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classification_set_writes_value(monkeypatch):
    from src.config import settings as app_settings
    from src.handlers.command_handler import classification_set

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)

    chat = _make_chat(name="Маша", telegram_id=42)
    chat.classification = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)

    callback = MagicMock()
    callback.from_user.id = 1
    callback.data = f"cls|{chat.id}|business"
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()

    await classification_set(callback, session)

    assert chat.classification == "business"
    session.commit.assert_awaited()
    callback.answer.assert_awaited()
    # Regression for BUG-005 — see test_glossary_set_writes_business.
    assert chat.updated_at is None or chat.updated_at.tzinfo is None


@pytest.mark.asyncio
async def test_classification_set_skip_does_not_write(monkeypatch):
    from src.config import settings as app_settings
    from src.handlers.command_handler import classification_set

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)

    chat = _make_chat()
    chat.classification = None
    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)

    callback = MagicMock()
    callback.from_user.id = 1
    callback.data = f"cls|{chat.id}|skip"
    callback.message = MagicMock()
    callback.answer = AsyncMock()

    await classification_set(callback, session)

    assert chat.classification is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_commit_action_marks_done(monkeypatch):
    from src.config import settings as app_settings
    from src.database.models import Commitment
    from src.handlers.command_handler import commit_action

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)

    commitment = Commitment(
        chat_id=uuid4(), direction="from_me", text="отправлю отчёт", status="open"
    )
    commitment.id = uuid4()

    session = AsyncMock()
    session.get = AsyncMock(return_value=commitment)

    callback = MagicMock()
    callback.from_user.id = 1
    callback.data = f"commit|{commitment.id}|done"
    callback.message = MagicMock()
    callback.message.text = "irrelevant"
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()

    await commit_action(callback, session)

    assert commitment.status == "done"
    assert commitment.completed_at is not None
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_event_action_marks_cancelled(monkeypatch):
    from src.config import settings as app_settings
    from src.database.models import Event
    from src.handlers.command_handler import event_action

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)

    event = Event(chat_id=uuid4(), description="ужин", status="upcoming")
    event.id = uuid4()

    session = AsyncMock()
    session.get = AsyncMock(return_value=event)

    callback = MagicMock()
    callback.from_user.id = 1
    callback.data = f"event|{event.id}|cancel"
    callback.message = MagicMock()
    callback.message.text = "irrelevant"
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()

    await event_action(callback, session)

    assert event.status == "cancelled"
    session.commit.assert_awaited()


# ---------------------------------------------------------------------------
# /glossary v2 — paginated, inline buttons (FEATURE-007 follow-up)
# ---------------------------------------------------------------------------


def _make_business_chat(name: str, classification=None) -> Chat:
    chat = Chat(
        name=name,
        telegram_id=hash(name) & 0xFFFFFFFF,
        type="MIXED",
        tg_type="private",
        description="x",
        business_connection_id="conn-1",
        classification=classification,
    )
    chat.id = uuid4()
    return chat


def test_glo_render_includes_pagination_when_total_exceeds_page():
    from src.handlers.command_handler import GLOSSARY_PAGE_SIZE, _glo_render

    chats = [_make_business_chat(f"Chat {i}") for i in range(GLOSSARY_PAGE_SIZE)]
    body, kb = _glo_render(chats, total=33, offset=0, only_unset=False)

    assert "стр. 1 из 4" in body
    assert "всего 33" in body
    # Header row + 10 chat rows + nav row.
    assert len(kb.inline_keyboard) == 1 + GLOSSARY_PAGE_SIZE + 1
    nav = kb.inline_keyboard[-1]
    assert any("далее" in b.text for b in nav)
    assert all("назад" not in b.text for b in nav)


def test_glo_render_no_pagination_when_single_page():
    from src.handlers.command_handler import _glo_render

    chats = [_make_business_chat("A"), _make_business_chat("B")]
    body, kb = _glo_render(chats, total=2, offset=0, only_unset=False)

    assert "стр. 1 из 1" in body
    # Header row + 2 chat rows. No nav row.
    assert len(kb.inline_keyboard) == 3


def test_glo_render_emits_4_buttons_per_chat_row():
    from src.handlers.command_handler import _glo_render

    chat = _make_business_chat("Маша")
    _, kb = _glo_render([chat], total=1, offset=0, only_unset=False)

    chat_row = kb.inline_keyboard[1]
    assert [b.text for b in chat_row] == ["💼", "👤", "🤝", "⏭"]
    # Callback data carries chat_id, value code, filter code and offset.
    for btn in chat_row:
        parts = btn.callback_data.split("|")
        assert parts[0] == "gs"
        assert parts[1] == str(chat.id)
        assert parts[3] == "a"
        assert parts[4] == "0"


def test_glo_render_unset_filter_only_shows_back_when_offset_positive():
    from src.handlers.command_handler import _glo_render

    chats = [_make_business_chat(f"C{i}", classification=None) for i in range(5)]
    _, kb = _glo_render(chats, total=20, offset=10, only_unset=True)

    nav = kb.inline_keyboard[-1]
    assert any("назад" in b.text for b in nav)
    # filter code in pagination callback should be "u" (only_unset).
    for btn in nav:
        assert btn.callback_data.split("|")[2] == "u"


@pytest.mark.asyncio
async def test_glossary_set_writes_business(monkeypatch):
    from src.config import settings as app_settings
    from src.handlers.command_handler import glossary_set

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)

    chat = _make_business_chat("Маша", classification=None)

    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)

    async def fake_render_for(_session, *, only_unset, offset):
        return "redrawn", MagicMock(), 0

    monkeypatch.setattr("src.handlers.command_handler._glo_render_for", fake_render_for)

    callback = MagicMock()
    callback.from_user.id = 1
    callback.data = f"gs|{chat.id}|b|a|0"
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()

    await glossary_set(callback, session)

    assert chat.classification == "business"
    session.commit.assert_awaited()
    callback.message.edit_text.assert_awaited_once()
    # Regression for BUG-005: ``chat.updated_at`` is a naive ``DateTime``
    # column. The handler must not assign a tz-aware value (asyncpg rejects
    # those with a DataError). SQLAlchemy's ``onupdate=datetime.utcnow``
    # touches the column at flush time, but here in unit tests there's no
    # flush — so ``updated_at`` should still be ``None``.
    assert chat.updated_at is None or chat.updated_at.tzinfo is None


@pytest.mark.asyncio
async def test_glossary_set_skip_does_not_write(monkeypatch):
    from src.config import settings as app_settings
    from src.handlers.command_handler import glossary_set

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)

    chat = _make_business_chat("Маша")
    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)

    callback = MagicMock()
    callback.from_user.id = 1
    callback.data = f"gs|{chat.id}|s|a|0"
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()

    await glossary_set(callback, session)

    # Skip is purely informational — no DB write, no redraw.
    session.commit.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_glossary_suggest_skips_chats_without_recent_messages(monkeypatch):
    """If there are unclassified chats but none has activity in 7d, just say so."""
    from src.config import settings as app_settings
    from src.handlers.command_handler import _glossary_suggest

    monkeypatch.setattr(app_settings, "OWNER_ID", 1)

    chat = _make_business_chat("Idle", classification=None)
    session = AsyncMock()

    # First execute() returns the candidates list, second one returns no
    # messages for that chat. We feed a small queue of fake results.
    def make_result(scalars_list):
        res = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=scalars_list)
        res.scalars = MagicMock(return_value=scalars)
        return res

    results_queue = [make_result([chat]), make_result([])]
    session.execute = AsyncMock(side_effect=results_queue)

    msg = MagicMock()
    msg.bot = AsyncMock()
    msg.answer = AsyncMock()

    await _glossary_suggest(msg, session)

    msg.answer.assert_awaited_once()
    args, _ = msg.answer.await_args
    assert "ни в одном нет сообщений" in args[0]
