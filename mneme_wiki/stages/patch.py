"""Stage 3d, patch: one model call per page → a proposed edit, validated by edits.py.

The model sees the current page (or a skeleton for a new page), the new claims
with their locators, and the pages it may link to. It returns a lead and
section operations, never a whole file. If `edits.apply` rejects an operation for
a reason the model can fix (a replace that drops links, or shrinks a section), the
model is asked once more with the reasons; whatever is still rejected after that is
reported, and the valid rest is applied.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .. import edits, links
from .. import frontmatter as fm
from ..llm import LLM
from ..prompts import load_prompt
from ..search import Doc, SearchIndex
from ..vault import Page, Vault
from .common import KnownPage, name_key, unique
from .plan import PagePlan

LINKABLE_LIMIT = 40
PAGE_CHAR_BUDGET = 24_000  # ≈ 6k tokens; bigger pages get headings only (see prompt)
STUB_MAX_CLAIMS = 2

SCHEMA = {
    "type": "object",
    "properties": {
        "lead": {"type": "string"},
        "ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "op": {"type": "string", "enum": ["append", "replace"]},
                    "text": {"type": "string"},
                },
                "required": ["section", "op", "text"],
            },
        },
    },
    "required": ["lead", "ops"],
}

SYSTEM = load_prompt("patch")

LANGUAGES = {"en": "English", "de": "German", "fr": "French", "it": "Italian", "es": "Spanish"}


@dataclass
class PatchResult:
    path: str
    new: bool
    written: bool
    rejected: list[edits.Rejection] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    proposal: dict | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "new": self.new,
            "written": self.written,
            "rejected": [r.to_dict() for r in self.rejected],
            "counters": self.counters,
            "error": self.error,
        }


def language_name(code: str) -> str:
    return LANGUAGES.get(code.lower(), code)


def skeleton(entry: PagePlan, source: str) -> str:
    lead = entry.description.strip() or entry.claims[0].text
    return f"\n# {entry.title}\n\n{lead} ([[{source}]])\n"


def new_meta(entry: PagePlan, today: dt.date) -> dict:
    meta = {
        "title": entry.title,
        "type": entry.kind,
        "aliases": [],
        "tags": [],
        "created": today,
        "updated": today,
        "sources": [],
        "status": "stub" if len(entry.claims) <= STUB_MAX_CLAIMS else "active",
    }
    if entry.kind == "entity":
        meta["entity_kind"] = entry.entity_kind
    return meta


def page_for_prompt(body: str) -> str:
    """The page as the model sees it; over budget, the sections are reduced to headings."""
    if len(body) <= PAGE_CHAR_BUDGET:
        return body
    parts = edits.split(body)
    pre = "\n".join(parts.pre)[: PAGE_CHAR_BUDGET // 2]
    heads = "\n".join(
        f"## {s.name}\n(… {len(edits.section_content(s))} chars, not shown …)"
        for s in parts.sections
    )
    return f"{pre}\n\n{heads}\n\n(Page too long to show in full: append only, never replace.)"


def linkable(
    entry: PagePlan, plans: list[PagePlan], pages: list[KnownPage]
) -> list[tuple[str, str]]:
    """(id, title) pairs: pages planned in this run first, then existing pages related to
    the claims (BM25), minus the page itself."""
    out: dict[str, str] = {}
    for p in plans:
        if p.path != entry.path:
            out.setdefault(p.path.removesuffix(".md"), p.title)
    if pages:
        index = SearchIndex(
            Doc(p.path, p.title, p.type, p.aliases, p.description, "") for p in pages
        )
        query = " ".join([entry.title, *(c.text for c in entry.claims)])[:4000]
        for hit in index.search(query, limit=LINKABLE_LIMIT, exclude=[entry.path]):
            out.setdefault(hit.path.removesuffix(".md"), hit.title)
    return list(out.items())[:LINKABLE_LIMIT]


def user_prompt(
    entry: PagePlan, body: str, source: str, source_title: str, link_list: list[tuple[str, str]]
) -> str:
    claims = "\n".join(f"- {c.text}  (section: {c.locator})" for c in entry.claims)
    targets = "\n".join(f"- [[{pid}|{title}]]" for pid, title in link_list) or "(none)"
    return (
        f'Source id: {source}  ("{source_title}")\n\n'
        f"--- CURRENT PAGE ({entry.path.removesuffix('.md')}) ---\n{page_for_prompt(body)}\n"
        f'--- END PAGE ---\n\nNew claims about "{entry.title}" from the source:\n{claims}\n\n'
        f"Linkable pages:\n{targets}"
    )


def retry_prompt(base: str, rejected: list[edits.Rejection]) -> str:
    reasons = "\n".join(f"- {r.reason}" for r in rejected)
    return (
        f"{base}\n\nYour previous answer was partly rejected:\n{reasons}\n"
        "Answer again. A replace must keep every link and citation of the section and "
        "must not shorten it; if unsure, use append."
    )


def patch_page(
    llm: LLM,
    ws: Vault,
    entry: PagePlan,
    plans: list[PagePlan],
    pages: list[KnownPage],
    ctx: edits.Context,
    *,
    source_title: str,
    language: str,
    today: dt.date,
    step: str,
    reserved_names: dict[str, str],
) -> PatchResult:
    """Propose, validate and write one page into `ws` (a Workspace)."""
    result = PatchResult(entry.path, entry.new, False)
    if entry.new:
        page = Page(
            entry.path, fm.new_document(new_meta(entry, today), skeleton(entry, ctx.source))
        )
    else:
        page = ws.read_page(entry.path)
    body = page.body.replace("\r\n", "\n")
    client = llm.for_role("patch")
    system = SYSTEM.replace("{source}", ctx.source).replace("{language}", language_name(language))
    base = user_prompt(entry, body, ctx.source, source_title, linkable(entry, plans, pages))

    applied: edits.Result | None = None
    prompt = base
    for attempt in (1, 2):
        data = client.json(system, prompt, SCHEMA, step=step if attempt == 1 else f"{step} (again)")
        if data is None:
            result.error = "no valid answer from the model"
            break
        proposal = edits.Proposal.from_json(data)
        result.proposal = proposal.to_dict()
        applied = edits.apply(body, proposal, ctx)
        retryable = [r for r in applied.rejected if r.retry]
        if attempt == 1 and retryable:
            prompt = retry_prompt(base, retryable)
            continue
        break

    if applied is None:
        if not entry.new:
            return result
        applied = edits.Result(body, True)  # new page: the skeleton alone is still a page
    result.rejected = applied.rejected
    result.counters = applied.counters
    if not applied.changed and not entry.new:
        return _finish_meta(ws, page, entry, ctx, today, result, reserved_names, body_changed=False)
    page.body = applied.body
    return _finish_meta(ws, page, entry, ctx, today, result, reserved_names, body_changed=True)


def _finish_meta(
    ws: Vault,
    page: Page,
    entry: PagePlan,
    ctx: edits.Context,
    today: dt.date,
    result: PatchResult,
    reserved_names: dict[str, str],
    *,
    body_changed: bool,
) -> PatchResult:
    meta = page.meta
    citation = links.format_link(ctx.source)
    sources = meta.get("sources") if isinstance(meta.get("sources"), list) else []
    if not body_changed and citation in sources:
        return result
    # Aliases: add the new names, unless another page already uses one (that would
    # be a duplicate-name lint error and break exact resolve).
    current = meta.get("aliases") if isinstance(meta.get("aliases"), list) else []
    mine = {name_key(n) for n in [page.title, *current]}
    addable = []
    for alias in entry.aliases:
        owner = reserved_names.get(name_key(alias))
        if owner in (None, page.path) and name_key(alias) not in mine:
            addable.append(alias)
    aliases = unique([*current, *addable], exclude=[page.title])
    if aliases != current:
        meta["aliases"] = aliases
    for alias in aliases:
        reserved_names.setdefault(name_key(alias), page.path)
    if citation not in sources:
        meta["sources"] = [*sources, citation]
    meta["updated"] = today
    ws.write_page(page)
    result.written = True
    return result
