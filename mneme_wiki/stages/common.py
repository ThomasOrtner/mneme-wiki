"""Data passed between stages, and the name helpers they share."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

from .. import text
from ..vault import Page, Vault

WIKI_TYPES = ("entity", "concept")
ENTITY_KINDS = (
    "person", "organisation", "team", "role", "project", "mission", "system",
    "software", "instrument", "place", "document", "other",
)  # fmt: skip
_STOP = {"of", "and", "the", "for", "to", "in", "on", "a", "an", "der", "die", "das", "und"}


@dataclass
class Claim:
    text: str
    locator: str  # the source heading the claim came from (set by code)


@dataclass
class Subject:
    name: str
    kind: str  # entity | concept
    entity_kind: str
    aliases: list[str]
    description: str
    claims: list[Claim]
    chunks: list[int] = field(default_factory=list)
    curated: list[str] = field(default_factory=list)  # glossary names (#24): trusted

    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Subject:
        claims = [Claim(**c) for c in d.get("claims", [])]
        return cls(**{**d, "claims": claims})


@dataclass(frozen=True)
class KnownPage:
    """An existing entity/concept page, as the stages see it."""

    path: str  # "entities/rocc.md"
    title: str
    type: str
    aliases: tuple[str, ...]
    description: str  # first sentence of the lead
    entity_kind: str = ""  # entities only; for the ontology's kind guard (#16)

    def names(self) -> list[str]:
        return [self.title, *self.aliases]


def known_pages(vault: Vault, types: tuple[str, ...] = WIKI_TYPES) -> list[KnownPage]:
    out = []
    for _, page in vault.iter_pages():
        if isinstance(page, Page) and page.meta.get("type") in types:
            out.append(known_page(page))
    return out


def known_page(page: Page) -> KnownPage:
    aliases = page.meta.get("aliases")
    lead = text.lead(page.body)
    return KnownPage(
        path=page.path,
        title=page.title,
        type=str(page.meta.get("type")),
        aliases=tuple(a for a in aliases if isinstance(a, str))
        if isinstance(aliases, list)
        else (),
        description=text.first_sentence(text.plain(lead.text), 200) if lead else "",
        entity_kind=str(page.meta.get("entity_kind") or ""),
    )


def name_key(name: str) -> str:
    """Key for exact name matching: ASCII-folded, lower, no punctuation or parentheses,
    a trailing plural "s" folded (M0: `Targets` = `Target`)."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s[:-1] if s.endswith("s") and len(s) > 4 else s


_LOCAL_ID = re.compile(r"[A-Z]{1,4}[ -]?\d+(?:\.\d+)*[a-z]?")


def looks_local_id(name: str) -> bool:
    """A name like `WP2`, `D3`, `MS3`, `AP4`, `T2.1`: 1-4 capitals, then a number (#13).

    Such ids are often unique only inside the document that defines them, so resolve
    never matches them across sources without a yes/no check. Language-independent on
    purpose (#13 D1); plain acronyms without a number (`ROCC`) are not affected."""
    return _LOCAL_ID.fullmatch(name.strip()) is not None


def initials(name: str) -> set[str]:
    """Initialisms of `name`, with and without stop words: `Regions of Interest` →
    {`ri`, `roi`}. Names of fewer than two words have none. (The M0 spike only
    dropped stop words, so `ROI` never matched `Regions of Interest`.)"""
    words = re.findall(r"[A-Za-z0-9]+", re.sub(r"\(.*?\)", " ", name))
    content = [w for w in words if w.lower() not in _STOP]
    out = set()
    for ws in (words, content):
        if len(ws) >= 2:
            out.add("".join(w[0] for w in ws).lower())
    return out


def unique(items: list[str], *, exclude: list[str] = ()) -> list[str]:
    """`items` without blanks and without duplicates by name_key, first spelling kept."""
    seen = {name_key(x) for x in exclude}
    out = []
    for item in items:
        item = " ".join(str(item).split())
        key = name_key(item)
        if item and key and key not in seen:
            seen.add(key)
            out.append(item)
    return out
