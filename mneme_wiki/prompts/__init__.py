"""System prompts, one Markdown file per stage (AGENTS.md: prompts live in one place).

Kept as files so a prompt can be read and diffed as text, and the bench can compare
prompt versions without touching code.
"""

from __future__ import annotations

from functools import cache
from importlib import resources


@cache
def load_prompt(name: str) -> str:
    return resources.files(__package__).joinpath(f"{name}.md").read_bytes().decode("utf-8").strip()
