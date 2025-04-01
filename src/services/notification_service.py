from aiogram import Bot
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class NotificationThresholds:
    """Thresholds for different notification types."""
    threshold_change: float = 0.2  # Minimum change in importance threshold to notify
    high_activity_count: int = 100  # Messages count for high activity
    high_activity_hours: int = 1  # Time window for high activity
    low_response_rate: float = 0.1  # Response rate below this triggers notification
    notification_cooldown: int = 60  # Minutes between similar notifications

class NotificationService:
    def __init__(self, bot: Bot, owner_id: int, thresholds: NotificationThresholds = None):
        self.bot = bot
        self.owner_id = owner_id
        self._last_notification = {}  # Cache to prevent spam
        self.thresholds = thresholds or NotificationThresholds()
    
    async def notify_style_change(self, chat_title: str, old_style: str, new_style: str) -> None:
        """Notify about chat style changes."""
        if self._should_notify('style_change', chat_title):
            await self._send_notification(
                f"🎨 Style changed for {chat_title}:\n"
                f"From: {old_style}\n"
                f"To: {new_style}"
            )
    
    async def notify_threshold_change(self, chat_title: str, old_threshold: float, new_threshold: float) -> None:
        """Notify about significant threshold changes."""
        if (abs(old_threshold - new_threshold) >= self.thresholds.threshold_change and 
            self._should_notify('threshold_change', chat_title)):
            await self._send_notification(
                f"⚠️ Importance threshold changed significantly for {chat_title}:\n"
                f"From: {old_threshold:.2f}\n"
                f"To: {new_threshold:.2f}\n"
                f"Change: {(new_threshold - old_threshold):+.2f}"
            )
    
    async def notify_high_activity(self, chat_title: str, msg_count: int, timespan_hours: float) -> None:
        """Notify about unusually high chat activity."""
        # Calculate messages per hour
        msgs_per_hour = msg_count / timespan_hours if timespan_hours > 0 else msg_count
        logger.debug(f"High activity check: {msgs_per_hour} msgs/hour >= {self.thresholds.high_activity_count}/{self.thresholds.high_activity_hours}")
        
        threshold_check = msgs_per_hour >= self.thresholds.high_activity_count / self.thresholds.high_activity_hours
        cooldown_check = self._should_notify('high_activity', chat_title)
        logger.debug(f"Notification decision: threshold_check={threshold_check}, cooldown_check={cooldown_check}")
        
        if threshold_check and cooldown_check:
            await self._send_notification(
                f"📈 High activity detected in {chat_title}:\n"
                f"{msg_count} messages in {timespan_hours:.1f}h\n"
                f"Rate: {msgs_per_hour:.1f} msgs/hour"
            )
    
    async def notify_low_response_rate(self, chat_title: str, rate: float) -> None:
        """Notify about low response rates."""
        if (rate < self.thresholds.low_response_rate and 
            self._should_notify('low_response_rate', chat_title)):
            await self._send_notification(
                f"📉 Low response rate in {chat_title}:\n"
                f"Current rate: {rate:.1%}\n"
                f"Threshold: {self.thresholds.low_response_rate:.1%}"
            )
    
    async def notify_error(self, error_type: str, details: str) -> None:
        """Notify about system errors."""
        if self._should_notify('error', error_type):
            await self._send_notification(
                f"❌ System Error - {error_type}:\n{details}"
            )
    
    async def notify_startup(self) -> None:
        """Send startup notification."""
        await self._send_notification(
            "🚀 vAIlentin 2.0 bot started successfully!\n"
            "Use /help to see available commands."
        )
    
    async def notify_shutdown(self) -> None:
        """Send shutdown notification."""
        await self._send_notification(
            "🔄 vAIlentin 2.0 bot is shutting down..."
        )
    
    async def notify_daily_summary(self, total_messages: int, response_rate: float, active_chats: int) -> None:
        """Send daily activity summary."""
        if self._should_notify('daily_summary', 'global'):
            await self._send_notification(
                "📊 Daily Summary:\n"
                f"Total Messages: {total_messages}\n"
                f"Response Rate: {response_rate:.1%}\n"
                f"Active Chats: {active_chats}"
            )
    
    def _should_notify(self, notification_type: str, key: str) -> bool:
        """Check if notification should be sent (prevent spam)."""
        now = datetime.utcnow()
        cache_key = f"{notification_type}_{key}"
        
        if cache_key in self._last_notification:
            # Use configured cooldown period
            time_since_last = now - self._last_notification[cache_key]
            cooldown = timedelta(minutes=self.thresholds.notification_cooldown)
            should_notify = time_since_last >= cooldown
            logger.debug(f"Cooldown check for {cache_key}: time_since_last={time_since_last}, cooldown={cooldown}, should_notify={should_notify}")
            if not should_notify:
                return False
        
        self._last_notification[cache_key] = now
        return True
    
    async def _send_notification(self, message: str) -> None:
        """Send notification to owner."""
        try:
            await self.bot.send_message(self.owner_id, message)
        except Exception as e:
            logger.error(f"Failed to send notification: {e}") 