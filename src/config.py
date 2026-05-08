import os
from typing import List

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))

    # Default settings
    DEFAULT_RESPONSE_PROBABILITY: float = 0.25
    MIN_RESPONSE_DELAY: int = 3
    MAX_RESPONSE_DELAY: int = 7
    MAX_CONTEXT_MESSAGES: int = 5

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    def get_async_database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if not url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    # Chat types
    CHAT_TYPES: List[str] = ["work", "friendly", "mixed"]

    # FEATURE-004: Telegram Business mode (observer-only). Bot doesn't reply
    # in business chats — it only persists messages for the daily digest.
    BUSINESS_OBSERVER_ENABLED: bool = True
    # TECH-009: hard TTL for `messages.text`. Anything older than this is
    # purged daily by `CleanupService`. 30 days = balance between digest
    # usefulness and personal-data retention.
    MESSAGE_TTL_DAYS: int = int(os.getenv("MESSAGE_TTL_DAYS", "30"))

    # Global state
    is_shutdown: bool = False
    # Local pause toggle for business observer (commands `/business on|off`).
    # When True, business_message updates are received but NOT saved.
    business_paused: bool = False

    model_config = {"env_file": ".env"}


settings = Settings()
