"""Unit tests for ``ContextService``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.database.models import DBMessage, MessageContext, MessageTag, MessageThread, Tag
from src.services.context_service import ContextService, _parse_message_analysis


@pytest.fixture
def context_service():
    """Create a ContextService backed by a fully mocked AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()  # add is sync in real SQLAlchemy
    service = ContextService(session)
    service.openai = AsyncMock()
    service.openai.chat_completion = AsyncMock(return_value="tags: tech, question\nimportance: 0.7")
    service.openai.calculate_similarity = AsyncMock(return_value=0.8)
    return service


def _result_with_scalar(value):
    """Build a fake SQLAlchemy ``Result`` returning ``value`` from ``scalar_one_or_none``."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _result_with_scalars(values):
    """Build a fake SQLAlchemy ``Result`` returning ``values`` from ``scalars().all()``."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=values)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


@pytest.mark.asyncio
async def test_get_or_create_thread_existing(context_service):
    thread = MessageThread(id=uuid4(), chat_id=uuid4(), topic="Test", is_active=True)
    context_service.session.execute = AsyncMock(return_value=_result_with_scalar(thread))

    result = await context_service.get_or_create_thread(thread.chat_id)

    assert result is thread
    context_service.session.add.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_thread_new(context_service):
    chat_id = uuid4()
    context_service.session.execute = AsyncMock(return_value=_result_with_scalar(None))

    result = await context_service.get_or_create_thread(chat_id, "New Topic")

    assert result.chat_id == chat_id
    assert result.topic == "New Topic"
    assert result.is_active is True
    context_service.session.add.assert_called_once()
    context_service.session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_analyze_message_parses_tags_and_importance(context_service):
    msg = DBMessage(text="Test message about technology")
    tags, importance = await context_service.analyze_message(msg)

    assert tags == ["tech", "question"]
    assert importance == 0.7
    context_service.openai.chat_completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_or_create_tags_existing(context_service):
    tag = Tag(id=uuid4(), name="tech")
    context_service.session.execute = AsyncMock(return_value=_result_with_scalar(tag))

    result = await context_service.get_or_create_tags(["tech"])

    assert result == [tag]
    context_service.session.add.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_tags_new(context_service):
    context_service.session.execute = AsyncMock(return_value=_result_with_scalar(None))

    result = await context_service.get_or_create_tags(["#newtag"])

    assert len(result) == 1
    assert result[0].name == "newtag"
    context_service.session.add.assert_called_once()
    context_service.session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_update_thread_context_creates_new(context_service):
    thread = MessageThread(id=uuid4(), chat_id=uuid4())
    messages = [
        DBMessage(text="First", created_at=datetime.now(timezone.utc) - timedelta(minutes=2)),
        DBMessage(text="Second", created_at=datetime.now(timezone.utc) - timedelta(minutes=1)),
    ]

    context_service.openai.chat_completion = AsyncMock(return_value="Brief summary.")
    context_service.session.execute = AsyncMock(
        side_effect=[
            _result_with_scalars(messages),
            _result_with_scalar(None),
        ]
    )

    await context_service.update_thread_context(thread)

    context_service.session.add.assert_called_once()
    added = context_service.session.add.call_args[0][0]
    assert isinstance(added, MessageContext)
    assert added.thread_id == thread.id
    assert added.context_summary == "Brief summary."


@pytest.mark.asyncio
async def test_find_related_threads_by_similarity(context_service):
    thread = MessageThread(id=uuid4(), chat_id=uuid4())
    other = MessageThread(id=uuid4(), chat_id=thread.chat_id, is_active=True)

    context = MessageContext(id=uuid4(), thread_id=thread.id, context_summary="ctx")
    other_ctx = MessageContext(id=uuid4(), thread_id=other.id, context_summary="other")

    context_service.session.execute = AsyncMock(
        side_effect=[
            _result_with_scalar(context),
            _result_with_scalars([other]),
            _result_with_scalar(other_ctx),
        ]
    )

    result = await context_service.find_related_threads(thread)

    assert result == [other]


@pytest.mark.asyncio
async def test_get_thread_stats_returns_dict(context_service):
    thread = MessageThread(id=uuid4(), chat_id=uuid4())
    now = datetime.now(timezone.utc)
    messages = [
        DBMessage(
            id=uuid4(),
            text="First",
            created_at=now - timedelta(hours=1),
            user_id=1,
            tags=[
                MessageTag(tag=Tag(name="tech")),
                MessageTag(tag=Tag(name="question")),
            ],
        ),
        DBMessage(
            id=uuid4(),
            text="Second message",
            created_at=now,
            user_id=2,
            tags=[MessageTag(tag=Tag(name="tech"))],
        ),
    ]
    context_service.session.execute = AsyncMock(return_value=_result_with_scalars(messages))

    stats = await context_service.get_thread_stats(thread)

    assert stats["message_count"] == 2
    assert stats["unique_users"] == 2
    assert "tech" in stats["top_tags"]
    assert stats["duration_hours"] == pytest.approx(1.0, rel=0.1)


def test_parse_message_analysis_handles_messy_input():
    tags, importance = _parse_message_analysis("tags: a , b ,c\nimportance: 1.5\nextra noise")
    assert tags == ["a", "b", "c"]
    assert importance == 1.0  # clamped

    tags, importance = _parse_message_analysis("nothing useful")
    assert tags == []
    assert importance == 0.5
