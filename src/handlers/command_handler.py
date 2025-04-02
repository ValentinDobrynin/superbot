from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.sql import func
from datetime import datetime, timedelta

from ..database.models import Chat, Style, ChatType, Message, MessageTag, Tag, MessageThread, MessageContext
from ..config import settings
from ..services.openai_service import OpenAIService
from ..services.context_service import ContextService

router = Router()

def is_owner(user_id: int) -> bool:
    return user_id == settings.OWNER_ID

@router.message(Command("help"))
async def help_command(message: Message):
    if not is_owner(message.from_user.id):
        return
    
    help_text = """🤖 vAIlentin 2.0 - Available Commands:

/help - Show this help message
/status - Show bot status and settings
/list_chats - List all chats and their modes
/setmode - Enable/disable bot in chat
/set_prob - Set response probability
/smart - Toggle smart mode
/refresh - Update communication style
/set_style - Set chat style (work/friendly/mixed)
/shutdown - Global silence mode
/test <msg> - Test response to message
/summ - Generate chat summary
/upload - Upload chat dump for training
/tag - Manage message tags
/thread - Manage message threads"""
    
    await message.answer(help_text)

@router.message(Command("status"))
async def status_command(message: Message, session: AsyncSession):
    if not is_owner(message.from_user.id):
        return
    
    # Get all chats
    chat_query = select(Chat)
    result = await session.execute(chat_query)
    chats = result.scalars().all()
    
    # Get global statistics
    yesterday = datetime.utcnow() - timedelta(days=1)
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    status_text = "🤖 vAIlentin 2.0 Status:\n\n"
    status_text += f"Global Shutdown: {'✅' if settings.is_shutdown else '❌'}\n"
    
    # Get last style update time
    style_query = select(Style).order_by(Style.last_updated.desc())
    result = await session.execute(style_query)
    latest_style = result.scalar_one_or_none()
    
    if latest_style:
        time_since_update = datetime.utcnow() - latest_style.last_updated
        status_text += f"Last Style Update: {time_since_update.days}d {time_since_update.seconds//3600}h ago\n"
    
    status_text += "\n"
    
    for chat in chats:
        status_text += f"📱 {chat.title}:\n"
        status_text += f"  • Active: {'✅' if chat.is_active else '❌'}\n"
        status_text += f"  • Type: {chat.chat_type.value}\n"
        status_text += f"  • Probability: {chat.response_probability:.2%}\n"
        status_text += f"  • Smart Mode: {'✅' if chat.smart_mode else '❌'}\n"
        if chat.smart_mode:
            status_text += f"  • Importance Threshold: {chat.importance_threshold:.2f}\n"
        
        # Get weekly messages for detailed analysis
        messages_query = select(Message).where(
            Message.chat_id == chat.id,
            Message.timestamp >= week_ago
        ).order_by(Message.timestamp)
        result = await session.execute(messages_query)
        messages = result.scalars().all()
        
        if messages:
            # Message length statistics
            msg_lengths = [len(msg.text) for msg in messages]
            avg_length = sum(msg_lengths) / len(msg_lengths)
            status_text += f"  • Avg Message Length: {avg_length:.0f} chars\n"
            
            # Response time statistics
            response_times = []
            for i in range(len(messages)-1):
                if messages[i].was_responded and messages[i+1].user_id == settings.OWNER_ID:
                    delta = messages[i+1].timestamp - messages[i].timestamp
                    response_times.append(delta.total_seconds())
            if response_times:
                avg_response_time = sum(response_times) / len(response_times)
                status_text += f"  • Avg Response Time: {avg_response_time/60:.1f}m\n"
            
            # Top users statistics
            user_messages = {}
            for msg in messages:
                user_messages[msg.user_id] = user_messages.get(msg.user_id, 0) + 1
            
            top_users = sorted(user_messages.items(), key=lambda x: x[1], reverse=True)[:3]
            status_text += "  • Top Active Users:\n"
            for user_id, count in top_users:
                status_text += f"    - User {user_id}: {count} messages\n"
            
            # Day of week statistics
            dow_stats = {}
            for msg in messages:
                dow = msg.timestamp.strftime('%A')
                dow_stats[dow] = dow_stats.get(dow, 0) + 1
            
            most_active_day = max(dow_stats.items(), key=lambda x: x[1])
            status_text += f"  • Most Active Day: {most_active_day[0]} ({most_active_day[1]} messages)\n"
        
        # Get 24h statistics
        messages_24h = [msg for msg in messages if msg.timestamp >= yesterday]
        total_24h = len(messages_24h)
        responded_24h = sum(1 for msg in messages_24h if msg.was_responded)
        
        if total_24h > 0:
            response_rate_24h = responded_24h / total_24h
            status_text += f"  • 24h Stats:\n"
            status_text += f"    - Messages: {total_24h}\n"
            status_text += f"    - Responses: {responded_24h}\n"
            status_text += f"    - Rate: {response_rate_24h:.1%}\n"
        
        # Get weekly statistics
        total_week = len(messages)
        responded_week = sum(1 for msg in messages if msg.was_responded)
        
        if total_week > 0:
            response_rate_week = responded_week / total_week
            status_text += f"  • 7d Stats:\n"
            status_text += f"    - Messages: {total_week}\n"
            status_text += f"    - Responses: {responded_week}\n"
            status_text += f"    - Rate: {response_rate_week:.1%}\n"
        
        # Get message activity by hour
        hour_stats = {}
        for msg in messages:
            hour = msg.timestamp.hour
            hour_stats[hour] = hour_stats.get(hour, 0) + 1
        
        if hour_stats:
            peak_hour = max(hour_stats.items(), key=lambda x: x[1])
            status_text += f"  • Peak Activity: {peak_hour[0]:02d}:00 ({peak_hour[1]} messages)\n"
            
            # Add quiet hours (0-2 messages per hour)
            quiet_hours = [f"{h:02d}:00" for h, c in hour_stats.items() if c <= 2]
            if quiet_hours:
                status_text += f"  • Quiet Hours: {', '.join(quiet_hours)}\n"
        
        status_text += "\n"
    
    # Split message if too long
    if len(status_text) > 4000:
        parts = [status_text[i:i+4000] for i in range(0, len(status_text), 4000)]
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(status_text)

@router.message(Command("setmode"))
async def setmode_command(message: Message, session: AsyncSession):
    if not is_owner(message.from_user.id):
        return
    
    # Get all chats
    chat_query = select(Chat)
    result = await session.execute(chat_query)
    chats = result.scalars().all()
    
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
    if not is_owner(callback.from_user.id):
        return
    
    chat_id = int(callback.data.split("_")[2])
    chat_query = select(Chat).where(Chat.id == chat_id)
    result = await session.execute(chat_query)
    chat = result.scalar_one_or_none()
    
    if chat:
        chat.is_active = not chat.is_active
        await session.commit()
        
        status = "✅" if chat.is_active else "❌"
        await callback.message.edit_text(
            f"Chat {chat.title} is now {'active' if chat.is_active else 'inactive'}",
            reply_markup=callback.message.reply_markup
        )

@router.message(Command("set_prob"))
async def set_prob_command(message: Message, session: AsyncSession):
    if not is_owner(message.from_user.id):
        return
    
    keyboard = [
        [
            InlineKeyboardButton(text="10%", callback_data="set_prob_0.1"),
            InlineKeyboardButton(text="25%", callback_data="set_prob_0.25"),
        ],
        [
            InlineKeyboardButton(text="50%", callback_data="set_prob_0.5"),
            InlineKeyboardButton(text="75%", callback_data="set_prob_0.75"),
        ]
    ]
    
    await message.answer(
        "Select response probability:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("set_prob_"))
async def set_prob_callback(callback: CallbackQuery, session: AsyncSession):
    if not is_owner(callback.from_user.id):
        return
    
    prob = float(callback.data.split("_")[2])
    
    # Update all chats
    chat_query = select(Chat)
    result = await session.execute(chat_query)
    chats = result.scalars().all()
    
    for chat in chats:
        chat.response_probability = prob
    
    await session.commit()
    await callback.message.edit_text(f"Response probability set to {prob*100}%")

@router.message(Command("test"))
async def test_command(message: Message, session: AsyncSession):
    if not is_owner(message.from_user.id):
        return
    
    # Get test message
    command = message.text.split(maxsplit=1)
    if len(command) < 2:
        await message.answer("Please provide a test message: /test <message>")
        return
    
    test_message = command[1]
    
    # Get default style
    style_query = select(Style).where(Style.chat_type == ChatType.MIXED)
    result = await session.execute(style_query)
    style = result.scalar_one_or_none()
    
    if not style:
        style_prompt = "Use a balanced, professional tone with occasional emojis."
    else:
        style_prompt = style.prompt_template
    
    # Generate test response
    response = await OpenAIService.generate_response(
        test_message,
        ChatType.MIXED,
        [],
        style_prompt
    )
    
    await message.answer(response)

@router.message(Command("smart"))
async def smart_command(message: Message, session: AsyncSession):
    if not is_owner(message.from_user.id):
        return
    
    # Get all chats
    chat_query = select(Chat)
    result = await session.execute(chat_query)
    chats = result.scalars().all()
    
    keyboard = []
    for chat in chats:
        status = "✅" if chat.smart_mode else "❌"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status} {chat.title}",
                callback_data=f"toggle_smart_{chat.id}"
            )
        ])
    
    await message.answer(
        "Select chat to toggle smart mode:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("toggle_smart_"))
async def toggle_smart(callback: CallbackQuery, session: AsyncSession):
    if not is_owner(callback.from_user.id):
        return
    
    chat_id = int(callback.data.split("_")[2])
    chat_query = select(Chat).where(Chat.id == chat_id)
    result = await session.execute(chat_query)
    chat = result.scalar_one_or_none()
    
    if chat:
        chat.smart_mode = not chat.smart_mode
        await session.commit()
        
        status = "✅" if chat.smart_mode else "❌"
        await callback.message.edit_text(
            f"Smart mode for {chat.title} is now {'enabled' if chat.smart_mode else 'disabled'}",
            reply_markup=callback.message.reply_markup
        )

@router.message(Command("shutdown"))
async def shutdown_command(message: Message):
    if not is_owner(message.from_user.id):
        return
    
    settings.is_shutdown = not settings.is_shutdown
    status = "enabled" if settings.is_shutdown else "disabled"
    await message.answer(f"Global shutdown mode is now {status}")

@router.message(Command("set_style"))
async def set_style_command(message: Message, session: AsyncSession):
    if not is_owner(message.from_user.id):
        return
    
    # Get all chats
    chat_query = select(Chat)
    result = await session.execute(chat_query)
    chats = result.scalars().all()
    
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
    if not is_owner(callback.from_user.id):
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
    if not is_owner(callback.from_user.id):
        return
    
    _, _, chat_id, style = callback.data.split("_")
    chat_id = int(chat_id)
    
    # Update chat style
    chat_query = select(Chat).where(Chat.id == chat_id)
    result = await session.execute(chat_query)
    chat = result.scalar_one_or_none()
    
    if chat:
        chat.chat_type = ChatType(style)
        await session.commit()
        
        await callback.message.edit_text(
            f"Style for {chat.title} set to {style}",
            reply_markup=None
        )

@router.message(Command("set_threshold"))
async def set_threshold_command(message: Message, session: AsyncSession):
    if not is_owner(message.from_user.id):
        return
    
    # Get all chats
    chat_query = select(Chat)
    result = await session.execute(chat_query)
    chats = result.scalars().all()
    
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
    if not is_owner(callback.from_user.id):
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
    if not is_owner(callback.from_user.id):
        return
    
    _, _, chat_id, threshold = callback.data.split("_")
    chat_id = int(chat_id)
    threshold = float(threshold)
    
    # Update chat threshold
    chat_query = select(Chat).where(Chat.id == chat_id)
    result = await session.execute(chat_query)
    chat = result.scalar_one_or_none()
    
    if chat:
        chat.importance_threshold = threshold
        await session.commit()
        
        await callback.message.edit_text(
            f"Importance threshold for {chat.title} set to {threshold:.2f}",
            reply_markup=None
        )

@router.message(Command("refresh"))
async def refresh_command(message: Message, session: AsyncSession):
    if not is_owner(message.from_user.id):
        return
    
    status_message = await message.answer("🔄 Starting style refresh...")
    
    try:
        # Get all chats grouped by type
        chat_query = select(Chat)
        result = await session.execute(chat_query)
        chats = result.scalars().all()
        
        chat_types = {}
        for chat in chats:
            if chat.chat_type not in chat_types:
                chat_types[chat.chat_type] = []
            chat_types[chat.chat_type].append(chat)
        
        # Update style for each chat type
        for chat_type, type_chats in chat_types.items():
            # Get messages from all chats of this type
            chat_ids = [chat.id for chat in type_chats]
            last_refresh = datetime.utcnow() - timedelta(days=1)  # Get last 24 hours
            
            messages_query = select(Message).where(
                Message.chat_id.in_(chat_ids),
                Message.timestamp >= last_refresh
            ).order_by(Message.timestamp)
            
            result = await session.execute(messages_query)
            messages = result.scalars().all()
            
            if messages:
                # Update style
                style_guide = await OpenAIService.update_chat_style(chat_type, messages, session)
                
                # Adjust importance thresholds
                for chat in type_chats:
                    if chat.smart_mode:
                        await chat.adjust_importance_threshold(session)
                
                await status_message.edit_text(
                    f"{status_message.text}\n✅ Updated {chat_type.value} style"
                )
            else:
                await status_message.edit_text(
                    f"{status_message.text}\n⚠️ No recent messages for {chat_type.value} style"
                )
        
        await status_message.edit_text(f"{status_message.text}\n\n✨ Style refresh complete!")
        
    except Exception as e:
        await status_message.edit_text(f"{status_message.text}\n\n❌ Error: {str(e)}")

@router.message(Command("tag"))
async def tag_command(message: Message, command: CommandObject, session: AsyncSession):
    """Handle tag-related commands."""
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