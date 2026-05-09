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
import re
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


# TECH-011 (step D of digest cleanup) — bare ``dateparser`` chokes on the
# Russian phrasing the bot actually receives ("до пятницы", "к выходным",
# "до 12.05", "в следующую пятницу"). We pre-normalise the raw string into
# something dateparser groks, and we capture urgency keywords separately
# (so "срочно" / "asap" still flip ``is_urgent`` even when the deadline
# itself is unparseable).

_URGENCY_KEYWORDS = (
    "срочно",
    "срочный",
    "срочная",
    "срочное",
    "срочные",
    "немедленно",
    "немедля",
    "asap",
    "as soon as possible",
    "urgent",
    "urgently",
    "немедля",
    "до конца дня",
    "к концу дня",
    "eod",
    "end of day",
)

_URGENCY_RE = re.compile(
    r"(?<![\wа-яёА-ЯЁ])(" + "|".join(map(re.escape, _URGENCY_KEYWORDS)) + r")(?![\wа-яёА-ЯЁ])",
    re.IGNORECASE,
)

# Russian weekday morphology → nominative form that ``dateparser`` knows.
# Cases covered: gen ("пятницы"), acc ("пятницу"), dat ("пятнице"),
# instr ("пятницей"), prep ("пятнице"). Same for short forms ("пн/вт/...").
_WEEKDAY_NORMALISE = {
    # Понедельник
    "понедельника": "понедельник",
    "понедельнику": "понедельник",
    "понедельником": "понедельник",
    "понедельнике": "понедельник",
    "пн": "понедельник",
    # Вторник
    "вторника": "вторник",
    "вторнику": "вторник",
    "вторником": "вторник",
    "вторнике": "вторник",
    "вт": "вторник",
    # Среда
    "среды": "среда",
    "среду": "среда",
    "средой": "среда",
    "среде": "среда",
    "ср": "среда",
    # Четверг
    "четверга": "четверг",
    "четвергу": "четверг",
    "четвергом": "четверг",
    "четверге": "четверг",
    "чт": "четверг",
    # Пятница
    "пятницы": "пятница",
    "пятницу": "пятница",
    "пятницей": "пятница",
    "пятнице": "пятница",
    "пт": "пятница",
    # Суббота
    "субботы": "суббота",
    "субботу": "суббота",
    "субботой": "суббота",
    "субботе": "суббота",
    "сб": "суббота",
    # Воскресенье
    "воскресенья": "воскресенье",
    "воскресенью": "воскресенье",
    "воскресеньем": "воскресенье",
    "воскресении": "воскресенье",
    "вс": "воскресенье",
}

_WEEKDAY_NOMINATIVE = {
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
}


def has_urgency_keyword(raw: Optional[str]) -> bool:
    """Return True if ``raw`` contains a phrase like 'срочно'/'asap'/'eod'."""
    if not raw:
        return False
    return bool(_URGENCY_RE.search(raw))


def _normalize_deadline_phrase(raw: str) -> Optional[str]:
    """Rewrite a Russian deadline phrase into something dateparser can chew.

    Returns ``None`` when the phrase is pure noise (urgency-only with no
    temporal anchor) — caller can still flag it urgent via
    ``has_urgency_keyword``.
    """
    text = raw.strip().lower()
    if not text:
        return None

    # Whole-phrase shortcuts (must run before token-level rewrites, so e.g.
    # "до конца дня" never gets stripped down to "дня").
    shortcuts = {
        "до конца дня": "сегодня 23:59",
        "к концу дня": "сегодня 23:59",
        "до конца недели": "воскресенье 23:59",
        "к концу недели": "воскресенье 23:59",
        "до конца месяца": "последний день месяца 23:59",
        "к концу месяца": "последний день месяца 23:59",
        "выходные": "суббота 09:00",
        "на выходные": "суббота 09:00",
        "на выходных": "суббота 09:00",
        "к выходным": "суббота 09:00",
        "до выходных": "пятница 23:59",
        "eod": "сегодня 23:59",
        "end of day": "сегодня 23:59",
    }
    if text in shortcuts:
        return shortcuts[text]

    # Strip a leading "deadline" preposition only if it's followed by a
    # weekday/date token (so we don't accidentally strip "в 18:00").
    # Examples: "до пятницы", "к понедельнику", "в следующую пятницу".
    prefix_patterns = [
        r"^до\s+",
        r"^к\s+",
        r"^в\s+следующ(ую|ий|ее)\s+",
        r"^на\s+следующ(ую|ий|ее)\s+",
        r"^на\s+ближайш(ую|ий|ее)\s+",
        r"^по\s+",  # "по средам" — нерегулярно, но всё равно к среде ближайшей
    ]
    for pat in prefix_patterns:
        text = re.sub(pat, "", text, count=1)

    # Token-level normalisation of weekday morphology and "time of day"
    # adverbs ("с утра"/"вечером"/...).
    _TIME_OF_DAY = {
        "утром": "09:00",
        "утра": "09:00",  # "с утра"
        "днём": "13:00",
        "днем": "13:00",
        "дня": "13:00",  # "с дня"
        "вечером": "19:00",
        "вечера": "19:00",  # "с вечера"
        "ночью": "23:00",
        "ночи": "23:00",  # "к ночи"
    }
    tokens = text.split()
    norm_tokens: List[str] = []
    for tok in tokens:
        # Strip trailing punctuation that confuses dictionary lookups.
        bare = tok.rstrip(",.;:!?")
        if bare in _WEEKDAY_NORMALISE:
            norm_tokens.append(_WEEKDAY_NORMALISE[bare])
        elif bare in _TIME_OF_DAY:
            norm_tokens.append(_TIME_OF_DAY[bare])
        elif bare == "с":
            # filler before "утра/вечера/ночи" — drop it so the time
            # token stays standalone.
            continue
        else:
            norm_tokens.append(tok)
    text = " ".join(norm_tokens).strip()
    if not text:
        return None

    # "12.05" / "12.5" / "12.05.26" / "12.05.2026" → rewrite to ISO
    # ("2026-05-12") so dateparser doesn't second-guess between DMY and MDY
    # nor confuse "12.05" with the time 12:05.
    def _ru_date_to_iso(m: "re.Match[str]") -> str:
        day = int(m.group(1))
        month = int(m.group(2))
        year_s = m.group(3)
        if year_s is None:
            year = datetime.now().year
        else:
            year = int(year_s)
            if year < 100:
                year += 2000
        try:
            return f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:  # pragma: no cover — unreachable, kept for safety
            return m.group(0)

    text = re.sub(
        r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?!\d|:)",
        _ru_date_to_iso,
        text,
    )

    # If the phrase is now exactly a weekday with no time, anchor it to
    # 23:59 МСК — semantically "by end of <day>" is what "до X" means.
    if text in _WEEKDAY_NOMINATIVE:
        return f"{text} 23:59"
    # "сегодня"/"завтра" alone — anchor to 23:59 too (otherwise dateparser
    # uses the current clock time, which is misleading for a deadline).
    if text in ("сегодня", "завтра", "послезавтра"):
        return f"{text} 23:59"
    return text


def parse_deadline(raw: Optional[str], *, now_utc: Optional[datetime] = None) -> Optional[datetime]:
    """Best-effort NL → tz-aware datetime parser.

    Uses ``dateparser`` with Russian locale and Europe/Moscow as the base
    timezone. Returns ``None`` if parsing fails or input is empty. Always
    returns a tz-aware UTC datetime to keep DB writes consistent.

    Russian phrasing (cases, prepositions, "выходные"/"конец дня") is
    pre-normalised — see ``_normalize_deadline_phrase``.
    """
    if not raw:
        return None
    try:
        import dateparser  # local import — heavy module
    except ImportError:  # pragma: no cover — dependency is required at runtime
        return None

    normalised = _normalize_deadline_phrase(raw)
    if normalised is None:
        return None

    relative_base = (now_utc or datetime.now(timezone.utc)).astimezone(OWNER_TZ)
    parsed = dateparser.parse(
        normalised,
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
# Helpers: defensive filters on top of LLM extract (TECH-012, step A)          #
# --------------------------------------------------------------------------- #

# A trailing "?" is a strong signal that the LLM mis-classified a question
# as a commit (we saw "Зум можешь сегодня дать?" land in commits=from_me).
_QUESTION_TAIL_RE = re.compile(r"\?\s*$")

# HH:MM patterns inside ``when_raw``. If the LLM ships "12 мая в 18:00" but
# the source messages never mentioned "18:00", that's a hallucinated time
# (this happened on 9-out-of-16 events in the 8 May digest).
_TIME_HHMM_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

# "12 мая" / "12 мая 2026" — verify the day-number actually appears in the
# source. Month name itself is too common to anchor on.
_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s+("
    r"янв(?:ар[ея])?|фев(?:рал[ея])?|мар(?:та)?|апр(?:ел[ея])?|"
    r"ма[яей]|июн[ея]?|июл[ея]?|авг(?:уст[ае])?|сент(?:ябр[ея])?|"
    r"окт(?:ябр[ея])?|нояб(?:р[ея])?|дек(?:абр[ея])?"
    r")\b",
    re.IGNORECASE,
)


def _normalize_for_match(s: Optional[str]) -> str:
    """Lowercase, collapse whitespace — used for case-insensitive dedup."""
    return " ".join((s or "").lower().strip().split())


def _sanitize_extracted(extracted: Dict[str, Any], messages_text: str) -> Dict[str, Any]:
    """Apply defensive filters on top of the LLM JSON before persisting.

    The LLM is greedy: it cheerfully creates events with fake "12 May 18:00"
    times, treats questions as commits, and mirrors the same line into
    both buckets. This pass cleans up the obvious noise without trying to
    second-guess the model's intent.

    Operations:

    1. Commits ending with ``?`` move to ``open_questions`` (with the same
       ``direction`` mapping).
    2. Tiny commits (<3 words) without a ``deadline_raw`` are dropped.
    3. Events with a description shorter than 2 words are dropped.
    4. Events deduped within a chat by (description, when_raw).
    5. Events with hallucinated dates/times: if ``when_raw`` mentions a
       HH:MM or DD MONTH that does not appear in the source messages,
       we erase ``when_raw`` (and consequently ``when_at``) — keeping
       the event itself, just without a fake anchor.
    6. Cross-bucket: the same text in commit & event is collapsed —
       event wins iff it has a ``when_raw``, else commit wins.
    """
    haystack = (messages_text or "").lower()
    commitments = list(extracted.get("commitments") or [])
    events = list(extracted.get("events") or [])
    questions = list(extracted.get("open_questions") or [])

    # 1+2: commits → questions / drop noise.
    kept_commits: List[Dict[str, Any]] = []
    for c in commitments:
        text = (c.get("text") or "").strip()
        if not text:
            continue
        if _QUESTION_TAIL_RE.search(text):
            questions.append(
                {
                    # ``direction`` semantics for questions: from_me means
                    # I asked the partner; to_me means partner asked me.
                    "direction": c.get("direction") or "from_me",
                    "text": text,
                }
            )
            continue
        deadline_raw = (c.get("deadline_raw") or "").strip()
        # Without a deadline, require at least 4 words — "как раз занимаюсь"
        # / "попрошу команду" / "сделаю" are reactions, not commitments.
        if not deadline_raw and len(text.split()) < 4:
            continue
        kept_commits.append(c)

    # 3+4+5: events — drop tiny, dedup, validate dates.
    kept_events: List[Dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for e in events:
        desc = (e.get("description") or "").strip()
        if len(desc.split()) < 2:
            continue
        when_raw_orig = (e.get("when_raw") or "").strip() or None

        key = (_normalize_for_match(desc), _normalize_for_match(when_raw_orig or ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        when_raw = when_raw_orig
        if when_raw:
            time_match = _TIME_HHMM_RE.search(when_raw)
            if time_match:
                hh, mm = time_match.group(1), time_match.group(2)
                # Both literal and zero-padded forms.
                literal = f"{hh}:{mm}"
                padded = f"{int(hh):02d}:{mm}"
                if literal not in haystack and padded not in haystack:
                    when_raw = None
            if when_raw:
                dm = _DAY_MONTH_RE.search(when_raw)
                if dm and dm.group(1) not in haystack:
                    when_raw = None

        e["when_raw"] = when_raw
        # Force re-parse from sanitised when_raw (DigestService._persist also
        # re-parses, but be explicit so downstream stat code doesn't see a
        # stale when_at after we wiped when_raw).
        if when_raw is None:
            e["when_at"] = None
        kept_events.append(e)

    # 6: cross-bucket overlap.
    event_by_key: Dict[str, int] = {}
    for idx, e in enumerate(kept_events):
        ekey = _normalize_for_match(e.get("description"))
        event_by_key.setdefault(ekey, idx)

    drop_commit_idx: set[int] = set()
    drop_event_idx: set[int] = set()
    for ci, c in enumerate(kept_commits):
        ckey = _normalize_for_match(c.get("text"))
        if ckey in event_by_key:
            ei = event_by_key[ckey]
            if kept_events[ei].get("when_raw"):
                drop_commit_idx.add(ci)
            else:
                drop_event_idx.add(ei)

    extracted["commitments"] = [c for i, c in enumerate(kept_commits) if i not in drop_commit_idx]
    extracted["events"] = [e for i, e in enumerate(kept_events) if i not in drop_event_idx]
    extracted["open_questions"] = questions
    return extracted


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
        body_parts: List[str] = []  # captured for daily_digests.body_md

        if not items:
            quiet = f"📊 Дайджест за {date_str}\n" "Тихий день — ни в одном чате не было сообщений."
            await self.bot.send_message(settings.OWNER_ID, quiet)
            body_parts.append(quiet)
        else:
            header = self._render_header(items, date_str)
            await self._send_md(header)
            body_parts.append(header)

            for item in items:
                block = await self._process_and_send_chat(item, day)
                body_parts.append(block)

            # Classification suggestions only after the day's prose is done
            # so the owner sees the digest first, then the meta-questions.
            await self._suggest_classifications(items)

        if record:
            entry = DailyDigest(
                digest_date=day,
                sent_at=datetime.now(timezone.utc),
                chat_count=len(items),
                message_count=sum(len(i.messages) for i in items),
                body_md="\n\n".join(body_parts) if body_parts else None,
            )
            self.session.add(entry)
            await self.session.commit()
        return len(items)

    # ---- internals ---- #

    def _render_header(self, items: Sequence[_ChatDigestItem], date_str: str) -> str:
        groups = sum(1 for i in items if not _is_business_private(i.chat))
        privates = sum(1 for i in items if _is_business_private(i.chat))
        return (
            f"📊 *Дайджест за {md_escape(date_str)}* — {len(items)} чат\\(ов\\)\n"
            f"_групповых: {groups}, личных: {privates}_"
        )

    async def _process_and_send_chat(self, item: _ChatDigestItem, day: date) -> str:
        """Render and send a single chat block; return the rendered MarkdownV2."""
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
        return block

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

        extracted = await OpenAIService.complete_json(
            prompt,
            rendered,
            system="Ты помощник владельца. Возвращай только валидный JSON по схеме из инструкции.",
        )
        # TECH-012 (step A): defensive filters on top of LLM output —
        # questions don't belong in commits, halluciated 18:00 is dropped,
        # cross-bucket duplicates collapse. ``messages_text`` is the same
        # source the LLM saw, so haystack-based time/date checks are fair.
        return _sanitize_extracted(extracted, formatted or "")

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
            # Urgency comes from any of: explicit LLM flag, parsed
            # deadline within 24h, or an urgency keyword anywhere in
            # ``deadline_raw`` / ``text`` (covers "срочно"/"asap"/"eod"
            # even when the deadline itself is unparseable).
            keyword_urgent = has_urgency_keyword(deadline_raw) or has_urgency_keyword(text)
            self.session.add(
                Commitment(
                    chat_id=chat.id,
                    direction=direction,
                    text=text,
                    deadline_raw=deadline_raw,
                    deadline_at=deadline_at,
                    is_urgent=(
                        llm_urgent or is_within_24h(deadline_at, now_utc=now_utc) or keyword_urgent
                    ),
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
            keyword_urgent = has_urgency_keyword(when_raw) or has_urgency_keyword(description)
            self.session.add(
                Event(
                    chat_id=chat.id,
                    description=description,
                    when_raw=when_raw,
                    when_at=when_at,
                    is_urgent=(
                        llm_urgent or is_within_24h(when_at, now_utc=now_utc) or keyword_urgent
                    ),
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


async def suggest_classification_for_chat(
    bot: Bot,
    session: AsyncSession,
    *,
    chat: Chat,
    messages: List[DBMessage],
) -> None:
    """Run the classifier on ``chat``'s ``messages`` and post a suggestion card.

    Public entry point for ad-hoc usage from owner commands (e.g.
    ``/glossary suggest``). Reuses the same prompt + card rendering as the
    daily digest so the UX is identical: model proposes, owner taps a button.
    Empty ``messages`` lists are no-ops.
    """
    if not messages:
        return
    svc = DigestService(session, bot)
    item = _ChatDigestItem(chat=chat, messages=messages)
    suggestion = await svc._classify_chat(item)
    await svc._send_classification_card(item, suggestion)


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
