from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.sql import func
from datetime import datetime, timedelta

from ..database.models import Chat, Style, ChatType, Message, MessageTag, Tag, MessageThread, MessageContext
from ..config import settings
from ..services.openai_service import OpenAIService
from ..services.context_service import ContextService

router = Router()

class TestStates(StatesGroup):
    waiting_for_message = State()

def is_owner(user_id: int) -> bool:
    return user_id == settings.OWNER_ID

@router.message(Command("help"))
async def help_command(message: Message, session: AsyncSession):
    """Show help message."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    help_text = """Available commands:
/help - Show this help message
/status - Show bot status
/setmode - Enable/disable bot in chats
/set_probability <chat_id> <probability> - Set response probability
/set_importance <chat_id> <threshold> - Set importance threshold
/set_style - Set chat style
/set_threshold - Set importance threshold
/smart_mode <chat_id> <on/off> - Toggle smart mode
/list_chats - List all chats
/summ <chat_id> - Generate chat summary
/upload - Upload new training data
/refresh - Refresh style guide
/test - Test bot response
/shutdown - Global silence mode
/tag - Manage message tags
/thread - Manage message threads"""
    
    await message.answer(help_text, parse_mode=None)

@router.message(Command("status"))
async def status_command(message: Message, session: AsyncSession):
    """Show bot status with detailed statistics."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    status_text = "🤖 Bot Status:\n\n"
    
    for chat in chats:
        status_text += f"📱 {chat.title}:\n"
        status_text += f"  • Active: {'✅' if chat.is_active else '❌'}\n"
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
    """Toggle global shutdown mode."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    settings.is_shutdown = not settings.is_shutdown
    status = "enabled" if settings.is_shutdown else "disabled"
    await message.answer(f"Global shutdown mode is now {status}")

@router.message(Command("setmode"))
async def setmode_command(message: Message, session: AsyncSession):
    """Enable/disable bot in chats."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    keyboard = []
    for chat in chats:
        status = "✅" if chat.is_active else "❌"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status} {chat.title}",
                callback_data=f"toggle_chat_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select chat to toggle:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("toggle_chat_"))
async def toggle_chat(callback: CallbackQuery, session: AsyncSession):
    """Toggle chat active status."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    chat_id = int(callback.data.split("_")[2])
    chat = await session.get(Chat, chat_id)
    
    if chat:
        chat.is_active = not chat.is_active
        await session.commit()
        
        status = "✅" if chat.is_active else "❌"
        await callback.message.edit_text(
            f"Chat {chat.title} is now {'active' if chat.is_active else 'inactive'}",
            reply_markup=callback.message.reply_markup
        )

@router.message(Command("set_probability"))
async def set_probability_command(message: Message, session: AsyncSession):
    """Set response probability for chat."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    try:
        _, chat_id, probability = message.text.split()
        chat_id = int(chat_id)
        probability = float(probability)
        
        if not 0 <= probability <= 1:
            await message.answer("❌ Probability must be between 0 and 1")
            return
            
        chat = await session.get(Chat, chat_id)
        if chat:
            chat.response_probability = probability
            await session.commit()
            await message.answer(f"✅ Response probability set to {probability} for chat {chat.title}")
        else:
            await message.answer("❌ Chat not found")
    except (IndexError, ValueError):
        await message.answer("❌ Usage: /set_probability <chat_id> <probability>")

@router.message(Command("set_importance"))
async def set_importance_command(message: Message, session: AsyncSession):
    """Set importance threshold for chat."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    try:
        _, chat_id, threshold = message.text.split()
        chat_id = int(chat_id)
        threshold = float(threshold)
        
        if not 0 <= threshold <= 1:
            await message.answer("❌ Threshold must be between 0 and 1")
            return
            
        chat = await session.get(Chat, chat_id)
        if chat:
            chat.importance_threshold = threshold
            await session.commit()
            await message.answer(f"✅ Importance threshold set to {threshold} for chat {chat.title}")
        else:
            await message.answer("❌ Chat not found")
    except (IndexError, ValueError):
        await message.answer("❌ Usage: /set_importance <chat_id> <threshold>")

@router.message(Command("smart_mode"))
async def smart_mode_command(message: Message, session: AsyncSession):
    """Toggle smart mode for a chat."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    # Create inline keyboard
    keyboard = InlineKeyboardMarkup(row_width=2)
    for chat in chats:
        keyboard.add(
            InlineKeyboardButton(
                f"{'✅' if chat.smart_mode else '❌'} {chat.title}",
                callback_data=f"smart_mode_{chat.chat_id}"
            )
        )
    
    await message.answer(
        "Select a chat to toggle smart mode:",
        reply_markup=keyboard
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
    
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    if not chats:
        await message.answer("❌ No chats found")
        return
        
    text = "📋 List of chats:\n\n"
    for chat in chats:
        text += f"Chat: {chat.title} (ID: {chat.chat_id})\n"
        text += f"Active: {'✅' if chat.is_active else '❌'}\n"
        text += f"Response Probability: {chat.response_probability}\n"
        text += f"Smart Mode: {'✅' if chat.smart_mode else '❌'}\n"
        text += f"Importance Threshold: {chat.importance_threshold}\n\n"
    
    await message.answer(text, parse_mode=None)

@router.message(Command("summ"))
async def summarize_chat_command(message: Message, session: AsyncSession):
    """Generate chat summary."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    try:
        chat_id = int(message.text.split()[1])
        chat = await session.get(Chat, chat_id)
        if not chat:
            await message.answer("❌ Chat not found")
            return
            
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
            await message.answer("❌ No messages found in the last week")
            return
            
        # Generate summary
        context_service = ContextService(session)
        summary = await context_service.generate_chat_summary(messages)
        
        await message.answer(f"📊 Summary for {chat.title}:\n\n{summary}")
    except (IndexError, ValueError):
        await message.answer("❌ Usage: /summ <chat_id>")

@router.message(Command("upload"))
async def upload_command(message: Message, session: AsyncSession):
    """Upload new training data."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get messages from the last month
    month_ago = datetime.now() - timedelta(days=30)
    messages = await session.execute(
        select(Message)
        .where(Message.timestamp >= month_ago)
        .order_by(Message.timestamp)
    )
    messages = messages.scalars().all()
    
    if not messages:
        await message.answer("❌ No messages found in the last month")
        return
        
    # Format messages for training
    conversation_text = "\n".join([
        f"{'User' if msg.user_id != settings.OWNER_ID else 'Valentin'}: {msg.text}"
        for msg in messages
    ])
    
    # Refresh style
    openai_service = OpenAIService()
    new_style = await openai_service.refresh_style(conversation_text)
    
    await message.answer(f"✅ Style guide updated:\n\n{new_style}")

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
async def test_command(message: Message, state: FSMContext):
    """Test bot response to a message."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    await state.set_state(TestStates.waiting_for_message)
    await message.answer("Please send a test message:")

@router.message(TestStates.waiting_for_message)
async def process_test_message(message: Message, state: FSMContext, session: AsyncSession):
    """Process test message and generate response."""
    if message.from_user.id != settings.OWNER_ID:
        return
    
    # Get chat
    chat = await session.get(Chat, message.chat.id)
    if not chat:
        await message.answer("❌ Chat not found in database")
        await state.clear()
        return
    
    # Generate response
    try:
        response = await openai_service.generate_response(
            message.text,
            chat.chat_type,
            chat.smart_mode,
            chat.importance_threshold
        )
        await message.answer(f"🤖 Test Response:\n\n{response}")
    except Exception as e:
        await message.answer(f"❌ Error generating response: {str(e)}")
    
    await state.clear()

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

@router.message(Command("set_threshold"))
async def set_threshold_command(message: Message, session: AsyncSession):
    """Set importance threshold."""
    if message.from_user.id != settings.OWNER_ID or message.chat.type != "private":
        return
    
    # Get all chats
    chats = await session.execute(select(Chat))
    chats = chats.scalars().all()
    
    keyboard = []
    for chat in chats:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🎯 {chat.title} (current: {chat.importance_threshold:.2f})",
                callback_data=f"select_chat_threshold_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select chat to set importance threshold:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("select_chat_threshold_"))
async def select_chat_for_threshold(callback: CallbackQuery, session: AsyncSession):
    """Select chat for threshold setting."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    chat_id = int(callback.data.split("_")[3])
    
    # Create threshold selection keyboard
    keyboard = [
        [
            InlineKeyboardButton(text="0.1", callback_data=f"set_threshold_{chat_id}_0.1"),
            InlineKeyboardButton(text="0.2", callback_data=f"set_threshold_{chat_id}_0.2"),
            InlineKeyboardButton(text="0.3", callback_data=f"set_threshold_{chat_id}_0.3"),
        ],
        [
            InlineKeyboardButton(text="0.4", callback_data=f"set_threshold_{chat_id}_0.4"),
            InlineKeyboardButton(text="0.5", callback_data=f"set_threshold_{chat_id}_0.5"),
            InlineKeyboardButton(text="0.6", callback_data=f"set_threshold_{chat_id}_0.6"),
        ],
        [
            InlineKeyboardButton(text="0.7", callback_data=f"set_threshold_{chat_id}_0.7"),
            InlineKeyboardButton(text="0.8", callback_data=f"set_threshold_{chat_id}_0.8"),
            InlineKeyboardButton(text="0.9", callback_data=f"set_threshold_{chat_id}_0.9"),
        ]
    ]
    
    await callback.message.edit_text(
        "Select importance threshold for this chat:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("set_threshold_"))
async def set_chat_threshold(callback: CallbackQuery, session: AsyncSession):
    """Set chat threshold."""
    if callback.from_user.id != settings.OWNER_ID:
        return
    
    _, _, chat_id, threshold = callback.data.split("_")
    chat_id = int(chat_id)
    threshold = float(threshold)
    
    # Update chat threshold
    chat = await session.get(Chat, chat_id)
    if chat:
        chat.importance_threshold = threshold
        await session.commit()
        
        await callback.message.edit_text(
            f"Importance threshold for {chat.title} set to {threshold:.2f}",
            reply_markup=None
        ) 