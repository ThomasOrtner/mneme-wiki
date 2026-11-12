"""Stage 3c, plan (code only): group claims by target page, give new pages a path."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..vault import CaseCollisionError, Vault, slugify
from .common import Claim, known_pages, looks_local_id, name_key, unique
from .resolve import Resolved

_SHORT = re.compile(r"[A-Z][A-Za-z0-9]{1,7}")  # an acronym-like short name: PA, ROCC, M2X


@dataclass
class PagePlan:
    path: str
    new: bool
    title: str
    kind: str
    entity_kind: str
    aliases: list[str]
    description: str
    claims: list[Claim] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def plan(
    resolved: list[Resolved],
    vault: Vault,
    *,
    owner: str = "",
    counters: dict[str, int] | None = None,
) -> list[PagePlan]:
    """One PagePlan per page to write, in first-seen order. Subjects without claims
    produce nothing. A new page whose slug is taken by an unrelated page (or differs
    only in case from one) gets `-2`, `-3`, … appended.

    Document-local ids (#13): a new page is never titled with a bare local id; it gets
    `owner` (the source's title) in front ("Project Beta Proposal D1"). Local-id aliases
    are qualified with their owner's short name or dropped (D3)."""
    counters = counters if counters is not None else {}
    plans: dict[str, PagePlan] = {}
    for r in resolved:
        s = r.subject
        if not s.claims:
            continue
        title = s.name
        if r.target:
            path, new = r.target, False
        else:
            if owner and looks_local_id(s.name):
                title = f"{owner} {s.name}"
                counters["local_id_title_qualified"] = (
                    counters.get("local_id_title_qualified", 0) + 1
                )
            path, new = _new_path(vault, s.kind, title, taken=plans), True
        entry = plans.get(path)
        if entry is None:
            entry = plans[path] = PagePlan(
                path=path,
                new=new,
                title=title,
                kind=s.kind,
                entity_kind=s.entity_kind,
                aliases=[],
                description=s.description,
            )
        # For an existing page the subject's name may be new to it, so it becomes an
        # alias; patch drops the ones the page (or another page) already has.
        names = s.aliases if new and entry.title == s.name else [s.name, *s.aliases]
        # (a qualified title keeps the bare id as an alias here; D3 below drops it)
        entry.aliases = unique([*entry.aliases, *names], exclude=[entry.title] if new else [])
        entry.claims.extend(s.claims)
    out = list(plans.values())
    _qualify_local_ids(out, vault, counters)
    return out


def _qualify_local_ids(plans: list[PagePlan], vault: Vault, counters: dict[str, int]) -> None:
    """#13 D3: a local id (`WP2`) is only valid inside its project, so it is never a bare
    alias. If the page title names the owner before the id ("Project Alpha WP2") and the
    owner has an acronym-like short name (`PA`), the alias becomes `PA-WP2`, a handle
    made up on purpose; otherwise it is dropped."""
    names: dict[str, list[str]] = {}  # owner name_key -> its names
    for p in known_pages(vault):
        names.setdefault(name_key(p.title), []).extend(p.names())
    for p in plans:
        names.setdefault(name_key(p.title), []).extend([p.title, *p.aliases])

    def bump(key: str) -> None:
        counters[key] = counters.get(key, 0) + 1

    for p in plans:
        if not any(looks_local_id(a) for a in p.aliases):
            continue
        kept = []
        for alias in p.aliases:
            if not looks_local_id(alias):
                kept.append(alias)
                continue
            bump("local_id_alias_dropped")
            short = _owner_short(p.title, alias, names)
            if short:
                kept.append(f"{short}-{alias.replace(' ', '')}")
                bump("local_id_alias_qualified")
        p.aliases = unique(kept, exclude=[p.title] if p.new else [])


def _owner_short(title: str, local_id: str, names: dict[str, list[str]]) -> str | None:
    """The owner's shortest acronym-like name, if `title` is "<owner> <local_id>…"."""
    m = re.search(rf"(?<!\w){re.escape(local_id)}(?!\w)", title)
    owner = title[: m.start()].strip(" -:") if m else ""
    if not owner:
        return None
    shorts = [
        n
        for n in names.get(name_key(owner), [])
        if _SHORT.fullmatch(n) and sum(c.isupper() for c in n) >= 2 and not looks_local_id(n)
    ]
    return min(shorts, key=len) if shorts else None


def _new_path(vault: Vault, kind: str, title: str, *, taken: dict[str, PagePlan]) -> str:
    base = slugify(title)
    for n in range(1, 50):
        stem = base if n == 1 else f"{base}-{n}"
        try:
            rel = vault.path_for(kind, stem)
        except CaseCollisionError:
            continue
        if rel in taken and taken[rel].new and taken[rel].title == title:
            return rel  # same new subject seen again (same slug): one page
        if not vault.exists(rel) and rel not in taken:
            return rel
    raise CaseCollisionError(f"no free path for {title!r}")
