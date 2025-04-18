from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum, select, func, Table, BigInteger, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timedelta, timezone
import enum
from uuid import uuid4

from .base import Base

class ChatType(enum.Enum):
    WORK = "work"
    FRIENDLY = "friendly"
    MIXED = "mixed"

class Chat(Base):
    __tablename__ = "chats"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    telegram_id = Column(BigInteger, nullable=False, unique=True)  # Telegram's chat ID
    name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    type = Column(String, nullable=False)  # Using string instead of enum
    is_silent = Column(Boolean, default=True)
    smart_mode = Column(Boolean, default=False)
    response_probability = Column(Float, default=0.5)
    importance_threshold = Column(Float, default=0.5)
    last_summary_timestamp = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    messages = relationship("DBMessage", back_populates="chat")
    threads = relationship("MessageThread", back_populates="chat")
    
    async def adjust_importance_threshold(self, session) -> None:
        """Adjust importance threshold based on response statistics."""
        # Get messages from last 24 hours
        yesterday = datetime.utcnow() - timedelta(days=1)
        stats_query = select(DBMessage).where(
            DBMessage.chat_id == self.id,
            DBMessage.created_at >= yesterday
        )
        result = await session.execute(stats_query)
        messages = result.scalars().all()
        
        if not messages:
            return  # No messages to analyze
        
        total_messages = len(messages)
        responded_messages = sum(1 for msg in messages if msg.was_responded)
        response_rate = responded_messages / total_messages
        
        # Target response rate is between 20% and 40%
        if response_rate < 0.20:  # Too few responses
            # Lower threshold to respond more
            self.importance_threshold = max(0.1, self.importance_threshold - 0.05)
        elif response_rate > 0.40:  # Too many responses
            # Raise threshold to respond less
            self.importance_threshold = min(0.9, self.importance_threshold + 0.05)
        
        await session.commit()

class MessageThread(Base):
    """Represents a thread of related messages."""
    __tablename__ = "message_threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id"))
    name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    topic = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    chat = relationship("Chat", back_populates="threads")
    messages = relationship("DBMessage", back_populates="thread")
    context_entries = relationship("MessageContext", back_populates="thread")
    related_threads = relationship(
        "MessageThread",
        secondary="thread_relations",
        primaryjoin="MessageThread.id==thread_relations.c.thread_id",
        secondaryjoin="MessageThread.id==thread_relations.c.related_thread_id",
        backref="related_to"
    )

class DBMessage(Base):
    """Message from a chat."""
    __tablename__ = "messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id = Column(Integer, nullable=False)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id"))
    user_id = Column(BigInteger, nullable=False)
    text = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    was_responded = Column(Boolean, default=False)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("message_threads.id"), nullable=True)
    
    chat = relationship("Chat", back_populates="messages")
    thread = relationship("MessageThread", back_populates="messages")
    tags = relationship("MessageTag", back_populates="message")
    context = relationship(
        "MessageContext",
        back_populates="message",
        uselist=False,
        primaryjoin="DBMessage.id==MessageContext.message_id"
    )
    
    @property
    def tag_names(self) -> list[str]:
        """Get list of tag names for this message."""
        return [mt.tag.name for mt in self.tags]

class Style(Base):
    __tablename__ = "styles"
    
    id = Column(Integer, primary_key=True)
    chat_type = Column(Enum(ChatType), unique=True)
    prompt_template = Column(String)
    last_updated = Column(DateTime, default=datetime.utcnow)
    training_data = Column(String)  # JSON string of training examples

class MessageContext(Base):
    """Stores context information for messages and threads."""
    __tablename__ = "message_contexts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("message_threads.id"))
    context_summary = Column(String)
    importance_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    thread = relationship("MessageThread", back_populates="context_entries")
    message = relationship("DBMessage", back_populates="context")

class Tag(Base):
    """Represents a tag that can be applied to messages."""
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, unique=True)
    description = Column(String, nullable=True)
    is_system = Column(Boolean, default=False)  # System tags like #question, #idea
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    message_tags = relationship("MessageTag", back_populates="tag")

class MessageTag(Base):
    """Association between messages and tags."""
    __tablename__ = "message_tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id = Column(Integer, ForeignKey("messages.id"))
    tag_id = Column(UUID(as_uuid=True), ForeignKey("tags.id"))
    is_auto = Column(Boolean, default=False)
    confidence = Column(Float, default=1.0)  # For auto-tagged messages
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    message = relationship("DBMessage", back_populates="tags")
    tag = relationship("Tag", back_populates="message_tags")

# Association table for related threads
thread_relations = Table(
    "thread_relations",
    Base.metadata,
    Column("thread_id", UUID(as_uuid=True), ForeignKey("message_threads.id"), primary_key=True),
    Column("related_thread_id", UUID(as_uuid=True), ForeignKey("message_threads.id"), primary_key=True)
)

class MessageStats(Base):
    """Statistics for messages in a chat."""
    __tablename__ = "message_stats"
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id"))
    period = Column(String)  # 'hour', 'day', 'week', 'month'
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Basic stats
    message_count = Column(Integer, default=0)
    user_count = Column(Integer, default=0)
    avg_length = Column(Float, default=0.0)
    
    # Content stats
    emoji_count = Column(Integer, default=0)
    sticker_count = Column(Integer, default=0)
    top_emojis = Column(JSON)  # List of [emoji, count] pairs
    top_stickers = Column(JSON)  # List of [sticker_id, count] pairs
    top_words = Column(JSON)  # List of [word, count] pairs
    top_topics = Column(JSON)  # List of [topic, count] pairs
    
    # Activity stats
    most_active_hour = Column(Integer)
    most_active_day = Column(String)
    activity_trend = Column(JSON)  # List of daily message counts

    def __repr__(self):
        return f"<MessageStats(chat_id={self.chat_id}, period={self.period})>" 