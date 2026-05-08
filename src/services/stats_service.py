"""Background statistics service: collects per-chat metrics for /status etc."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

import emoji
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.database import get_session
from ..database.models import Chat, DBMessage, MessageStats
from .openai_service import OpenAIService

logger = logging.getLogger(__name__)

CACHE_DURATION = timedelta(minutes=5)
PERIODIC_INTERVAL_SECONDS = 300

# Стоп-слова русского языка для подсчёта top_words.
RUSSIAN_STOP_WORDS = {
    # Предлоги / местоимения / частицы (минимально достаточный набор)
    "в",
    "во",
    "не",
    "что",
    "он",
    "на",
    "я",
    "с",
    "со",
    "как",
    "а",
    "то",
    "все",
    "она",
    "так",
    "его",
    "но",
    "да",
    "ты",
    "к",
    "у",
    "же",
    "вы",
    "за",
    "бы",
    "по",
    "только",
    "ее",
    "мне",
    "было",
    "вот",
    "от",
    "меня",
    "еще",
    "нет",
    "о",
    "из",
    "ему",
    "теперь",
    "когда",
    "даже",
    "ну",
    "вдруг",
    "ли",
    "если",
    "уже",
    "или",
    "ни",
    "быть",
    "был",
    "него",
    "чего",
    "при",
    "об",
    "оно",
    "они",
    "этот",
    "тот",
    "такой",
    "такая",
    "такое",
    "такие",
    "каждый",
    "каждая",
    "каждое",
    "каждые",
    "мой",
    "моя",
    "мое",
    "мои",
    "твой",
    "твоя",
    "твое",
    "твои",
    "наш",
    "наша",
    "наше",
    "наши",
    "ваш",
    "ваша",
    "ваше",
    "ваши",
    "их",
    # Союзы
    "и",
    "чтобы",
    "будто",
    "словно",
    "точно",
    "раз",
    "коль",
    "коли",
    "хотя",
    "пусть",
    "пускай",
    "дабы",
    "ибо",
    "поскольку",
    "притом",
    "причем",
    # Частицы
    "б",
    "ль",
    "ведь",
    "вон",
    "дескать",
    "де",
    "мол",
    "разве",
    "ровно",
    "ужели",
    "ужель",
    "давай",
    "давайте",
    "именно",
    "лишь",
    "хоть",
    "едва",
    "неужели",
    "неужель",
}


class StatsService:
    """Caches and computes ``MessageStats`` rows."""

    def __init__(self) -> None:
        self._cache: dict[UUID, MessageStats] = {}

    async def get_stats(self, chat_id: UUID, session: AsyncSession) -> MessageStats:
        """Return the latest cached or freshly computed stats for ``chat_id``."""
        cached = self._cache.get(chat_id)
        if cached is not None and self._is_fresh(cached):
            return cached

        result = await session.execute(
            select(MessageStats)
            .where(MessageStats.chat_id == chat_id, MessageStats.period == "week")
            .order_by(MessageStats.timestamp.desc())
            .limit(1)
        )
        stats = result.scalar_one_or_none()
        if stats is None or not self._is_fresh(stats):
            stats = await self._calculate_stats(chat_id, session)

        self._cache[chat_id] = stats
        return stats

    async def _calculate_stats(self, chat_id: UUID, session: AsyncSession) -> MessageStats:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        result = await session.execute(
            select(DBMessage)
            .where(DBMessage.chat_id == chat_id, DBMessage.created_at >= week_ago)
            .order_by(DBMessage.created_at)
        )
        messages = list(result.scalars().all())

        if not messages:
            stats = MessageStats(
                chat_id=chat_id,
                period="week",
                timestamp=now.replace(tzinfo=None),
                message_count=0,
                user_count=0,
                avg_length=0.0,
                emoji_count=0,
                sticker_count=0,
                top_emojis={},
                top_stickers={},
                top_words={},
                top_topics=[],
                most_active_hour=None,
                most_active_day=None,
                activity_trend=[],
            )
            session.add(stats)
            await session.commit()
            return stats

        message_count = len(messages)
        user_count = len({msg.user_id for msg in messages})
        avg_length = sum(len(msg.text or "") for msg in messages) / message_count

        emoji_counter: Counter[str] = Counter()
        emoji_total = 0
        for msg in messages:
            if not msg.text:
                continue
            chars = [c for c in msg.text if emoji.is_emoji(c)]
            emoji_total += len(chars)
            emoji_counter.update(chars)

        word_counter: Counter[str] = Counter()
        for msg in messages:
            if not msg.text:
                continue
            words = [
                w.lower()
                for w in re.findall(r"\b\w+\b", msg.text)
                if w.lower() not in RUSSIAN_STOP_WORDS and len(w) > 1
            ]
            word_counter.update(words)

        hours = [msg.created_at.hour for msg in messages]
        most_active_hour = max(set(hours), key=hours.count) if hours else None

        days = [msg.created_at.strftime("%A") for msg in messages]
        most_active_day = max(set(days), key=days.count) if days else None

        activity_trend = []
        for offset in range(7):
            target = (now - timedelta(days=offset)).date()
            count = sum(1 for msg in messages if msg.created_at.date() == target)
            activity_trend.append({"date": target.strftime("%Y-%m-%d"), "count": count})

        try:
            top_topics = await OpenAIService.analyze_topics(
                [msg.text for msg in messages if msg.text]
            )
        except Exception as exc:  # noqa: BLE001 — OpenAI errors vary
            logger.warning("Could not analyze topics for chat %s: %s", chat_id, exc)
            top_topics = []

        stats = MessageStats(
            chat_id=chat_id,
            period="week",
            timestamp=now.replace(tzinfo=None),
            message_count=message_count,
            user_count=user_count,
            avg_length=avg_length,
            emoji_count=emoji_total,
            sticker_count=0,
            top_emojis=dict(emoji_counter.most_common(10)),
            top_stickers={},
            top_words=dict(word_counter.most_common(10)),
            top_topics=top_topics,
            most_active_hour=most_active_hour,
            most_active_day=most_active_day,
            activity_trend=activity_trend,
        )
        session.add(stats)
        await session.commit()
        return stats

    @staticmethod
    def _is_fresh(stats: MessageStats) -> bool:
        ts = stats.timestamp
        if ts is None:
            return False
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts < CACHE_DURATION

    async def start_periodic_update(self) -> None:
        """Background loop: refresh stats for every chat every 5 minutes."""
        while True:
            try:
                async for session in get_session():
                    try:
                        result = await session.execute(select(Chat))
                        chats = list(result.scalars().all())
                        for chat in chats:
                            try:
                                await self._calculate_stats(chat.id, session)
                            except Exception as exc:  # noqa: BLE001 — продолжаем по другим чатам
                                logger.warning("Stats update failed for chat %s: %s", chat.id, exc)
                                await session.rollback()
                    finally:
                        await session.close()
            except asyncio.CancelledError:
                logger.info("Stats periodic update cancelled")
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("Periodic stats loop error: %s", exc, exc_info=True)

            await asyncio.sleep(PERIODIC_INTERVAL_SECONDS)
