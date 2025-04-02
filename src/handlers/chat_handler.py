from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import random
from typing import Optional, List

from ..database.models import Chat, Message as DBMessage, Style, MessageThread, MessageContext
from ..services.openai_service import OpenAIService
from ..services.context_service import ContextService
from ..config import settings

router = Router()

def should_respond(message: str, chat: Chat) -> bool:
    """Determine if the bot should respond to the message."""
    # Check global shutdown
    if settings.is_shutdown:
        return False
    
    # Check if bot is active in this chat
    if not chat.is_active:
        return False
    
    # Check for direct mentions
    if "@Valentin" in message or "Valentin" in message:
        return True
    
    # Check for urgency indicators
    urgency_indicators = ["срочно", "важно", "?"]
    if any(indicator in message.lower() for indicator in urgency_indicators):
        return True
    
    # Check smart mode
    if chat.smart_mode:
        # Smart mode will be handled in the message handler
        return True
    
    return random.random() < chat.response_probability

async def get_thread_context(context_service: ContextService, thread: MessageThread) -> str:
    """Get formatted context for the thread."""
    # Get thread context
    query = select(MessageContext).where(MessageContext.thread_id == thread.id)
    result = await context_service.session.execute(query)
    context = result.scalar_one_or_none()
    
    if not context:
        return ""
    
    # Get related threads
    related = await context_service.find_related_threads(thread)
    
    # Format context
    context_text = f"Current topic: {thread.topic}\n\n"
    context_text += f"Context summary:\n{context.context_summary}\n\n"
    
    if related:
        context_text += "Related discussions:\n"
        for rel in related:
            context_text += f"- {rel.topic}\n"
    
    return context_text

@router.message()
async def handle_message(message: Message, session: AsyncSession):
    # Skip processing for commands
    if message.text and message.text.startswith('/'):
        return
        
    # Get chat settings
    chat_query = select(Chat).where(Chat.chat_id == message.chat.id)
    result = await session.execute(chat_query)
    chat = result.scalar_one_or_none()
    
    if not chat:
        # Create new chat if it doesn't exist
        chat = Chat(
            chat_id=message.chat.id,
            title=message.chat.title or "Unknown Chat"
        )
        session.add(chat)
        await session.commit()
    
    # Check if we should respond
    if not should_respond(message.text or "", chat):
        return
    
    # Initialize context service
    context_service = ContextService(session)
    
    # Store the message
    db_message = DBMessage(
        message_id=message.message_id,
        chat_id=chat.id,
        user_id=message.from_user.id,
        text=message.text or ""
    )
    session.add(db_message)
    await session.commit()
    
    # Analyze message and add tags
    tags, importance = await context_service.analyze_message(db_message)
    if tags:
        tag_objects = await context_service.get_or_create_tags(tags)
        await context_service.add_tags_to_message(db_message, tag_objects)
    
    # Get or create thread
    thread = await context_service.get_or_create_thread(chat.id)
    db_message.thread_id = thread.id
    await session.commit()
    
    # Update thread context
    await context_service.update_thread_context(thread)
    
    # Handle smart mode
    if chat.smart_mode and importance < chat.importance_threshold:
        return
    
    # Get thread context
    thread_context = await get_thread_context(context_service, thread)
    
    # Get recent messages for conversation context
    context_query = select(DBMessage).where(
        DBMessage.thread_id == thread.id
    ).order_by(DBMessage.timestamp.desc()).limit(settings.MAX_CONTEXT_MESSAGES)
    result = await session.execute(context_query)
    context_messages = result.scalars().all()
    
    # Get style for this chat type
    style_query = select(Style).where(Style.chat_type == chat.chat_type)
    result = await session.execute(style_query)
    style = result.scalar_one_or_none()
    
    if not style:
        # Use default style if none is set
        style_prompt = "Use a balanced, professional tone with occasional emojis."
    else:
        style_prompt = style.prompt_template
    
    # Add thread context to style prompt
    if thread_context:
        style_prompt = f"{style_prompt}\n\nThread Context:\n{thread_context}"
    
    # Generate and send response
    response = await OpenAIService.generate_response(
        message.text or "",
        chat.chat_type,
        [{"text": msg.text, "is_user": msg.user_id != settings.OWNER_ID} 
         for msg in context_messages],
        style_prompt
    )
    
    sent_message = await message.answer(response)
    
    # Store bot's response
    bot_message = DBMessage(
        message_id=sent_message.message_id,
        chat_id=chat.id,
        user_id=settings.OWNER_ID,  # Use owner's ID for bot messages
        text=response,
        thread_id=thread.id
    )
    session.add(bot_message)
    
    # Mark original message as responded
    db_message.was_responded = True
    await session.commit() 