"""The vault glossary (#24): curated abbreviations and names that code reads.

`glossary.md` in the vault root holds a Markdown table with fixed columns (D2):

    | Term | Full name | Kind | Prefer | Definition |
    |---|---|---|---|---|
    | ROCC | Rover Operations Control Centre | organisation | short | Operates the rover. |

It is a registry, not pages: a page is only created when a source mentions a term,
so every claim still cites a source (BR-5). What code does with it:

- extract shows the terms mentioned in a chunk as known names;
- a subject named by a term or full name (or with one as alias) takes the full name
  as its name and the row's names as *curated* aliases, which resolve trusts for an
  exact match (model aliases are still checked, #15);
- `Kind` sets entity/concept and `entity_kind` of a **new** page (D3);
- the names check (#25) and the abbreviation check (TD-29) count it as evidence;
- `Prefer` (`short` / `full`; empty = as the source wrote it, D4) sets the shown text
  of autolinks and of the patch prompt's linkable pages;
- the `Definition` is context only and never becomes a lead (D5).

Without `glossary.md` nothing changes. Like `WIKI.md`, it is a vault file but not a
wiki page: it needs no front matter. Lint checks it (`glossary-format`,
`glossary-conflict`, `glossary-kind`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import links
from .stages.common import ENTITY_KINDS, name_key, unique
from .vault import GLOSSARY_FILE, Vault

__all__ = ["GLOSSARY_FILE", "Glossary", "Term", "load", "parse"]
COLUMNS = ("term", "full name", "kind", "prefer", "definition")
PREFER = ("short", "full", "")
_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_RULE_CELL = re.compile(r"^\s*:?-{3,}:?\s*$")


@dataclass(frozen=True)
class Term:
    term: str
    full: str
    kind: str  # entity | concept | "" (no override)
    entity_kind: str
    prefer: str  # short | full | ""
    definition: str
    line: int

    @property
    def title(self) -> str:
        """The title of a page created for this term: the full name if there is one."""
        return self.full or self.term

    def names(self) -> list[str]:
        return unique([self.title, self.term])

    def shown(self) -> str | None:
        """The form links should show, or None = as the text has it (D4)."""
        if self.prefer == "short" and self.term:
            return self.term
        if self.prefer == "full" and self.full:
            return self.full
        return None


@dataclass
class Problem:
    line: int
    check: str  # glossary-format | glossary-conflict
    message: str


@dataclass
class Glossary:
    terms: list[Term] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    _by_key: dict[str, Term] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.terms)

    def report(self, line: int, message: str, check: str = "glossary-format") -> None:
        self.problems.append(Problem(line, check, message))

    def add(self, t: Term) -> None:
        clash = {name_key(n): self._by_key[name_key(n)] for n in t.names()
                 if name_key(n) in self._by_key}  # fmt: skip
        if clash:
            other = next(iter(clash.values()))
            self.problems.append(Problem(t.line, "glossary-conflict",
                                         f"{t.title!r} shares a name with row {other.line} "
                                         f"({other.title!r}); this row is ignored"))  # fmt: skip
            return
        self.terms.append(t)
        for n in t.names():
            self._by_key[name_key(n)] = t

    def lookup(self, name: str) -> Term | None:
        return self._by_key.get(name_key(name)) if name else None

    def match(self, names: list[str]) -> Term | None:
        """The term of the first name in `names` that the glossary knows."""
        for n in names:
            t = self.lookup(n)
            if t:
                return t
        return None

    def shown_for(self, names: list[str]) -> str | None:
        t = self.match(names)
        return t.shown() if t else None

    def evidence(self) -> str:
        """Text for the abbreviation and names checks: every term with its full name."""
        return "\n".join(f"{t.term} ({t.full})" if t.term and t.full else t.title
                         for t in self.terms)  # fmt: skip


def load(vault: Vault) -> Glossary:
    """The vault's glossary; empty if there is no `glossary.md`."""
    if not vault.exists(GLOSSARY_FILE):
        return Glossary()
    return parse(vault.read_text(GLOSSARY_FILE))


def parse(markdown: str) -> Glossary:
    """Rows of every table whose header has the fixed columns (D2). Rows that can't be
    used are reported as problems, never raised."""
    g = Glossary()
    cols: list[str] | None = None
    in_code = False
    for n, line in enumerate(markdown.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        m = _ROW.match(line) if not in_code else None
        if not m:
            cols = None
            continue
        cells = _cells(m.group(1))
        if cols is None:
            header = [c.strip().casefold() for c in cells]
            if "term" in header and "full name" in header:
                cols = header
                missing = [c for c in COLUMNS if c not in header]
                if missing:
                    g.report(n, f"table has no column {', '.join(missing)}")
            continue
        if all(_RULE_CELL.match(c) for c in cells):
            continue
        if len(cells) != len(cols):
            g.report(n, f"row has {len(cells)} cells, the header {len(cols)}")
            continue
        row = {c: _plain(cells[i]) for i, c in enumerate(cols)}
        _add_row(g, row, n)
    return g


def _add_row(g: Glossary, row: dict[str, str], n: int) -> None:
    term, full = row.get("term", ""), row.get("full name", "")
    if not term and not full:
        g.report(n, "row has neither term nor full name")
        return
    kind_raw = row.get("kind", "").casefold()
    kind, entity_kind = "", ""
    if kind_raw == "concept":
        kind = "concept"
    elif kind_raw == "entity":
        kind, entity_kind = "entity", "other"
    elif kind_raw in ENTITY_KINDS:
        kind, entity_kind = "entity", kind_raw
    elif kind_raw:
        kinds = ", ".join(ENTITY_KINDS)
        g.report(n, f"unknown kind {kind_raw!r} (ignored); use concept, entity or one of {kinds}")
    prefer = row.get("prefer", "").casefold()
    if prefer not in PREFER:
        g.report(n, f"unknown prefer {prefer!r} (ignored); use short or full")
        prefer = ""
    g.add(Term(term, full, kind, entity_kind, prefer, row.get("definition", ""), n))


def _cells(inner: str) -> list[str]:
    """Split a table row at `|`, but not inside `[[target|alias]]` or after a backslash."""
    out, cur, depth, i = [], [], 0, 0
    while i < len(inner):
        ch = inner[i]
        if inner.startswith("[[", i):
            depth += 1
            cur.append("[[")
            i += 2
            continue
        if inner.startswith("]]", i) and depth:
            depth -= 1
            cur.append("]]")
            i += 2
            continue
        if ch == "\\" and i + 1 < len(inner) and inner[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if ch == "|" and not depth:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _plain(cell: str) -> str:
    """Cell text without link syntax or emphasis: `[[entities/rocc|ROCC]]` → `ROCC`."""

    def repl(m: re.Match[str]) -> str:
        inner = m.group(2)
        return inner.split("|", 1)[1] if "|" in inner else inner.split("#", 1)[0].split("/")[-1]

    text = links._LINK.sub(repl, cell)
    text = re.sub(r"\*+|`+|(?<!\w)_+|_+(?!\w)", "", text)
    return " ".join(text.split())
