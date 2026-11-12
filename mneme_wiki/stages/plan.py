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

    Document-local ids (#13): a new page whose bare local-id title (`D1`) is already a
    page's name gets `owner` (the source's title) in front ("Project Beta Proposal D1"):
    resolve decided they differ, so the same title would be a duplicate. Without a
    collision the title stays, since `M20`-shaped names can be global. Local-id aliases
    on an owner-qualified title are qualified or dropped (D3)."""
    counters = counters if counters is not None else {}
    taken_names = {name_key(n) for p in known_pages(vault) for n in p.names()}
    plans: dict[str, PagePlan] = {}
    for r in resolved:
        s = r.subject
        if not s.claims:
            continue
        title = s.name
        if r.target:
            path, new = r.target, False
        else:
            if owner and looks_local_id(s.name) and name_key(s.name) in taken_names:
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
    """#13 D3: a local id (`WP2`) is only valid inside its project, so it is no bare
    alias of a page whose title names the owner before the id ("Project Alpha WP2").
    If the owner has an acronym-like short name (`PA`) the alias becomes `PA-WP2`, a
    handle made up on purpose; otherwise it is dropped. Without an owner in the title
    there is no evidence the id is local (`M20` on "Mars 2020"), so the alias stays."""
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
            owner = _owner_in_title(p.title, alias) if looks_local_id(alias) else ""
            if not owner:
                kept.append(alias)
                continue
            bump("local_id_alias_dropped")
            short = _owner_short(owner, names)
            if short:
                kept.append(f"{short}-{alias.replace(' ', '')}")
                bump("local_id_alias_qualified")
        p.aliases = unique(kept, exclude=[p.title] if p.new else [])


def _owner_in_title(title: str, local_id: str) -> str:
    """ "Project Alpha" if `title` is "Project Alpha <local_id>…", else ""."""
    m = re.search(rf"(?<!\w){re.escape(local_id)}(?!\w)", title)
    return title[: m.start()].strip(" -:") if m else ""


def _owner_short(owner: str, names: dict[str, list[str]]) -> str | None:
    """The owner's shortest acronym-like name (`PA`), if it has one."""
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
