from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable, Union
from sqlalchemy.ext.asyncio import AsyncSession

from .database.database import get_session

class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], Dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: Dict[str, Any]
    ) -> Any:
        async for session in get_session():
            try:
                data["session"] = session
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                raise e
            finally:
                await session.close() 