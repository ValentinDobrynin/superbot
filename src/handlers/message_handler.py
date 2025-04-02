from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from ..database.database import get_session
from ..config import settings

router = Router()

@router.message()
async def handle_message(message: Message, db: AsyncSession = Depends(get_session)):
    """Handle all non-command messages."""
    # Skip if message is from bot itself
    if message.from_user.is_bot:
        return
        
    # Skip if bot is in shutdown mode
    if settings.is_shutdown:
        return
        
    # TODO: Add message handling logic here
    pass 