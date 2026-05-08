"""Pytest setup: ensure the project root is importable as ``src.*``."""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Минимальные значения для pydantic-settings, чтобы тесты не падали без .env.
os.environ.setdefault("BOT_TOKEN", "0:test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("OWNER_ID", "0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/test")
