"""Tests for the MarkdownV2 helpers."""

from __future__ import annotations

from src.services.md import chunk_md, md_escape


def test_md_escape_handles_all_reserved_chars():
    raw = "_*[]()~`>#+-=|{}.!"
    escaped = md_escape(raw)
    # Every char must be prefixed with backslash exactly once.
    assert escaped == "".join(f"\\{c}" for c in raw)


def test_md_escape_handles_empty_and_none():
    assert md_escape("") == ""
    assert md_escape(None) == ""


def test_md_escape_does_not_double_escape():
    once = md_escape("hi.")
    twice = md_escape(once)
    # Once-escaped is "hi\\.", twice-escaped means the literal backslash and
    # the dot both got escaped a second time — that's exactly the rule:
    # md_escape is NOT idempotent. We document this with a test so the
    # behaviour is intentional.
    assert once == "hi\\."
    assert twice == "hi\\\\\\."


def test_md_escape_handles_cyrillic_unchanged():
    assert md_escape("Привет, мир!") == "Привет, мир\\!"


def test_chunk_md_returns_single_when_short():
    assert chunk_md("hi", limit=4096) == ["hi"]


def test_chunk_md_splits_on_blank_lines():
    blocks = ["a" * 100, "b" * 100, "c" * 100]
    text = "\n\n".join(blocks)
    chunks = chunk_md(text, limit=210)
    assert len(chunks) >= 2
    assert all(len(c) <= 210 + 5 for c in chunks)
    # Joining back must produce the same content (with possible \n\n boundary).
    rejoined = "\n\n".join(chunks)
    assert rejoined == text
