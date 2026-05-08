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
    chat = Chat(name=name, telegram_id=telegram_id, type="MIXED", description="x")
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
