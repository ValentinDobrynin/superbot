"""Application entry point: build the bot, register handlers and start polling."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.token import validate_token
from dotenv import load_dotenv

from .config import settings
from .handlers import command_handler, message_handler
from .middleware import DatabaseMiddleware
from .services.digest_service import run_digest_scheduler
from .services.notification_service import NotificationService
from .services.stats_service import StatsService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()


async def main() -> None:
    """Start the bot."""
    if not validate_token(settings.BOT_TOKEN):
        raise ValueError("Invalid BOT_TOKEN")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    dp.chat_member.middleware(DatabaseMiddleware())

    dp.include_router(command_handler.router)
    dp.include_router(message_handler.router)

    notification_service = NotificationService(bot, settings.OWNER_ID)
    await notification_service.notify_startup()

    stats_service = StatsService()
    stats_task = asyncio.create_task(stats_service.start_periodic_update())
    digest_task = asyncio.create_task(run_digest_scheduler(bot))

    logger.info("Starting bot...")
    try:
        await dp.start_polling(bot)
    finally:
        for task in (stats_task, digest_task):
            task.cancel()
        for task in (stats_task, digest_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — игнорируем при выходе
                pass
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
