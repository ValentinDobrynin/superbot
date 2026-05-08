"""MarkdownV2 helpers for Telegram messages.

Telegram MarkdownV2 is strict: every reserved character outside of formatting
constructs must be escaped with a backslash, otherwise Telegram returns
``Bad Request: can't parse entities``. We always render digest text with
plain user content escaped via :func:`md_escape` and only wrap statically
controlled chunks (``*bold*``, ``_italic_``, ``\\(``, ``\\)``) ourselves.

See: https://core.telegram.org/bots/api#markdownv2-style
"""

from __future__ import annotations

import re
from typing import Iterable, List

# All MarkdownV2 reserved characters. Order doesn't matter for the regex; the
# class is exhaustive per Telegram docs.
_MD2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"
_MD2_RE = re.compile(f"([{re.escape(_MD2_SPECIAL)}])")

# Telegram message hard limit. We chunk well below it to leave room for
# Telegram's own formatting overhead.
TELEGRAM_MAX = 4096
SAFE_LIMIT = 3800


def md_escape(text: str | None) -> str:
    """Escape arbitrary user text for safe use in MarkdownV2."""
    if not text:
        return ""
    return _MD2_RE.sub(r"\\\1", text)


def chunk_md(text: str, *, limit: int = SAFE_LIMIT) -> List[str]:
    """Split a MarkdownV2 message into Telegram-sized chunks on blank lines.

    The splitter is conservative: it only breaks on already-present
    ``"\\n\\n"`` boundaries, so it will never split a formatting span across
    chunks. If a single block is larger than ``limit`` it is sent as-is and
    Telegram will reject it; the caller should send shorter blocks.
    """
    if len(text) <= limit:
        return [text]

    blocks = text.split("\n\n")
    out: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for block in blocks:
        # +2 accounts for the "\n\n" we'll glue back in.
        block_len = len(block) + 2
        if buf and buf_len + block_len > limit:
            out.append("\n\n".join(buf))
            buf = [block]
            buf_len = block_len
        else:
            buf.append(block)
            buf_len += block_len
    if buf:
        out.append("\n\n".join(buf))
    return out


def join_lines(lines: Iterable[str]) -> str:
    """Join MarkdownV2 lines with a single ``\\n``."""
    return "\n".join(lines)
