import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch
from sqlalchemy import select
from src.services.context_service import ContextService
from src.database.models import MessageThread, Message, Tag, MessageTag, MessageContext

@pytest.fixture
def context_service():
    """Create a context service with mocked session."""
    session = AsyncMock()
    service = ContextService(session)
    service.openai = AsyncMock()
    service.openai.chat_completion = AsyncMock(return_value="tags: tech, question\nimportance: 0.7")
    service.openai.calculate_similarity = AsyncMock(return_value=0.8)
    return service

@pytest.mark.asyncio
async def test_get_or_create_thread_existing(context_service):
    """Test getting existing active thread."""
    # Setup mock thread
    thread = MessageThread(
        id=uuid4(),
        chat_id=123,
        topic="Test Topic",
        is_active=True
    )
    
    # Setup mock execute result
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = AsyncMock(return_value=thread)
    context_service.session.execute = AsyncMock(return_value=mock_result)
    
    # Test
    result = await context_service.get_or_create_thread(123)
    assert result == thread

@pytest.mark.asyncio
async def test_get_or_create_thread_new(context_service):
    """Test creating new thread when none exists."""
    # Setup no existing thread
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = AsyncMock(return_value=None)
    context_service.session.execute = AsyncMock(return_value=mock_result)
    context_service.session.add = AsyncMock()
    context_service.session.commit = AsyncMock()
    
    # Test
    result = await context_service.get_or_create_thread(123, "New Topic")
    
    # Verify new thread was created
    assert result.chat_id == 123
    assert result.topic == "New Topic"
    assert result.is_active == True
    context_service.session.add.assert_awaited_once()
    context_service.session.commit.assert_awaited_once()

@pytest.mark.asyncio
async def test_analyze_message(context_service):
    """Test message analysis."""
    message = Message(text="Test message about technology")
    result = await context_service.analyze_message(message)
    tags = result[0]  # First element is tags list
    assert isinstance(tags, list)
    assert tags == ["tech", "question"]
    context_service.openai.chat_completion.assert_awaited_once()

@pytest.mark.asyncio
async def test_get_or_create_tags_existing(context_service):
    """Test getting existing tags."""
    # Setup mock tag
    tag = Tag(id=uuid4(), name="tech")
    
    # Setup mock execute result
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = AsyncMock(return_value=tag)
    context_service.session.execute = AsyncMock(return_value=mock_result)
    
    # Test
    result = await context_service.get_or_create_tags(["tech"])
    
    assert len(result) == 1
    assert result[0] == tag

@pytest.mark.asyncio
async def test_get_or_create_tags_new(context_service):
    """Test creating new tags."""
    # Setup no existing tag
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = AsyncMock(return_value=None)
    context_service.session.execute = AsyncMock(return_value=mock_result)
    context_service.session.add = AsyncMock()
    context_service.session.commit = AsyncMock()
    
    # Test
    result = await context_service.get_or_create_tags(["newtag"])
    
    assert len(result) == 1
    assert isinstance(result[0], Tag)
    assert result[0].name == "newtag"
    context_service.session.add.assert_awaited_once()
    context_service.session.commit.assert_awaited_once()

@pytest.mark.asyncio
async def test_update_thread_context(context_service):
    """Test updating thread context."""
    # Setup mock thread and messages
    thread = MessageThread(id=uuid4(), chat_id=123)
    messages = [
        Message(id=1, text="First message", timestamp=datetime.utcnow()),
        Message(id=2, text="Second message", timestamp=datetime.utcnow())
    ]
    
    # Setup mock execute results
    mock_messages_result = AsyncMock()
    mock_messages_scalars = AsyncMock()
    mock_messages_scalars.all = AsyncMock(return_value=messages)
    mock_messages_result.scalars = AsyncMock(return_value=mock_messages_scalars)
    
    mock_context_result = AsyncMock()
    mock_context_result.scalar_one_or_none = AsyncMock(return_value=None)
    
    context_service.session.execute = AsyncMock(side_effect=[
        mock_messages_result,
        mock_context_result
    ])
    context_service.session.add = AsyncMock()
    context_service.session.commit = AsyncMock()
    
    # Test
    await context_service.update_thread_context(thread)
    
    # Verify context was created
    context_service.session.add.assert_awaited_once()
    context_service.session.commit.assert_awaited_once()

@pytest.mark.asyncio
async def test_find_related_threads(context_service):
    """Test finding related threads."""
    # Setup mock thread and context
    thread = MessageThread(id=uuid4(), chat_id=123)
    context = MessageContext(
        id=uuid4(),
        thread_id=thread.id,
        context_summary="Test context"
    )
    other_thread = MessageThread(id=uuid4(), chat_id=123, is_active=True)
    
    # Setup mock execute results
    mock_context_result = AsyncMock()
    mock_context_result.scalar_one_or_none = AsyncMock(return_value=context)
    
    mock_threads_result = AsyncMock()
    mock_threads_scalars = AsyncMock()
    mock_threads_scalars.all = AsyncMock(return_value=[other_thread])
    mock_threads_result.scalars = AsyncMock(return_value=mock_threads_scalars)
    
    mock_other_context_result = AsyncMock()
    mock_other_context_result.scalar_one_or_none = AsyncMock(return_value=context)
    
    context_service.session.execute = AsyncMock(side_effect=[
        mock_context_result,
        mock_threads_result,
        mock_other_context_result
    ])
    
    # Test
    result = await context_service.find_related_threads(thread)
    assert len(result) == 1
    assert result[0] == other_thread

@pytest.mark.asyncio
async def test_get_thread_stats(context_service):
    """Test getting thread statistics."""
    # Setup mock thread and messages
    thread = MessageThread(id=uuid4(), chat_id=123)
    messages = [
        Message(
            id=1,
            text="First message",
            timestamp=datetime.utcnow() - timedelta(hours=1),
            user_id=1,
            tags=[
                MessageTag(tag=Tag(name="tech")),
                MessageTag(tag=Tag(name="question"))
            ]
        ),
        Message(
            id=2,
            text="Second message",
            timestamp=datetime.utcnow(),
            user_id=2,
            tags=[
                MessageTag(tag=Tag(name="tech"))
            ]
        )
    ]
    
    # Setup mock execute result
    mock_result = AsyncMock()
    mock_scalars = AsyncMock()
    mock_scalars.all = AsyncMock(return_value=messages)
    mock_result.scalars = AsyncMock(return_value=mock_scalars)
    context_service.session.execute = AsyncMock(return_value=mock_result)
    
    # Test
    stats = await context_service.get_thread_stats(thread)
    
    assert isinstance(stats, dict)
    assert stats["message_count"] == 2
    assert stats["unique_users"] == 2
    assert stats["top_tags"] == ["tech", "question"]