from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import settings
from ..database.models import Chat

router = Router()

@router.message()
async def handle_message(message: Message, session: AsyncSession):
    """Handle all non-command messages."""
    # Skip if message is from bot itself
    if message.from_user.is_bot:
        return
        
    # Skip if bot is in global shutdown mode
    if settings.is_shutdown:
        return
        
    # Get chat settings
    query = select(Chat).where(Chat.chat_id == message.chat.id)
    result = await session.execute(query)
    chat = result.scalar_one_or_none()
    
    # Skip if chat is not in database or completely disabled
    if not chat or not chat.is_active:
        return
        
    # If chat is in silent mode, only process the message without responding
    if chat.is_silent:
        # TODO: Process message for learning/context but don't respond
        return
        
    # TODO: Add normal message handling logic here
    pass 