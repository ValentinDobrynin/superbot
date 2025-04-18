from openai import AsyncOpenAI
from ..config import settings
from ..database.models import ChatType, Style, DBMessage, Chat
import random
import asyncio
import numpy as np
from typing import List, Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY,
    timeout=60.0  # Set a reasonable timeout
)

class OpenAIService:
    @staticmethod
    async def get_style_for_chat_type(session, chat_type: ChatType) -> str:
        """Get style guide for chat type from database."""
        style = await session.execute(
            select(Style).where(Style.chat_type == chat_type)
        )
        style = style.scalar_one_or_none()
        return style.prompt_template if style else ""

    @staticmethod
    async def generate_response(
        message: str,
        chat_type: ChatType,
        context_messages: list,
        session: AsyncSession
    ) -> str:
        # Add random delay to simulate human behavior
        delay = random.uniform(settings.MIN_RESPONSE_DELAY, settings.MAX_RESPONSE_DELAY)
        await asyncio.sleep(delay)
        
        # Get style from database
        style_prompt = await OpenAIService.get_style_for_chat_type(session, chat_type)
        
        # Prepare context from recent messages
        # Все сообщения считаем сообщениями от пользователей
        context = "\n".join([f"User: {msg['text']}" for msg in context_messages])
        
        # Construct the prompt
        prompt = f"""You are simulating a Telegram user named Valentin. Based on the user's historical messages and reactions in the chat, you have learned their communication style, tone, frequency of replies, and typical triggers for engaging in conversation.

Your job is to generate replies that imitate Valentin as closely as possible.
When composing a response, always consider:

1. The style and tone Valentin typically uses (casual, professional, humorous, sarcastic, etc.).
2. How often he replies and in what situations (e.g., when he's tagged, when a topic interests him, or when someone asks a direct question).
3. His preferred formats (e.g., emojis, short dry comments, voice of authority, etc.).

You are not ChatGPT — you are 🤖 ~ Valentin, responding as if you're him. Do not explain or over-elaborate. Stay in character.

If no reply is appropriate based on Valentin's history and style, stay silent.

Chat Type: {chat_type.value}
Previous conversation:
{context}

Current message: {message}

Style guidelines from training:
{style_prompt}

Respond in Valentin's style. Keep the response concise and natural. Use appropriate emojis and informal language if it matches the style.
Prefix your response with "🤖 ~ Valentin: "

Response:"""
        
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are Valentin's AI assistant, mimicking their communication style."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=150
        )
        
        return response.choices[0].message.content.strip()

    @staticmethod
    async def chat_completion(prompt: str, temperature: float = 0.3) -> str:
        """Generic chat completion method."""
        try:
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=500
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if "insufficient_quota" in str(e):
                return "⚠️ OpenAI API quota exceeded. Please check your billing details."
            elif "rate_limit" in str(e).lower():
                return "⚠️ OpenAI API rate limit reached. Please try again later."
            else:
                return f"⚠️ Error: {str(e)}"

    @staticmethod
    async def get_embedding(text: str) -> List[float]:
        """Get embedding vector for text."""
        response = await client.embeddings.create(
            model="text-embedding-ada-002",
            input=text
        )
        return response.data[0].embedding

    @staticmethod
    async def calculate_similarity(text1: str, text2: str) -> float:
        """Calculate cosine similarity between two texts."""
        # Get embeddings
        emb1 = await OpenAIService.get_embedding(text1)
        emb2 = await OpenAIService.get_embedding(text2)
        
        # Convert to numpy arrays
        vec1 = np.array(emb1)
        vec2 = np.array(emb2)
        
        # Calculate cosine similarity
        similarity = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
        return float(similarity)

    @staticmethod
    async def analyze_message_importance(message: str) -> float:
        """Analyze message importance for smart mode."""
        prompt = f"""You are an assistant trained to evaluate the importance of a message in a group chat context. Your goal is to return a **single numeric value from 0.0 to 1.0** representing how important this message is for the user to respond to.

### Scoring Guidelines:

- **1.0 — Critical**
  - Message directly asks the user a question or requests an action
  - Mentions the user explicitly (e.g., @Valentin)
  - Relates to urgent decisions, deadlines, emergencies, or personal matters

- **0.8 — High Importance**
  - Asks for advice, help, or expertise
  - Important group coordination or planning
  - Sensitive or emotionally charged topic
  - Not urgent but likely to require a thoughtful response

- **0.6 — Medium Importance**
  - General question to the group that the user may want to respond to
  - Ongoing group discussion with relevance to the user
  - New information that may be useful, but not urgent

- **0.4 — Low Importance**
  - Casual conversation, jokes, or memes
  - Social chatter or general observations
  - Greeting messages or emoji replies
  - User is not mentioned or expected to respond

- **0.2 — Very Low Importance**
  - Spam, automated replies, bots
  - System messages or notifications
  - Repetitive or off-topic content

### Instructions:
- Use your judgment based on the message content and context.
- Return a **single number between 0.0 and 1.0** (e.g., 0.8, 0.4).
- Do **not** include any explanation or additional text.

Message to analyze: {message}"""
        
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a message importance analyzer. Respond only with a number between 0 and 1."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=10
        )
        
        try:
            score = float(response.choices[0].message.content.strip())
            return max(0.0, min(1.0, score))  # Ensure score is between 0 and 1
        except ValueError:
            return 0.5  # Default to medium importance if parsing fails 

    async def refresh_style(self, chat_type: str, session: AsyncSession, message_count: str = "100") -> str:
        """Refresh style guide for a chat type."""
        try:
            logger.info(f"Starting style refresh for chat type: {chat_type}, message count: {message_count}")
            
            # Convert chat type to uppercase to match database
            chat_type = chat_type.upper()
            logger.info(f"Converted chat type to uppercase: {chat_type}")
            
            # Get historical messages for this chat type
            query = select(DBMessage).join(Chat).where(Chat.type == chat_type)
            logger.info(f"Base query created: {query}")
            
            # Apply message count filter
            if message_count == "week":
                # Get messages from the last week
                week_ago = datetime.now() - timedelta(days=7)
                query = query.where(DBMessage.created_at >= week_ago)
                logger.info(f"Week filter applied, from: {week_ago}")
            else:
                # Get last N messages
                try:
                    count = int(message_count)
                    query = query.order_by(DBMessage.created_at.desc()).limit(count)
                    logger.info(f"Count filter applied: {count} messages")
                except ValueError:
                    # Default to 100 if invalid count
                    query = query.order_by(DBMessage.created_at.desc()).limit(100)
                    logger.info("Invalid count, defaulting to 100 messages")
            
            # Execute query
            messages = await session.execute(query)
            messages = messages.scalars().all()
            logger.info(f"Query executed, found {len(messages)} messages")
            
            if not messages:
                logger.warning(f"No messages found for chat type: {chat_type}")
                return "No messages found for analysis"
            
            # Format messages for analysis
            formatted_messages = []
            for msg in messages:
                if msg.text:
                    formatted_messages.append(msg.text)
            
            logger.info(f"Formatted {len(formatted_messages)} messages for analysis")
            
            # Analyze messages and generate style guide
            style_guide = await OpenAIService._generate_style_guide(formatted_messages, chat_type.lower())
            
            # Update or create style in database
            style = await session.execute(
                select(Style).where(Style.chat_type == ChatType(chat_type.lower()))
            )
            style = style.scalar_one_or_none()
            
            if style:
                style.prompt_template = style_guide
                style.last_updated = datetime.now()
            else:
                style = Style(
                    chat_type=ChatType(chat_type.lower()),
                    prompt_template=style_guide,
                    last_updated=datetime.now()
                )
                session.add(style)
            
            await session.commit()
            return style_guide
            
        except Exception as e:
            logger.error(f"Error refreshing style: {e}")
            raise

    @staticmethod
    async def analyze_topics(messages: List[str]) -> List[Dict[str, int]]:
        """Analyze topics in messages and return list of topics with their counts."""
        # Combine messages into a single text
        text = "\n".join(messages)
        
        prompt = f"""Analyze the following conversation and identify the main topics being discussed.
        Return a JSON array of objects, where each object has:
        - "topic": A short topic name (1-3 words)
        - "count": Number of messages related to this topic
        
        Rules:
        1. Topics should be specific but not too narrow
        2. Each message can belong to multiple topics
        3. Return only the top 10 most frequent topics
        4. Topics should be in English
        5. Count should be an integer
        
        Example response:
        [
            {{"topic": "Work Projects", "count": 45}},
            {{"topic": "Technical Issues", "count": 32}},
            {{"topic": "Team Meetings", "count": 28}}
        ]
        
        Conversation:
        {text}"""
        
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a topic analyzer. Return only a JSON array of topics and their counts."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        try:
            import json
            topics = json.loads(response.choices[0].message.content.strip())
            return topics
        except (json.JSONDecodeError, ValueError):
            return []

    @staticmethod
    async def _generate_style_guide(messages: List[str], chat_type: str) -> str:
        """Generate style guide from messages."""
        # Format messages for analysis
        conversation_text = "\n".join(messages)
        
        # Create prompt for style analysis
        prompt = f"""
Analyze the following conversation and create a detailed style guide for imitating the communication style of Valentin. 
Consider the following aspects:
1. Language style (formal/informal, technical/casual)
2. Tone (friendly, professional, etc.)
3. Emoji usage patterns
4. Response structure and length
5. Common phrases and expressions
6. Response timing patterns
7. Specific formatting preferences
8. Topics of interest and expertise
9. Typical response patterns to different types of messages

Chat type: {chat_type}

Conversation:
{conversation_text}

Create a comprehensive style guide that captures all these aspects.
"""
        
        # Get style guide from OpenAI
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert at analyzing communication styles and creating detailed style guides."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip() 