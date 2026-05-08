import enum
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .base import Base


class ChatType(enum.Enum):
    WORK = "work"
    FRIENDLY = "friendly"
    MIXED = "mixed"


TG_CHAT_TYPES = ("private", "group", "supergroup", "channel")
CLASSIFICATIONS = ("business", "private", "mixed")
COMMIT_DIRECTIONS = ("from_me", "to_me")
COMMIT_STATUSES = ("open", "done", "cancelled")
EVENT_STATUSES = ("upcoming", "past", "cancelled")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    telegram_id = Column(BigInteger, nullable=False, unique=True)  # Telegram's chat ID
    name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    type = Column(String, nullable=False)  # internal style enum WORK/FRIENDLY/MIXED
    tg_type = Column(String(16), nullable=False)  # Telegram-side: group/supergroup/private/channel
    # Non-null only for private chats opened via Telegram Business Mode (FEATURE-004).
    # Without it, `tg_type='private'` would be ambiguous (owner-bot DM vs business chat).
    business_connection_id = Column(
        String(64),
        ForeignKey("business_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    # FEATURE-007: owner-confirmed bucket. NULL = unclassified (default for new
    # chats; the next digest will surface a classification suggestion).
    classification = Column(String(16), nullable=True)
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
            DBMessage.chat_id == self.id, DBMessage.created_at >= yesterday
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
        backref="related_to",
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
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    was_responded = Column(Boolean, default=False)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("message_threads.id"), nullable=True)

    chat = relationship("Chat", back_populates="messages")
    thread = relationship("MessageThread", back_populates="messages")
    tags = relationship("MessageTag", back_populates="message")
    context = relationship(
        "MessageContext",
        back_populates="message",
        uselist=False,
        primaryjoin="DBMessage.id==MessageContext.message_id",
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
    Column(
        "related_thread_id", UUID(as_uuid=True), ForeignKey("message_threads.id"), primary_key=True
    ),
)


class BusinessConnection(Base):
    """A Telegram Business connection between the bot and the owner (FEATURE-004).

    One row per ``connection_id`` returned by Telegram. We never delete rows —
    on disconnect we just flip ``is_enabled=False`` so the audit trail stays.
    """

    __tablename__ = "business_connections"

    id = Column(String(64), primary_key=True)  # Telegram's connection_id
    user_id = Column(BigInteger, nullable=False)  # owner's Telegram user id
    user_chat_id = Column(BigInteger, nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    can_reply = Column(Boolean, nullable=False, default=False)
    rights = Column(JSONB, nullable=True)  # full BusinessBotRights snapshot
    connected_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        state = "enabled" if self.is_enabled else "disabled"
        return f"<BusinessConnection(id={self.id}, user_id={self.user_id}, {state})>"


class DailyDigest(Base):
    """One row per calendar day (Europe/Moscow) for FEATURE-002 digests."""

    __tablename__ = "daily_digests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    digest_date = Column(Date, nullable=False, unique=True)
    sent_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    chat_count = Column(Integer, nullable=False, default=0)
    message_count = Column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<DailyDigest(date={self.digest_date}, chats={self.chat_count})>"


class Commitment(Base):
    """A commitment extracted from a chat (FEATURE-008).

    Persisted across digests so we can dedupe and let the owner mark it
    done/cancelled. ``direction`` specifies who promised whom:
    - ``from_me`` — owner committed something to the partner;
    - ``to_me`` — partner committed something to the owner.
    """

    __tablename__ = "commitments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    direction = Column(String(8), nullable=False)  # 'from_me' / 'to_me'
    text = Column(String, nullable=False)
    deadline_raw = Column(String, nullable=True)  # raw NL string from the chat
    deadline_at = Column(DateTime(timezone=True), nullable=True)  # parsed datetime
    is_urgent = Column(Boolean, nullable=False, default=False)
    status = Column(String(16), nullable=False, default="open")
    source_message_id = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    chat = relationship("Chat")

    def __repr__(self) -> str:
        return f"<Commitment({self.direction}, status={self.status}, text={self.text[:30]!r})>"


class Event(Base):
    """A date / event extracted from a chat (FEATURE-009)."""

    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    description = Column(String, nullable=False)
    when_raw = Column(String, nullable=True)
    when_at = Column(DateTime(timezone=True), nullable=True)
    is_urgent = Column(Boolean, nullable=False, default=False)
    status = Column(String(16), nullable=False, default="upcoming")
    source_message_id = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    chat = relationship("Chat")

    def __repr__(self) -> str:
        return (
            f"<Event(status={self.status}, when={self.when_raw!r}, desc={self.description[:30]!r})>"
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
