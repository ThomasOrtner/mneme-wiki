"""Stage 3a, extract: one model call per chunk → subjects with self-contained claims.

The model sees one chunk plus a short list of known page titles (pages mentioned in
the chunk, the best BM25 matches, and subjects found earlier in this source), so it
can reuse an existing name: the cheapest form of entity resolution. Locators come
from the chunk, never from the model. Output is validated and clipped here (L-3);
subjects from different chunks with the same name are merged by code.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..llm import LLM
from ..packet import Chunk, Packet
from ..prompts import load_prompt
from ..rules import with_rules
from ..search import Doc, SearchIndex
from .common import (
    ENTITY_KINDS,
    Claim,
    KnownPage,
    Subject,
    looks_local_id,
    name_key,
    unique,
)

if TYPE_CHECKING:
    from ..glossary import Glossary

MAX_SUBJECTS = 15  # per chunk; M0: 12 dropped subjects of a dense glossary chunk
MAX_CLAIMS = 8
MAX_ALIASES = 8
MAX_NAME = 120
MAX_CLAIM = 400
KNOWN_LIMIT = 40  # known page titles shown per chunk (token budget, L-2)

SCHEMA = {
    "type": "object",
    "properties": {
        "subjects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["entity", "concept"]},
                    "entity_kind": {"type": "string", "enum": list(ENTITY_KINDS)},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                    "claims": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "kind", "entity_kind", "aliases", "description", "claims"],
            },
        }
    },
    "required": ["subjects"],
}

SYSTEM = load_prompt("extract")
# With a vault ontology (#16), after the chunk. qwen3:14b with only the schema enum
# labelled a rover `instrument` 3/3; with this line, `rover` 3/3 (2026-11-13).
KINDS_HEADING = "Entity kinds in this vault (set entity_kind to the most specific one):"


def user_prompt(packet: Packet, chunk: Chunk, known: list[str]) -> str:
    listed = "\n".join(f"- {k}" for k in known) or "(none yet)"
    return (
        f"Document: {packet.title} ({packet.meta.get('source_type')})\n"
        f"Section: {chunk.locator}\n\n"
        f"Known wiki pages:\n{listed}\n\n--- CHUNK ---\n{chunk.text}\n--- END ---"
    )


def known_for_chunk(
    chunk: Chunk,
    pages: list[KnownPage],
    earlier: list[Subject],
    glossary: Glossary | None = None,
) -> list[str]:
    """Titles (with aliases) worth showing for this chunk, most relevant first. Glossary
    terms the chunk mentions come first, under their full name (#24)."""
    lowered = chunk.text.casefold()
    entries: dict[str, str] = {}

    def add(title: str, aliases: list[str] | tuple[str, ...]) -> None:
        key = name_key(title)
        if key and key not in entries and len(entries) < KNOWN_LIMIT:
            shown = [a for a in aliases if a][:4]
            entries[key] = title + (f" (aka {', '.join(shown)})" if shown else "")

    for t in glossary.terms if glossary else ():
        if any(_mentioned(n, chunk.text, lowered) for n in t.names()):
            add(t.title, [n for n in t.names() if n != t.title])
    for page in pages:  # mentioned in the chunk
        if any(_mentioned(n, chunk.text, lowered) for n in page.names()):
            add(page.title, page.aliases)
    for subject in earlier:
        if any(_mentioned(n, chunk.text, lowered) for n in subject.names()):
            add(subject.name, subject.aliases)
    if pages:
        index = SearchIndex(
            Doc(p.path, p.title, p.type, p.aliases, p.description, "") for p in pages
        )
        by_path = {p.path: p for p in pages}
        for hit in index.search(chunk.text[:4000], limit=KNOWN_LIMIT):
            page = by_path[hit.path]
            add(page.title, page.aliases)
    return list(entries.values())


def _mentioned(name: str, raw: str, lowered: str) -> bool:
    name = name.strip()
    if len(name) < 3:
        return False
    if len(name) <= 5:  # short names (acronyms) only case-sensitively, as whole words
        return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", raw) is not None
    return re.search(rf"(?<!\w){re.escape(name.casefold())}(?!\w)", lowered) is not None


def parse_subjects(
    data: dict, chunk: Chunk, kinds: tuple[str, ...] | list[str] = ENTITY_KINDS
) -> tuple[list[Subject], int]:
    """Validate model output; returns (subjects, number of items dropped)."""
    subjects, dropped = [], 0
    for item in (data.get("subjects") or [])[:MAX_SUBJECTS]:
        if not isinstance(item, dict):
            dropped += 1
            continue
        name = " ".join(str(item.get("name") or "").split())[:MAX_NAME]
        kind = item.get("kind") if item.get("kind") in ("entity", "concept") else "concept"
        entity_kind = item.get("entity_kind") if item.get("entity_kind") in kinds else "other"
        claims = [
            Claim(" ".join(str(c).split())[:MAX_CLAIM], chunk.locator)
            for c in (item.get("claims") or [])
            if isinstance(c, str) and c.strip()
        ][:MAX_CLAIMS]
        if not name_key(name) or not claims:
            dropped += 1
            continue
        aliases = unique(
            [a for a in (item.get("aliases") or []) if isinstance(a, str) and len(a) <= MAX_NAME],
            exclude=[name],
        )[:MAX_ALIASES]
        description = " ".join(str(item.get("description") or "").split())[:MAX_CLAIM]
        subjects.append(
            Subject(name, kind, entity_kind, aliases, description, claims, [chunk.index])
        )
    return subjects, dropped


def extract(
    llm: LLM,
    packet: Packet,
    chunks: list[Chunk],
    pages: list[KnownPage],
    *,
    log: Callable[[str], None] = lambda _m: None,
    counters: dict[str, int] | None = None,
    glossary: Glossary | None = None,
    rules: str = "",
    kinds: list[str] | None = None,
) -> list[Subject]:
    """`kinds`: the vault ontology's entity kinds (#16), replacing the built-in list."""
    client = llm.for_role("extract")
    schema = schema_for(kinds) if kinds else SCHEMA
    allowed = kinds or ENTITY_KINDS
    counters = counters if counters is not None else {}
    subjects: list[Subject] = []
    for chunk in chunks:
        known = known_for_chunk(chunk, pages, subjects, glossary)
        step = f"extract {chunk.index + 1}/{len(chunks)} {chunk.locator}"
        prompt = user_prompt(packet, chunk, known)
        if kinds:  # #16: the schema's enum alone isn't enough, the model needs the list
            prompt += f"\n\n{KINDS_HEADING} {', '.join(kinds)}"
        prompt = with_rules(prompt, rules)  # #14, after the chunk
        data = client.json(SYSTEM, prompt, schema, step=step)
        if data is None:
            counters["extract_chunk_failed"] = counters.get("extract_chunk_failed", 0) + 1
            log(f"    ✗ chunk {chunk.index + 1} failed twice; its subjects are missing")
            continue
        found, dropped = parse_subjects(data, chunk, allowed)
        counters["extract_items_dropped"] = counters.get("extract_items_dropped", 0) + dropped
        subjects.extend(found)
    return subjects


def schema_for(kinds: list[str]) -> dict:
    """SCHEMA with the vault's entity kinds as the `entity_kind` enum (#16)."""
    schema = copy.deepcopy(SCHEMA)
    schema["properties"]["subjects"]["items"]["properties"]["entity_kind"]["enum"] = list(kinds)
    return schema


def expand_local_ids(
    subjects: list[Subject],
    project: str,
    counters: dict[str, int] | None = None,
    is_local: Callable[[str], bool] = looks_local_id,
) -> None:
    """#27: the source declares its project, so a bare document-local id (`WP2`) is that
    project's: rename it to "Project Alpha WP2" (the bare id stays as an alias, which
    plan turns into `PA-WP2` or drops, #13 D3). Resolve then finds the page made from
    the project's other documents by exact match. A subject the glossary named (it has
    curated names) is never expanded: the glossary takes precedence."""
    if not project:
        return
    for s in subjects:
        if is_local(s.name) and not s.curated:
            bare = s.name
            s.name = f"{project} {bare}"
            s.aliases = unique([bare, *s.aliases], exclude=[s.name])
            if counters is not None:
                counters["local_id_project_expanded"] = (
                    counters.get("local_id_project_expanded", 0) + 1
                )


def merge_within_source(subjects: list[Subject]) -> list[Subject]:
    """Union subjects with the same normalised *name* (code, no model).

    A shared alias is not enough (#15): the model lists related names (a mission's
    rover, a sibling camera) as aliases, so a match through an alias goes to resolve's
    yes/no check instead."""
    groups: list[Subject] = []
    key_to_group: dict[str, int] = {}
    for s in subjects:
        hit = key_to_group.get(name_key(s.name))
        if hit is None:
            groups.append(
                Subject(s.name, s.kind, s.entity_kind, list(s.aliases), s.description,
                        list(s.claims), list(s.chunks), list(s.curated))
            )  # fmt: skip
            hit = len(groups) - 1
        else:
            g = groups[hit]
            g.aliases = unique([*g.aliases, s.name, *s.aliases], exclude=[g.name])
            g.claims.extend(s.claims)
            g.chunks.extend(c for c in s.chunks if c not in g.chunks)
            if g.entity_kind == "other" and s.entity_kind != "other":
                g.entity_kind = s.entity_kind
        key_to_group.setdefault(name_key(s.name), hit)
    for g in groups:
        g.claims = _dedupe_claims(g.claims)
    return groups


def _dedupe_claims(claims: list[Claim]) -> list[Claim]:
    seen, out = set(), []
    for c in claims:
        key = " ".join(c.text.casefold().split()).rstrip(".")
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out
