from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable, Union
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from .database.database import get_session

logger = logging.getLogger(__name__)

class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], Dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: Dict[str, Any]
    ) -> Any:
        session = None
        try:
            # Get a new session
            session = await get_session()
            # Store session in data dict instead of bot object
            data['session'] = session
            result = await handler(event, data)
            await session.commit()
            return result
        except Exception as e:
            logger.error(f"Error in middleware: {str(e)}")
            if session:
                await session.rollback()
            raise e
        finally:
            if session:
                try:
                    await session.close()
                except Exception as e:
                    logger.error(f"Error closing session: {str(e)}") 