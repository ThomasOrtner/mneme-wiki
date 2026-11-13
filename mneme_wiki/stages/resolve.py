"""Stage 3b, resolve: does a subject already have a page? (TD-18)

For each subject, in order:
1. exact match of the subject's *name* against the titles and aliases of existing
   pages and the names of subjects of this source already kept as new (code). A name
   that looks like a document-local id (`WP2`, `D3`; #13) only matches subjects of
   this source exactly; an existing page with that name becomes a candidate instead;
2. candidates (code): first every page or subject that shares a name only through an
   alias (#15: the model lists related names as aliases, so such a match is not
   proof), then name shape (one name contains the other, or is its initialism), then
   BM25 over names + description; at most MAX_CANDIDATES;
3. one pairwise yes/no call per candidate, with thinking; the first "same" wins.

Finally, an alias that is the title or alias of another page (or the name of another
new subject) is dropped and counted (`alias_conflict_dropped`): it would make a
`duplicate-name` and send later exact matches to the wrong page.

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
from ..rules import with_rules
from ..search import Doc, SearchIndex
from .common import KnownPage, Subject, initials, looks_local_id, name_key, unique

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
    entity_kind: str = ""


@dataclass
class Check:
    candidate: str
    same: bool
    reason: str
    via: str  # local-id | alias | shape | bm25


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


def kinds_differ(subject: Subject, cand: Candidate) -> bool:
    """Both entities with a known, different `entity_kind` ("other" is unknown)."""
    a, b = subject.entity_kind, cand.entity_kind
    return (
        subject.kind == "entity"
        and cand.kind == "entity"
        and bool(a and b)
        and "other" not in (a, b)
        and a != b
    )


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
    """Existing pages + subjects of this source kept as new, with two name maps.

    `by_name` holds names an exact match may trust: page titles and aliases, and the
    names of new subjects (and of subjects folded into them). `by_alias` holds the
    model's aliases of new subjects, which are unchecked (#15)."""

    def __init__(
        self, pages: list[KnownPage], is_local: Callable[[str], bool] = looks_local_id
    ) -> None:
        self.is_local = is_local  # which names are document-local ids (#13, #16)
        self.cands: dict[str, Candidate] = {}
        self.by_name: dict[str, str] = {}
        self.by_alias: dict[str, str] = {}
        self.new: dict[str, Subject] = {}
        for p in pages:
            self.cands[p.path] = Candidate(
                p.path, p.title, list(p.aliases), p.description, p.type, p.entity_kind
            )
            self.add_names(p.path, p.names())

    def add_new(self, subject: Subject) -> str:
        cid = f"new:{len(self.new)}"
        self.new[cid] = subject
        self.cands[cid] = Candidate(
            cid, subject.name, list(subject.aliases), subject.description, subject.kind,
            subject.entity_kind,
        )  # fmt: skip
        self.add_names(cid, [subject.name, *subject.curated], subject.aliases)
        return cid

    def add_names(self, cid: str, names: list[str], aliases: list[str] = ()) -> None:
        for n in names:
            if key := name_key(n):
                self.by_name.setdefault(key, cid)
        for a in aliases:
            if key := name_key(a):
                self.by_alias.setdefault(key, cid)

    def exact(self, subject: Subject) -> str | None:
        cid = self.by_name.get(name_key(subject.name))
        if cid and self.is_local(subject.name) and not cid.startswith("new:"):
            if not subject.curated:
                return None  # a local id of another document: ask, don't assume (#13)
        if cid is None:  # curated glossary names are trusted like the name (#24)
            cid = next(
                (self.by_name[k] for k in map(name_key, subject.curated) if k in self.by_name),
                None,
            )
        return cid

    def forced(self, subject: Subject) -> list[tuple[Candidate, str]]:
        """Pages/subjects that share a name with `subject` without an exact match: a
        local id of another source, or a name shared through an alias on either side."""
        out: dict[str, str] = {}
        name = name_key(subject.name)
        for key in map(name_key, subject.names()):
            for cid in (self.by_name.get(key), self.by_alias.get(key)):
                if cid and cid not in out:
                    local = key == name and cid == self.by_name.get(key)
                    out[cid] = "local-id" if local else "alias"
        return [(self.cands[cid], via) for cid, via in out.items()]

    def candidates(self, subject: Subject) -> list[tuple[Candidate, str]]:
        """Alias matches first, then name-shape matches (best BM25 score first), then up
        to MAX_BM25_CANDIDATES BM25-only matches; at most MAX_CANDIDATES in total."""
        if not self.cands:
            return []
        forced = self.forced(subject)
        names = subject.names()
        index = SearchIndex(
            Doc(c.id, c.title, c.kind, tuple(c.aliases), c.description, "")
            for c in self.cands.values()
        )
        scores = {h.path: h.score for h in index.search(" ".join(names), limit=len(self.cands))}
        seen = {c.id for c, _ in forced}
        shaped = [
            c
            for c in self.cands.values()
            if c.id not in seen and shape_match(names, [c.title, *c.aliases])
        ]
        shaped.sort(key=lambda c: -scores.get(c.id, 0.0))
        found = forced + [(c, "shape") for c in shaped]
        seen |= {c.id for c in shaped}
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
    rules: str = "",
    is_local: Callable[[str], bool] = looks_local_id,
    kind_guard: bool = False,
) -> tuple[list[Resolved], list[Decision]]:
    """Resolve every subject to an existing page or a new one; fold in-source duplicates.

    `kind_guard` (#16 D11, with an ontology): a candidate of another entity kind is never
    sent to the yes/no check; an exact name match still merges and is only counted."""
    counters = counters if counters is not None else {}
    client = llm.for_role("resolve")
    pool = _Pool(pages, is_local)
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
            pool.add_names(cid, [subject.name], subject.aliases)  # its name is confirmed
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
            if kind_guard and kinds_differ(subject, pool.cands[exact]):
                bump("resolve_kind_mismatch_exact")
                log(f"    ! '{subject.name}' ({subject.entity_kind}) matched by name a page "
                    f"of kind {pool.cands[exact].entity_kind}")  # fmt: skip
            decision.how = "exact"
            fold(subject, exact, "exact", decision)
            continue
        matched = None
        for cand, via in pool.candidates(subject):
            decision.candidates.append(cand.title)
            if kind_guard and kinds_differ(subject, cand):
                bump("resolve_kind_guard_skipped")
                reason = f"different kinds: {subject.entity_kind} vs {cand.entity_kind}"
                decision.checks.append(Check(cand.title, False, reason, "kind"))
                continue
            step = f"resolve '{subject.name}' vs '{cand.title}'"
            prompt = with_rules(pair_prompt(subject, cand), rules)  # #14, after the pair
            data = client.json(SYSTEM, prompt, SCHEMA, step=step)
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
    own = {id(r): cid for cid, r in new_resolved.items()}
    for r in kept:
        _drop_conflicting_aliases(r, r.target or own[id(r)], pool, bump, log)
    return kept, decisions


def _drop_conflicting_aliases(
    r: Resolved, own: str, pool: _Pool, bump: Callable[[str], None], log: Callable[[str], None]
) -> None:
    """Drop aliases that are another page's title/alias or another new subject's name."""
    keep = []
    for alias in r.subject.aliases:
        owner = pool.by_name.get(name_key(alias))
        if owner in (None, own):
            keep.append(alias)
        else:
            bump("alias_conflict_dropped")
            title = pool.cands[owner].title
            log(f"    ✗ alias '{alias}' of '{r.subject.name}' dropped: it names '{title}'")
    r.subject.aliases = keep
