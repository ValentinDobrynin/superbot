from openai import AsyncOpenAI
from ..config import settings
from ..database.models import ChatType
import random
import asyncio
import numpy as np
from typing import List, Optional

client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY,
    timeout=60.0  # Set a reasonable timeout
)

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
        context = "\n".join([f"{'User' if msg['is_user'] else 'Valentin'}: {msg['text']}" 
                           for msg in context_messages])
        
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

    @staticmethod
    async def refresh_style(conversation_text: str) -> str:
        """Refresh the style guide based on new conversation data."""
        prompt = f"""You are analyzing a Telegram chat history to extract the unique communication style of a user named **Valentin**.  
Your goal is to generate a detailed **style guide** that can be used by an AI to imitate Valentin's way of writing and reacting in chats.

Focus on identifying consistent **patterns** and **behaviors** based on the provided conversation.

### Analyze and extract:
1. **Language Style** — Typical vocabulary, sentence structure, and language preferences (e.g., simple/direct, slang, formal, etc.)
2. **Tone & Attitude** — Formality level, humor, sarcasm, emotional range, assertiveness, etc.
3. **Emoji & Formatting Usage** — Frequency and types of emojis, use of punctuation, caps, bold, etc.
4. **Response Length & Structure** — Short or long replies, use of lists, replies in-line vs separate, flow of thoughts
5. **Common Phrases & Expressions** — Repeated phrases, signature endings, fillers, or slang Valentin uses regularly
6. **Do's and Don'ts** — Specific habits to **emulate** (Do's) and things to **avoid** (Don'ts) based on his actual usage

### Output Format (strictly use this):

1. **Language Style**: [brief but rich description]
2. **Tone & Attitude**: [description]
3. **Emoji & Formatting Usage**: [description]
4. **Response Structure**: [description]
5. **Common Phrases & Expressions**:
   - "[phrase 1]"
   - "[phrase 2]"
6. **Do's and Don'ts**:
   - ✅ Do: [behavior to copy]
   - ❌ Don't: [behavior to avoid]

### Conversation Sample:
{conversation_text}"""
        
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a communication style analyzer. Extract and describe the user's unique writing style."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        return response.choices[0].message.content.strip() 