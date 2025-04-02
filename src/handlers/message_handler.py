from aiogram import Router, F
from aiogram.types import Message, ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import settings
from ..database.models import Chat, ChatType
from .command_handler import update_chat_title

router = Router()

@router.chat_member()
async def handle_chat_member_update(event: ChatMemberUpdated, session: AsyncSession):
    """Handle chat member updates."""
    # Skip if bot is in global shutdown mode
    if settings.is_shutdown:
        return
        
    # Update chat title if it changed
    if event.chat.title != event.old_chat.title:
        await update_chat_title(event.message, event.chat.id, session)

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
    
    # Create chat if it doesn't exist
    if not chat:
        chat = Chat(
            chat_id=message.chat.id,
            title=message.chat.title or "Unknown Chat",
            is_active=True,
            is_silent=False,
            response_probability=0.5,
            importance_threshold=0.5,
            smart_mode=True,
            chat_type=ChatType.mixed
        )
        session.add(chat)
        await session.commit()
        # Update chat title from Telegram
        await update_chat_title(message, message.chat.id, session)
    
    # Skip if chat is completely disabled
    if not chat.is_active:
        return
        
    # If chat is in silent mode, only process the message without responding
    if chat.is_silent:
        # TODO: Process message for learning/context but don't respond
        return
        
    # TODO: Add normal message handling logic here
    pass 