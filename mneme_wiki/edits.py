"""Stage 3e: validate a proposed page edit and apply it (TD-5, L-3, L-4).

The patch stage proposes `{lead, ops[{section, op: append|replace, text}]}` for one
page; this module decides what of it reaches the page. The model never writes a
file, and code checks every piece:

- links must resolve to a page that exists (or is planned in this run); others
  are turned back into plain text;
- every fact line cites a source; a missing citation is added and counted;
- `replace` may only rewrite lines that cite the source being integrated: every
  other line (citing another source, or nothing: human text) must come back with
  the same text (`_line_key`) and citations (#22);
- `replace` may not drop a link or citation of the section, nor shrink it below
  60 %; otherwise the op is rejected (the old section stays);
- a new lead that loses a link of the old lead is discarded; one that rewrites a
  lead backed by another source (or none) is rejected, only extending it is allowed;
- escaped `\\n` inside strings is repaired, echoed headings are dropped, lines the
  page already has are not added twice;
- finally the whole page: every link target of the old body must still be there,
  otherwise the whole edit is rejected (no silent data loss, L-4).

Sections the edit does not touch are kept byte for byte: the body is split at `##`
headings and only the changed pieces are rebuilt.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import links, text

SHRINK_LIMIT = 0.6
MAX_OP_CHARS = 6000
MAX_OPS = 12
FACT_MIN_WORDS = 4
DEFAULT_SECTION = "Notes"

_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_H2 = re.compile(r"^##[ \t]+(.+?)[ \t#]*$")
_H1_OR_H2 = re.compile(r"^[ \t]{0,3}#{1,2}[ \t]+(.+?)[ \t#]*$")
_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+\S")


@dataclass
class Op:
    section: str
    op: str  # append | replace
    text: str


@dataclass
class Proposal:
    lead: str
    ops: list[Op]

    @classmethod
    def from_json(cls, data: dict) -> Proposal:
        ops = []
        for item in (data.get("ops") or [])[:MAX_OPS]:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                kind = item.get("op") if item.get("op") in ("append", "replace") else "append"
                ops.append(Op(str(item.get("section") or ""), kind, item["text"]))
        return cls(str(data.get("lead") or ""), ops)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Rejection:
    reason: str
    section: str | None = None
    text: str | None = None
    retry: bool = True  # worth asking the model again with this reason

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    source: str  # "sources/x" (no .md): the citation target for this run
    index: links.LinkIndex  # every file that exists or will exist after this run


@dataclass
class Result:
    body: str
    changed: bool
    rejected: list[Rejection] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Body structure
# ---------------------------------------------------------------------------
@dataclass
class Section:
    name: str
    lines: list[str]  # including the "## name" line


@dataclass
class Parts:
    pre: list[str]  # lines before the first H2 (H1, lead, anything else)
    sections: list[Section]

    def render(self) -> str:
        out = list(self.pre)
        for s in self.sections:
            out.extend(s.lines)
        return "\n".join(out)

    def find(self, name: str) -> Section | None:
        key = _section_key(name)
        return next((s for s in self.sections if _section_key(s.name) == key), None)


def split(body: str) -> Parts:
    lines = body.split("\n")
    pre: list[str] = []
    sections: list[Section] = []
    fence: str | None = None
    for line in lines:
        m = _FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)
        elif (
            fence is not None and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)
        ):
            fence = None
        elif fence is None:
            h2 = _H2.match(line)
            if h2:
                sections.append(Section(h2.group(1).strip(), [line]))
                continue
        (sections[-1].lines if sections else pre).append(line)
    return Parts(pre, sections)


def _section_key(name: str) -> str:
    return " ".join(name.strip().strip("#").split()).casefold()


def section_content(section: Section) -> str:
    return "\n".join(section.lines[1:]).strip("\n")


# ---------------------------------------------------------------------------
# Text checks
# ---------------------------------------------------------------------------
def link_targets(markdown: str, index: links.LinkIndex) -> set[str]:
    """Resolved target paths of every link in `markdown` (unresolvable ones by raw target)."""
    out = set()
    for link in links.extract(markdown):
        if link.target:
            out.add(index.resolve(link.target) or f"?{link.target.casefold()}")
    return out


def fix_links(markdown: str, ctx: Context, counters: dict[str, int]) -> str:
    """Unwrap links whose target doesn't resolve to exactly one file."""
    found = links.extract(markdown)
    if not found:
        return markdown
    out, pos = [], 0
    for link in found:
        out.append(markdown[pos : link.start])
        if not link.target or ctx.index.resolve(link.target):
            out.append(link.raw)
        else:
            _bump(counters, "invalid_link_removed")
            out.append(link.alias or link.target.rsplit("/", 1)[-1].replace("-", " "))
        pos = link.end
    out.append(markdown[pos:])
    return "".join(out)


def _cites(line: str, ctx: Context) -> bool:
    return bool(cited_sources(line, ctx))


def cited_sources(markdown: str, ctx: Context) -> set[str]:
    """The source pages `markdown` links to, as "sources/x" (no .md)."""
    out = set()
    for link in links.extract(markdown):
        target = ctx.index.resolve(link.target) if link.target else None
        if target and target.startswith("sources/"):
            out.add(target.removesuffix(".md"))
    return out


def _protected(line: str, ctx: Context) -> bool:
    """#22: a line the model may not rewrite: it speaks for another source, or for
    nobody (human text). Only lines citing just this run's source are free."""
    return bool(_line_key(line)) and cited_sources(line, ctx) != {ctx.source}


PROTECTED_REASON = "lines citing other sources must stay as they are; use append"


def ensure_citations(markdown: str, ctx: Context, counters: dict[str, int]) -> str:
    """Append `([[source]])` to every fact line (list item or prose line) that cites nothing."""
    out = []
    fence: str | None = None
    for line in markdown.split("\n"):
        m = _FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)
        elif fence is not None:
            if m and m.group(1)[0] == fence[0]:
                fence = None
        elif _is_fact_line(line):
            if _cites(line, ctx):
                _bump(counters, "cited_lines")
            else:
                _bump(counters, "missing_citation_added")
                line = f"{line.rstrip()} ([[{ctx.source}]])"
        out.append(line)
    return "\n".join(out)


def _is_fact_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith(("#", ">", "|", "<", "![[")):
        return False
    if not (_LIST_ITEM.match(line) or not line[:1].isspace()):
        return False
    return text.word_count(text.plain(s)) >= FACT_MIN_WORDS


def clean_text(raw: str, section: str | None, counters: dict[str, int]) -> str:
    """Repair escaped newlines; drop an echoed section heading; demote other H1/H2 lines
    (they would split the page) to H3."""
    s = raw.replace("\r\n", "\n")
    if "\\n" in s:
        _bump(counters, "escaped_newlines_fixed")
        s = s.replace("\\n", "\n")
    lines = s.strip("\n").split("\n")
    out = []
    for i, line in enumerate(lines):
        m = _H1_OR_H2.match(line)
        if m:
            if i == 0 or (section and _section_key(m.group(1)) == _section_key(section)):
                _bump(counters, "echoed_heading_dropped")
                continue
            line = "### " + m.group(1)
        out.append(line.rstrip())
    return "\n".join(out).strip("\n")


def _line_key(line: str) -> str:
    return " ".join(text.plain(line).casefold().split()).rstrip(".")


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def apply(body: str, proposal: Proposal, ctx: Context) -> Result:
    """Apply what is valid in `proposal` to `body`; report the rest."""
    original = body.replace("\r\n", "\n")
    parts = split(original)
    counters: dict[str, int] = {}
    rejected: list[Rejection] = []
    existing = {_line_key(ln) for ln in original.split("\n") if ln.strip()}

    lead_rejection = _apply_lead(parts, proposal.lead, ctx, counters)
    if lead_rejection:
        rejected.append(lead_rejection)

    for op in proposal.ops:
        name = " ".join(op.section.strip().lstrip("#").split()) or DEFAULT_SECTION
        if len(op.text) > MAX_OP_CHARS:
            rejected.append(
                Rejection(f"text for '{name}' is longer than {MAX_OP_CHARS} chars", name)
            )
            continue
        cleaned = clean_text(op.text, name, counters)
        new_text = ensure_citations(fix_links(cleaned, ctx, counters), ctx, counters)
        if not new_text.strip():
            continue
        section = parts.find(name)
        if op.op == "replace" and section is not None:
            old = section_content(section)
            lost = link_targets(old, ctx.index) - link_targets(new_text, ctx.index)
            if lost:
                _bump(counters, "replace_rejected_lost_links")
                missing = ", ".join(sorted(t.removesuffix(".md") for t in lost))
                rejected.append(
                    Rejection(f"replace of '{name}' drops links: {missing}", name, new_text)
                )
                continue
            if len(new_text) < SHRINK_LIMIT * len(old):
                _bump(counters, "replace_rejected_shrink")
                rejected.append(Rejection(
                    f"replace of '{name}' shrinks it from {len(old)} to {len(new_text)} chars",
                    name, new_text,
                ))  # fmt: skip
                continue
            changed = _changed_protected(old, cleaned, ctx)
            if changed:
                _bump(counters, "replace_rejected_protected_lines")
                rejected.append(Rejection(
                    f"replace of '{name}' changes or drops {_quote(changed)}; {PROTECTED_REASON}",
                    name, new_text,
                ))  # fmt: skip
                continue
            new_text = _restore_protected(old, cleaned, new_text, ctx)
            section.lines = [section.lines[0], "", *new_text.split("\n"), ""]
            _bump(counters, "op_replace")
            continue
        added = []
        for line in new_text.split("\n"):
            key = _line_key(line)
            if line.strip() and key in existing:
                _bump(counters, "duplicate_line_skipped")
                continue
            existing.add(key)
            added.append(line)
        while added and not added[-1].strip():
            added.pop()
        if not any(ln.strip() for ln in added):
            continue
        if section is None:
            ensure_blank_end(parts)
            parts.sections.append(Section(name, [f"## {name}", "", *added, ""]))
        else:
            _append_to(section, added)
        _bump(counters, "op_append")

    new_body = parts.render()
    if not new_body.endswith("\n"):
        new_body += "\n"
    lost = link_targets(original, ctx.index) - link_targets(new_body, ctx.index)
    if lost:  # L-4: should be impossible after the checks above; a last line of defence
        missing = ", ".join(sorted(lost))
        return Result(original, False, [Rejection(f"edit drops links: {missing}", retry=False)],
                      counters)  # fmt: skip
    return Result(new_body, new_body != original, rejected, counters)


def _changed_protected(old: str, new: str, ctx: Context) -> list[str]:
    """Protected lines of `old` that `new` doesn't keep: same `_line_key` (D3: wording
    kept, formatting may change) and at least the same citations (the key ignores them)."""
    kept: dict[str, list[set[str]]] = {}
    for line in new.split("\n"):
        kept.setdefault(_line_key(line), []).append(cited_sources(line, ctx))
    return [
        line.strip()
        for line in old.split("\n")
        if _protected(line, ctx)
        and not any(cited_sources(line, ctx) <= c for c in kept.get(_line_key(line), []))
    ]


def _restore_protected(old: str, cleaned: str, new_text: str, ctx: Context) -> str:
    """Kept protected lines go back byte for byte (an uncited human line would otherwise
    get this run's citation). `new_text` is `cleaned` after fix_links and
    ensure_citations, which keep the line count."""
    originals: dict[str, str] = {}
    for line in old.split("\n"):
        if _protected(line, ctx):
            originals.setdefault(_line_key(line), line)
    out = new_text.split("\n")
    for i, line in enumerate(cleaned.split("\n")):
        orig = originals.get(_line_key(line))
        if orig is not None and cited_sources(line, ctx) == cited_sources(orig, ctx):
            out[i] = orig
    return "\n".join(out)


def _quote(lines: list[str], limit: int = 2) -> str:
    shown = "; ".join(f'"{ln[:120]}"' for ln in lines[:limit])
    more = f" (and {len(lines) - limit} more)" if len(lines) > limit else ""
    return f"{shown}{more}"


def _apply_lead(
    parts: Parts, lead: str, ctx: Context, counters: dict[str, int]
) -> Rejection | None:
    new = clean_text(lead, None, counters) if lead.strip() else ""
    new = re.split(r"\n\s*\n", new, maxsplit=1)[0] if new else ""
    new = " ".join(ln.strip() for ln in new.split("\n") if ln.strip())
    pre_text = "\n".join(parts.pre)
    block = text.lead(pre_text)
    old = block.text if block else ""
    if not new or _line_key(new) == _line_key(old):
        return None
    new = fix_links(new, ctx, counters)
    if link_targets(old, ctx.index) - link_targets(new, ctx.index):
        _bump(counters, "lead_lost_links_kept_old")
        return None
    if old and _protected(old, ctx) and _line_key(old) not in _line_key(new):
        # #22: the old lead speaks for another source (or a human): extend, never rewrite
        _bump(counters, "lead_rejected_protected")
        reason = (
            f"the new lead rewrites the current one; {PROTECTED_REASON} "
            "(keep the lead word for word; you may add a sentence)"
        )
        return Rejection(reason, "lead", new)
    if not _cites(new, ctx) and text.word_count(text.plain(new)) >= FACT_MIN_WORDS:
        _bump(counters, "missing_citation_added")
        new = f"{new} ([[{ctx.source}]])"
    if block:
        start = block.line - 1
        parts.pre[start : start + block.text.count("\n") + 1] = [new]
    else:  # no lead yet: after the H1 (or at the top)
        h1 = next((i for i, ln in enumerate(parts.pre) if ln.startswith("# ")), None)
        at = (h1 + 1) if h1 is not None else 0
        following = parts.pre[at] if at < len(parts.pre) else None
        insert = ([""] if h1 is not None else []) + [new] + ([] if following == "" else [""])
        parts.pre[at:at] = insert
    _bump(counters, "lead_changed")
    return None


def _append_to(section: Section, added: list[str]) -> None:
    """Insert `added` after the section's last non-blank line, keeping its trailing
    blank lines (they separate it from the next heading). A list continues a list
    directly; anything else gets a blank line first."""
    lines = section.lines
    end = len(lines)
    while end > 1 and not lines[end - 1].strip():
        end -= 1
    continues_list = end > 1 and _LIST_ITEM.match(lines[end - 1]) and _LIST_ITEM.match(added[0])
    sep = [] if continues_list else [""]
    section.lines = lines[:end] + sep + added + (lines[end:] or [""])


def ensure_blank_end(parts: Parts) -> None:
    """The last block ends with exactly one empty line before a new section is added
    (joined with "\\n", that gives the blank line between them)."""
    target = parts.sections[-1].lines if parts.sections else parts.pre
    while len(target) > 1 and not target[-1].strip():
        target.pop()
    target.append("")


def _bump(counters: dict[str, int], key: str) -> None:
    counters[key] = counters.get(key, 0) + 1
