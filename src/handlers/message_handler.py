from aiogram import Router, F
from aiogram.types import Message, ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging
import random

from ..config import settings
from ..database.models import Chat, ChatType
from .command_handler import update_chat_title

router = Router()
logger = logging.getLogger(__name__)

@router.chat_member()
async def handle_chat_member_update(event: ChatMemberUpdated, session: AsyncSession):
    """Handle chat member updates."""
    # Skip if bot is in global shutdown mode
    if settings.is_shutdown:
        return
        
    # Check if this is our bot being added to a chat
    if event.new_chat_member.user.id == event.bot.id:
        logger.info(f"Bot was added to chat {event.chat.id}")
        
        # Get chat from database
        query = select(Chat).where(Chat.chat_id == event.chat.id)
        result = await session.execute(query)
        chat = result.scalar_one_or_none()
        
        if not chat:
            # Create new chat
            logger.info(f"Creating new chat with ID {event.chat.id}")
            logger.info(f"Chat info from event: title='{event.chat.title}', type='{event.chat.type}'")
            
            # Get chat info from Telegram
            try:
                chat_info = await event.bot.get_chat(event.chat.id)
                logger.info(f"Got chat info from Telegram: title='{chat_info.title}', type='{chat_info.type}'")
                title = chat_info.title
            except Exception as e:
                logger.error(f"Failed to get chat info: {e}", exc_info=True)
                title = event.chat.title or "Unknown Chat"
            
            chat = Chat(
                chat_id=event.chat.id,
                title=title,
                is_silent=True,  # Set to silent mode by default
                response_probability=0.5,
                importance_threshold=0.5,
                smart_mode=False,
                chat_type=ChatType.MIXED
            )
            session.add(chat)
            await session.commit()
            logger.info(f"Created new chat: {chat.title} (ID: {chat.chat_id})")
        else:
            logger.info(f"Chat already exists in database: {chat.title} (ID: {chat.chat_id})")
        
    # Update chat title if it changed
    if event.chat.title != event.old_chat.title:
        logger.info(f"Chat title changed from '{event.old_chat.title}' to '{event.chat.title}'")
        # Create a dummy message object with bot instance
        dummy_message = Message(
            message_id=0,
            date=0,
            chat=event.chat,
            bot=event.bot
        )
        await update_chat_title(dummy_message, event.chat.id, session)

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
        logger.info(f"Creating new chat with ID {message.chat.id}")
        logger.info(f"Chat info from message: title='{message.chat.title}', type='{message.chat.type}'")
        
        # Get chat info from Telegram
        try:
            chat_info = await message.bot.get_chat(message.chat.id)
            logger.info(f"Got chat info from Telegram: title='{chat_info.title}', type='{chat_info.type}'")
            title = chat_info.title
        except Exception as e:
            logger.error(f"Failed to get chat info: {e}", exc_info=True)
            title = message.chat.title or "Unknown Chat"
        
        chat = Chat(
            chat_id=message.chat.id,
            title=title,
            is_silent=True,  # Set to silent mode by default
            response_probability=0.5,
            importance_threshold=0.5,
            smart_mode=False,
            chat_type=ChatType.MIXED
        )
        session.add(chat)
        await session.commit()
        logger.info(f"Created new chat: {chat.title} (ID: {chat.chat_id})")
    
    # If chat is in silent mode, only process the message without responding
    if chat.is_silent:
        # Process message for learning/context but don't respond
        await process_message_for_learning(message, chat, session)
        return
        
    # Process message and generate response
    await process_message_and_respond(message, chat, session)

async def process_message_for_learning(message: Message, chat: Chat, session: AsyncSession):
    """Process message for learning and context without generating response."""
    # Save message to database
    db_message = Message(
        message_id=message.message_id,
        chat_id=chat.id,
        user_id=message.from_user.id,
        text=message.text,
        timestamp=message.date,
        was_responded=False,
        date=message.date
    )
    session.add(db_message)
    await session.commit()
    
    # Process message for context
    from ..services.context_service import ContextService
    context_service = ContextService(session)
    await context_service.get_or_create_thread(chat.id)

async def process_message_and_respond(message: Message, chat: Chat, session: AsyncSession):
    """Process message and generate response."""
    # Save message to database
    db_message = Message(
        message_id=message.message_id,
        chat_id=chat.id,
        user_id=message.from_user.id,
        text=message.text,
        timestamp=message.date,
        was_responded=False,
        date=message.date
    )
    session.add(db_message)
    await session.commit()
    
    # Process message for context
    from ..services.context_service import ContextService
    context_service = ContextService(session)
    thread = await context_service.get_or_create_thread(chat.id)
    
    # Generate response based on chat settings
    if chat.smart_mode:
        # Use smart mode for response generation
        from ..services.openai_service import OpenAIService
        openai_service = OpenAIService()
        
        # Check if message is important enough to respond
        importance = await openai_service.analyze_message_importance(message.text)
        if importance < chat.importance_threshold:
            return
            
        # Generate response
        response = await openai_service.generate_response(message.text, thread.topic)
        if response:
            await message.answer(response)
            db_message.was_responded = True
            await session.commit()
    else:
        # Use simple mode with probability
        if random.random() < chat.response_probability:
            # Generate simple response
            from ..services.openai_service import OpenAIService
            openai_service = OpenAIService()
            response = await openai_service.generate_response(message.text, thread.topic)
            if response:
                await message.answer(response)
                db_message.was_responded = True
                await session.commit() 