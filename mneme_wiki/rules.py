"""Domain rules (#14): a vault's own rules for the model, from `WIKI.md`.

A vault can add a `## Domain rules` section to its `WIKI.md`: short bullet points in
plain language, written by the human ("'AP' means 'Activity Plan', never 'work
package'"; "A rover and its mission are different things"). Extract and resolve get
the section's text appended to their system prompt under a fixed heading (D1: the two
stages that decide what becomes a page and what merges; patch doesn't get it).

- Free text only (D2): names belong in the glossary (#24), kinds and relations in the
  ontology (#16).
- HTML comments are dropped, so the template's commented example is inactive.
- Without the section, or with an empty one, every prompt is byte for byte what it
  was before (`with_rules` returns the system prompt unchanged).
- The text is paid on every call (~120 resolve calls per source), so `lint` warns
  above `MAX_CHARS` (D3), and each run records the rules' hash (D4).
"""

from __future__ import annotations

import hashlib
import re

from .vault import SCHEMA_FILE, Vault

SECTION = "Domain rules"
HEADING = "## Rules for this vault"  # what the model sees
MAX_CHARS = 1500
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_H2 = re.compile(r"^##[ \t]+(.+?)[ \t#]*$")


def section(markdown: str) -> tuple[str, int] | None:
    """The raw text of the `## Domain rules` section and its 1-based heading line, or
    None. Headings inside code fences don't count."""
    lines = markdown.splitlines()
    fence = None
    start = None
    for n, line in enumerate(lines):
        m = _FENCE.match(line)
        if m:
            marker = m.group(1)[0]
            fence = None if fence == marker else (fence or marker)
            continue
        if fence:
            continue
        h = _H2.match(line)
        if not h:
            continue
        if start is not None:
            return "\n".join(lines[start + 1 : n]), start + 1
        if h.group(1).strip().casefold() == SECTION.casefold():
            start = n
    if start is not None:
        return "\n".join(lines[start + 1 :]), start + 1
    return None


def clean(raw: str) -> str:
    """The rules as the model sees them: comments dropped, blank runs collapsed."""
    text = _COMMENT.sub("", raw)
    out: list[str] = []
    for line in text.splitlines():
        line = line.rstrip()
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def load(vault: Vault) -> str:
    """The vault's domain rules, or "" (no `WIKI.md`, no section, or only comments)."""
    if not vault.exists(SCHEMA_FILE):
        return ""
    # The raw text, not a parsed page: front matter has no `## ` headings, and a
    # broken front matter in WIKI.md must not stop every integration.
    found = section(vault.read_text(SCHEMA_FILE))
    return clean(found[0]) if found else ""


def with_rules(system: str, rules: str) -> str:
    """`system` with the rules appended; unchanged without rules."""
    if not rules:
        return system
    return f"{system.rstrip()}\n\n{HEADING}\n\n{rules}\n"


def digest(rules: str) -> str:
    """Short hash for run reports (D4); "" without rules."""
    return hashlib.sha256(rules.encode("utf-8")).hexdigest()[:12] if rules else ""
