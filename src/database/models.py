from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum, select, func, Table, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timedelta
import enum
from uuid import uuid4

from .base import Base

class ChatType(enum.Enum):
    WORK = "work"
    FRIENDLY = "friendly"
    MIXED = "mixed"

class Chat(Base):
    __tablename__ = "chats"
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, nullable=False)
    title = Column(String, nullable=False)
    chat_type = Column(Enum(ChatType), default=ChatType.MIXED)
    is_silent = Column(Boolean, default=False)  # True means bot reads but doesn't respond
    response_probability = Column(Float, default=0.5)
    smart_mode = Column(Boolean, default=True)
    importance_threshold = Column(Float, default=0.5)  # Threshold for smart mode
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_summary_timestamp = Column(DateTime, nullable=True)
    
    messages = relationship("Message", back_populates="chat")
    threads = relationship("MessageThread", back_populates="chat")
    
    async def adjust_importance_threshold(self, session) -> None:
        """Adjust importance threshold based on response statistics."""
        # Get messages from last 24 hours
        yesterday = datetime.utcnow() - timedelta(days=1)
        stats_query = select(Message).where(
            Message.chat_id == self.id,
            Message.timestamp >= yesterday
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
    chat_id = Column(Integer, ForeignKey("chats.id"))
    topic = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    chat = relationship("Chat", back_populates="threads")
    messages = relationship("Message", back_populates="thread")
    context_entries = relationship("MessageContext", back_populates="thread")
    related_threads = relationship(
        "MessageThread",
        secondary="thread_relations",
        primaryjoin="MessageThread.id==thread_relations.c.thread_id",
        secondaryjoin="MessageThread.id==thread_relations.c.related_thread_id",
        backref="related_to"
    )

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer)
    chat_id = Column(BigInteger, ForeignKey("chats.id"))
    user_id = Column(Integer)
    text = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    was_responded = Column(Boolean, default=False)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("message_threads.id"), nullable=True)
    
    # Relationships
    chat = relationship("Chat", back_populates="messages")
    thread = relationship("MessageThread", back_populates="messages")
    tags = relationship("MessageTag", back_populates="message")
    
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
    thread_id = Column(UUID(as_uuid=True), ForeignKey("message_threads.id"))
    context_summary = Column(String)
    importance_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    thread = relationship("MessageThread", back_populates="context_entries")

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
    message = relationship("Message", back_populates="tags")
    tag = relationship("Tag", back_populates="message_tags")

# Association table for related threads
thread_relations = Table(
    "thread_relations",
    Base.metadata,
    Column("thread_id", UUID(as_uuid=True), ForeignKey("message_threads.id"), primary_key=True),
    Column("related_thread_id", UUID(as_uuid=True), ForeignKey("message_threads.id"), primary_key=True)
) 