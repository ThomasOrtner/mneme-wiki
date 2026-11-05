"""Stage 3b, resolve: does a subject already have a page? (TD-18)

For each subject, in order:
1. exact match of any normalised name/alias against existing pages *and* subjects of
   this source already kept as new (code);
2. candidates (code): name shape first (one name contains the other, or is its
   initialism), then BM25 over names + description; at most MAX_CANDIDATES;
3. one pairwise yes/no call per candidate, with thinking; the first "same" wins.

M0 showed that picking one of several candidates either never merged (strict
prompt) or merged anything related (loose prompt); pairwise + thinking had no false
merges. Every decision, including each yes/no with the model's reason, is returned
as a `Decision` so a wrong merge can be audited (`resolve_log.jsonl`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from ..llm import LLM
from ..prompts import load_prompt
from ..search import Doc, SearchIndex
from .common import KnownPage, Subject, initials, name_key, unique

MAX_CANDIDATES = 4
MAX_BM25_CANDIDATES = 2
BM25_MIN_SCORE = 2.0  # names field ×3 + description ×2; below this the overlap is a common word
SHAPE_MIN_LEN = 3

SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "same": {"type": "boolean"}},
    "required": ["reason", "same"],
}

SYSTEM = load_prompt("resolve")


@dataclass
class Candidate:
    id: str  # page path, or "new:<n>" for a subject of this source
    title: str
    aliases: list[str]
    description: str
    kind: str


@dataclass
class Check:
    candidate: str
    same: bool
    reason: str
    via: str  # shape | bm25


@dataclass
class Decision:
    name: str
    aliases: list[str]
    how: str  # exact | llm | new
    target: str  # page path, "new", or "this source: <name>"
    candidates: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Resolved:
    subject: Subject
    target: str | None  # existing page path, or None = new page
    how: str  # exact | llm | new

    def to_dict(self) -> dict:
        return {"target": self.target, "how": self.how, "subject": self.subject.to_dict()}


def pair_prompt(subject: Subject, cand: Candidate) -> str:
    return (
        f"A: {subject.name} (aliases: {subject.aliases})\n   {subject.description}\n"
        f"B: {cand.title} (aliases: {cand.aliases})\n   {cand.description}\n\n"
        "Are A and B the same thing?"
    )


def shape_match(names_a: list[str], names_b: list[str]) -> bool:
    """One name contains the other (≥ 3 chars), or one is the initialism of the other."""
    keys_a = {name_key(n) for n in names_a} - {""}
    keys_b = {name_key(n) for n in names_b} - {""}
    for a in keys_a:
        for b in keys_b:
            if len(a) >= SHAPE_MIN_LEN and len(b) >= SHAPE_MIN_LEN and (a in b or b in a):
                return True
    inits_a = set().union(*(initials(n) for n in names_a))
    inits_b = set().union(*(initials(n) for n in names_b))
    return bool(inits_a & keys_b) or bool(inits_b & keys_a)


class _Pool:
    """Existing pages + subjects of this source kept as new, with an exact-name map."""

    def __init__(self, pages: list[KnownPage]) -> None:
        self.cands: dict[str, Candidate] = {}
        self.by_key: dict[str, str] = {}
        self.new: dict[str, Subject] = {}
        for p in pages:
            self._add(Candidate(p.path, p.title, list(p.aliases), p.description, p.type))

    def _add(self, cand: Candidate) -> None:
        self.cands[cand.id] = cand
        for n in [cand.title, *cand.aliases]:
            key = name_key(n)
            if key:
                self.by_key.setdefault(key, cand.id)

    def add_new(self, subject: Subject) -> str:
        cid = f"new:{len(self.new)}"
        self.new[cid] = subject
        self._add(Candidate(cid, subject.name, list(subject.aliases), subject.description,
                            subject.kind))  # fmt: skip
        return cid

    def add_names(self, cid: str, names: list[str]) -> None:
        for n in names:
            key = name_key(n)
            if key:
                self.by_key.setdefault(key, cid)

    def exact(self, subject: Subject) -> str | None:
        return next(
            (self.by_key[k] for k in map(name_key, subject.names()) if k in self.by_key), None
        )

    def candidates(self, subject: Subject) -> list[tuple[Candidate, str]]:
        """Name-shape matches first (best BM25 score first), then up to
        MAX_BM25_CANDIDATES BM25-only matches; at most MAX_CANDIDATES in total."""
        if not self.cands:
            return []
        names = subject.names()
        index = SearchIndex(
            Doc(c.id, c.title, c.kind, tuple(c.aliases), c.description, "")
            for c in self.cands.values()
        )
        scores = {h.path: h.score for h in index.search(" ".join(names), limit=len(self.cands))}
        shaped = [c for c in self.cands.values() if shape_match(names, [c.title, *c.aliases])]
        shaped.sort(key=lambda c: -scores.get(c.id, 0.0))
        found = [(c, "shape") for c in shaped]
        seen = {c.id for c in shaped}
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        extra = [cid for cid, s in ranked if s >= BM25_MIN_SCORE and cid not in seen]
        found += [(self.cands[cid], "bm25") for cid in extra[:MAX_BM25_CANDIDATES]]
        return found[:MAX_CANDIDATES]


def resolve(
    llm: LLM,
    subjects: list[Subject],
    pages: list[KnownPage],
    *,
    log: Callable[[str], None] = lambda _m: None,
    counters: dict[str, int] | None = None,
) -> tuple[list[Resolved], list[Decision]]:
    """Resolve every subject to an existing page or a new one; fold in-source duplicates."""
    counters = counters if counters is not None else {}
    client = llm.for_role("resolve")
    pool = _Pool(pages)
    kept: list[Resolved] = []
    new_resolved: dict[str, Resolved] = {}
    decisions: list[Decision] = []

    def bump(key: str) -> None:
        counters[key] = counters.get(key, 0) + 1

    def fold(subject: Subject, cid: str, how: str, decision: Decision) -> None:
        if cid.startswith("new:"):  # the same thing as an earlier subject of this source
            target = new_resolved[cid].subject
            target.aliases = unique([*target.aliases, subject.name, *subject.aliases],
                                    exclude=[target.name])  # fmt: skip
            target.claims.extend(subject.claims)
            pool.add_names(cid, subject.names())
            decision.target = f"this source: {target.name}"
            bump(f"resolve_{how}_within_source")
        else:
            kept.append(Resolved(subject, cid, how))
            decision.target = cid
            bump(f"resolve_{how}")

    for subject in subjects:
        decision = Decision(subject.name, list(subject.aliases), "new", "new")
        decisions.append(decision)
        exact = pool.exact(subject)
        if exact:
            decision.how = "exact"
            fold(subject, exact, "exact", decision)
            continue
        matched = None
        for cand, via in pool.candidates(subject):
            decision.candidates.append(cand.title)
            step = f"resolve '{subject.name}' vs '{cand.title}'"
            data = client.json(SYSTEM, pair_prompt(subject, cand), SCHEMA, step=step)
            bump("resolve_llm_calls")
            same = bool((data or {}).get("same"))
            reason = str((data or {}).get("reason") or ("no valid answer" if data is None else ""))
            decision.checks.append(Check(cand.title, same, reason[:500], via))
            if same:
                matched = cand
                break
        if matched:
            decision.how = "llm"
            log(f"    → '{subject.name}' is '{matched.title}'")
            fold(subject, matched.id, "llm", decision)
        else:
            cid = pool.add_new(subject)
            resolved = Resolved(subject, None, "new")
            new_resolved[cid] = resolved
            kept.append(resolved)
            bump("resolve_new")
    return kept, decisions
