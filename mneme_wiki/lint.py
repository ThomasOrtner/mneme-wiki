"""Deterministic vault checks (BR-10). No model involved.

Errors break the vault for every later operation (broken links, front matter
that can't be read or violates the schema, two pages claiming one name, file
names that collide on NTFS). Warnings are heuristics or things a human may want
on purpose (orphans, uncited claims, ambiguous bare links, missing headings).
`mneme-wiki lint` exits non-zero on errors only.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass

from . import frontmatter as fm
from . import glossary, links, text
from .stages.common import name_key
from .vault import GLOSSARY_FILE, Page, Vault

ERROR, WARNING = "error", "warning"
CLAIM_MIN_WORDS = 8
CITED_TYPES = ("entity", "concept", "synthesis")  # pages whose claims need citations
ORPHAN_TYPES = ("source", "entity", "concept")  # syntheses are reached via the index
NAV_TYPES = ("index", "log")  # their links don't count as inbound links
CLAIM_KINDS = ("paragraph", "list_item")

CHECKS = {
    "frontmatter": ERROR,
    "broken-link": ERROR,
    "duplicate-name": ERROR,
    "case-collision": ERROR,
    "glossary-format": WARNING,
    "glossary-conflict": WARNING,
    "glossary-kind": WARNING,
    "ambiguous-link": WARNING,
    "missing-heading": WARNING,
    "orphan": WARNING,
    "uncited": WARNING,
}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    check: str
    level: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    findings: list[Finding]
    pages: int

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "pages": self.pages,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "findings": [f.to_dict() for f in self.findings],
        }


def body_line(page: Page) -> int:
    """File line number of the body's first line."""
    raw = page.doc.raw_front
    return (raw.count("\n") if raw else 0) + 1


def lint(vault: Vault) -> Report:
    findings: list[Finding] = []

    def add(path: str, line: int, check: str, message: str) -> None:
        findings.append(Finding(path, line, check, CHECKS[check], message))

    pages: dict[str, Page] = {}
    for rel, result in vault.iter_pages():
        if isinstance(result, fm.FrontMatterError):
            add(rel, 1, "frontmatter", _one_line(str(result)))
            continue
        pages[rel] = result
        if result.doc.raw_front is None:
            add(rel, 1, "frontmatter", "no front matter")
            continue
        for issue in fm.validate(result.meta):
            add(rel, 1, "frontmatter", f"{issue.field}: {issue.message}")

    for group in vault.case_collisions():
        for rel in group:
            add(rel, 1, "case-collision", "same name as " + ", ".join(p for p in group if p != rel))

    index = links.LinkIndex(vault.files())
    inbound: dict[str, set[str]] = defaultdict(set)
    headings_cache: dict[str, set[str]] = {}

    def headings_of(rel: str) -> set[str]:
        if rel not in headings_cache:
            body = pages[rel].body if rel in pages else ""
            headings_cache[rel] = {_norm(h) for h in links.headings(body)}
        return headings_cache[rel]

    for rel, page in pages.items():
        page_type = page.meta.get("type")
        offset = body_line(page) - 1
        found = [
            (offset + links.line_of(page.body, lk.start), lk) for lk in links.extract(page.body)
        ]
        for key in fm.LINK_LIST_KEYS:
            value = page.meta.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        found.extend((1, lk) for lk in links.extract(item))

        for line, link in found:
            if not link.target:  # [[#heading]] on the same page
                if link.heading and _norm(link.heading) not in headings_of(rel):
                    add(rel, line, "missing-heading", f"{link.raw}: no such heading on this page")
                continue
            candidates = index.candidates(link.target)
            if not candidates:
                add(rel, line, "broken-link", f"{link.raw}: no page {link.target!r}")
                continue
            if len(candidates) > 1:
                add(rel, line, "ambiguous-link", f"{link.raw}: could be {', '.join(candidates)}")
                continue
            target = candidates[0]
            if target != rel and page_type not in NAV_TYPES:
                inbound[target].add(rel)
            if link.heading and target in pages and _norm(link.heading) not in headings_of(target):
                add(rel, line, "missing-heading", f"{link.raw}: no heading {link.heading!r}")

        if page_type in CITED_TYPES:
            for block in text.blocks(page.body):
                if block.kind not in CLAIM_KINDS:
                    continue
                if text.word_count(text.plain(block.text)) < CLAIM_MIN_WORDS:
                    continue
                if not _cites_source(block.text, index):
                    snippet = text.first_sentence(text.plain(block.text), 60)
                    add(rel, offset + block.line, "uncited", f"no source citation: {snippet!r}")

    metas = {rel: p.meta for rel, p in pages.items() if p.meta.get("type") in fm.CONTENT_TYPES}
    for name, paths in sorted(links.alias_map(metas).items()):
        if len(paths) > 1:
            for rel in sorted(paths):
                others = ", ".join(p for p in sorted(paths) if p != rel)
                add(rel, 1, "duplicate-name", f"title/alias {name!r} also used by {others}")

    _lint_glossary(vault, pages, add)

    for rel, page in pages.items():
        if page.meta.get("type") in ORPHAN_TYPES and not inbound.get(rel):
            add(rel, 1, "orphan", "no other page links here")

    return Report(sorted(findings), len(pages))


def _lint_glossary(vault: Vault, pages: dict[str, Page], add) -> None:
    """#24: problems in `glossary.md`, pages the glossary says are one thing, names that
    a page carries but the glossary gives to something else, and kind mismatches (D3)."""
    gl = glossary.load(vault)
    for problem in gl.problems:
        add(GLOSSARY_FILE, problem.line, problem.check, problem.message)
    by_key: dict[str, set[str]] = defaultdict(set)
    for rel, page in pages.items():
        if page.meta.get("type") not in ("entity", "concept"):
            continue
        aliases = page.meta.get("aliases") if isinstance(page.meta.get("aliases"), list) else []
        for n in [page.title, *(a for a in aliases if isinstance(a, str))]:
            by_key[name_key(n)].add(rel)
    for t in gl.terms:
        keys = {name_key(n) for n in t.names()}
        matched = sorted(set().union(*(by_key.get(k, set()) for k in keys)))
        if len(matched) > 1:
            for rel in matched:
                others = ", ".join(p for p in matched if p != rel)
                add(
                    rel,
                    1,
                    "duplicate-name",
                    f"the glossary (line {t.line}) says {t.title!r} is one thing; also {others}",
                )
            continue
        if not matched:
            continue
        page = pages[matched[0]]
        if name_key(page.title) not in keys:
            add(
                GLOSSARY_FILE,
                t.line,
                "glossary-conflict",
                f"{t.title!r}: {matched[0]} carries one of its names, but its title "
                f"{page.title!r} isn't in this row",
            )
            continue
        kind, entity_kind = page.meta.get("type"), page.meta.get("entity_kind")
        if t.kind and (
            kind != t.kind
            or (t.kind == "entity" and t.entity_kind != "other" and entity_kind != t.entity_kind)
        ):
            want = t.entity_kind if t.kind == "entity" else t.kind
            add(
                matched[0],
                1,
                "glossary-kind",
                f"the glossary (line {t.line}) says {want}, the page is "
                f"{entity_kind if kind == 'entity' else kind}",
            )


def _cites_source(markdown: str, index: links.LinkIndex) -> bool:
    for link in links.extract(markdown):
        target = index.resolve(link.target) if link.target else None
        if target and target.startswith("sources/"):
            return True
    return False


def _one_line(message: str) -> str:
    """PyYAML errors span several lines; keep the first plus the position."""
    first = message.splitlines()[0] if message else message
    where = re.search(r"line \d+, column \d+", message)
    return f"{first} ({where.group(0)} of the front matter)" if where else first


def _norm(heading: str) -> str:
    return links.normalise_name(heading)
