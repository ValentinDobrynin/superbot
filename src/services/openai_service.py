from openai import AsyncOpenAI
from ..config import settings
from ..database.models import ChatType
import random
import asyncio
import numpy as np
from typing import List, Optional

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

class OpenAIService:
    @staticmethod
    async def generate_response(
        message: str,
        chat_type: ChatType,
        context_messages: list,
        style_prompt: str
    ) -> str:
        # Add random delay to simulate human behavior
        delay = random.uniform(settings.MIN_RESPONSE_DELAY, settings.MAX_RESPONSE_DELAY)
        await asyncio.sleep(delay)
        
        # Prepare context from recent messages
        context = "\n".join([f"{'User' if msg['is_user'] else 'Assistant'}: {msg['text']}" 
                           for msg in context_messages])
        
        # Construct the prompt
        prompt = f"""You are Valentin's AI assistant, mimicking their communication style in a {chat_type.value} chat.
Previous conversation:
{context}

Current message: {message}

Style guidelines:
{style_prompt}

Respond in Valentin's style. Keep the response concise and natural. Use appropriate emojis and informal language if it matches the style.
Prefix your response with "🤖 ~ Valentin: "

Response:"""
        
        response = await client.chat.completions.create(
            model="gpt-4",
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
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=500
        )
        return response.choices[0].message.content.strip()

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
        prompt = f"""Analyze the importance of this message and return a number between 0 and 1.

Criteria for importance scoring:
1.0 - Critical messages:
- Direct questions or requests requiring immediate response
- Emergency situations
- Important business/work decisions
- Direct mentions of Valentin
- Messages with "срочно" or "важно"
- Time-sensitive requests
- Critical bug reports or system issues
- Direct task assignments
- Meeting requests for important topics

0.7-0.9 - High importance:
- Technical discussions requiring expertise
- Project planning and coordination
- Scheduling meetings or calls
- Questions about ongoing work
- Code reviews and technical feedback
- Feature requests and proposals
- Status updates on critical tasks
- Questions about project architecture
- Important documentation updates
- Team coordination messages

0.4-0.6 - Medium importance:
- General discussions
- Updates without urgency
- Non-critical questions
- Social interactions
- General project updates
- Casual technical discussions
- Non-urgent meeting requests
- General feedback and suggestions
- Regular status updates
- Team announcements

0.1-0.3 - Low importance:
- Small talk
- Casual observations
- Emoji-only messages
- Reactions to others
- General greetings
- Non-technical discussions
- Personal updates
- Memes and jokes
- General acknowledgments
- Non-urgent notifications

0.0 - Ignore:
- System messages
- Bot commands
- Automated notifications
- Empty or meaningless messages
- Spam or promotional content
- Off-topic discussions
- Personal messages not related to work
- Automated status updates
- Technical logs or debug messages
- Duplicate messages

Additional factors to consider:
- Message length (longer messages often indicate more importance)
- Presence of technical terms or code snippets
- Number of participants mentioned
- Time of day (work hours vs. off-hours)
- Message format (structured vs. casual)
- Presence of action items or deadlines
- Context from previous messages

Message to analyze: {message}

Return only the importance score (e.g. 0.7):"""
        
        response = await client.chat.completions.create(
            model="gpt-4",
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