import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.token import validate_token
from dotenv import load_dotenv
import os

from .handlers import chat_handler, command_handler
from .database import init_db, get_session
from .config import settings
from .middleware import DatabaseMiddleware

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

# Initialize bot and dispatcher
bot = Bot(token=settings.BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# Add database middleware
dp.message.middleware(DatabaseMiddleware())
dp.callback_query.middleware(DatabaseMiddleware())

# Register handlers
dp.include_router(chat_handler.router)
dp.include_router(command_handler.router)

async def main():
    # Initialize database
    await init_db()
    
    # Start polling
    logger.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main()) 