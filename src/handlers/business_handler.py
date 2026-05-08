"""Telegram Business mode — observer (FEATURE-004, variant B).

We register two updates from the Bot API 7.2+ Business surface:

- ``business_connection`` — bookkeeping. We upsert a row in
  ``business_connections`` so we know which connection ids are currently
  enabled and which rights they were granted.
- ``business_message`` — observer. Every incoming/outgoing message in the
  owner's private chats (within the bot's whitelist on Telegram side) is
  persisted into ``messages``. We do NOT reply — `/business` toggles only
  control whether we **save**, never whether we send.

Edits and deletions of business messages are deferred (FEATURE-005).
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot, Router
from aiogram.types import BusinessConnection, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import BusinessConnection as DBBusinessConnection
from ..database.models import Chat, ChatType, DBMessage

router = Router()
logger = logging.getLogger(__name__)


def _format_partner_title(message: Message) -> str:
    """Format a private business chat name as ``First Last (@username)``."""
    chat = message.chat
    parts: list[str] = []
    first = (chat.first_name or "").strip()
    last = (chat.last_name or "").strip()
    name = " ".join(p for p in (first, last) if p)
    if name:
        parts.append(name)
    if chat.username:
        parts.append(f"(@{chat.username})")
    if not parts:
        parts.append(f"Chat {chat.id}")
    return " ".join(parts)


def _extract_rights(connection: BusinessConnection) -> tuple[bool, Optional[dict]]:
    """Return ``(can_reply, rights_json_or_none)`` from a BusinessConnection update."""
    rights = connection.rights
    rights_json: Optional[dict] = None
    if rights is not None:
        try:
            rights_json = rights.model_dump(exclude_none=True)
        except Exception:  # noqa: BLE001 — на случай несовместимой версии aiogram
            rights_json = None
    can_reply = bool(getattr(connection, "can_reply", False) or (rights and rights.can_reply))
    return can_reply, rights_json


async def _ensure_connection(
    bot: Bot,
    session: AsyncSession,
    connection_id: Optional[str],
) -> Optional[DBBusinessConnection]:
    """Look up the connection in DB; if missing, hydrate it from Telegram.

    This makes the observer self-healing: even if the original
    ``business_connection`` update was lost (e.g. delivered to a previous
    bot instance that didn't have business handlers registered), the next
    incoming ``business_message`` will trigger a one-shot fetch via
    ``getBusinessConnection`` and store the row.
    """
    if not connection_id:
        return None

    conn = await session.get(DBBusinessConnection, connection_id)
    if conn is not None:
        return conn

    try:
        info = await bot.get_business_connection(connection_id)
    except Exception as exc:  # noqa: BLE001 — TG может ответить чем угодно
        logger.warning("Failed to hydrate business connection %s: %s", connection_id, exc)
        return None

    can_reply, rights_json = _extract_rights(info)
    conn = DBBusinessConnection(
        id=info.id,
        user_id=info.user.id if info.user else 0,
        user_chat_id=info.user_chat_id,
        is_enabled=bool(info.is_enabled),
        can_reply=can_reply,
        rights=rights_json,
    )
    session.add(conn)
    await session.commit()
    logger.info(
        "Hydrated business connection from Telegram API: id=%s user_id=%s enabled=%s",
        info.id,
        info.user.id if info.user else None,
        info.is_enabled,
    )
    return conn


async def _upsert_business_chat(
    session: AsyncSession,
    *,
    telegram_id: int,
    title: str,
    connection_id: str,
) -> Chat:
    result = await session.execute(select(Chat).where(Chat.telegram_id == telegram_id))
    chat = result.scalar_one_or_none()
    if chat is not None:
        dirty = False
        if chat.name != title:
            chat.name = title
            dirty = True
        if chat.tg_type != "private":
            chat.tg_type = "private"
            dirty = True
        if chat.business_connection_id != connection_id:
            chat.business_connection_id = connection_id
            dirty = True
        if dirty:
            await session.commit()
        return chat

    chat = Chat(
        telegram_id=telegram_id,
        name=title,
        description=f"Telegram Business private chat {telegram_id}",
        type=ChatType.MIXED.value.upper(),
        tg_type="private",
        business_connection_id=connection_id,
        is_silent=True,  # observer never replies
    )
    session.add(chat)
    await session.commit()
    logger.info(
        "Created business chat: telegram_id=%s, conn=%s, name=%s",
        telegram_id,
        connection_id,
        title,
    )
    return chat


@router.business_connection()
async def handle_business_connection(event: BusinessConnection, session: AsyncSession) -> None:
    """Track the lifecycle of Telegram Business connections."""
    if not settings.BUSINESS_OBSERVER_ENABLED:
        return

    can_reply, rights_json = _extract_rights(event)

    existing = await session.get(DBBusinessConnection, event.id)
    if existing is None:
        session.add(
            DBBusinessConnection(
                id=event.id,
                user_id=event.user.id if event.user else 0,
                user_chat_id=event.user_chat_id,
                is_enabled=bool(event.is_enabled),
                can_reply=can_reply,
                rights=rights_json,
            )
        )
        await session.commit()
        logger.info(
            "Business connection registered: id=%s user_id=%s enabled=%s can_reply=%s",
            event.id,
            event.user.id if event.user else None,
            event.is_enabled,
            can_reply,
        )
        return

    existing.is_enabled = bool(event.is_enabled)
    existing.can_reply = can_reply
    existing.user_chat_id = event.user_chat_id
    existing.rights = rights_json
    await session.commit()
    logger.info(
        "Business connection updated: id=%s enabled=%s can_reply=%s",
        event.id,
        event.is_enabled,
        can_reply,
    )


@router.business_message()
async def handle_business_message(message: Message, session: AsyncSession) -> None:
    """Observer-only: persist every business message to the digest pipeline."""
    if not settings.BUSINESS_OBSERVER_ENABLED:
        return
    if settings.business_paused:
        # Toggle is the owner's manual local pause — Telegram still sends us
        # messages, we just decide not to write them down.
        return
    if settings.is_shutdown:
        return

    connection_id = message.business_connection_id
    if not connection_id:
        logger.warning("business_message without connection_id: %s", message.message_id)
        return

    connection = await _ensure_connection(message.bot, session, connection_id)
    if connection is None:
        logger.warning(
            "business_message for connection %s — couldn't hydrate, ignoring",
            connection_id,
        )
        return
    if not connection.is_enabled:
        logger.info("business_message for disabled connection %s — ignoring", connection_id)
        return

    # Telegram-side: a private business chat's `chat.id` IS the partner's
    # user id. We use it as the stable telegram_id for the Chat row.
    chat = await _upsert_business_chat(
        session,
        telegram_id=message.chat.id,
        title=_format_partner_title(message),
        connection_id=connection_id,
    )

    if message.from_user is None:
        return  # service messages without an author — can't attribute, skip

    db_message = DBMessage(
        message_id=message.message_id,
        chat_id=chat.id,
        user_id=message.from_user.id,
        text=message.text or message.caption,
        created_at=message.date,
        updated_at=message.date,
        was_responded=False,
    )
    session.add(db_message)
    await session.commit()
