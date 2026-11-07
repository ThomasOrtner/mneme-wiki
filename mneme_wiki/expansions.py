"""Abbreviation expansions the evidence doesn't back up (L-3).

Local models "helpfully" spell out abbreviations from general knowledge, and get them
wrong: M5 found "MMGIS (Mission Management Geospatial Interface)" in a summary, a
phrase that exists nowhere in the source. Once written it reads as fact, and citation
checks can't see it, because the sentence does cite its source.

An expansion counts as backed up if the evidence contains it word for word. The check
looks only at the explicit forms: `ABC (Long Name)`, `Long Name (ABC)` and
`ABC stands for Long Name`. The bracket forms can be removed without touching the
sentence; `stands for` can't, so it is only reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ABBR = r"[A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*"  # ≥ 2 capitals: DAR, MMGIS, PRo3D
_WORD = r"[A-Z][\w'-]*"
_SMALL = r"(?:and|of|for|the|in|on|to|&)"
_LONG = rf"{_WORD}(?:[ \t]+(?:{_SMALL}|[\w'-]+)){{1,7}}"
_TITLE = rf"{_WORD}(?:[ \t]+(?:{_SMALL}[ \t]+)*{_WORD}){{1,7}}"

_AFTER = re.compile(rf"\b(?P<abbr>{_ABBR})(?P<close>\]\])?[ \t]*\((?P<long>{_LONG})\)")
_BEFORE = re.compile(rf"\b(?P<long>{_TITLE})[ \t]*\((?P<abbr>{_ABBR})\)")
_STANDS = re.compile(
    rf"\b(?P<abbr>{_ABBR})[ \t]+(?:stands[ \t]+for|is[ \t]+short[ \t]+for|means)[ \t]+"
    rf"(?:the[ \t]+)?(?P<long>{_TITLE})"
)
_ARTICLES = {"the", "a", "an"}


@dataclass(frozen=True)
class Expansion:
    abbr: str
    long: str
    start: int
    end: int
    replacement: str | None  # text to put instead; None = can't be removed in place


def _norm(text: str) -> str:
    return " " + " ".join(re.findall(r"[\w'-]+", text.casefold())) + " "


def _plausible(abbr: str, long: str) -> bool:
    """The bracket may hold anything ("DAR (see below)"); only a phrase that starts with
    the abbreviation's letter and has several words is taken for an expansion."""
    words = [w for w in long.split() if w.casefold() not in _ARTICLES]
    return len(words) >= 2 and words[0][0].casefold() == abbr[0].casefold()


def _split_lead(abbr: str, long: str) -> tuple[str, str]:
    """("Uses ", "Data Archive") for DAR: capitalised words before the phrase aren't part
    of it. Without a word that starts like `abbr`, `long` stays whole (and isn't plausible)."""
    words = long.split()
    for n, word in enumerate(words):
        if word[0].casefold() == abbr[0].casefold():
            return " ".join(words[:n]) + (" " if n else ""), " ".join(words[n:])
    return "", long


def find(text: str, evidence: str) -> list[Expansion]:
    """Expansions in `text` that `evidence` doesn't contain, in text order."""
    known = _norm(evidence)
    out: list[Expansion] = []
    taken: list[tuple[int, int]] = []

    def add(m: re.Match[str], abbr: str, long: str, replacement: str | None) -> None:
        if not _plausible(abbr, long) or _norm(long) in known:
            return
        if any(m.start() < e and s < m.end() for s, e in taken):
            return
        taken.append((m.start(), m.end()))
        out.append(Expansion(abbr, long, m.start(), m.end(), replacement))

    for m in _AFTER.finditer(text):
        add(m, m["abbr"], m["long"], m["abbr"] + (m["close"] or ""))
    for m in _BEFORE.finditer(text):
        lead, long = _split_lead(m["abbr"], m["long"])
        add(m, m["abbr"], long, lead + m["abbr"])
    for m in _STANDS.finditer(text):
        add(m, m["abbr"], m["long"], None)
    return sorted(out, key=lambda x: x.start)


def strip(text: str, evidence: str, counters: dict[str, int] | None = None) -> str:
    """`text` without the removable expansions `evidence` doesn't contain."""
    for item in reversed(find(text, evidence)):
        if item.replacement is None:
            continue
        text = text[: item.start] + item.replacement + text[item.end :]
        if counters is not None:
            counters["expansion_removed"] = counters.get("expansion_removed", 0) + 1
    return text
