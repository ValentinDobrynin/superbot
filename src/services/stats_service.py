from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database.models import Chat, Message, MessageStats
import re
import emoji
from collections import Counter
import asyncio

class StatsService:
    def __init__(self):
        self._cache = {}
        self._cache_time = {}
        self._cache_duration = timedelta(minutes=5)

    async def get_stats(self, chat_id: int, session: AsyncSession) -> Dict:
        """Get statistics for a chat, using cache if available."""
        now = datetime.now()
        
        # Check cache
        if chat_id in self._cache and now - self._cache_time[chat_id] < self._cache_duration:
            return self._cache[chat_id]
        
        # Get or create stats
        stats = await session.execute(
            select(MessageStats)
            .where(MessageStats.chat_id == chat_id)
            .where(MessageStats.period == 'week')
            .order_by(MessageStats.timestamp.desc())
        )
        stats = stats.scalar_one_or_none()
        
        if not stats:
            stats = await self._calculate_stats(chat_id, session)
        else:
            # Update if older than 5 minutes
            if now - stats.timestamp > self._cache_duration:
                stats = await self._calculate_stats(chat_id, session)
        
        # Cache the results
        self._cache[chat_id] = stats
        self._cache_time[chat_id] = now
        
        return stats

    async def _calculate_stats(self, chat_id: int, session: AsyncSession) -> MessageStats:
        """Calculate statistics for a chat."""
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        
        # Get messages
        messages = await session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .where(Message.timestamp >= week_ago)
        )
        messages = messages.scalars().all()
        
        # Basic stats
        message_count = len(messages)
        user_count = len(set(m.user_id for m in messages))
        avg_length = sum(len(m.text or '') for m in messages) / message_count if message_count > 0 else 0
        
        # Content analysis
        emoji_count = 0
        sticker_count = 0
        emoji_stats = Counter()
        sticker_stats = Counter()
        word_stats = Counter()
        topic_stats = Counter()
        
        for msg in messages:
            # Count emojis
            emojis = emoji.emoji_list(msg.text or '')
            emoji_count += len(emojis)
            for e in emojis:
                emoji_stats[e['emoji']] += 1
            
            # Count stickers
            if msg.sticker:
                sticker_count += 1
                sticker_stats[msg.sticker.file_unique_id] += 1
            
            # Count words
            if msg.text:
                words = re.findall(r'\w+', msg.text.lower())
                word_stats.update(words)
            
            # Count topics
            if msg.topic:
                topic_stats[msg.topic] += 1
        
        # Activity analysis
        hour_stats = Counter()
        day_stats = Counter()
        activity_trend = Counter()
        
        for msg in messages:
            hour_stats[msg.timestamp.hour] += 1
            day_stats[msg.timestamp.strftime("%A")] += 1
            activity_trend[msg.timestamp.date()] += 1
        
        # Create stats object
        stats = MessageStats(
            chat_id=chat_id,
            period='week',
            timestamp=now,
            message_count=message_count,
            user_count=user_count,
            avg_length=avg_length,
            emoji_count=emoji_count,
            sticker_count=sticker_count,
            top_emojis=emoji_stats.most_common(10),
            top_stickers=sticker_stats.most_common(10),
            top_words=word_stats.most_common(10),
            top_topics=topic_stats.most_common(10),
            most_active_hour=hour_stats.most_common(1)[0][0] if hour_stats else 0,
            most_active_day=day_stats.most_common(1)[0][0] if day_stats else "Unknown",
            activity_trend=[{"date": str(date), "count": count} for date, count in activity_trend.items()]
        )
        
        session.add(stats)
        await session.commit()
        
        return stats

    async def start_periodic_update(self, session: AsyncSession):
        """Start periodic update of statistics."""
        while True:
            # Get all chats
            chats = await session.execute(select(Chat))
            chats = chats.scalars().all()
            
            # Update stats for each chat
            for chat in chats:
                await self._calculate_stats(chat.id, session)
            
            # Wait 5 minutes before next update
            await asyncio.sleep(300) 