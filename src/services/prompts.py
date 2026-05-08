"""Loader for prompt templates that live in the top-level ``prompts/`` folder.

A prompt file is plain UTF-8 text. The first lines starting with ``# key: value``
are parsed as metadata; everything after is the template body, used as a
``str.format`` template.

Recognised metadata keys:

- ``model``       — OpenAI model name (default ``gpt-3.5-turbo``).
- ``temperature`` — float (default ``0.7``).
- ``max_tokens``  — int (optional).
- ``purpose``     — free-text description (informational only).
- ``version``     — int (optional).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@dataclass(frozen=True)
class PromptSpec:
    """A loaded prompt: metadata + template body."""

    name: str
    template: str
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    purpose: Optional[str] = None
    version: Optional[int] = None

    def format(self, **kwargs: object) -> str:
        """Render the template with the given keyword arguments."""
        return self.template.format(**kwargs)


def _parse(name: str, text: str) -> PromptSpec:
    meta: dict[str, str] = {}
    body_lines: list[str] = []
    in_header = True
    for line in text.splitlines():
        if in_header and line.startswith("#"):
            stripped = line.lstrip("#").strip()
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                meta[key.strip().lower()] = value.strip()
            continue
        in_header = False
        body_lines.append(line)

    template = "\n".join(body_lines).strip("\n")

    return PromptSpec(
        name=name,
        template=template,
        model=meta.get("model", "gpt-3.5-turbo"),
        temperature=float(meta.get("temperature", "0.7")),
        max_tokens=int(meta["max_tokens"]) if "max_tokens" in meta else None,
        purpose=meta.get("purpose"),
        version=int(meta["version"]) if "version" in meta else None,
    )


@lru_cache(maxsize=None)
def load_prompt(name: str) -> PromptSpec:
    """Load and cache a prompt by basename (with or without ``.txt``)."""
    filename = name if name.endswith(".txt") else f"{name}.txt"
    path = PROMPTS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return _parse(name=path.stem, text=path.read_text(encoding="utf-8"))
