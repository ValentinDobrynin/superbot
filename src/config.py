from pydantic_settings import BaseSettings
from typing import List, Optional
import os
from dotenv import load_dotenv

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
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://superbot_user:fGKUr4bbKVXRYusJMepx5GH7WrF5f706@dpg-cvm4r2je5dus73afbbo0-a.oregon-postgres.render.com/superbot")
    
    # Chat types
    CHAT_TYPES: List[str] = ["work", "friendly", "mixed"]
    
    # Global state
    is_shutdown: bool = False
    
    model_config = {
        "env_file": ".env"
    }

settings = Settings() 