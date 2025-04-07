import asyncio
import logging
from aiogram import Bot, Dispatcher, Router
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.token import validate_token
from dotenv import load_dotenv
import os
from aiogram.client.default import DefaultBotProperties

from .config import settings
from .handlers import command_handler, message_handler, callback_handler
from .database.database import init_db, get_session
from .middleware import DatabaseMiddleware
from .services.notification_service import NotificationService
from .services.stats_service import StatsService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Validate token
if not validate_token(settings.BOT_TOKEN):
    raise ValueError("Invalid bot token")

async def main():
    """Main function."""
    # Initialize bot and dispatcher
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Initialize database
    await init_db()
    
    # Register middleware
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    
    # Register handlers
    dp.include_router(command_handler.router)
    dp.include_router(message_handler.router)
    dp.include_router(callback_handler.router)
    
    # Send startup notification
    notification_service = NotificationService(bot, settings.OWNER_ID)
    await notification_service.notify_startup()
    
    # Start periodic stats update
    session = await anext(get_session())
    stats_service = StatsService()
    asyncio.create_task(stats_service.start_periodic_update(session))
    
    # Start polling
    logger.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main()) 