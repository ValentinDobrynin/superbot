"""Tests for the Telegram Business observer (FEATURE-004)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import settings
from src.handlers import business_handler
from src.handlers.business_handler import (
    _format_partner_title,
    handle_business_connection,
    handle_business_message,
)


def _make_session(get_returns=None, execute_scalar=None) -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock(return_value=get_returns)
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=execute_scalar)
    session.execute = AsyncMock(return_value=res)
    session.add = MagicMock()
    return session


def _make_event(
    *,
    cid: str = "conn-1",
    user_id: int = 11,
    user_chat_id: int = 22,
    is_enabled: bool = True,
    can_reply_top: bool = True,
    rights_can_reply: bool = True,
):
    rights = MagicMock()
    rights.can_reply = rights_can_reply
    rights.model_dump = MagicMock(return_value={"can_reply": rights_can_reply})
    return SimpleNamespace(
        id=cid,
        user=SimpleNamespace(id=user_id),
        user_chat_id=user_chat_id,
        is_enabled=is_enabled,
        can_reply=can_reply_top,
        rights=rights,
    )


# ---------------------------------------------------------------------------
# _format_partner_title
# ---------------------------------------------------------------------------


def test_format_partner_title_with_username():
    msg = MagicMock()
    msg.chat.first_name = "Иван"
    msg.chat.last_name = "Петров"
    msg.chat.username = "ivan_p"
    msg.chat.id = 42
    assert _format_partner_title(msg) == "Иван Петров (@ivan_p)"


def test_format_partner_title_no_username():
    msg = MagicMock()
    msg.chat.first_name = "Иван"
    msg.chat.last_name = ""
    msg.chat.username = None
    msg.chat.id = 42
    assert _format_partner_title(msg) == "Иван"


def test_format_partner_title_falls_back_to_id():
    msg = MagicMock()
    msg.chat.first_name = ""
    msg.chat.last_name = ""
    msg.chat.username = None
    msg.chat.id = 42
    assert _format_partner_title(msg) == "Chat 42"


# ---------------------------------------------------------------------------
# handle_business_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_business_connection_inserts_new_row():
    session = _make_session(get_returns=None)
    event = _make_event(cid="abc", is_enabled=True)

    await handle_business_connection(event, session)

    session.add.assert_called_once()
    inserted = session.add.call_args.args[0]
    assert inserted.id == "abc"
    assert inserted.is_enabled is True
    assert inserted.can_reply is True
    assert inserted.rights == {"can_reply": True}
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_business_connection_updates_existing_row():
    existing = MagicMock()
    existing.is_enabled = True
    existing.can_reply = True
    existing.rights = None
    existing.user_chat_id = 0
    session = _make_session(get_returns=existing)
    event = _make_event(cid="abc", is_enabled=False, can_reply_top=False, rights_can_reply=False)

    await handle_business_connection(event, session)

    assert existing.is_enabled is False
    assert existing.can_reply is False
    assert existing.user_chat_id == 22
    session.add.assert_not_called()
    session.commit.assert_awaited()


# ---------------------------------------------------------------------------
# handle_business_message
# ---------------------------------------------------------------------------


def _make_business_message(
    *,
    connection_id: str = "conn-1",
    message_id: int = 100,
    chat_id: int = 555,
    user_id: int = 666,
    text: str = "hello",
):
    msg = MagicMock()
    msg.business_connection_id = connection_id
    msg.message_id = message_id
    msg.chat.id = chat_id
    msg.chat.type = "private"
    msg.chat.first_name = "Иван"
    msg.chat.last_name = "Петров"
    msg.chat.username = "ivan_p"
    msg.from_user = SimpleNamespace(id=user_id, is_bot=False)
    msg.text = text
    msg.caption = None
    msg.date = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    msg.bot = AsyncMock()  # _ensure_connection may call bot.get_business_connection
    return msg


@pytest.mark.asyncio
async def test_business_message_ignored_when_paused(monkeypatch):
    monkeypatch.setattr(settings, "business_paused", True)
    session = _make_session()

    await handle_business_message(_make_business_message(), session)

    session.get.assert_not_called()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_business_message_hydrates_unknown_connection_from_api(monkeypatch):
    monkeypatch.setattr(settings, "business_paused", False)
    monkeypatch.setattr(settings, "is_shutdown", False)

    session = AsyncMock()
    # First DB lookup — no connection. After hydrate (`session.add(conn)`), the
    # subsequent flow is similar to the "known connection" test.
    session.get = AsyncMock(return_value=None)
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=None)  # chat lookup misses
    session.execute = AsyncMock(return_value=res)

    added: list = []

    def _add(obj):
        if obj.__class__.__name__ == "Chat":
            obj.id = "chat-uuid"
        added.append(obj)

    session.add = MagicMock(side_effect=_add)

    msg = _make_business_message()
    api_conn = SimpleNamespace(
        id="conn-1",
        user=SimpleNamespace(id=123),
        user_chat_id=999,
        is_enabled=True,
        can_reply=False,
        rights=None,
    )
    msg.bot = AsyncMock()
    msg.bot.get_business_connection = AsyncMock(return_value=api_conn)

    await handle_business_message(msg, session)

    msg.bot.get_business_connection.assert_awaited_once_with("conn-1")
    # Three rows added: hydrated connection, new chat, new message.
    assert any(o.__class__.__name__ == "BusinessConnection" for o in added)
    assert any(o.__class__.__name__ == "Chat" for o in added)
    assert any(o.__class__.__name__ == "DBMessage" for o in added)


@pytest.mark.asyncio
async def test_business_message_ignored_when_hydration_fails(monkeypatch):
    monkeypatch.setattr(settings, "business_paused", False)
    monkeypatch.setattr(settings, "is_shutdown", False)

    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=res)
    session.add = MagicMock()

    msg = _make_business_message()
    msg.bot = AsyncMock()
    msg.bot.get_business_connection = AsyncMock(side_effect=Exception("forbidden"))

    await handle_business_message(msg, session)

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_business_message_ignored_when_connection_disabled(monkeypatch):
    monkeypatch.setattr(settings, "business_paused", False)
    monkeypatch.setattr(settings, "is_shutdown", False)

    conn = SimpleNamespace(is_enabled=False, id="conn-1")
    session = _make_session(get_returns=conn)
    msg = _make_business_message()
    msg.bot = AsyncMock()  # _ensure_connection will short-circuit on cache hit
    await handle_business_message(msg, session)

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_business_message_creates_chat_and_saves_message(monkeypatch):
    monkeypatch.setattr(settings, "business_paused", False)
    monkeypatch.setattr(settings, "is_shutdown", False)

    conn = SimpleNamespace(is_enabled=True, id="conn-1")

    chats_created: list = []
    messages_added: list = []

    async def fake_get(model, ident):
        return conn  # connection lookup hits cache, no API call

    session = AsyncMock()
    session.get = AsyncMock(side_effect=fake_get)
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=None)  # chat lookup misses
    session.execute = AsyncMock(return_value=res)

    def _add(obj):
        if obj.__class__.__name__ == "Chat":
            obj.id = "chat-uuid"
            chats_created.append(obj)
        else:
            messages_added.append(obj)

    session.add = MagicMock(side_effect=_add)

    msg = _make_business_message()
    await handle_business_message(msg, session)
    msg.bot.get_business_connection.assert_not_awaited()

    assert len(chats_created) == 1
    new_chat = chats_created[0]
    assert new_chat.tg_type == "private"
    assert new_chat.business_connection_id == "conn-1"
    assert new_chat.telegram_id == 555
    assert new_chat.name == "Иван Петров (@ivan_p)"

    assert len(messages_added) == 1
    saved = messages_added[0]
    assert saved.message_id == 100
    assert saved.user_id == 666
    assert saved.text == "hello"


@pytest.mark.asyncio
async def test_business_message_falls_back_to_caption(monkeypatch):
    monkeypatch.setattr(settings, "business_paused", False)
    monkeypatch.setattr(settings, "is_shutdown", False)

    conn = SimpleNamespace(is_enabled=True, id="conn-1")
    chat_obj = SimpleNamespace(
        id="chat-uuid",
        name="x",
        tg_type="private",
        business_connection_id="conn-1",
    )

    async def fake_get(model, ident):
        if model is business_handler.DBBusinessConnection:
            return conn
        return None

    session = AsyncMock()
    session.get = AsyncMock(side_effect=fake_get)
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=chat_obj)
    session.execute = AsyncMock(return_value=res)

    saved_msgs: list = []
    session.add = MagicMock(side_effect=lambda o: saved_msgs.append(o))

    msg = _make_business_message(text=None)
    msg.caption = "from photo"
    # Cached connection lookup, no API call needed.

    await handle_business_message(msg, session)

    assert any(getattr(o, "text", None) == "from photo" for o in saved_msgs)
