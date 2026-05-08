"""Daily chat digest builder (FEATURE-002 + FEATURE-007/008/009/010).

For each eligible chat (groups, supergroups, Business private chats) the
service:

1. Pulls messages for the day (Europe/Moscow, 00:00–23:59);
2. Loads currently open commits and upcoming events for that chat;
3. Calls OpenAI in JSON mode with a classification-specific prompt
   (``business`` / ``private`` / ``mixed``; defaults to ``business``);
4. Persists new commits/events, marks any closed commits as done/cancelled,
   auto-flags urgency for ≤24h deadlines;
5. Renders a MarkdownV2 block per chat and sends it to ``OWNER_ID``.

After all chats are processed it runs a classifier on every
``classification IS NULL`` chat that had messages today and posts a
suggestion message with inline buttons. The owner taps a button to commit
the bucket; from the next day onwards, the chat-specific prompt is used.

Idempotency: every successful automatic send is recorded in
``daily_digests``; manual ``/digest`` runs do not record.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import Chat, Commitment, DailyDigest, DBMessage, Event
from .md import SAFE_LIMIT, chunk_md, md_escape
from .openai_service import OpenAIService
from .prompts import load_prompt

logger = logging.getLogger(__name__)

OWNER_TZ = ZoneInfo("Europe/Moscow")
DIGEST_HOUR = 23
DIGEST_MINUTE = 50
MAX_MESSAGES_PER_CHAT = 200  # keep prompt small / cost bounded

# Classification → prompt name. Chats with NULL classification fall back to
# ``business`` (per product decision: most owner conversations are business).
PROMPT_BY_CLASSIFICATION: Dict[str, str] = {
    "business": "FEATURE-010_digest_business",
    "private": "FEATURE-010_digest_private",
    "mixed": "FEATURE-010_digest_mixed",
}
DEFAULT_PROMPT_NAME = PROMPT_BY_CLASSIFICATION["business"]


@dataclass
class _ChatDigestItem:
    chat: Chat
    messages: List[DBMessage]


# --------------------------------------------------------------------------- #
# Helpers: time, day boundaries, scheduler timing                             #
# --------------------------------------------------------------------------- #


def _is_business_private(chat: Chat) -> bool:
    return chat.tg_type == "private" and bool(chat.business_connection_id)


def period_for_day(day: date) -> tuple[datetime, datetime]:
    """Return UTC half-open interval [start, end) covering the given Moscow day."""
    start_local = datetime.combine(day, time(0, 0, 0), tzinfo=OWNER_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def yesterday_in_moscow(now_utc: Optional[datetime] = None) -> date:
    now_utc = now_utc or datetime.now(timezone.utc)
    return (now_utc.astimezone(OWNER_TZ).date()) - timedelta(days=1)


def today_in_moscow(now_utc: Optional[datetime] = None) -> date:
    now_utc = now_utc or datetime.now(timezone.utc)
    return now_utc.astimezone(OWNER_TZ).date()


def seconds_until_next_digest(now_utc: Optional[datetime] = None) -> float:
    now_utc = now_utc or datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(OWNER_TZ)
    target = now_msk.replace(hour=DIGEST_HOUR, minute=DIGEST_MINUTE, second=0, microsecond=0)
    if target <= now_msk:
        target = target + timedelta(days=1)
    return (target - now_msk).total_seconds()


def previous_trigger_day(now_utc: Optional[datetime] = None) -> date:
    """Most recent day whose 23:50 trigger has already passed."""
    now_utc = now_utc or datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(OWNER_TZ)
    if now_msk.hour > DIGEST_HOUR or (
        now_msk.hour == DIGEST_HOUR and now_msk.minute >= DIGEST_MINUTE
    ):
        return now_msk.date()
    return now_msk.date() - timedelta(days=1)


# --------------------------------------------------------------------------- #
# Helpers: deadline parsing                                                    #
# --------------------------------------------------------------------------- #


def parse_deadline(raw: Optional[str], *, now_utc: Optional[datetime] = None) -> Optional[datetime]:
    """Best-effort NL → tz-aware datetime parser.

    Uses ``dateparser`` with Russian locale and Europe/Moscow as the base
    timezone. Returns ``None`` if parsing fails or input is empty. Always
    returns a tz-aware UTC datetime to keep DB writes consistent.
    """
    if not raw:
        return None
    try:
        import dateparser  # local import — heavy module
    except ImportError:  # pragma: no cover — dependency is required at runtime
        return None

    relative_base = (now_utc or datetime.now(timezone.utc)).astimezone(OWNER_TZ)
    parsed = dateparser.parse(
        raw,
        languages=["ru", "en"],
        settings={
            "TIMEZONE": "Europe/Moscow",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": relative_base.replace(tzinfo=None),
            "PREFER_DATES_FROM": "future",
        },
    )
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=OWNER_TZ)
    return parsed.astimezone(timezone.utc)


def is_within_24h(when_utc: Optional[datetime], *, now_utc: Optional[datetime] = None) -> bool:
    if when_utc is None:
        return False
    now_utc = now_utc or datetime.now(timezone.utc)
    delta = when_utc - now_utc
    return timedelta(0) <= delta <= timedelta(hours=24)


# --------------------------------------------------------------------------- #
# Helpers: message formatting for the LLM                                      #
# --------------------------------------------------------------------------- #


def _short_user_label(user_id: int) -> str:
    """Stable short label for non-owner users in groups."""
    return f"user_{user_id % 100000:05d}"


def _format_messages(
    messages: Sequence[DBMessage], *, owner_id: int, partner_label: str, is_group: bool
) -> str:
    """Render messages for the LLM with normalised author labels.

    - Owner (``user_id == OWNER_ID``) is always rendered as ``Я``.
    - In a private (Business) chat: everyone else is ``partner_label``.
    - In a group: every other user is rendered as ``user_NNNNN`` so the
      LLM can still track who said what without us leaking real names.
    """
    lines: List[str] = []
    for msg in messages:
        text = (msg.text or "").strip()
        if not text:
            continue
        if msg.user_id == owner_id:
            label = "Я"
        elif is_group:
            label = _short_user_label(msg.user_id)
        else:
            label = partner_label
        lines.append(f"{label}: {text}")
    return "\n".join(lines)


def _partner_label_for(chat: Chat) -> str:
    """Best short partner label for a private (Business) chat."""
    name = (chat.name or "").strip()
    if not name:
        return f"Контакт_{chat.telegram_id}"
    # Drop "(@username)" suffix; keep first name only (stays inside JSON-prompt
    # placeholders without spoiling a JSON example).
    head = name.split("(")[0].strip()
    return head.split()[0] if head else f"Контакт_{chat.telegram_id}"


# --------------------------------------------------------------------------- #
# DigestService                                                                #
# --------------------------------------------------------------------------- #


class DigestService:
    """Build, render and send daily digests."""

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self.session = session
        self.bot = bot

    # ---- public API ---- #

    async def already_sent(self, day: date) -> bool:
        result = await self.session.execute(
            select(DailyDigest).where(DailyDigest.digest_date == day)
        )
        return result.scalar_one_or_none() is not None

    async def collect(self, day: date) -> List[_ChatDigestItem]:
        """Eligible chats with messages on ``day``.

        Includes groups/supergroups and Business private chats. Channels
        and the owner-bot DM are excluded. Empty chats are dropped.
        """
        start_utc, end_utc = period_for_day(day)

        chats_result = await self.session.execute(
            select(Chat).where(
                or_(
                    Chat.tg_type.in_(("group", "supergroup")),
                    (Chat.tg_type == "private") & (Chat.business_connection_id.isnot(None)),
                )
            )
        )
        chats: Sequence[Chat] = chats_result.scalars().all()

        items: List[_ChatDigestItem] = []
        for chat in chats:
            msg_result = await self.session.execute(
                select(DBMessage)
                .where(
                    DBMessage.chat_id == chat.id,
                    DBMessage.created_at >= start_utc,
                    DBMessage.created_at < end_utc,
                )
                .order_by(DBMessage.created_at.asc())
                .limit(MAX_MESSAGES_PER_CHAT)
            )
            messages = list(msg_result.scalars().all())
            if not messages:
                continue
            items.append(_ChatDigestItem(chat=chat, messages=messages))
        return items

    async def send_for_day(self, day: date, *, record: bool = True) -> int:
        """Build and send the digest. Returns the number of chats summarised."""
        if record and await self.already_sent(day):
            logger.info("Digest for %s already sent, skipping", day)
            return -1

        items = await self.collect(day)
        date_str = day.strftime("%d.%m.%Y")

        if not items:
            await self.bot.send_message(
                settings.OWNER_ID,
                f"📊 Дайджест за {date_str}\nТихий день — ни в одном чате не было сообщений.",
            )
        else:
            await self._send_header(items, date_str)
            for item in items:
                await self._process_and_send_chat(item, day)

            # Classification suggestions only after the day's prose is done
            # so the owner sees the digest first, then the meta-questions.
            await self._suggest_classifications(items)

        if record:
            entry = DailyDigest(
                digest_date=day,
                sent_at=datetime.now(timezone.utc),
                chat_count=len(items),
                message_count=sum(len(i.messages) for i in items),
            )
            self.session.add(entry)
            await self.session.commit()
        return len(items)

    # ---- internals ---- #

    async def _send_header(self, items: Sequence[_ChatDigestItem], date_str: str) -> None:
        groups = sum(1 for i in items if not _is_business_private(i.chat))
        privates = sum(1 for i in items if _is_business_private(i.chat))
        text = (
            f"📊 *Дайджест за {md_escape(date_str)}* — {len(items)} чат\\(ов\\)\n"
            f"_групповых: {groups}, личных: {privates}_"
        )
        await self._send_md(text)

    async def _process_and_send_chat(self, item: _ChatDigestItem, day: date) -> None:
        try:
            extracted = await self._extract(item, day)
            await self._persist(item.chat, extracted)
            block = self._render_block(item, extracted)
        except Exception as exc:  # noqa: BLE001 — не валим весь дайджест из-за одного чата
            logger.error(
                "Failed to process chat %s for digest: %s",
                item.chat.telegram_id,
                exc,
                exc_info=True,
            )
            title = md_escape(item.chat.name or f"Chat {item.chat.telegram_id}")
            block = f"*{title}*\n_не удалось получить саммари — см\\. логи_"
        await self._send_md(block)

    async def _extract(self, item: _ChatDigestItem, day: date) -> Dict[str, Any]:
        """Run the per-chat extraction prompt and return the parsed JSON."""
        chat = item.chat
        partner_label = _partner_label_for(chat)
        is_group = chat.tg_type in ("group", "supergroup")

        prompt_name = PROMPT_BY_CLASSIFICATION.get(chat.classification or "", DEFAULT_PROMPT_NAME)
        prompt = load_prompt(prompt_name)

        owner_id = settings.OWNER_ID
        count_me = sum(1 for m in item.messages if m.user_id == owner_id)
        count_partner = len(item.messages) - count_me

        formatted = _format_messages(
            item.messages,
            owner_id=owner_id,
            partner_label=partner_label,
            is_group=is_group,
        )

        open_commitments = await self._open_commitments(chat.id)
        open_events = await self._upcoming_events(chat.id)

        rendered = prompt.format(
            partner_name=partner_label if not is_group else (chat.name or "Группа"),
            date=day.strftime("%d.%m.%Y"),
            message_count=len(item.messages),
            count_me=count_me,
            count_partner=count_partner,
            messages_text=formatted or "(нет текстовых сообщений)",
            open_commitments_json=json.dumps(
                [
                    {
                        "id": str(c.id),
                        "direction": c.direction,
                        "text": c.text,
                        "deadline_raw": c.deadline_raw,
                    }
                    for c in open_commitments
                ],
                ensure_ascii=False,
            ),
            open_events_json=json.dumps(
                [
                    {
                        "id": str(e.id),
                        "description": e.description,
                        "when_raw": e.when_raw,
                    }
                    for e in open_events
                ],
                ensure_ascii=False,
            ),
        )

        return await OpenAIService.complete_json(
            prompt,
            rendered,
            system="Ты помощник владельца. Возвращай только валидный JSON по схеме из инструкции.",
        )

    async def _open_commitments(self, chat_id: UUID) -> List[Commitment]:
        result = await self.session.execute(
            select(Commitment)
            .where(Commitment.chat_id == chat_id, Commitment.status == "open")
            .order_by(Commitment.created_at.asc())
        )
        return list(result.scalars().all())

    async def _upcoming_events(self, chat_id: UUID) -> List[Event]:
        result = await self.session.execute(
            select(Event)
            .where(Event.chat_id == chat_id, Event.status == "upcoming")
            .order_by(Event.when_at.asc().nullslast())
        )
        return list(result.scalars().all())

    async def _persist(self, chat: Chat, extracted: Dict[str, Any]) -> None:
        """Save new commits/events; mark closed commits as done/cancelled."""
        now_utc = datetime.now(timezone.utc)

        for raw in extracted.get("commitments") or []:
            direction = raw.get("direction")
            text = (raw.get("text") or "").strip()
            if direction not in ("from_me", "to_me") or not text:
                continue
            deadline_raw = raw.get("deadline_raw")
            deadline_at = parse_deadline(deadline_raw, now_utc=now_utc)
            llm_urgent = bool(raw.get("is_urgent"))
            self.session.add(
                Commitment(
                    chat_id=chat.id,
                    direction=direction,
                    text=text,
                    deadline_raw=deadline_raw,
                    deadline_at=deadline_at,
                    is_urgent=llm_urgent or is_within_24h(deadline_at, now_utc=now_utc),
                    status="open",
                    source_message_id=raw.get("source_message_id"),
                )
            )

        for raw in extracted.get("closed_commitments") or []:
            cid = raw.get("id")
            reason = raw.get("reason")
            if not cid or reason not in ("completed", "cancelled"):
                continue
            try:
                cid_uuid = UUID(str(cid))
            except (ValueError, TypeError):
                continue
            commitment = await self.session.get(Commitment, cid_uuid)
            if commitment is None or commitment.chat_id != chat.id:
                continue
            commitment.status = "done" if reason == "completed" else "cancelled"
            commitment.completed_at = now_utc
            commitment.updated_at = now_utc

        for raw in extracted.get("events") or []:
            description = (raw.get("description") or "").strip()
            if not description:
                continue
            when_raw = raw.get("when_raw")
            when_at = parse_deadline(when_raw, now_utc=now_utc)
            llm_urgent = bool(raw.get("is_urgent"))
            self.session.add(
                Event(
                    chat_id=chat.id,
                    description=description,
                    when_raw=when_raw,
                    when_at=when_at,
                    is_urgent=llm_urgent or is_within_24h(when_at, now_utc=now_utc),
                    status="upcoming",
                    source_message_id=raw.get("source_message_id"),
                )
            )

        await self.session.commit()

    # ---- rendering ---- #

    def _render_block(self, item: _ChatDigestItem, extracted: Dict[str, Any]) -> str:
        chat = item.chat
        title = chat.name or f"Chat {chat.telegram_id}"
        owner_id = settings.OWNER_ID
        count_me = sum(1 for m in item.messages if m.user_id == owner_id)
        count_partner = len(item.messages) - count_me

        cls = chat.classification
        cls_badge = {"business": "💼", "private": "👤", "mixed": "🤝"}.get(cls or "", "❓")

        lines: List[str] = []
        lines.append(
            f"{cls_badge} *{md_escape(title)}* — {len(item.messages)} сообщ\\. "
            f"\\(мои: {count_me}, его/её: {count_partner}\\)"
        )

        summary = (extracted.get("summary_md") or "").strip()
        if summary:
            lines.append("")
            lines.append(md_escape(summary))

        commitments = extracted.get("commitments") or []
        if commitments:
            lines.append("")
            lines.append("🤝 *Коммиты*")
            for c in commitments:
                lines.append(self._format_commitment_inline(c))

        events = extracted.get("events") or []
        if events:
            lines.append("")
            lines.append("📅 *Даты и события*")
            for e in events:
                lines.append(self._format_event_inline(e))

        questions = extracted.get("open_questions") or []
        if questions:
            lines.append("")
            lines.append("❓ *Открытые вопросы*")
            for q in questions:
                lines.append(self._format_question_inline(q))

        urgent_lines = self._urgent_section(commitments, events)
        if urgent_lines:
            lines.append("")
            lines.append("⚠️ *Срочное*")
            lines.extend(urgent_lines)

        return "\n".join(lines)

    @staticmethod
    def _format_commitment_inline(c: Dict[str, Any]) -> str:
        direction = c.get("direction")
        arrow = "→ от меня" if direction == "from_me" else "← мне"
        text = md_escape((c.get("text") or "").strip())
        deadline = c.get("deadline_raw")
        suffix = f" \\({md_escape(deadline)}\\)" if deadline else ""
        return f"• {arrow}: {text}{suffix}"

    @staticmethod
    def _format_event_inline(e: Dict[str, Any]) -> str:
        when = md_escape((e.get("when_raw") or "").strip())
        desc = md_escape((e.get("description") or "").strip())
        if when and desc:
            return f"• {when} — {desc}"
        return f"• {desc or when or '?'}"

    @staticmethod
    def _format_question_inline(q: Dict[str, Any]) -> str:
        direction = q.get("direction")
        arrow = "← мне" if direction == "to_me" else "→ ему/ей"
        text = md_escape((q.get("text") or "").strip())
        return f"• {arrow}: {text}"

    @staticmethod
    def _urgent_section(
        commitments: Sequence[Dict[str, Any]], events: Sequence[Dict[str, Any]]
    ) -> List[str]:
        out: List[str] = []
        for c in commitments:
            if not c.get("is_urgent"):
                continue
            text = md_escape((c.get("text") or "").strip())
            deadline = c.get("deadline_raw")
            if deadline:
                out.append(f"• коммит: {text} \\({md_escape(deadline)}\\)")
            else:
                out.append(f"• коммит: {text}")
        for e in events:
            if not e.get("is_urgent"):
                continue
            when = md_escape((e.get("when_raw") or "").strip())
            desc = md_escape((e.get("description") or "").strip())
            if when:
                out.append(f"• событие: {when} — {desc}")
            else:
                out.append(f"• событие: {desc}")
        return out

    async def _send_md(self, text: str) -> None:
        """Send a MarkdownV2 message; chunk on overflow; fall back to plain text on parse error."""
        for chunk in chunk_md(text, limit=SAFE_LIMIT):
            try:
                await self.bot.send_message(
                    settings.OWNER_ID,
                    chunk,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                )
            except TelegramBadRequest as exc:
                logger.warning("MarkdownV2 send failed (%s); retrying as plain text", exc)
                await self.bot.send_message(
                    settings.OWNER_ID,
                    chunk,
                    disable_web_page_preview=True,
                )

    # ---- classification suggestions ---- #

    async def _suggest_classifications(self, items: Sequence[_ChatDigestItem]) -> None:
        """For each unclassified Business private chat, ask the LLM and post a suggestion."""
        candidates = [
            i for i in items if _is_business_private(i.chat) and not i.chat.classification
        ]
        if not candidates:
            return

        for item in candidates:
            try:
                suggestion = await self._classify_chat(item)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Classification failed for chat %s: %s",
                    item.chat.telegram_id,
                    exc,
                    exc_info=True,
                )
                continue

            await self._send_classification_card(item, suggestion)

    async def _classify_chat(self, item: _ChatDigestItem) -> Dict[str, Any]:
        prompt = load_prompt("FEATURE-010_classify")
        partner_label = _partner_label_for(item.chat)
        formatted = _format_messages(
            item.messages,
            owner_id=settings.OWNER_ID,
            partner_label=partner_label,
            is_group=False,
        )
        rendered = prompt.format(
            partner_name=partner_label,
            message_count=len(item.messages),
            messages_text=formatted or "(нет текстовых сообщений)",
        )
        return await OpenAIService.complete_json(
            prompt,
            rendered,
            system="Ты строгий классификатор. Возвращай только JSON.",
        )

    async def _send_classification_card(
        self, item: _ChatDigestItem, suggestion: Dict[str, Any]
    ) -> None:
        suggested = suggestion.get("classification")
        if suggested not in ("business", "private", "mixed"):
            suggested = "business"
        confidence = suggestion.get("confidence")
        try:
            confidence_pct = int(round(float(confidence) * 100))
        except (TypeError, ValueError):
            confidence_pct = 0
        reason = (suggestion.get("reason") or "").strip()
        title = item.chat.name or f"Chat {item.chat.telegram_id}"

        body = (
            f"🗂 *Классификация чата*\n"
            f"*{md_escape(title)}* — модель предлагает: *{_classification_label(suggested)}* "
            f"\\(уверенность {confidence_pct}%\\)\n"
            f"_{md_escape(reason)}_\n"
            f"Подтвердить или изменить:"
        )

        chat_id_str = str(item.chat.id)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💼 Бизнес", callback_data=f"cls|{chat_id_str}|business"
                    ),
                    InlineKeyboardButton(
                        text="👤 Личный", callback_data=f"cls|{chat_id_str}|private"
                    ),
                    InlineKeyboardButton(text="🤝 Микс", callback_data=f"cls|{chat_id_str}|mixed"),
                ],
                [
                    InlineKeyboardButton(text="⏭ Позже", callback_data=f"cls|{chat_id_str}|skip"),
                ],
            ]
        )
        try:
            await self.bot.send_message(
                settings.OWNER_ID,
                body,
                parse_mode="MarkdownV2",
                reply_markup=keyboard,
            )
        except TelegramBadRequest as exc:
            logger.warning("Classification card MarkdownV2 send failed (%s); falling back", exc)
            plain = (
                f"🗂 Классификация чата\n{title} — модель предлагает: "
                f"{_classification_label(suggested)} (уверенность {confidence_pct}%)\n{reason}"
            )
            await self.bot.send_message(settings.OWNER_ID, plain, reply_markup=keyboard)


def _classification_label(value: str) -> str:
    return {
        "business": "Бизнес",
        "private": "Личный",
        "mixed": "Микс",
    }.get(value, value)


# --------------------------------------------------------------------------- #
# Scheduler                                                                    #
# --------------------------------------------------------------------------- #


async def _send_with_fresh_session(bot: Bot, day: date) -> None:
    """Open a one-shot session, build a service and send a recorded digest."""
    from ..database.database import async_session  # local to avoid import cycle

    async with async_session() as session:
        service = DigestService(session, bot)
        await service.send_for_day(day, record=True)


async def run_digest_scheduler(bot: Bot) -> None:
    """Background loop: catch up if needed, then trigger every 23:50 Europe/Moscow."""
    catchup = previous_trigger_day()
    try:
        from ..database.database import async_session

        async with async_session() as session:
            already = await DigestService(session, bot).already_sent(catchup)
        if not already:
            logger.info("Catch-up: sending digest for %s", catchup)
            await _send_with_fresh_session(bot, catchup)
    except Exception as exc:  # noqa: BLE001 — никогда не падаем из catch-up
        logger.error("Catch-up digest failed: %s", exc, exc_info=True)

    while True:
        try:
            sleep_for = seconds_until_next_digest()
            logger.info("Daily digest: sleeping %.0f seconds until next 23:50 MSK", sleep_for)
            await asyncio.sleep(sleep_for)

            day = today_in_moscow()
            logger.info("Daily digest: trigger fired, sending digest for %s", day)
            await _send_with_fresh_session(bot, day)
        except asyncio.CancelledError:
            logger.info("Daily digest scheduler cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 — никогда не валим бота из-за дайджеста
            logger.error("Daily digest iteration failed: %s", exc, exc_info=True)
            await asyncio.sleep(60)
