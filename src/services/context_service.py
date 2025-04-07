from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from uuid import UUID
import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import DBMessage, MessageThread, MessageContext, Tag, MessageTag
from .openai_service import OpenAIService

logger = logging.getLogger(__name__)

class ContextService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.openai = OpenAIService()

    async def get_or_create_thread(self, chat_id: int, topic: Optional[str] = None) -> MessageThread:
        """Get active thread for the chat or create a new one."""
        # Try to find an active thread
        query = select(MessageThread).where(
            MessageThread.chat_id == chat_id,
            MessageThread.is_active == True
        )
        result = await self.session.execute(query)
        thread = await result.scalar_one_or_none()

        if thread and not topic:
            return thread

        # Create new thread if none exists or topic changed
        new_thread = MessageThread(
            chat_id=chat_id,
            topic=topic or "General Discussion",
            is_active=True
        )
        await self.session.add(new_thread)
        await self.session.commit()

        if thread:
            # Deactivate old thread
            thread.is_active = False
            await self.session.commit()

        return new_thread

    async def analyze_message(self, message: DBMessage) -> Tuple[List[str], float]:
        """Analyze message content for tags and importance."""
        prompt = f"""
        Analyze the following message and suggest tags and importance (0-1):
        {message.text}

        Format:
        tags: tag1, tag2, tag3
        importance: 0.X
        """
        response = await self.openai.chat_completion(prompt)
        lines = response.split('\n')
        tags = [tag.strip() for tag in lines[0].split(':')[1].split(',')]
        importance = float(lines[1].split(':')[1])
        return tags, importance

    async def get_or_create_tags(self, tag_names: List[str]) -> List[Tag]:
        """Get or create tags by name."""
        tags = []
        for name in tag_names:
            query = select(Tag).where(Tag.name == name)
            result = await self.session.execute(query)
            tag = await result.scalar_one_or_none()

            if not tag:
                tag = Tag(name=name)
                await self.session.add(tag)
                await self.session.commit()

            tags.append(tag)
        return tags

    async def add_tags_to_message(self, message: DBMessage, tags: List[Tag], is_auto: bool = True) -> None:
        """Add tags to a message."""
        for tag in tags:
            message_tag = MessageTag(
                message_id=message.id,
                tag_id=tag.id,
                is_auto=is_auto
            )
            self.session.add(message_tag)
        await self.session.commit()

    async def update_thread_context(self, thread: MessageThread) -> None:
        """Update thread context based on recent messages."""
        # Get recent messages from thread
        query = select(DBMessage).where(
            DBMessage.thread_id == thread.id
        ).order_by(DBMessage.created_at.desc()).limit(10)
        result = await self.session.execute(query)
        result_scalars = await result.scalars()
        messages = await result_scalars.all()

        if not messages:
            return

        # Generate context summary
        messages_text = "\n".join([f"- {msg.text}" for msg in messages])
        prompt = f"""
        Summarize the following conversation:
        {messages_text}

        Format:
        Brief summary in 1-2 sentences.
        """
        summary = await self.openai.chat_completion(prompt)

        # Update or create context
        query = select(MessageContext).where(MessageContext.thread_id == thread.id)
        result = await self.session.execute(query)
        context = await result.scalar_one_or_none()

        if context:
            context.context_summary = summary
        else:
            context = MessageContext(
                thread_id=thread.id,
                context_summary=summary
            )
            await self.session.add(context)

        await self.session.commit()

    async def find_related_threads(self, thread: MessageThread) -> List[MessageThread]:
        """Find threads related to the current one."""
        # Get thread context
        query = select(MessageContext).where(MessageContext.thread_id == thread.id)
        result = await self.session.execute(query)
        context = await result.scalar_one_or_none()

        if not context:
            return []

        # Get other active threads
        query = select(MessageThread).where(
            MessageThread.chat_id == thread.chat_id,
            MessageThread.id != thread.id,
            MessageThread.is_active == True
        )
        result = await self.session.execute(query)
        result_scalars = await result.scalars()
        other_threads = await result_scalars.all()

        # Find related threads based on context similarity
        related_threads = []
        for other_thread in other_threads:
            query = select(MessageContext).where(MessageContext.thread_id == other_thread.id)
            result = await self.session.execute(query)
            other_context = await result.scalar_one_or_none()

            if other_context:
                similarity = await self.openai.calculate_similarity(
                    context.context_summary,
                    other_context.context_summary
                )
                if similarity > 0.7:  # Threshold for relatedness
                    related_threads.append(other_thread)

        return related_threads

    async def get_thread_stats(self, thread: MessageThread) -> Dict[str, Any]:
        """Get statistics for a message thread."""
        # Get all messages in the thread
        query = select(DBMessage).where(DBMessage.thread_id == thread.id)
        result = await self.session.execute(query)
        messages = result.scalars().all()
        
        if not messages:
            return {}
        
        # Calculate basic statistics
        total_messages = len(messages)
        unique_users = len(set(msg.user_id for msg in messages))
        
        # Calculate duration
        first_message = min(messages, key=lambda m: m.created_at)
        last_message = max(messages, key=lambda m: m.created_at)
        duration = (last_message.created_at - first_message.created_at).total_seconds() / 3600
        
        # Get top tags
        tag_query = select(MessageTag).join(Tag).where(MessageTag.message_id.in_([m.id for m in messages]))
        result = await self.session.execute(tag_query)
        message_tags = result.scalars().all()
        
        tag_counts = Counter(tag.tag.name for tag in message_tags)
        top_tags = tag_counts.most_common(5)
        
        return {
            "total_messages": total_messages,
            "unique_users": unique_users,
            "duration_hours": duration,
            "top_tags": top_tags
        }

    async def generate_chat_summary(self, messages: List[DBMessage]) -> str:
        """Generate a summary of chat messages using OpenAI."""
        if not messages:
            return "No messages to summarize."
        
        # Prepare messages for summarization
        messages_text = "\n".join([
            f"{msg.created_at.strftime('%Y-%m-%d %H:%M')} - User {msg.user_id}: {msg.text}"
            for msg in messages
        ])
        
        # Create prompt for summarization
        prompt = f"""Please analyze the following chat messages and provide a concise summary. 
Focus on the main topics discussed, key decisions made, and any important information shared.

Chat Messages:
{messages_text}

Please provide a summary in the following format:
1. Main Topics: [list main topics discussed]
2. Key Decisions: [list any decisions made]
3. Important Information: [list important information shared]
4. Overall Tone: [describe the overall tone of the conversation]"""

        # Generate summary using OpenAI
        openai_service = OpenAIService()
        response = await openai_service.chat_completion(prompt)
        
        return response 