"""Daily chat digest builder (FEATURE-002).

Pulls messages for a given calendar day (Europe/Moscow), groups by chat
(skipping channels, private DMs and chats with zero messages), generates
per-chat summaries via OpenAI, and sends them to ``settings.OWNER_ID``.

Idempotency: every successful send is recorded in ``daily_digests``;
trying to send the same date twice is a no-op unless ``force=True``.
"""

from __future__ import annotations

import asyncio
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


def seconds_until_next_digest(now_utc: Optional[datetime] = None) -> float:
    """Seconds from ``now_utc`` until the next 23:50 in Europe/Moscow."""
    now_utc = now_utc or datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(OWNER_TZ)
    target = now_msk.replace(hour=DIGEST_HOUR, minute=DIGEST_MINUTE, second=0, microsecond=0)
    if target <= now_msk:
        target = target + timedelta(days=1)
    return (target - now_msk).total_seconds()


def previous_trigger_day(now_utc: Optional[datetime] = None) -> date:
    """The calendar day (Europe/Moscow) whose 23:50 trigger should already have fired.

    If we are past 23:50 today (MSK) — that's today's date.
    Otherwise — yesterday's date (yesterday's 23:50 trigger is the most recent
    one that has already passed).
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(OWNER_TZ)
    if now_msk.hour > DIGEST_HOUR or (
        now_msk.hour == DIGEST_HOUR and now_msk.minute >= DIGEST_MINUTE
    ):
        return now_msk.date()
    return now_msk.date() - timedelta(days=1)


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


async def _send_with_fresh_session(bot: Bot, day: date) -> None:
    """Open a one-shot session, build a service and send a recorded digest."""
    from ..database.database import async_session  # local to avoid import cycle

    async with async_session() as session:
        service = DigestService(session, bot)
        await service.send_for_day(day, record=True)


async def run_digest_scheduler(bot: Bot) -> None:
    """Background loop: catch up if needed, then trigger every 23:50 Europe/Moscow.

    Semantics: the 23:50 trigger fires once per calendar day (MSK). When it
    fires for day D, the digest sent covers day D itself (the day that has
    just almost ended). On bot startup, if the most recent past 23:50
    trigger has not been honoured (no row in ``daily_digests`` for that
    day yet), we send it as a catch-up.
    """
    catchup = previous_trigger_day()
    try:
        from ..database.database import async_session

        async with async_session() as session:
            already = await DigestService(session, bot).already_sent(catchup)
        if not already:
            logger.info("Catch-up: sending digest for %s", catchup)
            await _send_with_fresh_session(bot, catchup)
    except Exception as exc:  # noqa: BLE001 — никогда не падаем из catch-up
        logger.error("Catch-up digest failed: %s", exc, exc_info=True)

    while True:
        try:
            sleep_for = seconds_until_next_digest()
            logger.info("Daily digest: sleeping %.0f seconds until next 23:50 MSK", sleep_for)
            await asyncio.sleep(sleep_for)

            day = today_in_moscow()
            logger.info("Daily digest: trigger fired, sending digest for %s", day)
            await _send_with_fresh_session(bot, day)
        except asyncio.CancelledError:
            logger.info("Daily digest scheduler cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 — никогда не валим бота из-за дайджеста
            logger.error("Daily digest iteration failed: %s", exc, exc_info=True)
            await asyncio.sleep(60)
