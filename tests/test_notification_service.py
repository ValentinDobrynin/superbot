import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from src.services.notification_service import NotificationService, NotificationThresholds

@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot

@pytest.fixture
def notification_service(mock_bot):
    return NotificationService(
        bot=mock_bot,
        owner_id=12345,
        thresholds=NotificationThresholds()
    )

@pytest.fixture
def custom_thresholds():
    return NotificationThresholds(
        threshold_change=0.3,
        high_activity_count=200,
        high_activity_hours=2,
        low_response_rate=0.15,
        notification_cooldown=30
    )

@pytest.mark.asyncio
async def test_notify_style_change(notification_service):
    """Test style change notification."""
    await notification_service.notify_style_change(
        chat_title="Test Chat",
        old_style="Formal",
        new_style="Casual"
    )
    
    notification_service.bot.send_message.assert_called_once_with(
        12345,
        "🎨 Style changed for Test Chat:\nFrom: Formal\nTo: Casual"
    )

@pytest.mark.asyncio
async def test_notify_threshold_change(notification_service):
    """Test threshold change notification."""
    await notification_service.notify_threshold_change(
        chat_title="Test Chat",
        old_threshold=0.3,
        new_threshold=0.6
    )
    
    notification_service.bot.send_message.assert_called_once_with(
        12345,
        "⚠️ Importance threshold changed significantly for Test Chat:\n"
        "From: 0.30\nTo: 0.60\nChange: +0.30"
    )

@pytest.mark.asyncio
async def test_notify_high_activity(notification_service):
    """Test high activity notification."""
    await notification_service.notify_high_activity(
        chat_title="Test Chat",
        msg_count=120,
        timespan_hours=1
    )
    
    notification_service.bot.send_message.assert_called_once_with(
        12345,
        "📈 High activity detected in Test Chat:\n"
        "120 messages in 1.0h\n"
        "Rate: 120.0 msgs/hour"
    )

@pytest.mark.asyncio
async def test_notify_low_response_rate(notification_service):
    """Test low response rate notification."""
    await notification_service.notify_low_response_rate(
        chat_title="Test Chat",
        rate=0.05
    )
    
    notification_service.bot.send_message.assert_called_once_with(
        12345,
        "📉 Low response rate in Test Chat:\n"
        "Current rate: 5.0%\n"
        "Threshold: 10.0%"
    )

@pytest.mark.asyncio
async def test_notification_cooldown(notification_service):
    """Test notification cooldown period."""
    # First notification should go through
    await notification_service.notify_style_change("Test Chat", "Old", "New")
    assert notification_service.bot.send_message.call_count == 1
    
    # Second notification within cooldown period should not
    await notification_service.notify_style_change("Test Chat", "New", "Newer")
    assert notification_service.bot.send_message.call_count == 1
    
    # Simulate time passing
    with patch('src.services.notification_service.datetime') as mock_datetime:
        mock_datetime.utcnow.return_value = datetime.utcnow() + timedelta(minutes=61)
        await notification_service.notify_style_change("Test Chat", "Newer", "Newest")
        assert notification_service.bot.send_message.call_count == 2

@pytest.mark.asyncio
async def test_error_notification(notification_service):
    """Test error notification."""
    await notification_service.notify_error(
        error_type="Database Error",
        details="Connection failed"
    )
    
    notification_service.bot.send_message.assert_called_once_with(
        12345,
        "❌ System Error - Database Error:\nConnection failed"
    )

@pytest.mark.asyncio
async def test_daily_summary(notification_service):
    """Test daily summary notification."""
    await notification_service.notify_daily_summary(
        total_messages=500,
        response_rate=0.35,
        active_chats=5
    )
    
    notification_service.bot.send_message.assert_called_once_with(
        12345,
        "📊 Daily Summary:\n"
        "Total Messages: 500\n"
        "Response Rate: 35.0%\n"
        "Active Chats: 5"
    )

@pytest.mark.asyncio
async def test_startup_shutdown(notification_service):
    """Test startup and shutdown notifications."""
    await notification_service.notify_startup()
    notification_service.bot.send_message.assert_called_with(
        12345,
        "🚀 vAIlentin 2.0 bot started successfully!\n"
        "Use /help to see available commands."
    )
    
    notification_service.bot.send_message.reset_mock()
    
    await notification_service.notify_shutdown()
    notification_service.bot.send_message.assert_called_with(
        12345,
        "🔄 vAIlentin 2.0 bot is shutting down..."
    )

@pytest.mark.asyncio
async def test_failed_notification(notification_service):
    """Test handling of failed notifications."""
    notification_service.bot.send_message.side_effect = Exception("Network error")
    
    with patch('src.services.notification_service.logger') as mock_logger:
        await notification_service.notify_startup()
        mock_logger.error.assert_called_once_with("Failed to send notification: Network error")

@pytest.mark.asyncio
async def test_multiple_chat_notifications(notification_service):
    """Test notifications from different chats don't interfere."""
    # First chat notification
    await notification_service.notify_style_change("Chat 1", "Old", "New")
    assert notification_service.bot.send_message.call_count == 1
    
    # Second chat should send notification despite cooldown
    await notification_service.notify_style_change("Chat 2", "Old", "New")
    assert notification_service.bot.send_message.call_count == 2

@pytest.mark.asyncio
async def test_high_activity_edge_cases(notification_service):
    """Test edge cases for high activity notifications."""
    # Test exactly at threshold
    await notification_service.notify_high_activity(
        chat_title="Test Chat",
        msg_count=100,
        timespan_hours=1.0
    )
    assert notification_service.bot.send_message.call_count == 1
    
    notification_service.bot.send_message.reset_mock()
    notification_service._last_notification.clear()  # Reset cooldown
    
    # Test below threshold
    await notification_service.notify_high_activity(
        chat_title="Test Chat",
        msg_count=99,
        timespan_hours=1.0
    )
    assert notification_service.bot.send_message.call_count == 0
    
    notification_service._last_notification.clear()  # Reset cooldown
    
    # Test with very short timespan (150 msgs/hour)
    await notification_service.notify_high_activity(
        chat_title="Test Chat",
        msg_count=15,
        timespan_hours=0.1
    )
    assert notification_service.bot.send_message.call_count == 1  # Should trigger as > 100 msgs/hour

@pytest.mark.asyncio
async def test_message_formatting_special_chars(notification_service):
    """Test message formatting with special characters."""
    await notification_service.notify_style_change(
        chat_title="Test 🎉 Chat!",
        old_style="Formal 👔",
        new_style="Casual 🎨"
    )
    
    notification_service.bot.send_message.assert_called_once_with(
        12345,
        "🎨 Style changed for Test 🎉 Chat!:\n"
        "From: Formal 👔\n"
        "To: Casual 🎨"
    )

@pytest.mark.asyncio
async def test_message_formatting_numbers(notification_service):
    """Test number formatting in messages."""
    await notification_service.notify_threshold_change(
        chat_title="Test Chat",
        old_threshold=0.333333,
        new_threshold=0.666667
    )
    
    notification_service.bot.send_message.assert_called_once_with(
        12345,
        "⚠️ Importance threshold changed significantly for Test Chat:\n"
        "From: 0.33\nTo: 0.67\nChange: +0.33"
    )

@pytest.mark.asyncio
async def test_long_chat_title(notification_service):
    """Test handling of long chat titles."""
    long_title = "This is a very long chat title that might need special handling " * 3
    await notification_service.notify_style_change(
        chat_title=long_title,
        old_style="Old",
        new_style="New"
    )
    
    # Verify the message was sent and contains the full title
    notification_service.bot.send_message.assert_called_once()
    args = notification_service.bot.send_message.call_args[0]
    assert args[0] == 12345
    assert long_title in args[1]

@pytest.mark.asyncio
async def test_different_notification_types_cooldown(notification_service):
    """Test that different notification types have separate cooldowns."""
    # Style change notification
    await notification_service.notify_style_change("Test Chat", "Old", "New")
    assert notification_service.bot.send_message.call_count == 1
    
    # Threshold change should go through despite style change cooldown
    await notification_service.notify_threshold_change("Test Chat", 0.3, 0.6)
    assert notification_service.bot.send_message.call_count == 2
    
    # High activity should also go through
    await notification_service.notify_high_activity("Test Chat", 120, 1)
    assert notification_service.bot.send_message.call_count == 3

@pytest.mark.asyncio
async def test_custom_thresholds(mock_bot, custom_thresholds):
    """Test notification service with custom thresholds."""
    service = NotificationService(
        bot=mock_bot,
        owner_id=12345,
        thresholds=custom_thresholds
    )
    
    # Test high activity with custom threshold
    await service.notify_high_activity(
        chat_title="Test Chat",
        msg_count=150,
        timespan_hours=2
    )
    assert service.bot.send_message.call_count == 0  # Should not trigger (below 200/2h threshold)
    
    # Test threshold change with custom value
    await service.notify_threshold_change(
        chat_title="Test Chat",
        old_threshold=0.3,
        new_threshold=0.5
    )
    assert service.bot.send_message.call_count == 0  # Should not trigger (below 0.3 change)
    
    await service.notify_threshold_change(
        chat_title="Test Chat",
        old_threshold=0.3,
        new_threshold=0.7
    )
    assert service.bot.send_message.call_count == 1  # Should trigger (>= 0.3 change) 