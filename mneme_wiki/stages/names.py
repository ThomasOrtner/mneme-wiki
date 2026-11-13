"""Stage 3b', names (code only): new titles and aliases must be in the evidence (#25).

Extract can invent a name: "UPCUplink Processing Centre" for a chunk that only ever
says "UPC", an acronym glued to a made-up expansion. Resolve finds no match, so the
invented name would become a page title and slug, and the expansion check (TD-29)
would then take that title as its own evidence.

After resolve, every name that would become a **new** title or a **new** alias has to
appear word for word in the evidence: the source (title and text) or the names of
pages that existed before this run. Matching ignores case, punctuation, whitespace
and hyphens, and folds a plural "s"; nothing looser, since that would let glued and
reordered names through (D3). One exception (D3, amended 2026-11-12): an *owner name*
in front of a backed name, "Project Alpha WP2" where the source says "WP2". Extract is
told to qualify local ids that way (TD-32). An owner name is a page name from before
the run, a backed name of a subject of this source, or the start (≥ 2 words) of the
source's title; two arbitrary words of the source are not enough.

- An unbacked alias is dropped (`alias_unbacked_dropped`).
- An unbacked title of a new page is replaced by the subject's first backed alias
  (`title_unbacked_replaced`); with none, the subject is skipped
  (`subject_unbacked_skipped`) and nothing is written for it (D1).
- A subject matched to an existing page adds its name to that page as an alias, so
  an unbacked name there is dropped the same way.

Names that code builds later (plan's `PA-WP2` handles and owner-qualified titles, #13)
are not checked: they don't exist yet when this runs.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass

from .common import KnownPage, looks_local_id, name_key, unique
from .resolve import Resolved

_WORD = re.compile(r"[^\W_]+")


@dataclass
class NameChange:
    subject: str  # the subject's name as extract gave it
    change: str  # alias_dropped | title_replaced | subject_skipped
    name: str  # the unbacked name
    replacement: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def norm(text: str) -> str:
    """Words only, case-folded, hyphens and punctuation as spaces, a plural "s" folded:
    `Activity-Plans` → `activity plan`."""
    s = unicodedata.normalize("NFKC", text).casefold()
    words = [_fold(w) for w in _WORD.findall(s)]
    return " ".join(words)


def _fold(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


class Evidence:
    """The text a name has to appear in, normalised once, plus the names that may stand
    in front of another backed name as its owner ("Project Alpha" + "WP2")."""

    def __init__(
        self,
        source_text: str,
        pages: list[KnownPage],
        source_title: str = "",
        curated: list[str] = (),
    ) -> None:
        """`curated`: the vault glossary's names (#24), trusted like page names."""
        page_names = [*(n for p in pages for n in p.names()), *curated]
        parts = [source_title, source_text, *page_names]
        # "|" can't be part of a normalised name, so a name never spans two parts.
        self._text = " " + " | ".join(norm(p) for p in parts) + " "
        title = norm(source_title).split()
        self.owners = {norm(n) for n in page_names} | {
            " ".join(title[:n]) for n in range(2, len(title) + 1)
        }
        self.owners.discard("")

    def _found(self, key: str) -> bool:
        return bool(key) and f" {key} " in self._text

    def backs(self, name: str) -> bool:
        """Word for word in the evidence, or an owner name + a backed name (D3 as amended
        on 2026-11-12): extract is told to qualify local ids with their owner (TD-32), and
        the source then only says "WP2"."""
        key = norm(name)
        if self._found(key):
            return True
        words = key.split()
        return any(
            " ".join(words[:n]) in self.owners and self._found(" ".join(words[n:]))
            for n in range(1, len(words))
        )

    def add_owner(self, name: str) -> None:
        if self.backs(name):
            self.owners.add(norm(name))


def check(
    resolved: list[Resolved],
    pages: list[KnownPage],
    evidence: Evidence,
    *,
    log: Callable[[str], None] = lambda _m: None,
    counters: dict[str, int] | None = None,
    project: str = "",
    source_title: str = "",
    is_local: Callable[[str], bool] = looks_local_id,
) -> tuple[list[Resolved], list[NameChange]]:
    """The resolved subjects with unbacked names fixed, minus those with no backed name.

    `project` (#27): a fallback title that is a bare local id becomes "<project> <id>"
    ("Project Alpha Deliverable D2" → "Project Alpha D2", not "D2"). A new subject named
    like the source itself (`source_title`) is skipped: the source page is that page,
    and a second page with its title is a `duplicate-name` that rejects the whole run."""
    counters = counters if counters is not None else {}
    titles = {p.path: p.title for p in pages}
    changes: list[NameChange] = []
    kept: list[Resolved] = []

    def bump(key: str) -> None:
        counters[key] = counters.get(key, 0) + 1

    for r in resolved:  # this source's own backed names can own others ("Project Alpha")
        for name in r.subject.names():
            evidence.add_owner(name)
    for r in resolved:
        s = r.subject
        original = s.name
        if source_title and not r.target and name_key(s.name) == name_key(source_title):
            bump("subject_is_source_skipped")
            changes.append(NameChange(original, "subject_skipped", original))
            log(f"    ✗ '{original}' skipped: it is the source itself (its source page)")
            continue
        aliases = []
        for alias in s.aliases:
            if evidence.backs(alias):
                aliases.append(alias)
            else:
                bump("alias_unbacked_dropped")
                changes.append(NameChange(original, "alias_dropped", alias))
                log(f"    ✗ alias '{alias}' of '{original}' dropped: not in the source")
        s.aliases = aliases
        if evidence.backs(s.name):
            kept.append(r)
            continue
        if r.target:  # its name would only become an alias of the existing page
            bump("alias_unbacked_dropped")
            changes.append(NameChange(original, "alias_dropped", s.name))
            s.name = titles.get(r.target, s.name)
            kept.append(r)
            continue
        if s.aliases:
            s.name = s.aliases[0]
            if project and is_local(s.name) and not s.curated:
                s.name = f"{project} {s.name}"
            s.aliases = unique(s.aliases[1:], exclude=[s.name])
            bump("title_unbacked_replaced")
            changes.append(NameChange(original, "title_replaced", original, s.name))
            log(f"    ✗ title '{original}' not in the source: page is '{s.name}'")
            kept.append(r)
        else:
            bump("subject_unbacked_skipped")
            changes.append(NameChange(original, "subject_skipped", original))
            log(f"    ✗ '{original}' skipped: none of its names is in the source")
    return kept, changes
