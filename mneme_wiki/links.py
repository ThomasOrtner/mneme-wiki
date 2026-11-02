"""Obsidian wikilinks: extract, resolve, alias and backlink maps (TD-9).

Our own regex instead of a Markdown AST. Supported:
`[[page]]`, `[[folder/page]]`, `[[page|alias]]`, `[[page#heading]]`,
`[[page#heading|alias]]`, `[[#heading]]` (same page), embeds `![[file]]`, and the
`\\|` escape used inside Markdown tables. Links inside fenced code blocks and
inline code are ignored, as Obsidian does.

Resolution follows Obsidian: case-insensitive, `.md` optional; a target with a
`/` matches by path (exact, then path suffix); a bare name matches by file name
anywhere in the vault, and several matches are reported as ambiguous.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

_LINK = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t#]*$")


@dataclass(frozen=True)
class Link:
    raw: str  # the full match, e.g. "[[a#b|c]]"
    target: str  # "" for a same-page heading link
    heading: str | None
    alias: str | None
    embed: bool
    start: int  # offsets into the text that was scanned
    end: int


def line_of(text: str, offset: int) -> int:
    """1-based line number of `offset` in `text`."""
    return text.count("\n", 0, offset) + 1


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def mask_code(text: str) -> str:
    """`text` with fenced and inline code replaced by spaces (same length, newlines kept)."""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        m = _FENCE.match(stripped)
        if fence is None and m:
            fence = m.group(1)[0] * len(m.group(1))
            out.append(_blank(line))
        elif fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append(_blank(line))
        else:
            out.append(_INLINE_CODE.sub(lambda mm: " " * len(mm.group(0)), line))
    return "".join(out)


def _blank(line: str) -> str:
    body = line.rstrip("\r\n")
    return " " * len(body) + line[len(body) :]


def extract(text: str) -> list[Link]:
    """All wikilinks in `text` (outside code), in order."""
    # Match on the masked text, read from the original (masking keeps offsets).
    return [_parse(text, m) for m in _LINK.finditer(mask_code(text))]


def _parse(text: str, m: re.Match) -> Link:
    inner = text[m.start(2) : m.end(2)]
    pipe = re.search(r"\\?\|", inner)  # "|" or the table-escaped "\|"
    if pipe:
        target_part, alias = inner[: pipe.start()], inner[pipe.end() :].strip() or None
    else:
        target_part, alias = inner, None
    target, has_hash, heading = target_part.partition("#")
    return Link(
        raw=text[m.start() : m.end()],
        target=target.strip(),
        heading=(heading.strip() or None) if has_hash else None,
        alias=alias,
        embed=bool(m.group(1)),
        start=m.start(),
        end=m.end(),
    )


def headings(text: str) -> list[str]:
    """ATX heading texts in `text` (outside code), in order."""
    found = []
    for line in mask_code(text).splitlines():
        m = _HEADING.match(line)
        if m:
            found.append(m.group(2).strip())
    return found


def format_link(path: str, alias: str | None = None, heading: str | None = None) -> str:
    """`[[path#heading|alias]]` for a vault-relative page path (`.md` dropped)."""
    target = path[:-3] if path.lower().endswith(".md") else path
    out = target + (f"#{heading}" if heading else "")
    return f"[[{out}|{alias}]]" if alias else f"[[{out}]]"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def _key(target: str) -> str:
    t = target.strip().replace("\\", "/").lstrip("/")
    if t.lower().endswith(".md"):
        t = t[:-3]
    return t.casefold()


class LinkIndex:
    """Resolves link targets against the files of one vault."""

    def __init__(self, paths: Iterable[str]) -> None:
        self.by_path: dict[str, str] = {}
        self.by_name: dict[str, list[str]] = defaultdict(list)
        for path in sorted(paths):
            p = PurePosixPath(path)
            key = _key(path) if p.suffix.lower() == ".md" else path.casefold()
            self.by_path[key] = path
            self.by_name[key.rsplit("/", 1)[-1]].append(path)

    def candidates(self, target: str) -> list[str]:
        """Every file `target` could mean; one item = resolved, 0 = broken, 2+ = ambiguous."""
        key = _key(target)
        if not key:
            return []
        if "/" in key:
            if key in self.by_path:
                return [self.by_path[key]]
            return sorted(p for k, p in self.by_path.items() if k.endswith("/" + key))
        return list(self.by_name.get(key, []))

    def resolve(self, target: str) -> str | None:
        """The single file `target` points to, else None (broken or ambiguous)."""
        found = self.candidates(target)
        return found[0] if len(found) == 1 else None


def normalise_name(name: str) -> str:
    """Key for comparing titles/aliases: casefolded, whitespace collapsed."""
    return " ".join(name.split()).casefold()


def alias_map(metas: Mapping[str, Mapping]) -> dict[str, set[str]]:
    """normalised title/alias → page paths that claim it (2+ paths = duplicate)."""
    out: dict[str, set[str]] = defaultdict(set)
    for path, meta in metas.items():
        names = [meta.get("title")]
        aliases = meta.get("aliases")
        if isinstance(aliases, list):
            names.extend(aliases)
        for name in names:
            if isinstance(name, str) and name.strip():
                out[normalise_name(name)].add(path)
    return dict(out)


def backlinks(links_by_page: Mapping[str, Iterable[Link]], index: LinkIndex) -> dict[str, set[str]]:
    """target path → pages linking to it. Unresolved and self links are skipped."""
    out: dict[str, set[str]] = defaultdict(set)
    for source, links in links_by_page.items():
        for link in links:
            if not link.target:
                continue
            target = index.resolve(link.target)
            if target and target != source:
                out[target].add(source)
    return dict(out)
