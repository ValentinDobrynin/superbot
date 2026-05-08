"""Handle non-command messages and chat-membership updates."""

from __future__ import annotations

import logging
import random
from typing import Optional

from aiogram import F, Router
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import Chat, ChatType, DBMessage

router = Router()
logger = logging.getLogger(__name__)


async def _get_or_create_chat(
    *,
    session: AsyncSession,
    telegram_id: int,
    title: Optional[str],
    tg_type: str,
) -> Chat:
    """Look up a chat by ``telegram_id`` (the only stable identifier) or create it."""
    result = await session.execute(select(Chat).where(Chat.telegram_id == telegram_id))
    chat = result.scalar_one_or_none()
    if chat is not None:
        dirty = False
        if title and chat.name != title:
            chat.name = title
            dirty = True
        if chat.tg_type != tg_type:
            chat.tg_type = tg_type
            dirty = True
        if dirty:
            await session.commit()
        return chat

    chat = Chat(
        telegram_id=telegram_id,
        name=title or f"Chat {telegram_id}",
        description=f"Telegram chat {telegram_id}",
        type=ChatType.MIXED.value.upper(),
        tg_type=tg_type,
    )
    session.add(chat)
    await session.commit()
    logger.info(
        "Created new chat: telegram_id=%s, tg_type=%s, name=%s",
        telegram_id,
        tg_type,
        chat.name,
    )
    return chat


@router.chat_member()
async def handle_chat_member_update(event: ChatMemberUpdated, session: AsyncSession) -> None:
    """Track when the bot itself is added to or removed from chats."""
    if settings.is_shutdown:
        return

    if event.new_chat_member.user.id != event.bot.id:
        return

    if event.chat.type == "channel":
        # Per project requirement: bot only handles chats, never channels.
        logger.info("Bot was added to channel %s — leaving immediately", event.chat.id)
        try:
            await event.bot.leave_chat(event.chat.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to leave channel %s: %s", event.chat.id, exc)
        return

    title = event.chat.title
    try:
        chat_info = await event.bot.get_chat(event.chat.id)
        title = chat_info.title or title
    except Exception as exc:  # noqa: BLE001 — TG может вернуть что угодно
        logger.warning("Could not fetch chat info for %s: %s", event.chat.id, exc)

    await _get_or_create_chat(
        session=session,
        telegram_id=event.chat.id,
        title=title,
        tg_type=event.chat.type,
    )


@router.message(F.text)
async def handle_message(message: Message, session: AsyncSession) -> None:
    """Persist incoming messages and, when allowed, generate a reply."""
    if message.from_user is None or message.from_user.is_bot:
        return
    if settings.is_shutdown:
        return
    if message.chat.type == "private":
        # Управляющие команды владельца приходят в личку и обрабатываются
        # отдельно в command_handler; обычный текст в личке игнорируем.
        return
    if message.chat.type == "channel":
        # Channels are out of scope; safety net in case we somehow ended up there.
        return

    chat = await _get_or_create_chat(
        session=session,
        telegram_id=message.chat.id,
        title=message.chat.title,
        tg_type=message.chat.type,
    )

    if chat.is_silent:
        await _process_for_learning(message, chat, session)
        return

    await _process_and_respond(message, chat, session)


async def _save_message(message: Message, chat: Chat, session: AsyncSession) -> DBMessage:
    db_message = DBMessage(
        message_id=message.message_id,
        chat_id=chat.id,
        user_id=message.from_user.id,
        text=message.text,
        created_at=message.date,
        updated_at=message.date,
        was_responded=False,
    )
    session.add(db_message)
    await session.commit()
    return db_message


async def _process_for_learning(message: Message, chat: Chat, session: AsyncSession) -> None:
    """Silent mode: save the message and ensure an active thread exists."""
    await _save_message(message, chat, session)

    from ..services.context_service import ContextService  # avoid circular import

    context_service = ContextService(session)
    await context_service.get_or_create_thread(chat.id)


async def _process_and_respond(message: Message, chat: Chat, session: AsyncSession) -> None:
    """Active mode: persist, decide whether to reply, and reply."""
    if message.from_user.id == settings.OWNER_ID:
        # Не отвечаем самому владельцу — но историю продолжаем сохранять.
        await _save_message(message, chat, session)
        return

    db_message = await _save_message(message, chat, session)

    from ..services.context_service import ContextService
    from ..services.openai_service import OpenAIService

    context_service = ContextService(session)
    await context_service.get_or_create_thread(chat.id)

    result = await session.execute(
        select(DBMessage)
        .where(DBMessage.chat_id == chat.id)
        .order_by(DBMessage.created_at.desc())
        .limit(settings.MAX_CONTEXT_MESSAGES)
    )
    recent = list(result.scalars().all())
    context_messages = [{"text": msg.text, "is_user": True} for msg in reversed(recent) if msg.text]

    openai_service = OpenAIService()
    chat_type = ChatType((chat.type or ChatType.MIXED.value).lower())

    try:
        if chat.smart_mode:
            importance = await openai_service.analyze_message_importance(message.text or "")
            if importance < chat.importance_threshold:
                return
        else:
            if random.random() >= chat.response_probability:
                return

        response = await openai_service.generate_response(
            message=message.text or "",
            chat_type=chat_type,
            context_messages=context_messages,
            session=session,
        )
        if response:
            await message.reply(response)
            db_message.was_responded = True
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — не роняем поллер
        logger.error(
            "Error processing message in chat %s: %s", chat.telegram_id, exc, exc_info=True
        )
