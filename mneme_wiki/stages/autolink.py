"""Autolink (code, TD-19): link the first plain mention of another page's name.

M0: code linking gave ~2 links per page, the model without thinking 0.16. Rules:
- only prose: paragraphs and list items; never headings, tables, quotes/callouts,
  code, existing links, Markdown links or URLs;
- one link per target per page, and none if the page already links there;
- longest names first ("Integrated Activity Plan" before "Activity Plan");
- names of ≤ 5 characters match case-sensitively (`TIME`, `Task` are not `Time`,
  `task`), longer names case-insensitively; names under 3 characters never;
- a name that two pages claim is skipped (it's ambiguous; lint reports it).
Only the pages written in this run are linked, so the run's diff stays its own.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .. import links, text
from ..vault import Page, Vault
from .common import name_key

MIN_NAME = 3
CASE_SENSITIVE_MAX = 5
_SKIP_SUFFIX = (".md", ".xlsx", ".docx", ".pdf", ".json", ".csv", ".png")
_MD_LINK = re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)")
_URL = re.compile(r"https?://\S+|www\.\S+")
_PROSE = ("paragraph", "list_item")


@dataclass(frozen=True)
class Name:
    name: str
    target: str  # page path


def names_for(pages: list[Page]) -> list[Name]:
    """Linkable names of entity/concept pages, longest first; ambiguous ones dropped."""
    owners: dict[str, set[str]] = defaultdict(set)
    spelled: list[Name] = []
    for page in pages:
        if page.meta.get("type") not in ("entity", "concept"):
            continue
        aliases = page.meta.get("aliases") if isinstance(page.meta.get("aliases"), list) else []
        for n in {page.title, *(a for a in aliases if isinstance(a, str))}:
            n = " ".join(n.split())
            if len(n) >= MIN_NAME and not n.lower().endswith(_SKIP_SUFFIX) and name_key(n):
                owners[name_key(n)].add(page.path)
                spelled.append(Name(n, page.path))
    out = [nm for nm in spelled if len(owners[name_key(nm.name)]) == 1]
    out.sort(key=lambda nm: (-len(nm.name), nm.name))
    return out


def _mask(body: str) -> str:
    """`body` with every place a link must not go replaced by spaces (offsets kept)."""
    masked = list(links.mask_code(body))

    def blank(start: int, end: int) -> None:
        for i in range(start, end):
            if masked[i] not in "\r\n":
                masked[i] = " "

    for link in links.extract(body):
        blank(link.start, link.end)
    for rx in (_MD_LINK, _URL):
        for m in rx.finditer(body):
            blank(m.start(), m.end())
    line_starts = [0] + [i + 1 for i, ch in enumerate(body) if ch == "\n"]
    prose_lines: set[int] = set()
    for block in text.blocks(body):
        if block.kind in _PROSE:
            prose_lines.update(range(block.line, block.line + block.text.count("\n") + 1))
    for n, start in enumerate(line_starts, 1):
        if n not in prose_lines:
            end = line_starts[n] if n < len(line_starts) else len(body)
            blank(start, end)
    return "".join(masked)


def link_body(body: str, path: str, names: list[Name], index: links.LinkIndex) -> tuple[str, int]:
    """Add links to `body`; returns (new body, links added)."""
    linked = {index.resolve(lk.target) for lk in links.extract(body) if lk.target}
    added = 0
    masked = _mask(body)
    for nm in names:
        if nm.target == path or nm.target in linked:
            continue
        flags = 0 if len(nm.name) <= CASE_SENSITIVE_MAX else re.IGNORECASE
        rx = re.compile(rf"(?<![\w\[|/#-]){re.escape(nm.name)}(?![\w\]-])", flags)
        m = rx.search(masked)
        if not m:
            continue
        shown = body[m.start() : m.end()]
        body = body[: m.start()] + links.format_link(nm.target, alias=shown) + body[m.end() :]
        masked = _mask(body)
        linked.add(nm.target)
        added += 1
    return body, added


def autolink(ws: Vault, paths: list[str]) -> dict[str, int]:
    """Autolink the pages `paths` in `ws`; returns {path: links added}."""
    pages = [p for _, p in ws.iter_pages() if isinstance(p, Page)]
    names = names_for(pages)
    index = links.LinkIndex(ws.files())
    by_path = {p.path: p for p in pages}
    added: dict[str, int] = {}
    for path in paths:
        page = by_path.get(path)
        if page is None:
            continue
        new_body, n = link_body(page.body, path, names, index)
        if n:
            page.body = new_body
            ws.write_page(page)
            added[path] = n
    return added
