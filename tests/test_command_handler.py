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
