from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.sql import func
from datetime import datetime, timedelta
import logging
import re

from ..database.models import Chat, Style, ChatType, Message, MessageTag, Tag, MessageThread, MessageContext
from ..config import settings
from ..services.openai_service import OpenAIService
from ..services.context_service import ContextService

router = Router()
logger = logging.getLogger(__name__)

async def update_chat_title(message: Message, chat_id: int, session: AsyncSession) -> None:
    """Update chat title from Telegram."""
    try:
        logger.info(f"Updating chat title for chat_id: {chat_id}")
        chat_info = await message.bot.get_chat(chat_id)
        logger.info(f"Got chat info from Telegram: {chat_info.title}")
        
        # Get chat from database
        query = select(Chat).where(Chat.chat_id == chat_id)
        result = await session.execute(query)
        chat = result.scalar_one_or_none()
        
        if chat:
            if chat_info.title != chat.title:
                logger.info(f"Updating chat title from '{chat.title}' to '{chat_info.title}'")
                chat.title = chat_info.title
                await session.commit()
            else:
                logger.info(f"Chat title is already up to date: {chat.title}")
        else:
            # Create new chat if it doesn't exist
            logger.info(f"Creating new chat with title: {chat_info.title}")
            chat = Chat(
                chat_id=chat_id,
                title=chat_info.title,
                is_active=True,
                is_silent=False,
                response_probability=0.5,
                importance_threshold=0.5,
                smart_mode=True,
                chat_type=ChatType.MIXED
            )
            session.add(chat)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to update chat title for chat_id {chat_id}: {e}", exc_info=True)

class TestStates(StatesGroup):
    waiting_for_chat = State()
    waiting_for_message = State()
    waiting_for_probability = State()
    waiting_for_importance = State()
    waiting_for_hours = State()

class UploadState(StatesGroup):
    waiting_for_dump = State()
    waiting_for_type = State()

def is_owner(user_id: int) -> bool:
    return user_id == settings.OWNER_ID

@router.message(Command("help"))
async def help_command(message: Message, session: AsyncSession):
    """Show help message."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    help_text = """🤖 Bot Commands:

📊 Status & Info:
/help - Show this help message
/status - Show bot status and statistics
/list_chats - List all chats with settings

📈 Analytics:
/summ - Generate chat summary

⚙️ Chat Settings:
/setmode - Toggle silent mode in chats (bot reads but doesn't respond)
/set_style - Set chat style (work/friendly/mixed)
/set_probability - Set response probability
/set_importance - Set importance threshold
/smart_mode - Toggle smart mode

🔄 Training & Style:
/upload - Upload new training data
/refresh - Refresh style guide
/test - Test bot response

🏷 Content Management:
/tag - Manage message tags
/thread - Manage message threads

🔒 System:
/shutdown - Toggle global silent mode"""
    
    await message.answer(help_text, parse_mode=None)

@router.message(Command("status"))
async def status_command(message: Message, session: AsyncSession):
    """Show bot status with detailed statistics."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    logger.info("Starting status command")
    
    # Get all chats
    chats_query = select(Chat)
    logger.info(f"Executing query: {chats_query}")
    chats_result = await session.execute(chats_query)
    chats = chats_result.scalars().all()
    logger.info(f"Found {len(chats)} chats in database")
    
    # Update chat titles
    for chat in chats:
        logger.info(f"Updating title for chat {chat.chat_id} (current title: {chat.title})")
        await update_chat_title(message, chat.chat_id, session)
    
    status_text = "🤖 Bot Status:\n\n"
    
    # Add global shutdown status
    status_text += f"🔒 Global Status: {'🔴 Shutdown' if settings.is_shutdown else '🟢 Active'}\n\n"
    
    for chat in chats:
        logger.info(f"Processing chat: {chat.title} (ID: {chat.chat_id})")
        status_text += f"📱 {chat.title}:\n"
        
        # Show both active and silent status
        if not chat.is_active:
            status_text += "  • Status: ❌ Disabled\n"
        elif chat.is_silent:
            status_text += "  • Status: 🤫 Silent Mode\n"
        else:
            status_text += "  • Status: ✅ Active\n"
            
        status_text += f"  • Type: {chat.chat_type.value if chat.chat_type else 'Not set'}\n"
        status_text += f"  • Probability: {chat.response_probability*100:.2f}%\n"
        status_text += f"  • Smart Mode: {'✅' if chat.smart_mode else '❌'}\n"
        
        # Get message statistics
        now = datetime.now()
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)
        
        # Get messages from last 24h
        day_messages = await session.execute(
            select(Message)
            .where(Message.chat_id == chat.chat_id)
            .where(Message.timestamp >= day_ago)
        )
        day_messages = day_messages.scalars().all()
        
        # Get messages from last week
        week_messages = await session.execute(
            select(Message)
            .where(Message.chat_id == chat.chat_id)
            .where(Message.timestamp >= week_ago)
        )
        week_messages = week_messages.scalars().all()
        
        # Calculate statistics
        avg_length = sum(len(m.text) for m in week_messages) / len(week_messages) if week_messages else 0
        
        # Get user activity
        user_stats = {}
        for msg in week_messages:
            user_stats[msg.user_id] = user_stats.get(msg.user_id, 0) + 1
        
        # Get day activity
        day_stats = {}
        for msg in week_messages:
            day = msg.timestamp.strftime("%A")
            day_stats[day] = day_stats.get(day, 0) + 1
        
        # Get hour activity
        hour_stats = {}
        for msg in week_messages:
            hour = msg.timestamp.strftime("%H:00")
            hour_stats[hour] = hour_stats.get(hour, 0) + 1
        
        # Add statistics to status
        status_text += f"  • Avg Message Length: {avg_length:.0f} chars\n"
        
        if user_stats:
            status_text += "  • Top Active Users:\n"
            for user_id, count in sorted(user_stats.items(), key=lambda x: x[1], reverse=True)[:3]:
                status_text += f"    - User {user_id}: {count} messages\n"
        
        if day_stats:
            most_active_day = max(day_stats.items(), key=lambda x: x[1])
            status_text += f"  • Most Active Day: {most_active_day[0]} ({most_active_day[1]} messages)\n"
        
        # 24h stats
        day_responses = sum(1 for m in day_messages if m.is_bot)
        day_rate = (day_responses / len(day_messages) * 100) if day_messages else 0
        status_text += "  • 24h Stats:\n"
        status_text += f"    - Messages: {len(day_messages)}\n"
        status_text += f"    - Responses: {day_responses}\n"
        status_text += f"    - Rate: {day_rate:.1f}%\n"
        
        # 7d stats
        week_responses = sum(1 for m in week_messages if m.is_bot)
        week_rate = (week_responses / len(week_messages) * 100) if week_messages else 0
        status_text += "  • 7d Stats:\n"
        status_text += f"    - Messages: {len(week_messages)}\n"
        status_text += f"    - Responses: {week_responses}\n"
        status_text += f"    - Rate: {week_rate:.1f}%\n"
        
        if hour_stats:
            peak_hour = max(hour_stats.items(), key=lambda x: x[1])
            quiet_hour = min(hour_stats.items(), key=lambda x: x[1])
            status_text += f"  • Peak Activity: {peak_hour[0]} ({peak_hour[1]} messages)\n"
            status_text += f"  • Quiet Hours: {quiet_hour[0]}\n"
        
        status_text += "\n"
    
    await message.answer(status_text, parse_mode=None)

@router.message(Command("shutdown"))
async def shutdown_command(message: Message, session: AsyncSession):
    """Toggle global silent mode (sets all chats to silent mode)."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    settings.is_shutdown = not settings.is_shutdown
    
    if settings.is_shutdown:
        # Set all chats to silent mode
        chats = await session.execute(select(Chat))
        chats = chats.scalars().all()
        for chat in chats:
            chat.is_silent = True
        await session.commit()
        
        await message.answer(
            "🔴 Global silent mode enabled\n"
            "ℹ️ All chats are now in silent mode (bot reads but doesn't respond)",
            parse_mode=None
        )
    else:
        await message.answer(
            "🟢 Global silent mode disabled\n"
            "ℹ️ Chats will return to their previous state",
            parse_mode=None
        )

@router.message(Command("setmode"))
async def setmode_command(message: Message, session: AsyncSession):
    """Toggle silent mode in chats (bot reads but doesn't respond)."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    # Update chat titles
    for chat in chats:
        await update_chat_title(message, chat.chat_id, session)
    
    keyboard = []
    for chat in chats:
        status = "🔇" if chat.is_silent else "🔊"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status} {chat.title}",
                callback_data=f"toggle_silent_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select chat to toggle silent mode (🔇 = silent mode):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(lambda c: c.data.startswith("toggle_silent_"))
async def process_toggle_silent(callback: CallbackQuery, session: AsyncSession):
    """Process toggle silent mode callback."""
    if callback.from_user.id != settings.OWNER_ID:
        await callback.answer("Only the owner can toggle silent mode", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[2])
    chat = await session.get(Chat, chat_id)
    
    if chat:
        chat.is_silent = not chat.is_silent
        await session.commit()
        
        # Update button text
        status = "🔇" if chat.is_silent else "🔊"
        keyboard = callback.message.reply_markup.inline_keyboard
        for row in keyboard:
            for button in row:
                if button.callback_data == callback.data:
                    button.text = f"{status} {chat.title}"
                    break
        
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer(f"Silent mode {'enabled' if chat.is_silent else 'disabled'} for {chat.title}")
    else:
        await callback.answer("Chat not found", show_alert=True)

@router.message(Command("set_probability"))
async def set_probability_command(message: Message, session: AsyncSession):
    """Set response probability for a chat."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    # Update chat titles
    for chat in chats:
        await update_chat_title(message, chat.chat_id, session)
    
    keyboard = []
    for chat in chats:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🎯 {chat.title} ({chat.response_probability*100:.0f}%)",
                callback_data=f"select_chat_prob_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select chat to set response probability:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("select_chat_prob_"))
async def select_chat_for_probability(callback: CallbackQuery, session: AsyncSession):
    """Select chat for probability setting."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    chat_id = int(callback.data.split("_")[3])
    
    # Create probability selection keyboard
    keyboard = [
        [
            InlineKeyboardButton(
                text="25%",
                callback_data=f"set_prob_{chat_id}_0.25"
            ),
            InlineKeyboardButton(
                text="50%",
                callback_data=f"set_prob_{chat_id}_0.5"
            )
        ],
        [
            InlineKeyboardButton(
                text="75%",
                callback_data=f"set_prob_{chat_id}_0.75"
            ),
            InlineKeyboardButton(
                text="100%",
                callback_data=f"set_prob_{chat_id}_1.0"
            )
        ],
        [
            InlineKeyboardButton(
                text="Custom",
                callback_data=f"custom_prob_{chat_id}"
            )
        ]
    ]
    
    await callback.message.edit_text(
        "Select response probability:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("set_prob_"))
async def set_chat_probability(callback: CallbackQuery, session: AsyncSession):
    """Set chat probability."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    _, _, chat_id, prob = callback.data.split("_")
    chat_id = int(chat_id)
    probability = float(prob)
    
    # Update chat probability
    chat = await session.get(Chat, chat_id)
    if chat:
        chat.response_probability = probability
        await session.commit()
        
        await callback.message.edit_text(
            f"Response probability for {chat.title} set to {probability*100:.0f}%",
            reply_markup=None
        )

@router.callback_query(F.data.startswith("custom_prob_"))
async def custom_probability(callback: CallbackQuery, state: FSMContext):
    """Handle custom probability input."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    chat_id = int(callback.data.split("_")[2])
    await state.set_state(TestStates.waiting_for_probability)
    await state.update_data(chat_id=chat_id)
    
    await callback.message.edit_text(
        "Enter custom probability (0-100):",
        reply_markup=None
    )

@router.message(TestStates.waiting_for_probability)
async def process_custom_probability(message: Message, state: FSMContext, session: AsyncSession):
    """Process custom probability input."""
    if message.from_user.id != settings.OWNER_ID:
        return
    
    try:
        probability = float(message.text) / 100
        if not 0 <= probability <= 1:
            await message.answer("❌ Probability must be between 0 and 100")
            await state.clear()
            return
            
        data = await state.get_data()
        chat_id = data.get("chat_id")
        
        chat = await session.get(Chat, chat_id)
        if chat:
            chat.response_probability = probability
            await session.commit()
            await message.answer(f"✅ Response probability set to {probability*100:.0f}% for {chat.title}")
        else:
            await message.answer("❌ Chat not found")
    except ValueError:
        await message.answer("❌ Please enter a valid number")
    
    await state.clear()

@router.message(Command("set_importance"))
async def set_importance_command(message: Message, session: AsyncSession):
    """Set importance threshold for a chat."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    # Update chat titles
    for chat in chats:
        await update_chat_title(message, chat.chat_id, session)
    
    keyboard = []
    for chat in chats:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🎯 {chat.title} ({chat.importance_threshold*100:.0f}%)",
                callback_data=f"select_chat_imp_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select chat to set importance threshold:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("select_chat_imp_"))
async def select_chat_for_importance(callback: CallbackQuery, session: AsyncSession):
    """Select chat for importance setting."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    chat_id = int(callback.data.split("_")[3])
    
    # Create importance selection keyboard
    keyboard = [
        [
            InlineKeyboardButton(
                text="25%",
                callback_data=f"set_imp_{chat_id}_0.25"
            ),
            InlineKeyboardButton(
                text="50%",
                callback_data=f"set_imp_{chat_id}_0.5"
            )
        ],
        [
            InlineKeyboardButton(
                text="75%",
                callback_data=f"set_imp_{chat_id}_0.75"
            ),
            InlineKeyboardButton(
                text="100%",
                callback_data=f"set_imp_{chat_id}_1.0"
            )
        ],
        [
            InlineKeyboardButton(
                text="Custom",
                callback_data=f"custom_imp_{chat_id}"
            )
        ]
    ]
    
    await callback.message.edit_text(
        "Select importance threshold:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("set_imp_"))
async def set_chat_importance(callback: CallbackQuery, session: AsyncSession):
    """Set chat importance threshold."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    _, _, chat_id, imp = callback.data.split("_")
    chat_id = int(chat_id)
    importance = float(imp)
    
    # Update chat importance
    chat = await session.get(Chat, chat_id)
    if chat:
        chat.importance_threshold = importance
        await session.commit()
        
        await callback.message.edit_text(
            f"Importance threshold for {chat.title} set to {importance*100:.0f}%",
            reply_markup=None
        )

@router.callback_query(F.data.startswith("custom_imp_"))
async def custom_importance(callback: CallbackQuery, state: FSMContext):
    """Handle custom importance input."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    chat_id = int(callback.data.split("_")[2])
    await state.set_state(TestStates.waiting_for_importance)
    await state.update_data(chat_id=chat_id)
    
    await callback.message.edit_text(
        "Enter custom importance threshold (0-100):",
        reply_markup=None
    )

@router.message(TestStates.waiting_for_importance)
async def process_custom_importance(message: Message, state: FSMContext, session: AsyncSession):
    """Process custom importance input."""
    if message.from_user.id != settings.OWNER_ID:
        return
    
    try:
        importance = float(message.text) / 100
        if not 0 <= importance <= 1:
            await message.answer("❌ Importance must be between 0 and 100")
            await state.clear()
            return
            
        data = await state.get_data()
        chat_id = data.get("chat_id")
        
        chat = await session.get(Chat, chat_id)
        if chat:
            chat.importance_threshold = importance
            await session.commit()
            await message.answer(f"✅ Importance threshold set to {importance*100:.0f}% for {chat.title}")
        else:
            await message.answer("❌ Chat not found")
    except ValueError:
        await message.answer("❌ Please enter a valid number")
    
    await state.clear()

@router.message(Command("smart_mode"))
async def smart_mode_command(message: Message, session: AsyncSession):
    """Toggle smart mode for a chat."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    # Update chat titles
    for chat in chats:
        await update_chat_title(message, chat.chat_id, session)
    
    # Create inline keyboard
    keyboard = []
    for chat in chats:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{'✅' if chat.smart_mode else '❌'} {chat.title}",
                callback_data=f"smart_mode_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select a chat to toggle smart mode:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(lambda c: c.data.startswith("smart_mode_"))
async def process_smart_mode_callback(callback_query: CallbackQuery, session: AsyncSession):
    """Process smart mode toggle callback."""
    if callback_query.from_user.id != settings.OWNER_ID:
        await callback_query.answer("You are not authorized to use this command.")
        return
    
    chat_id = int(callback_query.data.split("_")[2])
    
    # Get chat
    chat = await session.get(Chat, chat_id)
    if not chat:
        await callback_query.answer("Chat not found.")
        return
    
    # Toggle smart mode
    chat.smart_mode = not chat.smart_mode
    await session.commit()
    
    # Update button text
    keyboard = callback_query.message.reply_markup
    for row in keyboard.inline_keyboard:
        for button in row:
            if button.callback_data == callback_query.data:
                button.text = f"{'✅' if chat.smart_mode else '❌'} {chat.title}"
    
    await callback_query.message.edit_reply_markup(reply_markup=keyboard)
    await callback_query.answer(f"Smart mode {'enabled' if chat.smart_mode else 'disabled'} for {chat.title}")

@router.message(Command("list_chats"))
async def list_chats_command(message: Message, session: AsyncSession):
    """List all chats."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    logger.info("Starting list_chats command")
    
    # Get all chats
    chats_query = select(Chat)
    logger.info(f"Executing query: {chats_query}")
    chats_result = await session.execute(chats_query)
    chats = chats_result.scalars().all()
    logger.info(f"Found {len(chats)} chats in database")
    
    # Update chat titles
    for chat in chats:
        logger.info(f"Updating title for chat {chat.chat_id} (current title: {chat.title})")
        await update_chat_title(message, chat.chat_id, session)
    
    if not chats:
        await message.answer("❌ No chats found")
        return
        
    text = "📋 List of chats:\n\n"
    for chat in chats:
        # Refresh chat object from database to get updated title
        chat = await session.get(Chat, chat.id)
        logger.info(f"Refreshed chat from database: {chat.title} (ID: {chat.chat_id})")
        text += f"Chat: {chat.title} (ID: {chat.chat_id})\n"
        text += f"Silent Mode: {'🔇' if chat.is_silent else '🔊'}\n"
        text += f"Response Probability: {chat.response_probability*100:.0f}%\n"
        text += f"Smart Mode: {'✅' if chat.smart_mode else '❌'}\n"
        text += f"Importance Threshold: {chat.importance_threshold*100:.0f}%\n\n"
    
    await message.answer(text, parse_mode=None)

@router.message(Command("summ"))
async def summarize_chat_command(message: Message, session: AsyncSession):
    """Generate chat summary."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    # Update chat titles
    for chat in chats:
        await update_chat_title(message, chat.chat_id, session)
    
    keyboard = []
    for chat in chats:
        keyboard.append([
            InlineKeyboardButton(
                text=f"📊 {chat.title}",
                callback_data=f"summ_chat_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select chat to generate summary:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(lambda c: c.data.startswith("summ_chat_"))
async def select_summary_period(callback: CallbackQuery, session: AsyncSession):
    """Select summary period."""
    if callback.from_user.id != settings.OWNER_ID:
        await callback.answer("Only the owner can generate summaries", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[2])
    chat = await session.get(Chat, chat_id)
    
    if not chat:
        await callback.answer("Chat not found", show_alert=True)
        return
    
    # Create period selection keyboard
    keyboard = [
        [
            InlineKeyboardButton(
                text="🔄 Since last summary",
                callback_data=f"summ_period_{chat_id}_last"
            )
        ],
        [
            InlineKeyboardButton(
                text="📅 Last 24 hours",
                callback_data=f"summ_period_{chat_id}_24h"
            )
        ],
        [
            InlineKeyboardButton(
                text="⏰ Custom hours",
                callback_data=f"summ_period_{chat_id}_custom"
            )
        ]
    ]
    
    await callback.message.edit_text(
        f"Select summary period for {chat.title}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(lambda c: c.data.startswith("summ_period_"))
async def generate_summary(callback: CallbackQuery, session: AsyncSession):
    """Generate summary for selected period."""
    if callback.from_user.id != settings.OWNER_ID:
        await callback.answer("Only the owner can generate summaries", show_alert=True)
        return
    
    _, _, chat_id, period_type = callback.data.split("_")
    chat_id = int(chat_id)
    chat = await session.get(Chat, chat_id)
    
    if not chat:
        await callback.answer("Chat not found", show_alert=True)
        return
    
    # Update chat title
    await update_chat_title(callback.message, chat_id, session)
    
    # Get messages based on period type
    now = datetime.now()
    if period_type == "last":
        # Use last summary timestamp if available, otherwise use 24h
        start_time = chat.last_summary_timestamp or (now - timedelta(days=1))
    elif period_type == "24h":
        start_time = now - timedelta(days=1)
    elif period_type == "custom":
        # Store chat_id in state for custom hours input
        await state.set_state(TestStates.waiting_for_hours)
        await state.update_data(chat_id=chat_id)
        await callback.message.edit_text(
            "Enter number of hours for summary:",
            reply_markup=None
        )
        return
    
    messages = await session.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .where(Message.timestamp >= start_time)
        .order_by(Message.timestamp)
    )
    messages = messages.scalars().all()
    
    if not messages:
        await callback.answer("No messages found for selected period", show_alert=True)
        return
    
    # Generate summary
    context_service = ContextService(session)
    summary = await context_service.generate_chat_summary(messages)
    
    # Update last summary timestamp
    chat.last_summary_timestamp = now
    await session.commit()
    
    await callback.message.answer(f"📊 Summary for {chat.title}:\n\n{summary}")

@router.message(TestStates.waiting_for_hours)
async def process_custom_hours(message: Message, state: FSMContext, session: AsyncSession):
    """Process custom hours input for summary."""
    if message.from_user.id != settings.OWNER_ID:
        return
    
    try:
        hours = float(message.text)
        if hours <= 0:
            await message.answer("❌ Hours must be positive")
            await state.clear()
            return
            
        data = await state.get_data()
        chat_id = data.get("chat_id")
        
        chat = await session.get(Chat, chat_id)
        if not chat:
            await message.answer("❌ Chat not found")
            await state.clear()
            return
        
        # Update chat title
        await update_chat_title(message, chat_id, session)
        
        # Get messages for specified hours
        start_time = datetime.now() - timedelta(hours=hours)
        messages = await session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .where(Message.timestamp >= start_time)
            .order_by(Message.timestamp)
        )
        messages = messages.scalars().all()
        
        if not messages:
            await message.answer("❌ No messages found for selected period")
            await state.clear()
            return
        
        # Generate summary
        context_service = ContextService(session)
        summary = await context_service.generate_chat_summary(messages)
        
        # Update last summary timestamp
        chat.last_summary_timestamp = datetime.now()
        await session.commit()
        
        await message.answer(f"📊 Summary for {chat.title} (last {hours:.1f} hours):\n\n{summary}")
    except ValueError:
        await message.answer("❌ Please enter a valid number")
    
    await state.clear()

@router.message(Command("upload"))
async def upload_command(message: Message, session: AsyncSession):
    """Handle chat dump upload for style training."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Create keyboard for chat type selection
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👔 Рабочий", callback_data="upload_work"),
            InlineKeyboardButton(text="😊 Дружеский", callback_data="upload_friendly")
        ],
        [
            InlineKeyboardButton(text="🔄 Смешанный", callback_data="upload_mixed")
        ]
    ])
    
    await message.answer(
        "📝 Загрузите дамп переписки одним из способов:\n\n"
        "1️⃣ Отправьте текстовое сообщение в формате:\n"
        "[Дата] Имя пользователя: Сообщение\n"
        "[Дата] Имя пользователя: Сообщение\n\n"
        "2️⃣ Отправьте файл:\n"
        "- Текстовый файл (.txt) с дампом переписки\n"
        "- JSON-файл с экспортом переписки из Telegram\n\n"
        "Пример текстового формата:\n"
        "[2024-01-15 14:30] Valentin: Привет, как дела?\n"
        "[2024-01-15 14:31] John: Все хорошо, спасибо!\n\n"
        "Выберите тип переписки:",
        reply_markup=keyboard
    )

@router.callback_query(lambda c: c.data.startswith("upload_"))
async def process_upload_type(callback: CallbackQuery, state: FSMContext):
    """Process chat type selection for upload."""
    chat_type = callback.data.split("_")[1]
    await state.update_data(chat_type=chat_type)
    await state.set_state(UploadState.waiting_for_dump)
    await callback.message.edit_text(
        "📤 Теперь отправьте дамп переписки текстовым сообщением или файлом.\n"
        "Поддерживаемые форматы: .txt, .json\n"
        "Убедитесь, что формат соответствует примеру."
    )

@router.message(UploadState.waiting_for_dump)
async def process_dump_upload(message: Message, state: FSMContext, session: AsyncSession):
    """Process chat dump upload and update style."""
    data = await state.get_data()
    chat_type = data.get("chat_type")
    
    try:
        # Get text content from message or file
        if message.document:
            # Download file
            file = await message.bot.get_file(message.document.file_id)
            file_path = await message.bot.download_file(file.file_path)
            file_content = file_path.read().decode('utf-8')
            
            if message.document.mime_type == "application/json":
                # Parse JSON
                import json
                json_data = json.loads(file_content)
                conversation_text = []
                
                # Handle different JSON formats
                if isinstance(json_data, list):
                    # Telegram export format
                    for msg in json_data:
                        if 'text' in msg and 'from' in msg:
                            username = msg['from'].get('first_name', 'Unknown')
                            if username.lower() == message.from_user.first_name.lower():
                                username = "Valentin"
                            conversation_text.append(f"{username}: {msg['text']}")
                else:
                    # Custom JSON format
                    for msg in json_data.get('messages', []):
                        if 'text' in msg and 'from' in msg:
                            username = msg['from'].get('name', 'Unknown')
                            if username.lower() == message.from_user.first_name.lower():
                                username = "Valentin"
                            conversation_text.append(f"{username}: {msg['text']}")
                
                text_content = "\n".join(conversation_text)
            else:
                # Text file
                text_content = file_content
        else:
            # Text message
            text_content = message.text
        
        if not text_content:
            await message.answer("❌ Не удалось получить содержимое дампа. Проверьте формат.")
            return
        
        # Parse the dump
        lines = text_content.split("\n")
        conversation_text = []
        
        for line in lines:
            if not line.strip():
                continue
                
            # Extract message content
            match = re.match(r'\[(.*?)\] (.*?): (.*)', line)
            if match:
                timestamp, username, text = match.groups()
                # Replace owner's name with "Valentin" for consistency
                if username.lower() == message.from_user.first_name.lower():
                    username = "Valentin"
                conversation_text.append(f"{username}: {text}")
            else:
                # Handle non-formatted lines (from JSON)
                conversation_text.append(line)
        
        if not conversation_text:
            await message.answer("❌ Не удалось извлечь сообщения из дампа. Проверьте формат.")
            return
        
        # Format for training
        formatted_text = "\n".join(conversation_text)
        
        # Update style
        openai_service = OpenAIService()
        new_style = await openai_service.refresh_style(formatted_text, chat_type=chat_type)
        
        await message.answer(
            f"✅ Стиль успешно обновлен для типа '{chat_type}':\n\n"
            f"{new_style}"
        )
        
    except Exception as e:
        logger.error(f"Error processing dump: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при обработке дампа. "
            "Проверьте формат и попробуйте снова."
        )
    
    await state.clear()

@router.message(Command("refresh"))
async def refresh_command(message: Message, session: AsyncSession):
    """Refresh style guide."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all messages
    messages = await session.execute(select(Message).order_by(Message.timestamp))
    messages = messages.scalars().all()
    
    if not messages:
        await message.answer("❌ No messages found")
        return
        
    # Format messages for training
    conversation_text = "\n".join([
        f"{'User' if msg.user_id != settings.OWNER_ID else 'Valentin'}: {msg.text}"
        for msg in messages
    ])
    
    # Refresh style
    openai_service = OpenAIService()
    new_style = await openai_service.refresh_style(conversation_text)
    
    await message.answer(f"✅ Style guide refreshed:\n\n{new_style}")

@router.message(Command("test"))
async def test_command(message: Message, session: AsyncSession):
    """Test bot functionality in a specific chat."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    # Update chat titles
    for chat in chats:
        await update_chat_title(message, chat.chat_id, session)
    
    keyboard = []
    for chat in chats:
        keyboard.append([
            InlineKeyboardButton(
                text=f"📱 {chat.title}",
                callback_data=f"test_chat_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select chat to test bot functionality:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(lambda c: c.data.startswith("test_chat_"))
async def process_test_chat(callback: CallbackQuery, session: AsyncSession):
    """Process test chat selection."""
    if callback.from_user.id != settings.OWNER_ID:
        await callback.answer("Only the owner can test bot functionality", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[2])
    chat = await session.get(Chat, chat_id)
    
    if chat:
        # Get chat info from Telegram
        try:
            chat_info = await callback.bot.get_chat(chat_id)
            title = chat_info.title
        except Exception as e:
            logger.error(f"Failed to get chat info: {e}", exc_info=True)
            title = chat.title or "Unknown Chat"
        
        # Update chat title if needed
        if title != chat.title:
            chat.title = title
            await session.commit()
        
        # Send test message
        await callback.bot.send_message(
            chat_id=chat_id,
            text="🤖 Test message from bot"
        )
        
        await callback.answer(f"Test message sent to {chat.title}")
    else:
        await callback.answer("Chat not found", show_alert=True)

@router.message(Command("tag"))
async def tag_command(message: Message, command: CommandObject, session: AsyncSession):
    """Handle tag-related commands."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    if not command.args:
        await message.answer(
            "Usage:\n"
            "/tag add <message_id> <tag> - Add tag to message\n"
            "/tag remove <message_id> <tag> - Remove tag from message\n"
            "/tag list <message_id> - List message tags\n"
            "/tag stats - Show tag statistics"
        )
        return

    args = command.args.split()
    if not args:
        return

    context_service = ContextService(session)
    action = args[0].lower()

    if action == "stats":
        # Get tag statistics
        query = select(MessageTag).join(Tag)
        result = await session.execute(query)
        tags = result.scalars().all()

        tag_stats = {}
        for mt in tags:
            tag_stats[mt.tag.name] = tag_stats.get(mt.tag.name, 0) + 1

        if not tag_stats:
            await message.answer("No tags found.")
            return

        # Format statistics
        stats_text = "📊 Tag Statistics:\n\n"
        for tag, count in sorted(tag_stats.items(), key=lambda x: x[1], reverse=True):
            stats_text += f"{tag}: {count} uses\n"

        await message.answer(stats_text)
        return

    if len(args) < 2:
        await message.answer("Please provide message_id")
        return

    try:
        target_msg_id = int(args[1])
    except ValueError:
        await message.answer("Invalid message ID")
        return

    # Get target message
    query = select(Message).where(
        Message.chat_id == message.chat.id,
        Message.message_id == target_msg_id
    )
    result = await session.execute(query)
    target_msg = result.scalar_one_or_none()

    if not target_msg:
        await message.answer("Message not found")
        return

    if action == "list":
        if not target_msg.tags:
            await message.answer("No tags for this message")
            return

        tags_text = "🏷 Tags:\n"
        for mt in target_msg.tags:
            tags_text += f"#{mt.tag.name}"
            if mt.is_auto:
                tags_text += " (auto)"
            tags_text += "\n"

        await message.answer(tags_text)

    elif action == "add" and len(args) >= 3:
        tag_name = args[2].strip("#")  # Remove # if present
        tags = await context_service.get_or_create_tags([tag_name])
        await context_service.add_tags_to_message(target_msg, tags, is_auto=False)
        await message.answer(f"Added tag #{tag_name} to message {target_msg_id}")

    elif action == "remove" and len(args) >= 3:
        tag_name = args[2].strip("#")
        # Find and remove tag
        for mt in target_msg.tags:
            if mt.tag.name == tag_name:
                await session.delete(mt)
                await session.commit()
                await message.answer(f"Removed tag #{tag_name} from message {target_msg_id}")
                return
        await message.answer(f"Tag #{tag_name} not found on message {target_msg_id}")

    else:
        await message.answer("Invalid command format")

@router.message(Command("thread"))
async def thread_command(message: Message, command: CommandObject, session: AsyncSession):
    """Handle thread-related commands."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    if not command.args:
        await message.answer(
            "Usage:\n"
            "/thread info - Show current thread info\n"
            "/thread list - List active threads\n"
            "/thread new <topic> - Start new thread\n"
            "/thread close - Close current thread"
        )
        return

    context_service = ContextService(session)
    args = command.args.split()
    action = args[0].lower()

    if action == "list":
        # List active threads
        query = select(MessageThread).where(
            MessageThread.chat_id == message.chat.id,
            MessageThread.is_active == True
        )
        result = await session.execute(query)
        threads = result.scalars().all()

        if not threads:
            await message.answer("No active threads")
            return

        text = "🧵 Active Threads:\n\n"
        for thread in threads:
            # Get thread stats
            stats = await context_service.get_thread_stats(thread)
            
            text += f"📌 {thread.topic}\n"
            if stats:
                text += f"Messages: {stats['total_messages']}\n"
                text += f"Users: {stats['unique_users']}\n"
                text += f"Duration: {stats['duration_hours']:.1f}h\n"
                if stats['top_tags']:
                    text += "Top tags: " + ", ".join(f"#{tag}" for tag, _ in stats['top_tags']) + "\n"
            text += "\n"

        await message.answer(text)

    elif action == "info":
        # Get current thread
        thread = await context_service.get_or_create_thread(message.chat.id)
        
        # Get thread context
        query = select(MessageContext).where(MessageContext.thread_id == thread.id)
        result = await session.execute(query)
        context = result.scalar_one_or_none()

        if not context:
            await message.answer("No context available for current thread")
            return

        # Get thread stats
        stats = await context_service.get_thread_stats(thread)

        # Get related threads
        related = await context_service.find_related_threads(thread)

        text = f"🧵 Thread: {thread.topic}\n\n"
        text += f"Context Summary:\n{context.context_summary}\n\n"
        
        if stats:
            text += "📊 Statistics:\n"
            text += f"Messages: {stats['total_messages']}\n"
            text += f"Users: {stats['unique_users']}\n"
            text += f"Avg Length: {stats['avg_message_length']:.0f} chars\n"
            text += f"Rate: {stats['messages_per_hour']:.1f} msgs/hour\n"
            if stats['top_tags']:
                text += "Top tags: " + ", ".join(f"#{tag}" for tag, _ in stats['top_tags']) + "\n"
            text += "\n"

        if related:
            text += "🔗 Related Threads:\n"
            for rel in related:
                text += f"- {rel.topic}\n"

        await message.answer(text)

    elif action == "new" and len(args) > 1:
        # Start new thread
        topic = " ".join(args[1:])
        thread = await context_service.get_or_create_thread(message.chat.id, topic)
        await message.answer(f"Started new thread: {topic}")

    elif action == "close":
        # Close current thread
        thread = await context_service.get_or_create_thread(message.chat.id)
        thread.is_active = False
        await session.commit()
        await message.answer(f"Closed thread: {thread.topic}")

    else:
        await message.answer("Invalid command format")

@router.message(Command("set_style"))
async def set_style_command(message: Message, session: AsyncSession):
    """Set chat style."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    keyboard = []
    for chat in chats:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🎯 {chat.title}",
                callback_data=f"select_chat_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select chat to set style:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("select_chat_"))
async def select_chat_for_style(callback: CallbackQuery, session: AsyncSession):
    """Select chat for style setting."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    chat_id = int(callback.data.split("_")[2])
    
    # Create style selection keyboard
    keyboard = [
        [
            InlineKeyboardButton(
                text="💼 Work",
                callback_data=f"set_style_{chat_id}_work"
            ),
            InlineKeyboardButton(
                text="😊 Friendly",
                callback_data=f"set_style_{chat_id}_friendly"
            )
        ],
        [
            InlineKeyboardButton(
                text="🤝 Mixed",
                callback_data=f"set_style_{chat_id}_mixed"
            )
        ]
    ]
    
    await callback.message.edit_text(
        "Select style for this chat:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("set_style_"))
async def set_chat_style(callback: CallbackQuery, session: AsyncSession):
    """Set chat style."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    _, _, chat_id, style = callback.data.split("_")
    chat_id = int(chat_id)
    
    # Update chat style
    chat = await session.get(Chat, chat_id)
    if chat:
        chat.chat_type = ChatType(style)
        await session.commit()
        
        await callback.message.edit_text(
            f"Style for {chat.title} set to {style}",
            reply_markup=None
        )

@router.callback_query(F.data.startswith("summ_chat_"))
async def summarize_chat(callback: CallbackQuery, session: AsyncSession):
    """Generate chat summary."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    chat_id = int(callback.data.split("_")[2])
    chat = await session.get(Chat, chat_id)
    if not chat:
        await callback.answer("❌ Chat not found")
        return
    
    # Update chat title
    await update_chat_title(callback.message, chat_id, session)
    
    # Get messages from the last week
    week_ago = datetime.now() - timedelta(days=7)
    messages = await session.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .where(Message.timestamp >= week_ago)
        .order_by(Message.timestamp)
    )
    messages = messages.scalars().all()
    
    if not messages:
        await callback.answer("❌ No messages found in the last week")
        return
    
    # Generate summary
    context_service = ContextService(session)
    summary = await context_service.generate_chat_summary(messages)
    
    await callback.message.answer(f"📊 Summary for {chat.title}:\n\n{summary}") 