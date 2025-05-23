from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings

router = Router()

@router.callback_query()
async def handle_callback(callback: CallbackQuery):
    """Handle all callback queries."""
    # Skip if callback is from bot itself
    if callback.from_user.is_bot:
        return
        
    # Skip if bot is in shutdown mode
    if settings.is_shutdown:
        return
        
    # TODO: Add callback handling logic here
    pass 