"""Unit tests for ``src.services.prompts.load_prompt``."""

from __future__ import annotations

import pytest

from src.services.prompts import PROMPTS_DIR, _parse, load_prompt


def test_parse_extracts_metadata_and_body():
    raw = (
        "# model: gpt-4\n"
        "# temperature: 0.5\n"
        "# max_tokens: 42\n"
        "# purpose: testing\n"
        "# version: 3\n"
        "Hello {name}\n"
    )
    spec = _parse("test", raw)

    assert spec.model == "gpt-4"
    assert spec.temperature == 0.5
    assert spec.max_tokens == 42
    assert spec.purpose == "testing"
    assert spec.version == 3
    assert spec.template == "Hello {name}"
    assert spec.format(name="world") == "Hello world"


def test_parse_uses_defaults_when_no_metadata():
    spec = _parse("anon", "just a body")
    assert spec.model == "gpt-3.5-turbo"
    assert spec.temperature == 0.7
    assert spec.max_tokens is None
    assert spec.template == "just a body"


def test_load_prompt_reads_each_repository_prompt():
    """Every shipped prompt must parse and expose a non-empty template."""
    for path in PROMPTS_DIR.glob("*.txt"):
        spec = load_prompt(path.stem)
        assert spec.template, f"{path.name} has empty body"
        assert spec.model, f"{path.name} missing model"


def test_load_prompt_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_prompt("does-not-exist")
