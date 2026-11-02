"""YAML front matter: parse, serialise, validate (TD-9).

Round-trip guarantee: `dump(parse(text)) == text` byte for byte whenever the
document was not changed. To get that from PyYAML (which drops comments, quoting
and formatting on dump), the original front-matter block is kept verbatim and
only re-serialised when `meta` was actually changed. The body is never touched
by this module.

When `meta` *is* changed, existing keys keep their original order, new keys are
added in schema order, unknown keys are preserved, and the file's newline style
(LF / CRLF) and UTF-8 BOM are kept. YAML comments inside a changed front-matter
block are lost; that is the accepted cost of not writing our own YAML emitter.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

BOM = chr(0xFEFF)  # UTF-8 byte-order mark, kept if a file starts with one

PAGE_TYPES = ("source", "entity", "concept", "synthesis", "index", "log")
CONTENT_TYPES = ("source", "entity", "concept", "synthesis")
STATUSES = ("active", "stub", "stale", "contested")

# Schema order, used for keys added to a page that didn't have them yet.
KEY_ORDER = (
    "title", "type", "aliases", "tags", "created", "updated", "sources", "status",
    "source_type", "origin", "author", "published", "ingested", "language",
    "entity_kind", "question", "contradicts",
)  # fmt: skip
REQUIRED_BY_TYPE: dict[str, tuple[str, ...]] = {
    "source": ("source_type", "origin"),
    "entity": ("entity_kind",),
    "synthesis": ("question",),
}
LIST_KEYS = ("aliases", "tags", "sources", "contradicts")
LINK_LIST_KEYS = ("sources", "contradicts")
DATE_KEYS = ("created", "updated", "ingested")

_OPEN = re.compile(r"---[ \t]*(\r\n|\n)")
_CLOSE = re.compile(r"(---|\.\.\.)[ \t]*(\r\n|\n)?")
_WIKILINK = re.compile(r"^\[\[[^\[\]]+\]\]$")


class FrontMatterError(ValueError):
    """The front matter can't be parsed (bad YAML, not a mapping, unterminated)."""


@dataclass
class Document:
    """A Markdown file split into front matter and body.

    Change `meta` and `body` freely; `dump()` decides what has to be rewritten.
    """

    meta: dict[str, Any]
    body: str
    newline: str = "\n"
    bom: bool = False
    raw_front: str | None = None  # original block incl. both `---` lines, verbatim
    _orig_meta: dict[str, Any] = field(default_factory=dict, repr=False)
    _orig_body: str = field(default="", repr=False)

    @property
    def meta_changed(self) -> bool:
        return self.meta != self._orig_meta

    @property
    def body_changed(self) -> bool:
        return self.body != self._orig_body


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    field: str
    message: str


# ---------------------------------------------------------------------------
# YAML loader / dumper
# ---------------------------------------------------------------------------
class _Loader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys instead of silently keeping the last."""


def _construct_mapping(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise FrontMatterError(f"duplicate key {key!r} (line {key_node.start_mark.line + 1})")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:  # never emit &id001 anchors
        return True


def _represent_str(dumper: _Dumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


def _represent_list(dumper: _Dumper, value: list) -> yaml.SequenceNode:
    # Lists of scalars inline (`aliases: [RAG]`), anything nested as a block.
    flat = all(not isinstance(v, (list, dict)) for v in value)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", value, flow_style=flat)


_Dumper.add_representer(str, _represent_str)
_Dumper.add_representer(list, _represent_list)


def _dump_yaml(meta: dict[str, Any]) -> str:
    if not meta:
        return ""
    return yaml.dump(
        meta,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,
    )


# ---------------------------------------------------------------------------
# Parse / dump
# ---------------------------------------------------------------------------
def parse(text: str) -> Document:
    """Split `text` into front matter and body. Raises FrontMatterError."""
    bom = text.startswith(BOM)
    if bom:
        text = text[1:]
    first_nl = re.search(r"\r\n|\n", text)
    newline = first_nl.group(0) if first_nl else "\n"

    opened = _OPEN.match(text)
    if not opened:
        return _document({}, text, newline=newline, bom=bom, raw_front=None)

    pos = opened.end()
    while pos <= len(text):
        end_of_line = text.find("\n", pos)
        line_end = len(text) if end_of_line == -1 else end_of_line + 1
        closed = _CLOSE.fullmatch(text, pos, line_end)
        if closed:
            inner = text[opened.end() : pos]
            meta = _load(inner)
            return _document(
                meta, text[line_end:], newline=newline, bom=bom, raw_front=text[:line_end]
            )
        if end_of_line == -1:
            break
        pos = line_end
    raise FrontMatterError("front matter is not closed (missing '---' line)")


def _load(inner: str) -> dict[str, Any]:
    try:
        data = yaml.load(inner, Loader=_Loader)  # noqa: S506 - _Loader is a SafeLoader
    except yaml.YAMLError as exc:
        raise FrontMatterError(f"invalid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise FrontMatterError(f"front matter must be a mapping, got {type(data).__name__}")
    return data


def _document(meta: dict, body: str, *, newline: str, bom: bool, raw_front: str | None):
    return Document(
        meta=meta,
        body=body,
        newline=newline,
        bom=bom,
        raw_front=raw_front,
        _orig_meta=copy.deepcopy(meta),
        _orig_body=body,
    )


def dump(doc: Document) -> str:
    """Serialise `doc`. Unchanged parts are emitted exactly as they were read."""
    if doc.meta_changed:
        front = _serialise_front(doc)
    else:
        front = doc.raw_front or ""
    body = doc.body
    if doc.body_changed and doc.newline == "\r\n":
        body = re.sub(r"(?<!\r)\n", "\r\n", body)
    return (BOM if doc.bom else "") + front + body


def _serialise_front(doc: Document) -> str:
    if not doc.meta:
        return ""
    ordered = {k: doc.meta[k] for k in doc._orig_meta if k in doc.meta}
    for key in KEY_ORDER:
        if key in doc.meta and key not in ordered:
            ordered[key] = doc.meta[key]
    for key in doc.meta:  # remaining unknown new keys, in insertion order
        ordered.setdefault(key, doc.meta[key])
    text = "---\n" + _dump_yaml(ordered) + "---\n"
    return text.replace("\n", doc.newline)


def new_document(meta: dict[str, Any], body: str) -> Document:
    """A document that doesn't exist on disk yet (always serialised in full)."""
    return Document(meta=meta, body=body, _orig_meta={}, _orig_body="")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate(meta: dict[str, Any]) -> list[Issue]:
    """Check `meta` against the vault schema (AGENTS.md §5). Unknown keys are allowed."""
    issues: list[Issue] = []

    def err(key: str, msg: str) -> None:
        issues.append(Issue("error", key, msg))

    title = meta.get("title")
    if not isinstance(title, str) or not title.strip():
        err("title", "missing or empty")

    page_type = meta.get("type")
    if page_type is None:
        err("type", "missing")
    elif page_type not in PAGE_TYPES:
        err("type", f"unknown type {page_type!r} (expected one of {', '.join(PAGE_TYPES)})")

    if page_type in CONTENT_TYPES:
        for key in ("created", "updated"):
            if key not in meta:
                err(key, "missing")
        for key in REQUIRED_BY_TYPE.get(page_type, ()):
            value = meta.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                err(key, f"required for type {page_type!r}")

    for key in DATE_KEYS:
        if key in meta and not _is_date(meta[key]):
            err(key, f"not a date (YYYY-MM-DD): {meta[key]!r}")

    for key in LIST_KEYS:
        if key not in meta or meta[key] is None:
            continue
        value = meta[key]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            err(key, "must be a list of strings")
            continue
        if key in LINK_LIST_KEYS:
            for item in value:
                if not _WIKILINK.match(item.strip()):
                    err(key, f"entry is not a [[wikilink]]: {item!r}")

    status = meta.get("status")
    if status is not None and status not in STATUSES:
        err("status", f"unknown status {status!r} (expected one of {', '.join(STATUSES)})")

    return issues


def _is_date(value: Any) -> bool:
    if isinstance(value, dt.datetime):
        return False
    if isinstance(value, dt.date):
        return True
    if isinstance(value, str):
        try:
            dt.date.fromisoformat(value)
        except ValueError:
            return False
        return len(value) == 10
    return False
