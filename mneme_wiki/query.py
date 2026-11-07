"""Answer a question from the wiki, and optionally file the answer back (BR-9, M5).

1. Retrieve (code): BM25 over every content page; the best pages are included in
   full while they fit the budget (L-2), the next ones as one-line index entries
   so the model knows they exist.
2. Answer (one `query` call): JSON `{answer, answerable, pages}`. The answer cites
   the source citations the pages give, and links the pages it used.
3. Check (code): links that don't resolve to an existing page are unwrapped,
   `pages` is reduced to pages that were actually shown; both are counted. An answer
   that cites no source, or spells out an abbreviation the pages don't, gets one retry
   that names the problem (M5: 28% of the answers cited nothing, though the prompt asks
   for it). Expansions still left in brackets are removed.
4. `--file`: the answer becomes a `synthesis` page (`question` field, `sources`
   = the sources it cites), then reindex, log, one git commit, through a
   `Workspace` like integrate. An answer that cites no source is not filed: it would
   become an uncited page that later queries read as fact (BR-5).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from . import edits, expansions, links, text
from . import frontmatter as fm
from .index_log import append_log, reindex
from .integrate import IntegrateError, vault_language
from .lint import lint
from .llm import LLM
from .prompts import load_prompt
from .search import SearchIndex
from .stages.patch import language_name
from .vault import Page, Vault, slugify
from .workspace import Workspace

BUDGET_CHARS = 24_000  # ≈ 6k tokens of page text; the prompt stays under ~8k (L-2)
MAX_FULL_PAGES = 8
MAX_INDEX_LINES = 20
TITLE_MAX = 90

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "answerable": {"type": "boolean"},
        "pages": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "answerable", "pages"],
}


@dataclass
class Answer:
    question: str
    answer: str
    answerable: bool
    pages: list[str]  # pages used (vault paths)
    shown: list[str]  # pages given in full
    listed: list[str]  # pages given as index lines
    sources: list[str] = field(default_factory=list)  # source pages cited in the answer
    unbacked: list[str] = field(default_factory=list)  # "ABC = Long Name" the pages lack
    counters: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    filed: str | None = None
    commit: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def retrieve(
    vault: Vault, question: str, budget: int = BUDGET_CHARS
) -> tuple[list[Page], list[Page]]:
    """(pages shown in full, pages listed by one line), best match first."""
    pages = {p.path: p for _, p in vault.iter_pages() if isinstance(p, Page)}
    hits = SearchIndex.from_vault(vault).search(question, limit=MAX_FULL_PAGES + MAX_INDEX_LINES)
    shown: list[Page] = []
    listed: list[Page] = []
    used = 0
    for hit in hits:
        page = pages[hit.path]
        size = len(page.body)
        if len(shown) < MAX_FULL_PAGES and (used + size <= budget or not shown):
            shown.append(page)
            used += min(size, budget)
        else:
            listed.append(page)
    return shown, listed[:MAX_INDEX_LINES]


def _page_block(page: Page, budget: int) -> str:
    body = page.body.strip()
    if len(body) > budget:
        body = body[:budget] + "\n(… page cut …)"
    return f"--- PAGE {page.path.removesuffix('.md')} ({page.title}) ---\n{body}\n--- END PAGE ---"


def user_prompt(question: str, shown: list[Page], listed: list[Page]) -> str:
    parts = [f"Question: {question}", ""]
    parts += [_page_block(p, BUDGET_CHARS) for p in shown]
    if listed:
        parts += ["", "Other pages that exist (not shown):"]
        for p in listed:
            lead = text.lead(p.body)
            desc = text.first_sentence(text.plain(lead.text), 100) if lead else ""
            parts.append(
                f"- [[{p.path.removesuffix('.md')}|{p.title}]]" + (f" — {desc}" if desc else "")
            )
    return "\n".join(parts)


def _citable(shown: list[Page], index: links.LinkIndex) -> list[str]:
    """Source pages a retry may point the model at: the shown ones and those they cite."""
    found = {p.path for p in shown if p.path.startswith("sources/")}
    for page in shown:
        found |= {t for t in edits.link_targets(page.body, index) if t.startswith("sources/")}
    return sorted(found)


def _read_reply(data: dict, ctx: edits.Context) -> tuple[str, bool, list[str], dict[str, int]]:
    """(answer, answerable, cited sources, counters) of one model reply."""
    counters: dict[str, int] = {}
    answer = edits.clean_text(str(data.get("answer") or ""), None, counters)
    answer = edits.fix_links(answer, ctx, counters).strip()
    sources = sorted(t for t in edits.link_targets(answer, ctx.index) if t.startswith("sources/"))
    return answer, bool(data.get("answerable")) and bool(answer), sources, counters


def _retry_prompt(
    answer: str, cited: bool, unbacked: list[expansions.Expansion], citable: list[str]
) -> str:
    problems = []
    if not cited:
        ids = ", ".join(f"[[{p.removesuffix('.md')}]]" for p in citable)
        problems.append(f"It cites no source. Put a citation after each fact, from: {ids}.")
    problems += [
        f'It spells out {e.abbr} as "{e.long}", which the pages don\'t say. Write {e.abbr} only.'
        for e in unbacked
    ]
    listing = "\n".join(f"- {p}" for p in problems)
    return (
        f"\n\nYour previous answer:\n{answer}\n\nProblems:\n{listing}\n\n"
        "Write the answer again with these problems fixed. Keep everything else."
    )


def ask(
    vault: Vault,
    question: str,
    *,
    llm: LLM | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> Answer:
    question = " ".join(question.split())
    if not question:
        raise ValueError("empty question")
    shown, listed = retrieve(vault, question)
    result = Answer(question, "", False, [], [p.path for p in shown], [p.path for p in listed])
    if not shown:
        result.answer = "The wiki has no page about this."
        return result
    llm = llm or LLM(log=log)
    client = llm.for_role("query")
    system = load_prompt("query").replace("{language}", language_name(vault_language(vault)))
    prompt = user_prompt(question, shown, listed)
    data = client.json(system, prompt, SCHEMA, step=f"query {question[:50]}")
    if data is None:
        result.error = "no valid answer from the model"
        return result
    index = links.LinkIndex(vault.files())
    ctx = edits.Context("", index)
    evidence = "\n".join(f"{p.title}\n{text.plain(p.body)}" for p in shown)

    answer, answerable, sources, counters = _read_reply(data, ctx)
    unbacked = expansions.find(text.plain(answer), evidence)
    citable = _citable(shown, index)
    if answerable and ((not sources and citable) or unbacked):
        retry = client.json(
            system,
            prompt + _retry_prompt(answer, bool(sources), unbacked, citable),
            SCHEMA,
            step=f"query retry {question[:44]}",
        )
        if retry is not None:
            second = _read_reply(retry, ctx)
            unbacked2 = expansions.find(text.plain(second[0]), evidence)
            if second[1] and (not second[2], len(unbacked2)) < (not sources, len(unbacked)):
                data = retry
                answer, answerable, sources, counters = second
        counters["answer_retry"] = 1
    answer = expansions.strip(answer, evidence, counters)
    result.unbacked = [
        f"{e.abbr} = {e.long}" for e in expansions.find(text.plain(answer), evidence)
    ]
    if answerable and not sources:
        counters["uncited_answer"] = 1

    known = {p.path for p in shown} | {p.path for p in listed}
    used = []
    for pid in data.get("pages") or []:
        path = index.resolve(str(pid)) if isinstance(pid, str) and pid.strip() else None
        if path in known and path not in used:
            used.append(path)
        else:
            counters["unknown_page_dropped"] = counters.get("unknown_page_dropped", 0) + 1
    for target in edits.link_targets(answer, index):  # pages linked in the text count as used
        if target in known and target not in used:
            used.append(target)
    result.answer = answer
    result.answerable = answerable
    result.pages = used
    result.sources = sources
    result.counters = counters
    return result


def synthesis_path(ws: Vault, question: str) -> str:
    base = slugify(question)
    for n in range(1, 50):
        rel = ws.path_for("synthesis", base if n == 1 else f"{base}-{n}")
        if not ws.exists(rel):
            return rel
    raise IntegrateError(f"no free synthesis path for {question!r}")


def synthesis_page(path: str, result: Answer, today: dt.date) -> Page:
    """The answer as a synthesis page; `sources` = the sources the answer cites."""
    title = result.question
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1].rsplit(" ", 1)[0] + "…"
    sources = [links.format_link(s) for s in result.sources]
    meta = {
        "title": title,
        "type": "synthesis",
        "aliases": [],
        "tags": [],
        "created": today,
        "updated": today,
        "sources": sources,
        "status": "active",
        "question": result.question,
    }
    used = "\n".join(f"- {links.format_link(p)}" for p in result.pages) or "- (none)"
    body = f"\n# {title}\n\n{result.answer}\n\n## Based on\n\n{used}\n"
    return Page(path, fm.new_document(meta, body))


def _filed_before(vault: Vault, question: str) -> str | None:
    key = links.normalise_name(question)
    for rel, page in vault.iter_pages():
        if isinstance(page, Page) and page.meta.get("type") == "synthesis":
            if links.normalise_name(str(page.meta.get("question") or "")) == key:
                return rel
    return None


def file_answer(
    vault: Vault, result: Answer, *, today: dt.date | None = None, log=lambda _m: None
) -> Answer:
    """Save `result` as a synthesis page, reindex, log, commit (one commit)."""
    if not result.answerable or result.error:
        raise IntegrateError("only an answer the wiki could give is filed")
    if not result.sources:
        raise IntegrateError("the answer cites no source, so it is not filed (BR-5)")
    if result.unbacked:
        raise IntegrateError(
            "not filed: abbreviations spelled out in a way not backed by the pages: "
            + "; ".join(result.unbacked)
        )
    if not vault.is_repo():
        raise IntegrateError(f"{vault.root} is not a git repository")
    if not vault.is_clean():
        raise IntegrateError("the vault has uncommitted changes; commit or discard them first")
    day = today or dt.date.today()
    ws = Workspace(vault)
    existing = _filed_before(ws, result.question)
    if existing:  # a second page with the same title would be a duplicate-name error
        raise IntegrateError(f"this question is already filed as {existing}")
    path = synthesis_path(ws, result.question)
    ws.write_page(synthesis_page(path, result, day))
    reindex(ws, today=day)
    before = {(f.check, f.path, f.message) for f in lint(vault).errors}
    new_errors = [f for f in lint(ws).errors if (f.check, f.path, f.message) not in before]
    if new_errors:
        raise IntegrateError(
            "filing would add lint errors: "
            + "; ".join(f"{f.path} {f.message}" for f in new_errors)
        )
    append_log(ws, "query", result.question, [f"- filed: {links.format_link(path)}"], today=day)
    ws.flush()
    result.filed = path
    result.commit = vault.commit(f"query: {result.question}\n\nfiled as {path}\n")
    log(f"✓ filed as {path}, commit {result.commit[:7] if result.commit else '-'}")
    return result
