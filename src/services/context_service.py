"""Thread / context / tag service for the bot's chat memory."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import DBMessage, MessageContext, MessageTag, MessageThread, Tag
from .openai_service import OpenAIService
from .prompts import load_prompt

logger = logging.getLogger(__name__)


class ContextService:
    """Threads, contexts and tags around the message stream."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.openai = OpenAIService()

    async def get_or_create_thread(
        self,
        chat_id: UUID,
        topic: Optional[str] = None,
    ) -> MessageThread:
        """Return the active thread for ``chat_id``, creating one if needed."""
        result = await self.session.execute(
            select(MessageThread).where(
                MessageThread.chat_id == chat_id,
                MessageThread.is_active.is_(True),
            )
        )
        thread = result.scalar_one_or_none()

        if thread and not topic:
            return thread

        new_thread = MessageThread(
            chat_id=chat_id,
            topic=topic or "General Discussion",
            is_active=True,
        )
        self.session.add(new_thread)

        if thread is not None:
            thread.is_active = False

        await self.session.commit()
        return new_thread

    async def analyze_message(self, message: DBMessage) -> Tuple[List[str], float]:
        """Use the LLM to suggest tags and an importance score."""
        prompt = load_prompt("TECH-001_message_analysis")
        response = await self.openai.chat_completion(prompt.format(message=message.text or ""))
        return _parse_message_analysis(response)

    async def get_or_create_tags(self, tag_names: List[str]) -> List[Tag]:
        """Resolve a list of tag names to ``Tag`` rows, creating missing ones."""
        tags: List[Tag] = []
        for name in tag_names:
            clean = name.strip().lstrip("#")
            if not clean:
                continue
            result = await self.session.execute(select(Tag).where(Tag.name == clean))
            tag = result.scalar_one_or_none()
            if tag is None:
                tag = Tag(name=clean)
                self.session.add(tag)
                await self.session.commit()
            tags.append(tag)
        return tags

    async def add_tags_to_message(
        self,
        message: DBMessage,
        tags: List[Tag],
        is_auto: bool = True,
    ) -> None:
        """Attach a list of tags to a message."""
        for tag in tags:
            self.session.add(MessageTag(message_id=message.id, tag_id=tag.id, is_auto=is_auto))
        await self.session.commit()

    async def update_thread_context(self, thread: MessageThread) -> None:
        """Refresh the rolling context summary of a thread from its last messages."""
        result = await self.session.execute(
            select(DBMessage)
            .where(DBMessage.thread_id == thread.id)
            .order_by(DBMessage.created_at.desc())
            .limit(10)
        )
        messages = list(result.scalars().all())
        if not messages:
            return

        prompt = load_prompt("TECH-001_thread_summary")
        messages_text = "\n".join(f"- {msg.text}" for msg in messages if msg.text)
        summary = await self.openai.chat_completion(prompt.format(messages_text=messages_text))

        result = await self.session.execute(
            select(MessageContext).where(MessageContext.thread_id == thread.id)
        )
        context = result.scalar_one_or_none()
        if context is not None:
            context.context_summary = summary
        else:
            self.session.add(MessageContext(thread_id=thread.id, context_summary=summary))
        await self.session.commit()

    async def find_related_threads(self, thread: MessageThread) -> List[MessageThread]:
        """Find threads with semantically similar context summaries."""
        result = await self.session.execute(
            select(MessageContext).where(MessageContext.thread_id == thread.id)
        )
        context = result.scalar_one_or_none()
        if context is None or not context.context_summary:
            return []

        result = await self.session.execute(
            select(MessageThread).where(
                MessageThread.chat_id == thread.chat_id,
                MessageThread.id != thread.id,
                MessageThread.is_active.is_(True),
            )
        )
        other_threads = list(result.scalars().all())

        related: List[MessageThread] = []
        for other in other_threads:
            other_ctx_result = await self.session.execute(
                select(MessageContext).where(MessageContext.thread_id == other.id)
            )
            other_ctx = other_ctx_result.scalar_one_or_none()
            if other_ctx is None or not other_ctx.context_summary:
                continue

            similarity = await self.openai.calculate_similarity(
                context.context_summary,
                other_ctx.context_summary,
            )
            if similarity > 0.7:
                related.append(other)

        return related

    async def get_thread_stats(self, thread: MessageThread) -> Dict[str, Any]:
        """Return a small dict with thread statistics, or ``{}`` if empty."""
        result = await self.session.execute(
            select(DBMessage).where(DBMessage.thread_id == thread.id)
        )
        messages = list(result.scalars().all())
        if not messages:
            return {}

        message_count = len(messages)
        unique_users = len({msg.user_id for msg in messages})

        first_msg = min(messages, key=lambda m: m.created_at)
        last_msg = max(messages, key=lambda m: m.created_at)
        duration_hours = max(
            0.0,
            (last_msg.created_at - first_msg.created_at).total_seconds() / 3600.0,
        )

        avg_message_length = sum(len(m.text or "") for m in messages) / message_count
        messages_per_hour = (
            message_count / duration_hours if duration_hours else float(message_count)
        )

        tag_counter: Counter[str] = Counter()
        for msg in messages:
            for mt in msg.tags or []:
                if mt.tag is not None:
                    tag_counter[mt.tag.name] += 1
        top_tags = [name for name, _ in tag_counter.most_common(5)]

        return {
            "message_count": message_count,
            "total_messages": message_count,  # backwards-compatible alias
            "unique_users": unique_users,
            "duration_hours": duration_hours,
            "avg_message_length": avg_message_length,
            "messages_per_hour": messages_per_hour,
            "top_tags": top_tags,
        }

    async def get_context_for_summary(self, chat_id: UUID) -> str:
        """Return a brief context summary for a chat (latest active thread)."""
        thread = await self.get_or_create_thread(chat_id)
        result = await self.session.execute(
            select(MessageContext).where(MessageContext.thread_id == thread.id)
        )
        context = result.scalar_one_or_none()
        return context.context_summary if context and context.context_summary else ""

    async def generate_chat_summary(self, messages: List[DBMessage]) -> str:
        """Generate a friendly retelling of the given messages."""
        if not messages:
            return "No messages to summarize."

        first_msg = messages[0]
        chat = first_msg.chat
        user_ids = {msg.user_id for msg in messages}
        user_names: Dict[int, str] = {}

        for user_id in user_ids:
            try:
                member = await first_msg.bot.get_chat_member(chat.telegram_id, user_id)
                if member and member.user:
                    full = member.user.first_name or ""
                    if member.user.last_name:
                        full = f"{full} {member.user.last_name}".strip()
                    user_names[user_id] = full or f"User {user_id}"
                else:
                    user_names[user_id] = f"User {user_id}"
            except Exception as exc:  # noqa: BLE001 — TG API может отдать что угодно
                logger.warning("Could not resolve user %s: %s", user_id, exc)
                user_names[user_id] = f"User {user_id}"

        messages_text = "\n".join(
            f"{msg.created_at.strftime('%Y-%m-%d %H:%M')} - "
            f"{user_names.get(msg.user_id, f'User {msg.user_id}')}: {msg.text}"
            for msg in messages
            if msg.text
        )
        prompt = load_prompt("TECH-001_chat_summary")
        return await self.openai.chat_completion(prompt.format(messages_text=messages_text))


def _parse_message_analysis(response: str) -> Tuple[List[str], float]:
    """Parse the ``tags: ...`` / ``importance: 0.X`` response from the LLM."""
    tags: List[str] = []
    importance = 0.5
    for line in response.splitlines():
        line = line.strip()
        if line.lower().startswith("tags:"):
            _, _, raw = line.partition(":")
            tags = [t.strip() for t in raw.split(",") if t.strip()]
        elif line.lower().startswith("importance:"):
            _, _, raw = line.partition(":")
            try:
                importance = float(raw.strip())
            except ValueError:
                importance = 0.5
    return tags, max(0.0, min(1.0, importance))
