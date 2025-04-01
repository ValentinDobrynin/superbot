from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Table
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# Association table for related threads
thread_relations = Table(
    'thread_relations',
    Base.metadata,
    Column('thread_id', PgUUID(as_uuid=True), ForeignKey('message_threads.id'), primary_key=True),
    Column('related_thread_id', PgUUID(as_uuid=True), ForeignKey('message_threads.id'), primary_key=True)
)

class MessageThread(Base):
    """Represents a thread of related messages."""
    __tablename__ = 'message_threads'

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    topic: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey('chats.id'))
    
    # Relationships
    messages = relationship('Message', back_populates='thread')
    context_entries = relationship('MessageContext', back_populates='thread')
    related_threads = relationship(
        'MessageThread',
        secondary=thread_relations,
        primaryjoin=id==thread_relations.c.thread_id,
        secondaryjoin=id==thread_relations.c.related_thread_id,
        backref='related_to'
    )

class MessageContext(Base):
    """Stores context information for messages and threads."""
    __tablename__ = 'message_contexts'

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    thread_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey('message_threads.id'))
    context_summary: Mapped[str] = mapped_column(String)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    thread = relationship('MessageThread', back_populates='context_entries')

class Tag(Base):
    """Represents a tag that can be applied to messages."""
    __tablename__ = 'tags'

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # System tags like #question, #idea
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    message_tags = relationship('MessageTag', back_populates='tag')

class MessageTag(Base):
    """Association between messages and tags."""
    __tablename__ = 'message_tags'

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey('messages.id'))
    tag_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey('tags.id'))
    is_auto: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)  # For auto-tagged messages
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    message = relationship('Message', back_populates='tags')
    tag = relationship('Tag', back_populates='message_tags') 