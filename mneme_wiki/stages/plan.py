"""Stage 3c, plan (code only): group claims by target page, give new pages a path."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..vault import CaseCollisionError, Vault, slugify
from .common import Claim, unique
from .resolve import Resolved


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


def plan(resolved: list[Resolved], vault: Vault) -> list[PagePlan]:
    """One PagePlan per page to write, in first-seen order. Subjects without claims
    produce nothing. A new page whose slug is taken by an unrelated page (or differs
    only in case from one) gets `-2`, `-3`, … appended."""
    plans: dict[str, PagePlan] = {}
    for r in resolved:
        s = r.subject
        if not s.claims:
            continue
        if r.target:
            path, new = r.target, False
        else:
            path, new = _new_path(vault, s.kind, s.name, taken=plans), True
        entry = plans.get(path)
        if entry is None:
            entry = plans[path] = PagePlan(
                path=path,
                new=new,
                title=s.name,
                kind=s.kind,
                entity_kind=s.entity_kind,
                aliases=[],
                description=s.description,
            )
        # For an existing page the subject's name may be new to it, so it becomes an
        # alias; patch drops the ones the page (or another page) already has.
        names = s.aliases if new and entry.title == s.name else [s.name, *s.aliases]
        entry.aliases = unique([*entry.aliases, *names], exclude=[entry.title] if new else [])
        entry.claims.extend(s.claims)
    return list(plans.values())


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
