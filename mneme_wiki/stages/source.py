"""The source page: summary + metadata, and the list of pages this source updated.

Uses the packet's upstream `summary.md` if there is one, otherwise one `summary`
call. A source page keeps the source's language (TD-17). The "Pages updated from
this source" section is owned by the pipeline and rewritten on every run, which is
what makes links run both ways (page → source via citations, source → page here).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .. import edits, links
from .. import frontmatter as fm
from ..llm import LLM
from ..packet import Packet
from ..vault import Page, Vault

TOUCHED_SECTION = "Pages updated from this source"
SUMMARY_INPUT_WORDS = 6000  # ≈ 8k tokens, the top of the per-call budget (L-2)

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "key_points"],
}
SYSTEM = (
    "Summarise the document for a wiki source page. summary: 2-4 sentences, what the "
    "document is and covers. key_points: 4-10 short bullet points with the most important "
    "content. Use only the document. Write abbreviations exactly as the document does: "
    "never spell one out unless the document itself does. Write in the language of the "
    "document."
)


@dataclass
class Summary:
    text: str
    key_points: list[str]
    upstream: bool


def find_existing(ws: Vault, origin: str) -> str | None:
    """Path of a source page with this `origin`, if the source was integrated before."""
    for rel, page in ws.iter_pages():
        if isinstance(page, Page) and page.meta.get("type") == "source":
            if str(page.meta.get("origin") or "").strip() == origin.strip():
                return rel
    return None


def summarise(llm: LLM, packet: Packet) -> Summary:
    if packet.summary:
        body = packet.summary.strip()
        lines = body.split("\n")
        if lines and lines[0].startswith("# "):  # drop the upstream H1; the page has its own
            body = "\n".join(lines[1:]).strip()
        return Summary(body, [], True)
    words = packet.text.split()
    user = f"Title: {packet.title}\n\n" + " ".join(words[:SUMMARY_INPUT_WORDS])
    data = llm.for_role("summary").json(SYSTEM, user, SCHEMA, step=f"summary {packet.name}")
    if data is None:
        return Summary("(The summary could not be generated.)", [], False)
    points = [" ".join(str(p).split()) for p in data.get("key_points") or [] if str(p).strip()]
    return Summary(" ".join(str(data.get("summary") or "").split()), points[:12], False)


def source_meta(packet: Packet, today: dt.date) -> dict:
    m = packet.meta
    meta: dict = {
        "title": packet.title,
        "type": "source",
        "tags": [],
        "created": today,
        "updated": today,
        "status": "active",
        "source_type": str(m["source_type"]),
        "origin": str(m["origin"]),
    }
    if m.get("author"):
        meta["author"] = str(m["author"])
    published = m.get("published") or m.get("date")
    if published:
        meta["published"] = str(published)
    meta["ingested"] = today
    if m.get("language"):
        meta["language"] = str(m["language"])
    return meta


def source_page(packet: Packet, path: str, summary: Summary, today: dt.date) -> Page:
    body = f"\n# {packet.title}\n\n{summary.text}\n"
    if summary.key_points:
        body += "\n## Key points\n\n" + "\n".join(f"- {p}" for p in summary.key_points) + "\n"
    return Page(path, fm.new_document(source_meta(packet, today), body))


def set_touched(page: Page, touched: list[tuple[str, str]]) -> None:
    """Rewrite the 'Pages updated from this source' section with `touched` (path, title)."""
    parts = edits.split(page.body.replace("\r\n", "\n"))
    listing = [f"- {links.format_link(p, alias=t)}" for p, t in sorted(touched, key=lambda x: x[0])]
    lines = [f"## {TOUCHED_SECTION}", "", *(listing or ["(none)"]), ""]
    section = parts.find(TOUCHED_SECTION)
    if section is not None:
        section.lines = lines
    else:
        edits.ensure_blank_end(parts)
        parts.sections.append(edits.Section(TOUCHED_SECTION, lines))
    page.body = parts.render()
