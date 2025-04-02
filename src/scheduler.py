import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

from .database.models import Chat, Message
from .config import settings

logger = logging.getLogger(__name__)

async def schedule_refresh(session: AsyncSession, owner_id: int, bot: Bot):
    """Schedule periodic refresh of chat statistics and settings."""
    while True:
        try:
            # Get all active chats
            query = select(Chat).where(Chat.is_active == True)
            result = await session.execute(query)
            chats = result.scalars().all()
            
            for chat in chats:
                try:
                    # Get messages from last 24 hours
                    yesterday = datetime.utcnow() - timedelta(days=1)
                    messages_query = select(Message).where(
                        Message.chat_id == chat.id,
                        Message.timestamp >= yesterday
                    )
                    result = await session.execute(messages_query)
                    messages = result.scalars().all()
                    
                    if not messages:
                        continue
                    
                    # Calculate statistics
                    total_messages = len(messages)
                    responded_messages = sum(1 for msg in messages if msg.was_responded)
                    response_rate = responded_messages / total_messages if total_messages > 0 else 0
                    
                    # Adjust settings based on statistics
                    if response_rate < 0.20:  # Too few responses
                        chat.importance_threshold = max(0.1, chat.importance_threshold - 0.05)
                    elif response_rate > 0.40:  # Too many responses
                        chat.importance_threshold = min(0.9, chat.importance_threshold + 0.05)
                    
                    # Commit changes
                    await session.commit()
                    
                except Exception as e:
                    logger.error(f"Error processing chat {chat.id}: {e}")
                    continue
            
            # Wait for 1 hour before next refresh
            await asyncio.sleep(3600)  # 3600 seconds = 1 hour
            
        except Exception as e:
            logger.error(f"Error in schedule_refresh: {e}")
            await asyncio.sleep(60)  # Wait 1 minute before retrying 