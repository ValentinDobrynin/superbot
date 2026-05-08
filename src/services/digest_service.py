"""Daily chat digest builder (FEATURE-002).

Pulls messages for a given calendar day (Europe/Moscow), groups by chat
(skipping channels, private DMs and chats with zero messages), generates
per-chat summaries via OpenAI, and sends them to ``settings.OWNER_ID``.

Idempotency: every successful send is recorded in ``daily_digests``;
trying to send the same date twice is a no-op unless ``force=True``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Sequence
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import Chat, DailyDigest, DBMessage
from .openai_service import OpenAIService
from .prompts import load_prompt

logger = logging.getLogger(__name__)

OWNER_TZ = ZoneInfo("Europe/Moscow")
DIGEST_HOUR = 23
DIGEST_MINUTE = 50
MAX_MESSAGES_PER_CHAT = 200  # cap to keep prompt small and OpenAI cost bounded


@dataclass
class _ChatDigestItem:
    chat: Chat
    messages: List[DBMessage]


def period_for_day(day: date) -> tuple[datetime, datetime]:
    """Return UTC half-open interval [start, end) covering the given Moscow day."""
    start_local = datetime.combine(day, time(0, 0, 0), tzinfo=OWNER_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def yesterday_in_moscow(now_utc: Optional[datetime] = None) -> date:
    """Return yesterday's calendar date in Europe/Moscow."""
    now_utc = now_utc or datetime.now(timezone.utc)
    return (now_utc.astimezone(OWNER_TZ).date()) - timedelta(days=1)


def today_in_moscow(now_utc: Optional[datetime] = None) -> date:
    now_utc = now_utc or datetime.now(timezone.utc)
    return now_utc.astimezone(OWNER_TZ).date()


def _format_message(msg: DBMessage) -> str:
    text = (msg.text or "").strip()
    if not text:
        return ""
    return f"user{msg.user_id}: {text}"


class DigestService:
    """Build and send daily digests."""

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self.session = session
        self.bot = bot

    async def already_sent(self, day: date) -> bool:
        result = await self.session.execute(
            select(DailyDigest).where(DailyDigest.digest_date == day)
        )
        return result.scalar_one_or_none() is not None

    async def collect(self, day: date) -> List[_ChatDigestItem]:
        """Return per-chat groups of messages for the given Moscow day.

        Channels and private chats are filtered out at the SQL level.
        Chats without any messages in the period are not included.
        """
        start_utc, end_utc = period_for_day(day)

        chats_result = await self.session.execute(
            select(Chat).where(Chat.tg_type.in_(("group", "supergroup")))
        )
        chats: Sequence[Chat] = chats_result.scalars().all()

        items: List[_ChatDigestItem] = []
        for chat in chats:
            msg_result = await self.session.execute(
                select(DBMessage)
                .where(
                    DBMessage.chat_id == chat.id,
                    DBMessage.created_at >= start_utc,
                    DBMessage.created_at < end_utc,
                )
                .order_by(DBMessage.created_at.asc())
                .limit(MAX_MESSAGES_PER_CHAT)
            )
            messages = list(msg_result.scalars().all())
            if not messages:
                continue
            items.append(_ChatDigestItem(chat=chat, messages=messages))
        return items

    async def _summarize(self, item: _ChatDigestItem, day: date) -> str:
        prompt = load_prompt("FEATURE-002_daily_digest")
        formatted = "\n".join(filter(None, (_format_message(m) for m in item.messages)))
        rendered = prompt.format(
            chat_name=item.chat.name or f"Chat {item.chat.telegram_id}",
            date=day.strftime("%d.%m.%Y"),
            messages_text=formatted or "(нет текстовых сообщений)",
        )
        return await OpenAIService._complete(
            prompt,
            rendered,
            system="Ты помощник, который кратко резюмирует переписку в чате.",
        )

    async def send_for_day(self, day: date, *, record: bool = True) -> int:
        """Build and send the digest. Returns number of chats summarised.

        ``record=True`` (default, used by the automatic scheduler):
            insert a row into ``daily_digests`` so the same day is not
            sent again. If a row for ``day`` already exists, returns -1
            and sends nothing.

        ``record=False`` (used by the manual ``/digest`` command):
            always send, regardless of whether a row already exists.
            Does NOT insert into ``daily_digests`` — the manual digest
            is the owner playing with the command, not the official
            once-a-day artefact.
        """
        if record and await self.already_sent(day):
            logger.info("Digest for %s already sent, skipping", day)
            return -1

        items = await self.collect(day)
        date_str = day.strftime("%d.%m.%Y")

        if not items:
            await self.bot.send_message(
                settings.OWNER_ID,
                f"📊 Дайджест за {date_str}\nТихий день — ни в одном чате не было сообщений.",
            )
        else:
            await self.bot.send_message(
                settings.OWNER_ID,
                f"📊 Дайджест за {date_str} — {len(items)} чат(ов)",
            )
            for item in items:
                try:
                    summary = await self._summarize(item, day)
                except Exception as exc:  # noqa: BLE001 — не валим весь дайджест из-за одного чата
                    logger.error(
                        "Failed to summarise chat %s: %s",
                        item.chat.telegram_id,
                        exc,
                        exc_info=True,
                    )
                    summary = "(не удалось получить саммари — см. логи)"
                title = item.chat.name or f"Chat {item.chat.telegram_id}"
                await self.bot.send_message(
                    settings.OWNER_ID,
                    f"<b>{title}</b>\n{summary}",
                    parse_mode="HTML",
                )

        if record:
            entry = DailyDigest(
                digest_date=day,
                sent_at=datetime.now(timezone.utc),
                chat_count=len(items),
                message_count=sum(len(i.messages) for i in items),
            )
            self.session.add(entry)
            await self.session.commit()
        return len(items)
