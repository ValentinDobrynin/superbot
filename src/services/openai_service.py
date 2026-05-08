"""OpenAI-powered services: response generation, importance scoring, style analysis."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import numpy as np
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import Chat, ChatType, DBMessage, Style
from .prompts import PromptSpec, load_prompt

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY,
    timeout=60.0,
)


class OpenAIService:
    """Thin wrapper around the OpenAI API used across the bot."""

    @staticmethod
    async def _complete(
        prompt: PromptSpec,
        rendered: str,
        *,
        system: str,
        json_mode: bool = False,
    ) -> str:
        kwargs: Dict[str, object] = {
            "model": prompt.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": rendered},
            ],
            "temperature": prompt.temperature,
        }
        if prompt.max_tokens is not None:
            kwargs["max_tokens"] = prompt.max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()

    @staticmethod
    async def complete_json(
        prompt: PromptSpec,
        rendered: str,
        *,
        system: str = "You output strict JSON. No markdown, no preamble.",
    ) -> dict:
        """Run a prompt in OpenAI JSON mode and return the parsed object.

        Falls back to permissive parsing (locating the first ``{`` and the
        last ``}``) if the model still wraps the JSON in prose for some
        reason.
        """
        text = await OpenAIService._complete(prompt, rendered, system=system, json_mode=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                return json.loads(text[start : end + 1])
            raise

    @staticmethod
    async def get_style_for_chat_type(session: AsyncSession, chat_type: ChatType) -> str:
        """Return the stored style guide for a chat type, or an empty string."""
        result = await session.execute(select(Style).where(Style.chat_type == chat_type))
        style = result.scalar_one_or_none()
        return style.prompt_template if style else ""

    @staticmethod
    async def generate_response(
        message: str,
        chat_type: ChatType,
        context_messages: List[Dict[str, object]],
        session: AsyncSession,
    ) -> str:
        """Generate a Valentin-style response with a humanising delay."""
        delay = random.uniform(settings.MIN_RESPONSE_DELAY, settings.MAX_RESPONSE_DELAY)
        await asyncio.sleep(delay)

        style_prompt = await OpenAIService.get_style_for_chat_type(session, chat_type)
        context = "\n".join(f"User: {msg['text']}" for msg in context_messages)

        prompt = load_prompt("TECH-001_generate_response")
        rendered = prompt.format(
            chat_type=chat_type.value,
            context=context,
            message=message,
            style_prompt=style_prompt,
        )
        return await OpenAIService._complete(
            prompt,
            rendered,
            system="You are Valentin's AI assistant, mimicking their communication style.",
        )

    @staticmethod
    async def chat_completion(prompt_text: str, temperature: float = 0.3) -> str:
        """Generic chat completion used for ad-hoc summarisation tasks."""
        try:
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt_text},
                ],
                temperature=temperature,
                max_tokens=500,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001 — собираем все ошибки OpenAI в одно сообщение
            text = str(exc)
            if "insufficient_quota" in text:
                return "⚠️ OpenAI API quota exceeded. Please check your billing details."
            if "rate_limit" in text.lower():
                return "⚠️ OpenAI API rate limit reached. Please try again later."
            logger.error("OpenAI chat_completion failed: %s", exc)
            return f"⚠️ Error: {text}"

    @staticmethod
    async def get_embedding(text: str) -> List[float]:
        """Return the embedding vector for the given text."""
        response = await client.embeddings.create(
            model="text-embedding-ada-002",
            input=text,
        )
        return response.data[0].embedding

    @staticmethod
    async def calculate_similarity(text1: str, text2: str) -> float:
        """Cosine similarity between two pieces of text."""
        emb1, emb2 = await asyncio.gather(
            OpenAIService.get_embedding(text1),
            OpenAIService.get_embedding(text2),
        )
        vec1 = np.array(emb1)
        vec2 = np.array(emb2)
        denom = np.linalg.norm(vec1) * np.linalg.norm(vec2)
        if denom == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / denom)

    @staticmethod
    async def analyze_message_importance(message: str) -> float:
        """Return importance score in [0.0, 1.0]; default to 0.5 on parse failure."""
        prompt = load_prompt("TECH-001_message_importance")
        rendered = prompt.format(message=message)
        text = await OpenAIService._complete(
            prompt,
            rendered,
            system="You are a message importance analyzer. Respond only with a number between 0 and 1.",
        )
        try:
            score = float(text)
        except ValueError:
            logger.warning("Could not parse importance score: %r", text)
            return 0.5
        return max(0.0, min(1.0, score))

    async def refresh_style(
        self,
        chat_type: str,
        session: AsyncSession,
        message_count: str = "100",
    ) -> str:
        """Rebuild the style guide for a chat type from historical messages."""
        logger.info("Starting style refresh: chat_type=%s, count=%s", chat_type, message_count)
        chat_type_upper = chat_type.upper()

        query = select(DBMessage).join(Chat).where(Chat.type == chat_type_upper)

        if message_count == "week":
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            query = query.where(DBMessage.created_at >= week_ago)
        else:
            try:
                limit = int(message_count)
            except ValueError:
                limit = 100
            query = query.order_by(DBMessage.created_at.desc()).limit(limit)

        result = await session.execute(query)
        messages = result.scalars().all()
        logger.info("Found %d messages for style refresh", len(messages))

        if not messages:
            return "No messages found for analysis"

        formatted = [msg.text for msg in messages if msg.text]
        style_guide = await OpenAIService._generate_style_guide(formatted, chat_type.lower())

        result = await session.execute(
            select(Style).where(Style.chat_type == ChatType(chat_type.lower()))
        )
        style = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)

        if style:
            style.prompt_template = style_guide
            style.last_updated = now
        else:
            session.add(
                Style(
                    chat_type=ChatType(chat_type.lower()),
                    prompt_template=style_guide,
                    last_updated=now,
                )
            )

        await session.commit()
        return style_guide

    @staticmethod
    async def analyze_topics(messages: List[str]) -> List[Dict[str, object]]:
        """Extract top topics as a list of ``{"topic": str, "count": int}`` dicts."""
        if not messages:
            return []

        prompt = load_prompt("TECH-001_topics")
        rendered = prompt.format(conversation_text="\n".join(messages))
        text = await OpenAIService._complete(
            prompt,
            rendered,
            system="You are a topic analyzer. Return only a JSON array of topics and their counts.",
        )

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            logger.warning("Could not parse topics JSON: %r", text)
        return []

    @staticmethod
    async def _generate_style_guide(messages: List[str], chat_type: str) -> str:
        prompt = load_prompt("TECH-001_style_guide")
        rendered = prompt.format(
            chat_type=chat_type,
            conversation_text="\n".join(messages),
        )
        return await OpenAIService._complete(
            prompt,
            rendered,
            system="You are an expert at analyzing communication styles and creating detailed style guides.",
        )
