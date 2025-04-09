from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database.models import Chat, DBMessage, MessageStats
import re
import emoji
from collections import Counter
import asyncio
from ..services.openai_service import OpenAIService
from ..database.database import get_session

class StatsService:
    def __init__(self):
        self._cache = {}
        self._cache_time = {}
        self._cache_duration = timedelta(minutes=5)

    async def get_stats(self, chat_id: str, session: AsyncSession) -> MessageStats:
        """Get message statistics for a chat."""
        # Check cache first
        if chat_id in self._cache:
            cached_stats = self._cache[chat_id]
            if datetime.now(timezone.utc) - cached_stats.timestamp < timedelta(minutes=5):
                return cached_stats
        
        # Get from database
        stats = await session.execute(
            select(MessageStats)
            .where(MessageStats.chat_id == chat_id)
            .where(MessageStats.period == "week")
            .order_by(MessageStats.timestamp.desc())
            .limit(1)
        )
        stats = stats.scalar_one_or_none()
        
        if not stats:
            # Calculate new stats if none found
            stats = await self._calculate_stats(chat_id, session)
        
        # Update cache
        self._cache[chat_id] = stats
        return stats

    async def _calculate_stats(self, chat_id: str, session: AsyncSession) -> MessageStats:
        """Calculate statistics for a chat."""
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        
        # Get messages for the period
        messages = await session.execute(
            select(DBMessage)
            .where(DBMessage.chat_id == chat_id)
            .where(DBMessage.created_at >= week_ago)
            .order_by(DBMessage.created_at)
        )
        messages = messages.scalars().all()
        
        if not messages:
            # Return empty stats instead of None
            return MessageStats(
                chat_id=chat_id,
                period='week',
                message_count=0,
                user_count=0,
                avg_length=0.0,
                emoji_count=0,
                sticker_count=0,
                top_emojis={},
                top_stickers={},
                top_words={},
                top_topics={},
                most_active_hour=None,
                most_active_day=None,
                activity_trend=[]
            )
        
        # Calculate basic stats
        message_count = len(messages)
        user_count = len(set(msg.user_id for msg in messages))
        avg_length = sum(len(msg.text or '') for msg in messages) / message_count if message_count > 0 else 0
        
        # Calculate emoji and sticker stats
        emoji_count = 0
        sticker_count = 0
        top_emojis = Counter()
        top_stickers = Counter()
        
        for msg in messages:
            if msg.text:
                emojis = [c for c in msg.text if emoji.is_emoji(c)]
                emoji_count += len(emojis)
                top_emojis.update(emojis)
        
        # Calculate word stats
        words = []
        # Список стоп-слов русского языка (предлоги, союзы, частицы)
        stop_words = {
            # Предлоги
            'в', 'во', 'не', 'что', 'он', 'на', 'я', 'с', 'со', 'как', 'а', 'то', 'все', 'она',
            'так', 'его', 'но', 'да', 'ты', 'к', 'у', 'же', 'вы', 'за', 'бы', 'по', 'только', 'ее',
            'мне', 'было', 'вот', 'от', 'меня', 'еще', 'нет', 'о', 'из', 'ему', 'теперь', 'когда',
            'даже', 'ну', 'вдруг', 'ли', 'если', 'уже', 'или', 'ни', 'быть', 'был', 'него', 'чего',
            'при', 'на', 'об', 'но', 'он', 'она', 'оно', 'они', 'этот', 'тот', 'такой', 'такая',
            'такое', 'такие', 'каждый', 'каждая', 'каждое', 'каждые', 'мой', 'моя', 'мое', 'мои',
            'твой', 'твоя', 'твое', 'твои', 'наш', 'наша', 'наше', 'наши', 'ваш', 'ваша', 'ваше',
            'ваши', 'их', 'его', 'ее', 'их',
            # Союзы
            'и', 'а', 'но', 'или', 'что', 'чтобы', 'как', 'будто', 'словно', 'точно', 'если',
            'раз', 'коль', 'коли', 'хотя', 'пусть', 'пускай', 'дабы', 'ибо', 'так как', 'поскольку',
            'затем что', 'оттого что', 'потому что', 'притом', 'причем', 'не только', 'но и',
            'не столько', 'сколько', 'не то чтобы', 'а', 'не то', 'а то', 'не то', 'а не то',
            # Частицы
            'бы', 'б', 'ли', 'ль', 'не', 'ни', 'как', 'ведь', 'вон', 'вот', 'дескать', 'де',
            'дека', 'мол', 'нехай', 'пусть', 'пускай', 'разве', 'ровно', 'словно', 'точно',
            'ужели', 'ужель', 'частицы', 'да', 'давай', 'давайте', 'даже', 'еще', 'именно',
            'как раз', 'только', 'только что', 'уже', 'хотя', 'хотя бы', 'чуть', 'чуть ли',
            'чуть не', 'чуть было', 'не', 'неужели', 'неужель', 'разве', 'разве что', 'едва',
            'едва ли', 'едва не', 'едва только', 'лишь', 'лишь только', 'лишь бы', 'хоть',
            'хотя бы', 'хоть бы', 'хотя', 'хотя бы', 'хотя', 'хотя бы', 'хотя', 'хотя бы'
        }
        
        for msg in messages:
            if msg.text:
                # Подсчет слов (исключая только стоп-слова)
                msg_words = [word.lower() for word in re.findall(r'\b\w+\b', msg.text) 
                           if word.lower() not in stop_words]
                words.extend(msg_words)
        top_words = Counter(words).most_common(10)
        
        # Calculate activity stats
        hours = [msg.created_at.hour for msg in messages]
        most_active_hour = max(set(hours), key=hours.count) if hours else None
        
        days = [msg.created_at.strftime('%A') for msg in messages]
        most_active_day = max(set(days), key=days.count) if days else None
        
        # Calculate activity trend
        activity_trend = []
        for i in range(7):
            date = (now - timedelta(days=i)).date()
            count = sum(1 for msg in messages if msg.created_at.date() == date)
            activity_trend.append({
                'date': date.strftime('%Y-%m-%d'),
                'count': count
            })
        
        # Analyze topics
        message_texts = [msg.text for msg in messages if msg.text]
        top_topics = await OpenAIService.analyze_topics(message_texts)
        
        # Create stats object with timezone-aware timestamp
        stats = MessageStats(
            chat_id=chat_id,
            period='week',
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),  # Convert to naive datetime
            message_count=message_count,
            user_count=user_count,
            avg_length=avg_length,
            emoji_count=emoji_count,
            sticker_count=sticker_count,
            top_emojis=dict(top_emojis.most_common(10)),
            top_stickers=dict(top_stickers.most_common(10)),
            top_words=dict(top_words),
            top_topics=top_topics,
            most_active_hour=most_active_hour,
            most_active_day=most_active_day,
            activity_trend=activity_trend
        )
        
        session.add(stats)
        await session.commit()
        
        return stats

    async def start_periodic_update(self, session: AsyncSession):
        """Start periodic update of statistics."""
        while True:
            try:
                # Create new session for each update
                async for update_session in get_session():
                    try:
                        # Get all chats
                        chats = await update_session.execute(select(Chat))
                        chats = chats.scalars().all()
                        
                        # Update stats for each chat
                        for chat in chats:
                            await self._calculate_stats(chat.id, update_session)
                        
                        # Commit changes
                        await update_session.commit()
                    except Exception as e:
                        await update_session.rollback()
                        print(f"Error updating stats: {e}")
                    finally:
                        await update_session.close()
            except Exception as e:
                print(f"Error in periodic update: {e}")
            
            # Wait 5 minutes before next update
            await asyncio.sleep(300) 