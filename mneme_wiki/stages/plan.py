"""Stage 3c, plan (code only): group claims by target page, give new pages a path."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from .. import links
from ..vault import CaseCollisionError, Vault, slugify

if TYPE_CHECKING:
    from ..glossary import Glossary
    from ..ontology import Ontology
    from ..packet import Project
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
    part_of: str = ""  # #16: the owner page (link) or name, for a scoped id's page

    def to_dict(self) -> dict:
        return asdict(self)


def plan(
    resolved: list[Resolved],
    vault: Vault,
    *,
    owner: str = "",
    counters: dict[str, int] | None = None,
    glossary: Glossary | None = None,
    project: Project | None = None,
    ontology: Ontology | None = None,
    is_local: Callable[[str], bool] = looks_local_id,
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
            if owner and is_local(s.name) and name_key(s.name) in taken_names:
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
    if glossary:
        _add_glossary_names(out, vault, glossary)
    _qualify_local_ids(out, vault, counters, project, is_local)
    if ontology:
        _scoped_kinds(out, vault, ontology, project, counters)
    return out


def _scoped_kinds(
    plans: list[PagePlan],
    vault: Vault,
    ontology: Ontology,
    project: Project | None,
    counters: dict[str, int],
) -> None:
    """#16 step 2: a page whose title is a local id of a scoped kind ("WP2", or "Project
    Alpha WP2") gets that kind, if new, and `part_of` the source's owner when the kind is
    part of a top-level kind (a deliverable of the project, not a task of a WP)."""
    owner_ref = _owner_ref(vault, project) if project else ""
    for p in plans:
        kind = ontology.kind_of_qualified(p.title)
        if kind is None:
            continue
        if p.new:
            p.kind, p.entity_kind = "entity", kind.name
            counters["ontology_scoped_kind"] = counters.get("ontology_scoped_kind", 0) + 1
        if owner_ref and ontology.owner_part_of(kind):
            p.part_of = owner_ref


def _owner_ref(vault: Vault, project: Project) -> str:
    """A link to the owner's page if it exists, else its name (no broken link)."""
    keys = {name_key(n) for n in project.names()}
    for page in known_pages(vault):
        if any(name_key(n) in keys for n in page.names()):
            return links.format_link(page.path)
    return project.name


def _add_glossary_names(plans: list[PagePlan], vault: Vault, glossary: Glossary) -> None:
    """#24 D6: a page this run touches gets its glossary row's names as aliases, also
    when the source used none of them (an existing `ROCC` page gets the full name)."""
    known = {p.path: p.names() for p in known_pages(vault)}
    for p in plans:
        t = glossary.match([p.title, *p.aliases, *known.get(p.path, [])])
        if t:
            p.aliases = unique([*p.aliases, *t.names()], exclude=[p.title] if p.new else [])


def _qualify_local_ids(
    plans: list[PagePlan],
    vault: Vault,
    counters: dict[str, int],
    project: Project | None = None,
    is_local: Callable[[str], bool] = looks_local_id,
) -> None:
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
    if project and project.short:  # #27 D1: a declared short name wins
        names[name_key(project.name)] = [project.short, *names.get(name_key(project.name), [])]

    def bump(key: str) -> None:
        counters[key] = counters.get(key, 0) + 1

    for p in plans:
        if not any(is_local(a) for a in p.aliases):
            continue
        kept = []
        for alias in p.aliases:
            owner = _owner_in_title(p.title, alias) if is_local(alias) else ""
            if not owner:
                kept.append(alias)
                continue
            bump("local_id_alias_dropped")
            short = _owner_short(owner, names, is_local)
            if short:
                kept.append(f"{short}-{alias.replace(' ', '')}")
                bump("local_id_alias_qualified")
        p.aliases = unique(kept, exclude=[p.title] if p.new else [])


def _owner_in_title(title: str, local_id: str) -> str:
    """ "Project Alpha" if `title` is "Project Alpha <local_id>…", else ""."""
    m = re.search(rf"(?<!\w){re.escape(local_id)}(?!\w)", title)
    return title[: m.start()].strip(" -:") if m else ""


def _owner_short(
    owner: str, names: dict[str, list[str]], is_local: Callable[[str], bool] = looks_local_id
) -> str | None:
    """The owner's shortest acronym-like name (`PA`), if it has one."""
    shorts = [
        n
        for n in names.get(name_key(owner), [])
        if _SHORT.fullmatch(n) and sum(c.isupper() for c in n) >= 2 and not is_local(n)
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
