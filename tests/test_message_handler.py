"""Smoke tests for message_handler chat-type filtering (FEATURE-003)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.handlers.message_handler import handle_chat_member_update, handle_message


def _make_session_returning(chat=None) -> AsyncMock:
    """Build an async session whose `execute().scalar_one_or_none()` returns ``chat``."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=chat)
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_handle_chat_member_update_leaves_channel_and_skips_db():
    bot = AsyncMock()
    bot.id = 99
    bot.leave_chat = AsyncMock()
    bot.get_chat = AsyncMock()

    event = MagicMock()
    event.bot = bot
    event.new_chat_member.user.id = 99  # <- bot itself was added
    event.chat.id = -1001234567890
    event.chat.type = "channel"
    event.chat.title = "Some Channel"

    session = _make_session_returning(chat=None)

    await handle_chat_member_update(event, session)

    bot.leave_chat.assert_awaited_once_with(-1001234567890)
    bot.get_chat.assert_not_awaited()
    session.execute.assert_not_called()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_handle_chat_member_update_creates_chat_for_supergroup():
    bot = AsyncMock()
    bot.id = 99
    bot.leave_chat = AsyncMock()
    chat_info = MagicMock()
    chat_info.title = "My Group"
    bot.get_chat = AsyncMock(return_value=chat_info)

    event = MagicMock()
    event.bot = bot
    event.new_chat_member.user.id = 99
    event.chat.id = -100555
    event.chat.type = "supergroup"
    event.chat.title = "My Group"

    session = _make_session_returning(chat=None)

    await handle_chat_member_update(event, session)

    bot.leave_chat.assert_not_awaited()
    bot.get_chat.assert_awaited_once_with(-100555)
    session.add.assert_called_once()
    added_chat = session.add.call_args.args[0]
    assert added_chat.tg_type == "supergroup"
    assert added_chat.telegram_id == -100555


@pytest.mark.asyncio
async def test_handle_message_ignores_channel():
    message = MagicMock()
    message.from_user.is_bot = False
    message.from_user.id = 12345
    message.chat.type = "channel"
    message.chat.id = -100555
    message.chat.title = "Channel"

    session = _make_session_returning(chat=None)

    await handle_message(message, session)

    session.execute.assert_not_called()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_ignores_private():
    message = MagicMock()
    message.from_user.is_bot = False
    message.from_user.id = 12345
    message.chat.type = "private"

    session = _make_session_returning(chat=None)

    await handle_message(message, session)

    session.execute.assert_not_called()
