"""Owner-facing commands and inline-callback handlers.

Все команды отвечают только владельцу (``settings.OWNER_ID``) и только в
личном чате с ботом. Управление чатами идёт через выбор чата в инлайн-
клавиатуре, поиск чата всегда по ``Chat.id`` (UUID); ``Chat.name`` /
``Chat.telegram_id`` используются только для отображения и Telegram API.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import (
    BusinessConnection,
    Chat,
    ChatType,
    Commitment,
    DBMessage,
    Event,
    MessageContext,
    MessageThread,
    Style,
    Tag,
)
from ..services.context_service import ContextService
from ..services.openai_service import OpenAIService
from ..services.stats_service import StatsService

router = Router()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Permissions / helpers
# ---------------------------------------------------------------------------


def _is_owner_private(message: Message) -> bool:
    """Owner-only AND only in a private chat with the bot."""
    return (
        message.from_user is not None
        and message.from_user.id == settings.OWNER_ID
        and message.chat.type == "private"
    )


def _owner_callback(callback: CallbackQuery) -> bool:
    return callback.from_user is not None and callback.from_user.id == settings.OWNER_ID


async def _get_chat(session: AsyncSession, chat_id: str) -> Optional[Chat]:
    """Fetch a chat by string UUID, returning ``None`` on bad UUID or miss."""
    try:
        uuid_value = UUID(chat_id)
    except (ValueError, AttributeError):
        return None
    return await session.get(Chat, uuid_value)


async def _get_all_chats(session: AsyncSession) -> List[Chat]:
    result = await session.execute(select(Chat).order_by(Chat.name))
    return list(result.scalars().all())


async def update_chat_title(message: Message, chat_id: UUID, session: AsyncSession) -> None:
    """Refresh ``Chat.name`` from Telegram. Safe to call best-effort."""
    chat = await session.get(Chat, chat_id)
    if chat is None:
        logger.info("Chat %s not in DB, skipping title update", chat_id)
        return

    try:
        chat_info = await message.bot.get_chat(chat.telegram_id)
    except TelegramForbiddenError:
        logger.warning("Bot was kicked from chat %s, removing record", chat.telegram_id)
        await session.delete(chat)
        await session.commit()
        return
    except Exception as exc:  # noqa: BLE001 — Telegram errors vary
        text = str(exc).lower()
        if "chat not found" in text:
            logger.info("Chat %s not found in Telegram, skipping title update", chat.telegram_id)
            return
        logger.error("Error fetching chat info for %s: %s", chat.telegram_id, exc)
        return

    new_title = getattr(chat_info, "title", None) or chat.name
    if new_title and chat.name != new_title:
        chat.name = new_title
        chat.updated_at = datetime.now(timezone.utc)
        await session.commit()
        logger.info("Updated chat title for %s -> %s", chat.telegram_id, new_title)


def _format_chat_name(chat: Chat) -> str:
    return chat.name or f"Chat {chat.telegram_id}"


def _chat_keyboard(chats: List[Chat], prefix: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"📱 {_format_chat_name(chat)}",
                callback_data=f"{prefix}|{chat.id}",
            )
        ]
        for chat in chats
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ---------------------------------------------------------------------------
# FSM states
# ---------------------------------------------------------------------------


class TestStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_probability = State()
    waiting_for_importance = State()
    waiting_for_hours = State()


class UploadState(StatesGroup):
    waiting_for_dump = State()


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


@router.message(Command("help"))
async def help_command(message: Message, session: AsyncSession) -> None:
    """Show help message."""
    if not _is_owner_private(message):
        return

    help_text = (
        "🤖 Команды бота\n\n"
        "📰 Дайджест и действия:\n"
        "/digest [today|yesterday|YYYY-MM-DD] — дайджест за день (по умолчанию: вчера)\n"
        "/today — дайджест за сегодня (с начала дня до сейчас)\n"
        "/glossary — классификация чатов (бизнес / личный / микс)\n"
        "/commits — открытые коммиты (✅ Сделано / 🗑 Отменить)\n"
        "/events — предстоящие события (✅ Прошло / 🗑 Отменить)\n\n"
        "🤝 Telegram Business:\n"
        "/business — статус observer'а (подключения, чаты, пауза)\n"
        "/business on|off — снять / поставить на паузу сохранение сообщений\n\n"
        "📊 Статус и аналитика:\n"
        "/help — этот список команд\n"
        "/status — статус бота + статистика по выбранному чату\n"
        "/list_chats — все чаты с настройками\n"
        "/summ — суммаризация чата за период\n\n"
        "⚙️ Настройки чата:\n"
        "/setmode — silent mode (бот читает, но не отвечает)\n"
        "/set_style — стиль чата (work / friendly / mixed)\n"
        "/set_probability — вероятность ответа\n"
        "/set_importance — порог важности сообщения\n"
        "/smart_mode — smart mode (LLM-фильтр по важности)\n\n"
        "🔄 Обучение и стили:\n"
        "/upload — загрузить дамп переписки для обучения стилю\n"
        "/refresh — пересобрать стиль из истории\n"
        "/style — просмотр профилей стилей\n"
        "/test — тестовое сообщение в чат\n\n"
        "🏷 Контент:\n"
        "/tag — теги сообщений (add/remove/list/stats)\n"
        "/thread — треды сообщений (info/list/new/close)\n\n"
        "🔒 Система:\n"
        "/shutdown — глобальный silent mode (вкл / выкл)"
    )
    await message.answer(help_text, parse_mode=None)


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


@router.message(Command("status"))
async def status_command(message: Message, session: AsyncSession) -> None:
    """Show bot status with detailed statistics."""
    if not _is_owner_private(message):
        return

    chats = await _get_all_chats(session)
    for chat in chats:
        await update_chat_title(message, chat.id, session)

    text = "🤖 Bot Status:\n\n"
    text += (
        "🔴 Global silent mode is enabled\n"
        if settings.is_shutdown
        else "🟢 Bot is running normally\n"
    )
    text += "\n📊 Select a chat to view detailed statistics:\n"

    if not chats:
        await message.answer(text + "\n(no chats yet)", parse_mode=None)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📱 {_format_chat_name(c)}", callback_data=f"stats|{c.id}")]
        for c in chats
    ]
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=None,
    )


@router.callback_query(F.data.startswith("stats|"))
async def process_stats_selection(callback: CallbackQuery, session: AsyncSession) -> None:
    """Process chat selection for statistics."""
    if not _owner_callback(callback):
        await callback.answer("Only the owner can view statistics", show_alert=True)
        return

    _, chat_id = callback.data.split("|", 1)
    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    stats = await StatsService().get_stats(chat.id, session)

    lines = [f"📊 Statistics for {_format_chat_name(chat)}:\n"]
    lines.append("📈 Basic Statistics:")
    lines.append(f"• Messages (week): {stats.message_count}")
    lines.append(f"• Active users: {stats.user_count}")
    lines.append(f"• Avg message length: {stats.avg_length:.1f} chars\n")

    lines.append("🎨 Content Analysis:")
    lines.append(f"• Emoji usage: {stats.emoji_count}")
    lines.append(f"• Sticker usage: {stats.sticker_count}")

    if stats.top_emojis:
        lines.append("\n😊 Top Emojis:")
        for emo, count in list(stats.top_emojis.items())[:5]:
            lines.append(f"• {emo}: {count}")

    if stats.top_words:
        lines.append("\n📝 Top Words:")
        for word, count in list(stats.top_words.items())[:5]:
            lines.append(f"• {word}: {count}")

    if stats.top_topics:
        lines.append("\n💬 Top Topics:")
        for topic in stats.top_topics[:5]:
            if isinstance(topic, dict):
                lines.append(f"• {topic.get('topic')}: {topic.get('count')}")

    lines.append("\n⏰ Activity Analysis:")
    if stats.most_active_hour is not None:
        lines.append(f"• Most active hour: {stats.most_active_hour:02d}:00")
    if stats.most_active_day:
        lines.append(f"• Most active day: {stats.most_active_day}")

    if stats.activity_trend:
        lines.append("\n📅 Activity Trend:")
        for day in stats.activity_trend:
            lines.append(f"• {day['date']}: {day['count']} messages")

    lines.append("\n⚙️ Chat Settings:")
    lines.append(f"• Type: {chat.type}")
    lines.append(f"• Probability: {chat.response_probability * 100:.2f}%")
    lines.append(f"• Smart Mode: {'✅' if chat.smart_mode else '❌'}")
    lines.append(f"• Silent Mode: {'✅' if chat.is_silent else '❌'}")

    await callback.message.edit_text("\n".join(lines), parse_mode=None)
    await callback.answer()


# ---------------------------------------------------------------------------
# /shutdown
# ---------------------------------------------------------------------------


@router.message(Command("shutdown"))
async def shutdown_command(message: Message, session: AsyncSession) -> None:
    """Toggle global silent mode (sets all chats to silent)."""
    if not _is_owner_private(message):
        return

    settings.is_shutdown = not settings.is_shutdown
    if settings.is_shutdown:
        result = await session.execute(select(Chat))
        for chat in result.scalars().all():
            chat.is_silent = True
        await session.commit()
        await message.answer(
            "🔴 Global silent mode enabled\n"
            "ℹ️ All chats are now in silent mode (bot reads but doesn't respond)",
            parse_mode=None,
        )
    else:
        await message.answer(
            "🟢 Global silent mode disabled\n" "ℹ️ Chats will return to their previous state",
            parse_mode=None,
        )


# ---------------------------------------------------------------------------
# /setmode (silent toggle)
# ---------------------------------------------------------------------------


def _silent_keyboard(chats: List[Chat]) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"{'🔇' if chat.is_silent else '🔊'} {_format_chat_name(chat)}",
                callback_data=f"silent|{chat.id}",
            )
        ]
        for chat in chats
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(Command("setmode"))
async def setmode_command(message: Message, session: AsyncSession) -> None:
    """Toggle silent mode in a chat."""
    if not _is_owner_private(message):
        return

    chats = await _get_all_chats(session)
    if not chats:
        await message.answer("No chats found in database.")
        return

    await message.answer(
        "Select a chat to toggle silent mode:",
        reply_markup=_silent_keyboard(chats),
    )


@router.callback_query(F.data.startswith("silent|"))
async def process_toggle_silent(callback: CallbackQuery, session: AsyncSession) -> None:
    """Process silent mode toggle."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_id = callback.data.split("|", 1)
    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    chat.is_silent = not chat.is_silent
    await session.commit()

    chats = await _get_all_chats(session)
    await callback.message.edit_text(
        "Select a chat to toggle silent mode:",
        reply_markup=_silent_keyboard(chats),
    )
    await callback.answer(
        f"Silent mode {'enabled' if chat.is_silent else 'disabled'} for {_format_chat_name(chat)}"
    )


# ---------------------------------------------------------------------------
# /set_probability
# ---------------------------------------------------------------------------


def _probability_keyboard(chat_id: UUID) -> InlineKeyboardMarkup:
    values = [0.0, 0.25, 0.5, 0.75, 1.0]
    keyboard = [
        [InlineKeyboardButton(text=f"{int(v * 100)}%", callback_data=f"prob|{chat_id}|{v}")]
        for v in values
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(Command("set_probability"))
async def set_probability_command(message: Message, session: AsyncSession) -> None:
    """Set response probability for a chat."""
    if not _is_owner_private(message):
        return

    chats = await _get_all_chats(session)
    if not chats:
        await message.answer("No chats found in database.")
        return

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"{_format_chat_name(c)} ({c.response_probability:.2f})",
                callback_data=f"sel|{c.id}",
            )
        ]
        for c in chats
    ]
    await message.answer(
        "Select a chat to set response probability:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


@router.callback_query(F.data.startswith("sel|"))
async def select_chat_for_probability(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show probability options for the selected chat."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_id = callback.data.split("|", 1)
    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.message.edit_text("❌ Чат не найден")
        return

    await callback.message.edit_text(
        f"Выбран чат: {_format_chat_name(chat)}\nВыберите вероятность ответа:",
        reply_markup=_probability_keyboard(chat.id),
    )


@router.callback_query(F.data.startswith("prob|"))
async def set_chat_probability(callback: CallbackQuery, session: AsyncSession) -> None:
    """Apply selected probability."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    try:
        _, chat_id, raw_prob = callback.data.split("|", 2)
        prob = float(raw_prob)
    except (ValueError, IndexError):
        await callback.message.edit_text("❌ Неверный формат")
        return

    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.message.edit_text("❌ Чат не найден")
        return

    chat.response_probability = max(0.0, min(1.0, prob))
    await session.commit()
    await callback.message.edit_text(
        f"✅ Вероятность ответа для чата {_format_chat_name(chat)} установлена на {prob:.2f}"
    )


# ---------------------------------------------------------------------------
# /set_importance
# ---------------------------------------------------------------------------


def _importance_keyboard(chat_id: UUID) -> InlineKeyboardMarkup:
    values = [0.1, 0.3, 0.5, 0.7, 0.9]
    keyboard = [
        [InlineKeyboardButton(text=f"{v:.1f}", callback_data=f"imp|{chat_id}|{v}")] for v in values
    ]
    keyboard.append([InlineKeyboardButton(text="✏️ Custom", callback_data=f"impc|{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(Command("set_importance"))
async def set_importance_command(message: Message, session: AsyncSession) -> None:
    """Set importance threshold for a chat."""
    if not _is_owner_private(message):
        return

    chats = await _get_all_chats(session)
    if not chats:
        await message.answer("No chats found in database.")
        return

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"{_format_chat_name(c)} ({c.importance_threshold:.2f})",
                callback_data=f"impsel|{c.id}",
            )
        ]
        for c in chats
    ]
    await message.answer(
        "Select a chat to set importance threshold:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


@router.callback_query(F.data.startswith("impsel|"))
async def select_chat_for_importance(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show importance options for the selected chat."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_id = callback.data.split("|", 1)
    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    await callback.message.edit_text(
        f"Select importance threshold for {_format_chat_name(chat)}:",
        reply_markup=_importance_keyboard(chat.id),
    )


@router.callback_query(F.data.startswith("imp|"))
async def set_chat_importance(callback: CallbackQuery, session: AsyncSession) -> None:
    """Apply selected importance threshold."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    try:
        _, chat_id, raw_imp = callback.data.split("|", 2)
        imp = float(raw_imp)
    except (ValueError, IndexError):
        await callback.message.edit_text("❌ Неверный формат")
        return

    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    chat.importance_threshold = max(0.0, min(1.0, imp))
    await session.commit()
    await callback.message.edit_text(
        f"Importance threshold set to {imp:.2f} for {_format_chat_name(chat)}"
    )
    await callback.answer("Importance threshold updated")


@router.callback_query(F.data.startswith("impc|"))
async def custom_importance(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask for a free-form importance value."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_id = callback.data.split("|", 1)
    await state.set_state(TestStates.waiting_for_importance)
    await state.update_data(chat_id=chat_id)
    await callback.message.edit_text("Enter custom importance threshold (0.0 to 1.0):")


@router.message(TestStates.waiting_for_importance)
async def process_custom_importance(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Apply free-form importance value."""
    if not _is_owner_private(message):
        return

    try:
        imp = float(message.text or "")
        if not 0.0 <= imp <= 1.0:
            raise ValueError
    except ValueError:
        await message.answer("Please enter a valid number between 0 and 1.")
        await state.clear()
        return

    data = await state.get_data()
    chat_id = data.get("chat_id")
    chat = await _get_chat(session, chat_id) if chat_id else None
    if chat is None:
        await message.answer("Chat not found in database.")
        await state.clear()
        return

    chat.importance_threshold = imp
    await session.commit()
    await message.answer(f"Importance threshold set to {imp:.2f} for {_format_chat_name(chat)}")
    await state.clear()


# ---------------------------------------------------------------------------
# /smart_mode
# ---------------------------------------------------------------------------


def _smart_keyboard(chats: List[Chat]) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"{'🤖' if c.smart_mode else '💭'} {_format_chat_name(c)}",
                callback_data=f"smart|{c.id}",
            )
        ]
        for c in chats
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(Command("smart_mode"))
async def smart_mode_command(message: Message, session: AsyncSession) -> None:
    """Toggle smart mode."""
    if not _is_owner_private(message):
        return

    chats = await _get_all_chats(session)
    if not chats:
        await message.answer("No chats found in database.")
        return

    await message.answer(
        "Select a chat to toggle smart mode:",
        reply_markup=_smart_keyboard(chats),
    )


@router.callback_query(F.data.startswith("smart|"))
async def process_smart_mode_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    """Toggle smart mode for the selected chat."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_id = callback.data.split("|", 1)
    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    chat.smart_mode = not chat.smart_mode
    await session.commit()

    chats = await _get_all_chats(session)
    await callback.message.edit_text(
        "Select a chat to toggle smart mode:",
        reply_markup=_smart_keyboard(chats),
    )
    await callback.answer(
        f"Smart mode {'enabled' if chat.smart_mode else 'disabled'} for {_format_chat_name(chat)}"
    )


# ---------------------------------------------------------------------------
# /list_chats
# ---------------------------------------------------------------------------


@router.message(Command("list_chats"))
async def list_chats_command(message: Message, session: AsyncSession) -> None:
    """List all chats with their settings."""
    if not _is_owner_private(message):
        return

    chats = await _get_all_chats(session)
    if not chats:
        await message.answer("No chats found in database.")
        return

    text_parts = ["📊 Chat Settings:\n"]
    for chat in chats:
        text_parts.append(f"Chat: {_format_chat_name(chat)}")
        text_parts.append(f"Type: {chat.type}")
        text_parts.append(f"Silent Mode: {'🔇' if chat.is_silent else '🔊'}")
        text_parts.append(f"Smart Mode: {'🤖' if chat.smart_mode else '💭'}")
        text_parts.append(f"Response Probability: {chat.response_probability:.2f}")
        text_parts.append(f"Importance Threshold: {chat.importance_threshold:.2f}")
        if chat.created_at:
            text_parts.append(f"Created: {chat.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if chat.updated_at:
            text_parts.append(f"Updated: {chat.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        text_parts.append("")

    await message.answer("\n".join(text_parts))


# ---------------------------------------------------------------------------
# /summ — chat summary
# ---------------------------------------------------------------------------


@router.message(Command("summ"))
async def summarize_chat_command(message: Message, session: AsyncSession) -> None:
    """Generate chat summary."""
    if not _is_owner_private(message):
        return

    chats = await _get_all_chats(session)
    if not chats:
        await message.answer("No chats found in database.")
        return

    for chat in chats:
        await update_chat_title(message, chat.id, session)

    await message.answer(
        "Select chat to generate summary:",
        reply_markup=_chat_keyboard(chats, prefix="summchat"),
    )


@router.callback_query(F.data.startswith("summchat|"))
async def select_summary_period(callback: CallbackQuery, session: AsyncSession) -> None:
    """Pick a period for the summary."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_id = callback.data.split("|", 1)
    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text="🔄 Since last summary", callback_data=f"summp|{chat.id}|last")],
        [InlineKeyboardButton(text="📅 Last 24 hours", callback_data=f"summp|{chat.id}|24h")],
        [InlineKeyboardButton(text="⏰ Custom hours", callback_data=f"summp|{chat.id}|custom")],
    ]
    await callback.message.edit_text(
        f"Select summary period for {_format_chat_name(chat)}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


@router.callback_query(F.data.startswith("summp|"))
async def generate_summary(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Generate summary for the selected period."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    try:
        _, chat_id, period = callback.data.split("|", 2)
    except ValueError:
        await callback.message.edit_text("❌ Неверный период")
        return

    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.message.edit_text("❌ Чат не найден")
        return

    now = datetime.now(timezone.utc)
    if period == "last":
        start_time = chat.last_summary_timestamp or (now - timedelta(days=1))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
    elif period == "24h":
        start_time = now - timedelta(days=1)
    elif period == "custom":
        await state.set_state(TestStates.waiting_for_hours)
        await state.update_data(chat_id=str(chat.id))
        await callback.message.edit_text("Enter number of hours to summarize:", reply_markup=None)
        return
    else:
        await callback.message.edit_text("❌ Неверный период")
        return

    await _send_summary(callback.message, chat, start_time, session)


@router.message(TestStates.waiting_for_hours)
async def process_custom_hours(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Apply custom hours for summary."""
    if not _is_owner_private(message):
        return

    try:
        hours = float(message.text or "")
        if hours <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Please enter a valid positive number")
        await state.clear()
        return

    data = await state.get_data()
    chat = await _get_chat(session, data.get("chat_id"))
    await state.clear()

    if chat is None:
        await message.answer("❌ Chat not found")
        return

    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    await _send_summary(message, chat, start_time, session)


async def _send_summary(
    sink: Message,
    chat: Chat,
    start_time: datetime,
    session: AsyncSession,
) -> None:
    result = await session.execute(
        select(DBMessage)
        .where(DBMessage.chat_id == chat.id, DBMessage.created_at >= start_time)
        .order_by(DBMessage.created_at)
    )
    messages = list(result.scalars().all())
    if not messages:
        await sink.answer("❌ Нет сообщений за выбранный период")
        return

    summary = await ContextService(session).generate_chat_summary(messages)
    chat.last_summary_timestamp = datetime.now(timezone.utc)
    await session.commit()
    await sink.answer(f"📊 Суммаризация для {_format_chat_name(chat)}:\n\n{summary}")


# ---------------------------------------------------------------------------
# /upload — chat dump
# ---------------------------------------------------------------------------


@router.message(Command("upload"))
async def upload_command(message: Message, session: AsyncSession) -> None:
    """Handle chat dump upload for style training."""
    if not _is_owner_private(message):
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👔 Рабочий", callback_data="upload|work"),
                InlineKeyboardButton(text="😊 Дружеский", callback_data="upload|friendly"),
            ],
            [InlineKeyboardButton(text="🔄 Смешанный", callback_data="upload|mixed")],
        ]
    )
    await message.answer(
        "📝 Загрузите дамп переписки одним из способов:\n\n"
        "1️⃣ Текстовое сообщение в формате:\n"
        "[Дата] Имя пользователя: Сообщение\n\n"
        "2️⃣ Файл (.txt или JSON-экспорт Telegram).\n\n"
        "Выберите тип переписки:",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("upload|"))
async def process_upload_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Process chat type selection for upload."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_type = callback.data.split("|", 1)
    if chat_type not in {"work", "friendly", "mixed"}:
        await callback.message.edit_text("❌ Неверный тип чата")
        return

    await state.update_data(chat_type=chat_type)
    await state.set_state(UploadState.waiting_for_dump)
    await callback.message.edit_text(
        "📤 Теперь отправьте дамп переписки текстовым сообщением или файлом.\n"
        "Поддерживаемые форматы: .txt, .json"
    )


@router.message(UploadState.waiting_for_dump)
async def process_dump_upload(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Process chat dump upload and update style."""
    if not _is_owner_private(message):
        return

    data = await state.get_data()
    chat_type = data.get("chat_type")
    await state.clear()

    if chat_type not in {"work", "friendly", "mixed"}:
        await message.answer("❌ Тип чата не выбран. Запустите /upload заново.")
        return

    try:
        text_content = await _read_dump(message)
    except Exception as exc:  # noqa: BLE001 — пользовательский ввод
        logger.error("Error reading dump: %s", exc, exc_info=True)
        await message.answer("❌ Не удалось прочитать дамп. Проверьте формат.")
        return

    if not text_content:
        await message.answer("❌ Не удалось получить содержимое дампа. Проверьте формат.")
        return

    parsed = _parse_dump(text_content, message.from_user.first_name if message.from_user else None)
    if not parsed:
        await message.answer("❌ Не удалось извлечь сообщения из дампа. Проверьте формат.")
        return

    try:
        new_style = await OpenAIService()._generate_style_guide(parsed, chat_type)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error generating style: %s", exc, exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке дампа.")
        return

    style_result = await session.execute(
        select(Style).where(Style.chat_type == ChatType(chat_type))
    )
    style = style_result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if style:
        style.prompt_template = new_style
        style.last_updated = now
    else:
        session.add(
            Style(
                chat_type=ChatType(chat_type),
                prompt_template=new_style,
                last_updated=now,
            )
        )
    await session.commit()
    await message.answer(f"✅ Стиль успешно обновлен для типа '{chat_type}':\n\n{new_style}")


async def _read_dump(message: Message) -> str:
    """Extract a UTF-8 string from either a document or message text."""
    if message.document is None:
        return message.text or ""

    file = await message.bot.get_file(message.document.file_id)
    buf = await message.bot.download_file(file.file_path)
    raw = buf.read().decode("utf-8")

    if message.document.mime_type == "application/json":
        return _json_dump_to_text(
            raw, owner_name=(message.from_user.first_name if message.from_user else None)
        )
    return raw


def _json_dump_to_text(raw: str, owner_name: Optional[str]) -> str:
    """Normalise a Telegram JSON export to ``Name: text`` lines."""
    data = json.loads(raw)
    msgs = data if isinstance(data, list) else data.get("messages", [])
    lines: List[str] = []
    owner_low = (owner_name or "").lower()
    for msg in msgs:
        text = msg.get("text") if isinstance(msg, dict) else None
        sender = msg.get("from") if isinstance(msg, dict) else None
        if not text or not sender:
            continue
        if isinstance(sender, dict):
            name = sender.get("first_name") or sender.get("name") or "Unknown"
        else:
            name = str(sender)
        if owner_low and name.lower() == owner_low:
            name = "Valentin"
        if isinstance(text, list):
            text = "".join(part if isinstance(part, str) else part.get("text", "") for part in text)
        lines.append(f"{name}: {text}")
    return "\n".join(lines)


def _parse_dump(text: str, owner_name: Optional[str]) -> List[str]:
    """Parse a ``[Date] Name: Text`` dump into a list of normalised messages."""
    parsed: List[str] = []
    owner_low = (owner_name or "").lower()
    pattern = re.compile(r"\[(.*?)\]\s*(.*?):\s*(.*)")
    for line in text.splitlines():
        if not line.strip():
            continue
        match = pattern.match(line)
        if match:
            _, name, body = match.groups()
            if owner_low and name.lower() == owner_low:
                name = "Valentin"
            parsed.append(f"{name}: {body}")
        else:
            parsed.append(line.strip())
    return parsed


# ---------------------------------------------------------------------------
# /refresh — rebuild style profile from history
# ---------------------------------------------------------------------------


@router.message(Command("refresh"))
async def refresh_command(message: Message, session: AsyncSession) -> None:
    """Refresh style for chat type."""
    if not _is_owner_private(message):
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💼 Work", callback_data="reftype|work"),
                InlineKeyboardButton(text="😊 Friendly", callback_data="reftype|friendly"),
            ],
            [InlineKeyboardButton(text="🤝 Mixed", callback_data="reftype|mixed")],
        ]
    )
    await message.reply("Select chat type to refresh style profile:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("reftype|"))
async def select_refresh_type(callback: CallbackQuery) -> None:
    """Pick how many messages to analyse."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_type = callback.data.split("|", 1)
    if chat_type not in {"work", "friendly", "mixed"}:
        await callback.message.edit_text("❌ Неверный тип")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Last 100 messages", callback_data=f"refcnt|{chat_type}|100"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Last 200 messages", callback_data=f"refcnt|{chat_type}|200"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Last 500 messages", callback_data=f"refcnt|{chat_type}|500"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 All messages (last week)", callback_data=f"refcnt|{chat_type}|week"
                )
            ],
        ]
    )
    await callback.message.edit_text(
        f"Select how many messages to analyze for {chat_type} style profile:",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("refcnt|"))
async def refresh_style_with_count(callback: CallbackQuery, session: AsyncSession) -> None:
    """Run style refresh with the chosen scope."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    try:
        _, chat_type, count = callback.data.split("|", 2)
    except ValueError:
        await callback.message.edit_text("❌ Неверный формат")
        return

    await callback.message.edit_text(f"🔄 Refreshing {chat_type} style profile...")
    try:
        new_style = await OpenAIService().refresh_style(chat_type, session, message_count=count)
    except Exception as exc:  # noqa: BLE001 — OpenAI ошибки разные
        logger.error("Error refreshing style: %s", exc, exc_info=True)
        await callback.message.edit_text("Sorry, I couldn't refresh the style profile.")
        return

    text = (
        f"🎨 Style Profile for {chat_type.title()} Chats:\n\n"
        f"Last Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Style Guide:\n{new_style}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Refresh Again",
                    callback_data=f"refcnt|{chat_type}|{count}",
                )
            ]
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


# ---------------------------------------------------------------------------
# /test — send a test message into a chat
# ---------------------------------------------------------------------------


@router.message(Command("test"))
async def test_command(message: Message, session: AsyncSession) -> None:
    """Test bot functionality in a specific chat."""
    if not _is_owner_private(message):
        return

    chats = await _get_all_chats(session)
    if not chats:
        await message.answer("No chats found in database.")
        return

    for chat in chats:
        await update_chat_title(message, chat.id, session)

    await message.answer(
        "Select chat to test bot functionality:",
        reply_markup=_chat_keyboard(chats, prefix="testchat"),
    )


@router.callback_query(F.data.startswith("testchat|"))
async def process_test_chat(callback: CallbackQuery, session: AsyncSession) -> None:
    """Process test chat selection."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_id = callback.data.split("|", 1)
    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    try:
        await callback.bot.send_message(chat_id=chat.telegram_id, text="🤖 Test message from bot")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send test message: %s", exc)
        await callback.answer("Failed to send test message", show_alert=True)
        return

    await callback.answer(f"Test message sent to {_format_chat_name(chat)}")


# ---------------------------------------------------------------------------
# /tag
# ---------------------------------------------------------------------------


@router.message(Command("tag"))
async def tag_command(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
) -> None:
    """Handle tag-related commands."""
    if not _is_owner_private(message):
        return

    if not command.args:
        await message.answer(
            "Usage:\n"
            "/tag add <message_id> <tag> - Add tag to message\n"
            "/tag remove <message_id> <tag> - Remove tag from message\n"
            "/tag list <message_id> - List message tags\n"
            "/tag stats - Show tag statistics"
        )
        return

    args = command.args.split()
    if not args:
        return

    action = args[0].lower()
    context_service = ContextService(session)

    if action == "stats":
        result = await session.execute(select(Tag))
        all_tags = list(result.scalars().all())
        if not all_tags:
            await message.answer("No tags found.")
            return
        lines = ["📊 Tag Statistics:\n"]
        for tag in all_tags:
            lines.append(f"#{tag.name}")
        await message.answer("\n".join(lines))
        return

    if len(args) < 2:
        await message.answer("Please provide message_id")
        return

    try:
        target_msg_id = int(args[1])
    except ValueError:
        await message.answer("Invalid message ID")
        return

    result = await session.execute(select(DBMessage).where(DBMessage.message_id == target_msg_id))
    target_msg = result.scalar_one_or_none()
    if target_msg is None:
        await message.answer("Message not found")
        return

    if action == "list":
        if not target_msg.tags:
            await message.answer("No tags for this message")
            return
        lines = ["🏷 Tags:"]
        for mt in target_msg.tags:
            suffix = " (auto)" if mt.is_auto else ""
            lines.append(f"#{mt.tag.name}{suffix}")
        await message.answer("\n".join(lines))
        return

    if action == "add" and len(args) >= 3:
        tag_name = args[2].strip("#")
        tags = await context_service.get_or_create_tags([tag_name])
        await context_service.add_tags_to_message(target_msg, tags, is_auto=False)
        await message.answer(f"Added tag #{tag_name} to message {target_msg_id}")
        return

    if action == "remove" and len(args) >= 3:
        tag_name = args[2].strip("#")
        for mt in target_msg.tags:
            if mt.tag.name == tag_name:
                await session.delete(mt)
                await session.commit()
                await message.answer(f"Removed tag #{tag_name} from message {target_msg_id}")
                return
        await message.answer(f"Tag #{tag_name} not found on message {target_msg_id}")
        return

    await message.answer("Invalid command format")


# ---------------------------------------------------------------------------
# /thread
# ---------------------------------------------------------------------------


@router.message(Command("thread"))
async def thread_command(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
) -> None:
    """Handle thread-related commands."""
    if not _is_owner_private(message):
        return

    if not command.args:
        await message.answer(
            "Usage:\n"
            "/thread info <chat_telegram_id> - Show current thread info\n"
            "/thread list <chat_telegram_id> - List active threads\n"
            "/thread new <chat_telegram_id> <topic> - Start new thread\n"
            "/thread close <chat_telegram_id> - Close current thread"
        )
        return

    args = command.args.split()
    if len(args) < 2:
        await message.answer("Please provide chat_telegram_id as the second argument.")
        return

    action = args[0].lower()
    try:
        telegram_id = int(args[1])
    except ValueError:
        await message.answer("Invalid chat_telegram_id")
        return

    result = await session.execute(select(Chat).where(Chat.telegram_id == telegram_id))
    chat = result.scalar_one_or_none()
    if chat is None:
        await message.answer("Chat not found")
        return

    context_service = ContextService(session)

    if action == "list":
        result = await session.execute(
            select(MessageThread).where(
                MessageThread.chat_id == chat.id,
                MessageThread.is_active.is_(True),
            )
        )
        threads = list(result.scalars().all())
        if not threads:
            await message.answer("No active threads")
            return
        lines = ["🧵 Active Threads:\n"]
        for thread in threads:
            stats = await context_service.get_thread_stats(thread)
            lines.append(f"📌 {thread.topic}")
            if stats:
                lines.append(f"Messages: {stats['message_count']}")
                lines.append(f"Users: {stats['unique_users']}")
                lines.append(f"Duration: {stats['duration_hours']:.1f}h")
                if stats["top_tags"]:
                    lines.append("Top tags: " + ", ".join(f"#{t}" for t in stats["top_tags"]))
            lines.append("")
        await message.answer("\n".join(lines))
        return

    if action == "info":
        thread = await context_service.get_or_create_thread(chat.id)
        ctx_result = await session.execute(
            select(MessageContext).where(MessageContext.thread_id == thread.id)
        )
        context = ctx_result.scalar_one_or_none()
        stats = await context_service.get_thread_stats(thread)
        related = await context_service.find_related_threads(thread)

        lines = [f"🧵 Thread: {thread.topic}\n"]
        if context and context.context_summary:
            lines.append(f"Context Summary:\n{context.context_summary}\n")
        if stats:
            lines.append("📊 Statistics:")
            lines.append(f"Messages: {stats['message_count']}")
            lines.append(f"Users: {stats['unique_users']}")
            lines.append(f"Avg Length: {stats['avg_message_length']:.0f} chars")
            lines.append(f"Rate: {stats['messages_per_hour']:.1f} msgs/hour")
            if stats["top_tags"]:
                lines.append("Top tags: " + ", ".join(f"#{t}" for t in stats["top_tags"]))
            lines.append("")
        if related:
            lines.append("🔗 Related Threads:")
            for rel in related:
                lines.append(f"- {rel.topic}")
        await message.answer("\n".join(lines))
        return

    if action == "new" and len(args) > 2:
        topic = " ".join(args[2:])
        await context_service.get_or_create_thread(chat.id, topic)
        await message.answer(f"Started new thread: {topic}")
        return

    if action == "close":
        thread = await context_service.get_or_create_thread(chat.id)
        thread.is_active = False
        await session.commit()
        await message.answer(f"Closed thread: {thread.topic}")
        return

    await message.answer("Invalid command format")


# ---------------------------------------------------------------------------
# /set_style
# ---------------------------------------------------------------------------


@router.message(Command("set_style"))
async def set_style_command(message: Message, session: AsyncSession) -> None:
    """Set chat style."""
    if not _is_owner_private(message):
        return

    chats = await _get_all_chats(session)
    if not chats:
        await message.answer("No chats found in database.")
        return

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"🎯 {_format_chat_name(c)}",
                callback_data=f"setchat|{c.id}",
            )
        ]
        for c in chats
    ]
    await message.answer(
        "Select chat to set style:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


@router.callback_query(F.data.startswith("setchat|"))
async def select_chat_for_style(callback: CallbackQuery, session: AsyncSession) -> None:
    """Pick a style for the selected chat."""
    if not _owner_callback(callback):
        return

    _, chat_id = callback.data.split("|", 1)
    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💼 Work", callback_data=f"setstyle|{chat.id}|work"),
                InlineKeyboardButton(
                    text="😊 Friendly", callback_data=f"setstyle|{chat.id}|friendly"
                ),
            ],
            [InlineKeyboardButton(text="🤝 Mixed", callback_data=f"setstyle|{chat.id}|mixed")],
        ]
    )
    await callback.message.edit_text("Select style for this chat:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("setstyle|"))
async def set_chat_style(callback: CallbackQuery, session: AsyncSession) -> None:
    """Apply a style to the selected chat."""
    if not _owner_callback(callback):
        return

    try:
        _, chat_id, style = callback.data.split("|", 2)
    except ValueError:
        await callback.message.edit_text("❌ Неверный формат")
        return

    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    chat.type = style.upper()
    await session.commit()
    await callback.message.edit_text(
        f"Style for {_format_chat_name(chat)} set to {style}",
        reply_markup=None,
    )


# ---------------------------------------------------------------------------
# /style — view style profiles
# ---------------------------------------------------------------------------


@router.message(Command("style"))
async def style_command(message: Message, session: AsyncSession) -> None:
    """View current style profiles."""
    if not _is_owner_private(message):
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💼 Work Style", callback_data="viewstyle|work"),
                InlineKeyboardButton(text="😊 Friendly Style", callback_data="viewstyle|friendly"),
            ],
            [InlineKeyboardButton(text="🤝 Mixed Style", callback_data="viewstyle|mixed")],
        ]
    )
    await message.answer("Select style type to view:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("viewstyle|"))
async def view_style_profile(callback: CallbackQuery, session: AsyncSession) -> None:
    """View style profile for selected type."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, style_type = callback.data.split("|", 1)
    if style_type not in {"work", "friendly", "mixed"}:
        await callback.message.edit_text("❌ Неверный тип")
        return

    result = await session.execute(select(Style).where(Style.chat_type == ChatType(style_type)))
    style = result.scalar_one_or_none()
    if style is None:
        await callback.message.edit_text(
            f"No style profile found for {style_type} chats.\n" f"Use /refresh to create one."
        )
        return

    last_updated = style.last_updated.strftime("%Y-%m-%d %H:%M:%S") if style.last_updated else "—"
    text = (
        f"🎨 Style Profile for {style_type.title()} Chats:\n\n"
        f"Last Updated: {last_updated}\n\n"
        f"Style Guide:\n{style.prompt_template}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Refresh Style",
                    callback_data=f"refcnt|{style_type}|100",
                )
            ]
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


# ---------------------------------------------------------------------------
# /digest — daily chat digest (FEATURE-002)
# ---------------------------------------------------------------------------


def _parse_digest_arg(arg: Optional[str]):
    """Parse the /digest argument into a calendar date (Europe/Moscow).

    - empty / None → yesterday (the canonical "last full day").
    - "today"      → today (partial day, 00:00..now).
    - "YYYY-MM-DD" → that exact day.
    Returns ``None`` on malformed input.
    """
    from datetime import date as _date

    from ..services.digest_service import today_in_moscow, yesterday_in_moscow

    if not arg or not arg.strip():
        return yesterday_in_moscow()
    arg = arg.strip().lower()
    if arg == "today":
        return today_in_moscow()
    if arg == "yesterday":
        return yesterday_in_moscow()
    try:
        return _date.fromisoformat(arg)
    except ValueError:
        return None


@router.message(Command("digest"))
async def digest_command(message: Message, command: CommandObject, session: AsyncSession) -> None:
    """Send a chat digest to the owner.

    Usage:
        /digest                 — yesterday (default)
        /digest today           — today so far
        /digest 2026-05-08      — explicit date
    """
    if not _is_owner_private(message):
        return

    day = _parse_digest_arg(command.args)
    if day is None:
        await message.answer("Не понял дату. Примеры: /digest, /digest today, /digest 2026-05-08")
        return

    from ..services.digest_service import DigestService

    service = DigestService(session, message.bot)
    await message.answer(f"⏳ Готовлю дайджест за {day.strftime('%d.%m.%Y')}…")
    try:
        sent = await service.send_for_day(day, record=False)
    except Exception as exc:  # noqa: BLE001 — командой управляет владелец, ему и логи
        logger.error("Digest failed for %s: %s", day, exc, exc_info=True)
        await message.answer(f"❌ Ошибка при сборке дайджеста: {exc}")
        return

    if sent == 0:
        await message.answer("✅ Тихий день — отправил уведомление.")
    else:
        await message.answer(f"✅ Готово: {sent} чат(ов).")


# ---------------------------------------------------------------------------
# /today — shortcut: digest for today (FEATURE-006)
# ---------------------------------------------------------------------------


@router.message(Command("today"))
async def today_command(message: Message, session: AsyncSession) -> None:
    """Send the digest for today (so far). Equivalent to ``/digest today``."""
    if not _is_owner_private(message):
        return

    from ..services.digest_service import DigestService, today_in_moscow

    day = today_in_moscow()
    service = DigestService(session, message.bot)
    await message.answer(f"⏳ Готовлю дайджест за сегодня ({day.strftime('%d.%m.%Y')})…")
    try:
        sent = await service.send_for_day(day, record=False)
    except Exception as exc:  # noqa: BLE001 — owner-only, ему и логи
        logger.error("/today digest failed: %s", exc, exc_info=True)
        await message.answer(f"❌ Ошибка при сборке дайджеста: {exc}")
        return
    if sent == 0:
        await message.answer("✅ Тихий день пока — отправил уведомление.")
    else:
        await message.answer(f"✅ Готово: {sent} чат(ов).")


# ---------------------------------------------------------------------------
# /business — Telegram Business observer (FEATURE-004)
# ---------------------------------------------------------------------------


@router.message(Command("business"))
async def business_command(message: Message, command: CommandObject, session: AsyncSession) -> None:
    """Inspect / pause / resume the Business observer.

    Usage:
        /business              — show status
        /business off          — locally pause saving (Telegram still streams)
        /business on           — resume saving
    """
    if not _is_owner_private(message):
        return

    arg = (command.args or "").strip().lower()
    if arg == "off":
        settings.business_paused = True
        await message.answer(
            "🟡 Business observer на паузе.\n"
            "Telegram всё ещё шлёт сообщения, но в БД мы их не пишем.\n"
            "Чтобы полностью отключить — выключи бота в Telegram → "
            "Settings → Telegram Business → Chatbots."
        )
        return
    if arg == "on":
        settings.business_paused = False
        await message.answer("🟢 Business observer включён, сообщения снова сохраняются.")
        return
    if arg and arg != "status":
        await message.answer("Не понял команду. Примеры: /business, /business on, /business off")
        return

    conn_result = await session.execute(select(BusinessConnection))
    connections = list(conn_result.scalars().all())
    enabled = [c for c in connections if c.is_enabled]
    chat_result = await session.execute(
        select(Chat).where(
            Chat.tg_type == "private",
            Chat.business_connection_id.isnot(None),
        )
    )
    business_chats = list(chat_result.scalars().all())

    paused_line = "🟡 на паузе" if settings.business_paused else "🟢 активен"
    feature_line = (
        "🟢 включён в коде" if settings.BUSINESS_OBSERVER_ENABLED else "🔴 выключен в коде"
    )

    lines = [
        "🤝 Business observer",
        f"• Состояние: {paused_line}",
        f"• Код: {feature_line}",
        f"• Подключений всего: {len(connections)} (активных: {len(enabled)})",
        f"• Бизнес-чатов в БД: {len(business_chats)}",
    ]
    if business_chats:
        lines.append("\nЧаты:")
        for chat in business_chats[:20]:
            lines.append(f"  • {_format_chat_name(chat)}")
        if len(business_chats) > 20:
            lines.append(f"  …и ещё {len(business_chats) - 20}")
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------------------
# /glossary, /commits, /events — FEATURE-007/008/009
# ---------------------------------------------------------------------------


_CLASSIFICATION_LABELS = {
    "business": "💼 Бизнес",
    "private": "👤 Личный",
    "mixed": "🤝 Микс",
}


def _classification_badge(value: Optional[str]) -> str:
    if not value:
        return "❓ не задан"
    return _CLASSIFICATION_LABELS.get(value, value)


@router.message(Command("glossary"))
async def glossary_command(message: Message, session: AsyncSession) -> None:
    """List all Business private chats with their classification + buttons."""
    if not _is_owner_private(message):
        return

    result = await session.execute(
        select(Chat)
        .where(Chat.tg_type == "private", Chat.business_connection_id.isnot(None))
        .order_by(Chat.name)
    )
    chats = list(result.scalars().all())
    if not chats:
        await message.answer("Пока нет личных бизнес-чатов в БД.")
        return

    lines = ["🗂 Глоссарий чатов\n"]
    keyboard: List[List[InlineKeyboardButton]] = []
    for chat in chats:
        label = _classification_badge(chat.classification)
        lines.append(f"• {_format_chat_name(chat)} — {label}")
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"⚙️ {_format_chat_name(chat)}",
                    callback_data=f"glo|{chat.id}",
                )
            ]
        )
    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


@router.callback_query(F.data.startswith("glo|"))
async def glossary_pick_chat(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    _, chat_id = callback.data.split("|", 1)
    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    body = (
        f"⚙️ Чат: {_format_chat_name(chat)}\n"
        f"Сейчас: {_classification_badge(chat.classification)}\n"
        "Выбери новую классификацию:"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💼 Бизнес", callback_data=f"cls|{chat.id}|business"),
                InlineKeyboardButton(text="👤 Личный", callback_data=f"cls|{chat.id}|private"),
                InlineKeyboardButton(text="🤝 Микс", callback_data=f"cls|{chat.id}|mixed"),
            ],
            [
                InlineKeyboardButton(text="🧹 Сбросить", callback_data=f"cls|{chat.id}|clear"),
                InlineKeyboardButton(text="⏭ Позже", callback_data=f"cls|{chat.id}|skip"),
            ],
        ]
    )
    await callback.message.edit_text(body, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("cls|"))
async def classification_set(callback: CallbackQuery, session: AsyncSession) -> None:
    """Apply a classification to a chat (used by glossary AND digest suggestions)."""
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    try:
        _, chat_id, value = callback.data.split("|", 2)
    except ValueError:
        await callback.answer("Bad callback", show_alert=True)
        return

    if value == "skip":
        await callback.answer("Окей, спрошу позже.")
        return

    chat = await _get_chat(session, chat_id)
    if chat is None:
        await callback.answer("Chat not found", show_alert=True)
        return

    if value == "clear":
        chat.classification = None
        await session.commit()
        await callback.answer("Сбросил классификацию.")
        try:
            await callback.message.edit_text(
                f"🧹 {_format_chat_name(chat)} — классификация сброшена."
            )
        except TelegramForbiddenError:  # pragma: no cover — race with deleted message
            pass
        return

    if value not in ("business", "private", "mixed"):
        await callback.answer("Bad value", show_alert=True)
        return

    chat.classification = value
    chat.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await callback.answer(f"Сохранил: {_CLASSIFICATION_LABELS[value]}")
    try:
        await callback.message.edit_text(
            f"✅ {_format_chat_name(chat)} → {_CLASSIFICATION_LABELS[value]}"
        )
    except TelegramForbiddenError:  # pragma: no cover
        pass


def _commit_short(text: str, *, max_len: int = 60) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


@router.message(Command("commits"))
async def commits_command(message: Message, session: AsyncSession) -> None:
    """List all open commitments across chats with done/cancel buttons."""
    if not _is_owner_private(message):
        return

    result = await session.execute(
        select(Commitment, Chat)
        .join(Chat, Chat.id == Commitment.chat_id)
        .where(Commitment.status == "open")
        .order_by(Commitment.is_urgent.desc(), Commitment.deadline_at.asc().nullslast())
    )
    rows = list(result.all())
    if not rows:
        await message.answer("✅ Открытых коммитов нет.")
        return

    await message.answer(f"🤝 Открытых коммитов: {len(rows)}")
    for commitment, chat in rows:
        direction = "→ от меня" if commitment.direction == "from_me" else "← мне"
        urgent = "⚠️ " if commitment.is_urgent else ""
        deadline = f" ({commitment.deadline_raw})" if commitment.deadline_raw else ""
        body = (
            f"{urgent}{direction} в чате «{_format_chat_name(chat)}»\n"
            f"{_commit_short(commitment.text)}{deadline}"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Сделано", callback_data=f"commit|{commitment.id}|done"
                    ),
                    InlineKeyboardButton(
                        text="🗑 Отменить", callback_data=f"commit|{commitment.id}|cancel"
                    ),
                ]
            ]
        )
        await message.answer(body, reply_markup=keyboard)


@router.callback_query(F.data.startswith("commit|"))
async def commit_action(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    try:
        _, raw_id, action = callback.data.split("|", 2)
        commit_id = UUID(raw_id)
    except (ValueError, IndexError):
        await callback.answer("Bad callback", show_alert=True)
        return

    if action not in ("done", "cancel"):
        await callback.answer("Bad action", show_alert=True)
        return

    commitment = await session.get(Commitment, commit_id)
    if commitment is None:
        await callback.answer("Не нашёл коммит — возможно, уже удалён.", show_alert=True)
        return

    now = datetime.now(timezone.utc)
    commitment.status = "done" if action == "done" else "cancelled"
    commitment.updated_at = now
    commitment.completed_at = now
    await session.commit()

    label = "✅ Сделано" if action == "done" else "🗑 Отменено"
    try:
        original = callback.message.text or ""
        await callback.message.edit_text(f"{label}\n\n{original}", reply_markup=None)
    except TelegramForbiddenError:  # pragma: no cover
        pass
    await callback.answer(label)


@router.message(Command("events"))
async def events_command(message: Message, session: AsyncSession) -> None:
    """List all upcoming events across chats with done/cancel buttons."""
    if not _is_owner_private(message):
        return

    result = await session.execute(
        select(Event, Chat)
        .join(Chat, Chat.id == Event.chat_id)
        .where(Event.status == "upcoming")
        .order_by(Event.is_urgent.desc(), Event.when_at.asc().nullslast())
    )
    rows = list(result.all())
    if not rows:
        await message.answer("📅 Запланированных событий нет.")
        return

    await message.answer(f"📅 Запланированных событий: {len(rows)}")
    for event, chat in rows:
        urgent = "⚠️ " if event.is_urgent else ""
        when = f" — {event.when_raw}" if event.when_raw else ""
        body = (
            f"{urgent}В чате «{_format_chat_name(chat)}»\n"
            f"{_commit_short(event.description)}{when}"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Прошло", callback_data=f"event|{event.id}|done"),
                    InlineKeyboardButton(
                        text="🗑 Отменить", callback_data=f"event|{event.id}|cancel"
                    ),
                ]
            ]
        )
        await message.answer(body, reply_markup=keyboard)


@router.callback_query(F.data.startswith("event|"))
async def event_action(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _owner_callback(callback):
        await callback.answer("Not authorised", show_alert=True)
        return

    try:
        _, raw_id, action = callback.data.split("|", 2)
        event_id = UUID(raw_id)
    except (ValueError, IndexError):
        await callback.answer("Bad callback", show_alert=True)
        return

    if action not in ("done", "cancel"):
        await callback.answer("Bad action", show_alert=True)
        return

    event = await session.get(Event, event_id)
    if event is None:
        await callback.answer("Не нашёл событие — возможно, уже удалено.", show_alert=True)
        return

    now = datetime.now(timezone.utc)
    event.status = "past" if action == "done" else "cancelled"
    event.updated_at = now
    await session.commit()

    label = "✅ Прошло" if action == "done" else "🗑 Отменено"
    try:
        original = callback.message.text or ""
        await callback.message.edit_text(f"{label}\n\n{original}", reply_markup=None)
    except TelegramForbiddenError:  # pragma: no cover
        pass
    await callback.answer(label)
