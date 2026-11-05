"""Markdown body structure without an AST library (TD-9).

Splits a page body into blocks (headings, paragraphs, list items, tables, quotes,
code, embeds) with line numbers, and turns Markdown into plain text. Used by lint
(uncited claims), the index (lead sentence), search and the integration stages.
Only the subset of Markdown the vault uses is recognised; anything unusual falls
back to "paragraph", which is the safe choice for every caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import links

_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.*?)[ \t#]*$")
_LIST = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]+")
_QUOTE = re.compile(r"^[ \t]{0,3}>")
_TABLE = re.compile(r"^[ \t]*\|")
_RULE = re.compile(r"^[ \t]{0,3}([-*_])([ \t]*\1){2,}[ \t]*$")
_EMBED_LINE = re.compile(r"^[ \t]*(!\[\[[^\]]+\]\][ \t]*)+$")
_HTML = re.compile(r"^[ \t]{0,3}<")
_WORD = re.compile(r"\w+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9\"“(\[])")


@dataclass(frozen=True)
class Block:
    kind: str  # heading | paragraph | list_item | table | quote | code | embed | html | rule
    text: str  # raw Markdown of the block (lines joined with "\n")
    line: int  # 1-based line in the scanned text where the block starts
    level: int = 0  # heading level (1-6), else 0


def blocks(text: str) -> list[Block]:
    """The blocks of `text` in order. Blank lines are not blocks."""
    out: list[Block] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        start = i + 1
        if not line.strip():
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            mark = fence.group(1)
            j = i + 1
            while j < len(lines):
                close = _FENCE.match(lines[j])
                if close and close.group(1)[0] == mark[0] and len(close.group(1)) >= len(mark):
                    break
                j += 1
            out.append(Block("code", "\n".join(lines[i : j + 1]), start))
            i = j + 1
            continue
        heading = _HEADING.match(line)
        if heading:
            out.append(Block("heading", heading.group(2).strip(), start, len(heading.group(1))))
            i += 1
            continue
        if _RULE.match(line):
            out.append(Block("rule", line, start))
            i += 1
            continue
        for kind, pattern in (("quote", _QUOTE), ("table", _TABLE), ("html", _HTML)):
            if pattern.match(line):
                j = i + 1
                while (
                    j < len(lines)
                    and lines[j].strip()
                    and (kind == "html" or pattern.match(lines[j]))
                ):
                    j += 1
                out.append(Block(kind, "\n".join(lines[i:j]), start))
                i = j
                break
        else:
            if _EMBED_LINE.match(line):
                out.append(Block("embed", line, start))
                i += 1
                continue
            item = _LIST.match(line)
            j = i + 1
            while j < len(lines) and lines[j].strip() and not _starts_block(lines[j]):
                j += 1
            out.append(Block("list_item" if item else "paragraph", "\n".join(lines[i:j]), start))
            i = j
    return out


def _starts_block(line: str) -> bool:
    return bool(
        _FENCE.match(line)
        or _HEADING.match(line)
        or _LIST.match(line)
        or _QUOTE.match(line)
        or _TABLE.match(line)
        or _RULE.match(line)
    )


def lead(body: str) -> Block | None:
    """The lead paragraph: the first paragraph before the first H2, if any."""
    for block in blocks(body):
        if block.kind == "heading" and block.level >= 2:
            return None
        if block.kind == "paragraph":
            return block
    return None


_CITATION = re.compile(r"\s*\(\s*(?:\[\[sources/[^\]]*\]\][\s,;]*)+\)")
_LIST_MARK = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~|==)(?=\S)(.+?)(?<=\S)\1")
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def plain(markdown: str, *, drop_citations: bool = True) -> str:
    """Readable plain text: link syntax → display text, emphasis and list marks removed."""
    text = _CITATION.sub("", markdown) if drop_citations else markdown

    def show(link: links.Link) -> str:
        if link.embed:
            return ""
        if link.alias:
            return link.alias
        name = link.target.rsplit("/", 1)[-1] if link.target else ""
        if name.lower().endswith(".md"):
            name = name[:-3]
        return name.replace("-", " ") if name else (link.heading or "")

    found = links.extract(text)
    parts, pos = [], 0
    for link in found:
        parts.append(text[pos : link.start])
        parts.append(show(link))
        pos = link.end
    parts.append(text[pos:])
    text = "".join(parts)
    text = _MD_LINK.sub(r"\1", text)
    text = _LIST_MARK.sub("", text)
    text = text.replace("`", "")
    for _ in range(2):  # nested emphasis
        text = _EMPHASIS.sub(r"\2", text)
    return " ".join(text.split())


def first_sentence(text: str, max_len: int = 100) -> str:
    """The first sentence of plain `text`, cut at a word boundary to `max_len` chars."""
    sentence = _SENTENCE_END.split(text.strip(), maxsplit=1)[0]
    if len(sentence) <= max_len:
        return sentence
    cut = sentence[: max_len - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def tokens(text: str) -> list[str]:
    """Search tokens: casefolded Unicode words, no stemming (sources are multilingual)."""
    return [t for t in _WORD.findall(text.casefold()) if len(t) > 1 or t.isdigit()]
