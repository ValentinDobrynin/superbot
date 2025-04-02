import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database.database import init_db, get_session
from .handlers import chat_handler, command_handler
from .scheduler import schedule_refresh
from .lock import ProcessLock
from .middleware import DatabaseMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def startup_notification(bot: Bot):
    """Send startup notification to owner."""
    try:
        await bot.send_message(
            settings.OWNER_ID,
            "🚀 vAIlentin 2.0 bot started successfully!\n"
            "Use /help to see available commands."
        )
    except Exception as e:
        logger.error(f"Failed to send startup notification: {e}")

async def main():
    # Initialize process lock
    lock = ProcessLock()
    if not lock.acquire():
        logger.error("Another bot instance is already running. Exiting...")
        return

    try:
        # Initialize bot and dispatcher
        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher()
        
        # Add database middleware
        dp.message.middleware(DatabaseMiddleware())
        
        # Initialize database
        await init_db()
        
        # Register routers
        dp.include_router(chat_handler.router)
        dp.include_router(command_handler.router)
        
        # Send startup notification
        await startup_notification(bot)
        
        # Start background tasks
        async def start_scheduler():
            async for session in get_session():
                await schedule_refresh(session, settings.OWNER_ID, bot)
        
        # Create tasks
        scheduler_task = asyncio.create_task(start_scheduler())
        
        # Start polling
        try:
            logger.info("Starting bot...")
            await dp.start_polling(bot)
        finally:
            # Cancel background tasks
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
            
            await bot.session.close()
    finally:
        # Release the lock
        lock.release()

if __name__ == "__main__":
    asyncio.run(main()) 