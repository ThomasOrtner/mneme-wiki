"""Source packets (TD-8): the upstream contract, loaded and checked, then chunked.

```
inbox/<name>/
  source.md          required: the content, already Markdown
  source.meta.json   required: title, source_type, origin, date; optional author,
                     published, language
  summary.md         optional: upstream summary (saves one model call)
  toc.json           optional: section structure (not used yet)
```

Chunking is code: split at headings, pack sections into chunks of at most
`CHUNK_WORDS` words, split an oversize section at paragraphs. The heading a chunk
starts under is its *locator*, so where a claim came from is never up to the model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CHUNK_WORDS = 500  # M0: 900-word chunks hit the per-chunk subject cap and dropped concepts
REQUIRED_META = ("title", "source_type", "origin", "date")
MAX_SOURCE_BYTES = 2_000_000

_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t#]*$")


class PacketError(ValueError):
    """The packet is missing files or its metadata is incomplete."""


@dataclass(frozen=True)
class Project:
    """The project a source belongs to (#27): its document-local ids (`WP2`) are expanded
    to `<name> <id>`. `short` (e.g. `PA`) is used for the `PA-WP2` alias (#13 D3)."""

    name: str
    short: str = ""

    def names(self) -> list[str]:
        return [n for n in (self.name, self.short) if n]


def project_of(meta: dict) -> Project | None:
    """`"project": "Project Alpha"` or `{"name": "Project Alpha", "short": "PA"}` (D1)."""
    value = meta.get("project")
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return Project(" ".join(value.split()))
    if isinstance(value, dict) and isinstance(value.get("name"), str) and value["name"].strip():
        short = value.get("short")
        if short is not None and not isinstance(short, str):
            raise PacketError("project.short must be a string")
        return Project(" ".join(value["name"].split()), " ".join((short or "").split()))
    raise PacketError('project must be a name or {"name": ..., "short": ...}')


@dataclass
class Packet:
    name: str
    path: Path
    text: str
    meta: dict
    summary: str | None = None
    toc: object | None = None

    @property
    def title(self) -> str:
        return str(self.meta["title"])

    @property
    def project(self) -> Project | None:
        return project_of(self.meta)

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True)
class Chunk:
    index: int
    locator: str
    text: str
    words: int = field(default=0)


def load(path: Path | str) -> Packet:
    root = Path(path)
    if not root.is_dir():
        raise PacketError(f"{root} is not a packet folder")
    source, meta_file = root / "source.md", root / "source.meta.json"
    for f in (source, meta_file):
        if not f.is_file():
            raise PacketError(f"{root.name}: missing {f.name}")
    if source.stat().st_size > MAX_SOURCE_BYTES:
        raise PacketError(f"{root.name}: source.md is larger than {MAX_SOURCE_BYTES} bytes")
    try:
        meta = json.loads(meta_file.read_bytes().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PacketError(f"{root.name}: source.meta.json is not valid JSON: {exc}") from exc
    if not isinstance(meta, dict):
        raise PacketError(f"{root.name}: source.meta.json must be an object")
    missing = [k for k in REQUIRED_META if not str(meta.get(k) or "").strip()]
    if missing:
        raise PacketError(f"{root.name}: source.meta.json lacks {', '.join(missing)}")
    try:
        project_of(meta)
    except PacketError as exc:
        raise PacketError(f"{root.name}: source.meta.json: {exc}") from exc
    text = _read(source).lstrip("﻿")
    if not text.strip():
        raise PacketError(f"{root.name}: source.md is empty")
    summary = _read(root / "summary.md").strip() if (root / "summary.md").is_file() else None
    toc = None
    if (root / "toc.json").is_file():
        try:
            toc = json.loads(_read(root / "toc.json"))
        except json.JSONDecodeError:
            toc = None  # optional file; a broken one is ignored, not fatal
    return Packet(root.name, root, text, meta, summary or None, toc)


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def sections(text: str) -> list[tuple[str, str]]:
    """[(heading, text incl. its heading line)]; text before the first heading is 'start'."""
    out: list[tuple[str, list[str]]] = [("start", [])]
    fence: str | None = None
    for line in text.splitlines():
        m = _FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)
        elif (
            fence is not None and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)
        ):
            fence = None
        elif fence is None:
            heading = _HEADING.match(line)
            if heading:
                out.append((heading.group(1).strip(), [line]))
                continue
        out[-1][1].append(line)
    return [(loc, "\n".join(lines).strip()) for loc, lines in out if "\n".join(lines).strip()]


def chunk(text: str, max_words: int = CHUNK_WORDS) -> list[Chunk]:
    """Pack sections into chunks of at most `max_words` (a single paragraph may exceed it)."""
    pieces: list[tuple[str, str, int]] = []  # (locator, text, words), each ≤ max_words if possible
    for loc, body in sections(text):
        words = len(body.split())
        if words <= max_words:
            pieces.append((loc, body, words))
            continue
        buf: list[str] = []
        count = 0
        for para in re.split(r"\n\s*\n", body):
            pw = len(para.split())
            if buf and count + pw > max_words:
                pieces.append((loc, "\n\n".join(buf), count))
                buf, count = [], 0
            buf.append(para)
            count += pw
        if buf:
            pieces.append((loc, "\n\n".join(buf), count))

    chunks: list[Chunk] = []
    loc: str | None = None
    buf, count = [], 0
    for piece_loc, body, words in pieces:
        if buf and count + words > max_words:
            chunks.append(Chunk(len(chunks), loc or piece_loc, "\n\n".join(buf), count))
            loc, buf, count = None, [], 0
        loc = loc or piece_loc
        buf.append(body)
        count += words
    if buf:
        chunks.append(Chunk(len(chunks), loc or "start", "\n\n".join(buf), count))
    return chunks
