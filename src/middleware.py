import logging
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message
from .database.database import get_session
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        try:
            # Get session from generator
            async for session in get_session():
                # Add session to data
                data['session'] = session
                # Call handler with session
                return await handler(event, data)
        except Exception as e:
            logger.error(f"Error in middleware: {str(e)}")
            raise e 