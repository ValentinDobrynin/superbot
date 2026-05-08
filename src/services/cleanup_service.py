"""Background message TTL cleanup (TECH-009).

Hard 30-day retention for ``messages.text``: anything older is purged daily.

The schedule is intentionally offset from the digest (23:50 MSK) — we run at
04:00 MSK so the previous day's digest is already built before we drop its
underlying messages.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import DBMessage, Event

logger = logging.getLogger(__name__)

OWNER_TZ = ZoneInfo("Europe/Moscow")
CLEANUP_HOUR = 4
CLEANUP_MINUTE = 0


def seconds_until_next_cleanup(now_utc: Optional[datetime] = None) -> float:
    """Seconds from ``now_utc`` until the next 04:00 in Europe/Moscow."""
    now_utc = now_utc or datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(OWNER_TZ)
    target = datetime.combine(now_msk.date(), time(CLEANUP_HOUR, CLEANUP_MINUTE), tzinfo=OWNER_TZ)
    if target <= now_msk:
        target = target + timedelta(days=1)
    return (target - now_msk).total_seconds()


class CleanupService:
    """Drop messages older than ``settings.MESSAGE_TTL_DAYS``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def purge_old_messages(self, *, now_utc: Optional[datetime] = None) -> int:
        ttl_days = max(1, int(settings.MESSAGE_TTL_DAYS))
        threshold = (now_utc or datetime.now(timezone.utc)) - timedelta(days=ttl_days)
        # `messages.created_at` is timezone-aware (DateTime(timezone=True)).
        result = await self.session.execute(
            delete(DBMessage).where(DBMessage.created_at < threshold)
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def mark_past_events(self, *, now_utc: Optional[datetime] = None) -> int:
        """Auto-flip ``events.status`` from ``upcoming`` to ``past`` once
        ``when_at`` has elapsed (FEATURE-009).

        Events without a parsed ``when_at`` are left alone — there's nothing
        objective to compare against, and we don't want to spuriously hide
        something whose deadline string we just couldn't parse.
        """
        cutoff = now_utc or datetime.now(timezone.utc)
        result = await self.session.execute(
            update(Event)
            .where(
                Event.status == "upcoming",
                Event.when_at.isnot(None),
                Event.when_at < cutoff,
            )
            .values(status="past", updated_at=cutoff)
        )
        await self.session.commit()
        return int(result.rowcount or 0)


async def _run_cleanup_pass() -> tuple[int, int]:
    from ..database.database import async_session  # local: avoid import cycle

    async with async_session() as session:
        service = CleanupService(session)
        purged = await service.purge_old_messages()
        marked = await service.mark_past_events()
    return purged, marked


async def run_cleanup_scheduler() -> None:
    """Background loop: every day at 04:00 MSK run a cleanup pass."""
    while True:
        try:
            sleep_for = seconds_until_next_cleanup()
            logger.info("Cleanup: sleeping %.0f s until next 04:00 MSK", sleep_for)
            await asyncio.sleep(sleep_for)
            purged, marked = await _run_cleanup_pass()
            logger.info(
                "Cleanup pass done: purged %s old messages (TTL=%s d), marked %s events as past",
                purged,
                settings.MESSAGE_TTL_DAYS,
                marked,
            )
        except asyncio.CancelledError:
            logger.info("Cleanup scheduler cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 — никогда не валим бота из-за чистки
            logger.error("Cleanup pass failed: %s", exc, exc_info=True)
            await asyncio.sleep(60)
