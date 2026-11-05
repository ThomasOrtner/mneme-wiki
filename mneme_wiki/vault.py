"""The vault on disk: page I/O, slugs, path confinement, git.

Every write in the package goes through `Vault.write_text()`, which is atomic
(temp file in the same folder + `os.replace`), refuses paths outside the vault,
refuses names Windows can't store, and refuses to write `foo.md` where `Foo.md`
already exists (on NTFS that would silently overwrite the other file).

Files are read and written as bytes decoded/encoded as UTF-8, with no newline
translation, so a file nobody changed is written back byte for byte.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import subprocess
import tempfile
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from . import frontmatter as fm

Log = Callable[[str], None]

FOLDERS = {
    "source": "sources",
    "entity": "entities",
    "concept": "concepts",
    "synthesis": "syntheses",
}
VAULT_DIRS = (*FOLDERS.values(), "attachments")
SCHEMA_FILE = "WIKI.md"  # instructions for the maintainer, not a wiki page
SKIP_DIRS = {"attachments"}  # plus every folder whose name starts with "."

_RESERVED = {"con", "prn", "aux", "nul"} | {f"{p}{i}" for p in ("com", "lpt") for i in range(10)}
_BAD_CHARS = re.compile(r'[<>:"|?*\\\x00-\x1f]')
_TRANSLIT = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
     "æ": "ae", "Æ": "Ae", "ø": "o", "Ø": "O", "œ": "oe", "Œ": "Oe", "ł": "l", "Ł": "L",
     "đ": "d", "Đ": "D", "þ": "th", "ð": "d"}
)  # fmt: skip
SLUG_MAX = 80


class VaultError(Exception):
    pass


class UnsafePathError(VaultError):
    """A path outside the vault, or a name that isn't safe on Windows/NTFS."""


class CaseCollisionError(VaultError):
    """The path differs only in letter case from an existing file or folder."""


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------
def slugify(title: str, max_len: int = SLUG_MAX) -> str:
    """Kebab-case ASCII file stem for `title`, safe on every filesystem.

    German umlauts are transliterated (Größe → groesse), other accents dropped.
    Titles with no Latin letters at all get a stable hash-based stem.
    """
    s = unicodedata.normalize("NFKD", title.translate(_TRANSLIT))
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > max_len:
        cut = s[:max_len]
        s = cut.rsplit("-", 1)[0] if "-" in cut[max_len // 2 :] else cut
        s = s.strip("-")
    if not s:
        return "page-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    if s in _RESERVED:
        s += "-page"
    return s


def check_name(rel: str) -> None:
    """Raise UnsafePathError unless every part of `rel` is a portable file name."""
    for part in PurePosixPath(rel).parts:
        if _BAD_CHARS.search(part):
            raise UnsafePathError(f"invalid character in {part!r}")
        if part != part.rstrip(". "):
            raise UnsafePathError(f"name ends with a dot or space: {part!r}")
        if part.split(".", 1)[0].casefold() in _RESERVED:
            raise UnsafePathError(f"reserved name on Windows: {part!r}")


def case_collisions(paths: list[str]) -> list[list[str]]:
    """Groups of paths that differ only in letter case (pure; works on any OS)."""
    groups: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        groups[p.casefold()].append(p)
    return [sorted(g) for g in groups.values() if len(g) > 1]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@dataclass
class Page:
    path: str  # vault-relative, POSIX separators, e.g. "concepts/rag.md"
    doc: fm.Document

    @property
    def meta(self) -> dict[str, Any]:
        return self.doc.meta

    @property
    def body(self) -> str:
        return self.doc.body

    @body.setter
    def body(self, value: str) -> None:
        self.doc.body = value

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or PurePosixPath(self.path).stem)


class Vault:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    # -- paths ---------------------------------------------------------------
    def abspath(self, rel: str, *, for_write: bool = False) -> Path:
        """Absolute path for vault-relative `rel`; raises UnsafePathError if it escapes."""
        rel = str(rel).replace("\\", "/")
        if not rel or PureWindowsPath(rel).is_absolute() or PureWindowsPath(rel).drive:
            raise UnsafePathError(f"not a vault-relative path: {rel!r}")
        if rel.startswith("/") or ".." in PurePosixPath(rel).parts:
            raise UnsafePathError(f"path escapes the vault: {rel!r}")
        if for_write:
            check_name(rel)
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise UnsafePathError(f"path escapes the vault: {rel!r}")
        return path

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _check_case(self, rel: str) -> None:
        """Raise if any existing component of `rel` differs from it only in case."""
        current = self.root
        for part in PurePosixPath(rel).parts:
            if not current.is_dir():
                return
            matches = [n for n in os.listdir(current) if n.casefold() == part.casefold()]
            if matches and part not in matches:
                existing = (current / matches[0]).relative_to(self.root).as_posix()
                raise CaseCollisionError(f"{rel!r} collides with existing {existing!r}")
            current = current / part

    def path_for(self, page_type: str, title: str) -> str:
        """Vault-relative path a new page of `page_type` titled `title` should get."""
        if page_type not in FOLDERS:
            raise VaultError(f"pages of type {page_type!r} have no folder")
        rel = f"{FOLDERS[page_type]}/{slugify(title)}.md"
        self._check_case(rel)
        return rel

    # -- reading ---------------------------------------------------------------
    def exists(self, rel: str) -> bool:
        return self.abspath(rel).is_file()

    def read_text(self, rel: str) -> str:
        return self.abspath(rel).read_bytes().decode("utf-8")

    def read_page(self, rel: str) -> Page:
        """Parse a page. Raises FrontMatterError for broken front matter."""
        return Page(rel, fm.parse(self.read_text(rel)))

    def files(self) -> list[str]:
        """Every file in the vault (incl. attachments), skipping hidden folders."""
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if not name.startswith("."):
                    out.append(self.rel(Path(dirpath) / name))
        return out

    def page_paths(self) -> list[str]:
        """Every Markdown page (WIKI.md and attachments excluded)."""
        return [
            p
            for p in self.files()
            if p.lower().endswith(".md")
            and p != SCHEMA_FILE
            and PurePosixPath(p).parts[0] not in SKIP_DIRS
        ]

    def iter_pages(self) -> Iterator[tuple[str, Page | fm.FrontMatterError]]:
        """(path, page) for every page; broken front matter yields the error instead."""
        for rel in self.page_paths():
            try:
                yield rel, self.read_page(rel)
            except fm.FrontMatterError as exc:
                yield rel, exc

    def case_collisions(self) -> list[list[str]]:
        return case_collisions(self.files())

    # -- writing ---------------------------------------------------------------
    def write_text(self, rel: str, text: str) -> bool:
        """Atomically write `text` (UTF-8, newlines as given). False if unchanged."""
        path = self.abspath(rel, for_write=True)
        self._check_case(rel)
        data = text.encode("utf-8")
        if path.is_file() and path.read_bytes() == data:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, data)
        return True

    def write_page(self, page: Page) -> bool:
        return self.write_text(page.path, fm.dump(page.doc))

    # -- git -------------------------------------------------------------------
    def is_repo(self) -> bool:
        return (self.root / ".git").exists()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode not in (0, 1):
            raise VaultError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc

    def commit(self, message: str) -> str | None:
        """Stage everything in the vault and commit. Returns the sha, or None if clean."""
        if not self.is_repo():
            raise VaultError(f"{self.root} is not a git repository")
        self.git("add", "-A")
        if self.git("diff", "--cached", "--quiet").returncode == 0:
            return None
        proc = self.git("commit", "-q", "-m", message)
        if proc.returncode != 0:
            raise VaultError(f"git commit failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return self.git("rev-parse", "HEAD").stdout.strip()


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(5):  # Windows: another process may hold the file briefly
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------
VAULT_GITIGNORE = """\
# Obsidian per-device state
.obsidian/workspace*.json
.obsidian/cache
.trash/
# mneme-wiki caches: derived, rebuildable (TD-4)
.mneme-wiki/
"""


# Git must store pages exactly as they are on disk (no core.autocrlf rewriting),
# otherwise byte-exact round trips and clean diffs break on Windows.
VAULT_GITATTRIBUTES = "* -text\n"


def schema_template(language: str) -> str:
    text = resources.files("mneme_wiki").joinpath("templates/WIKI.md").read_text("utf-8")
    return text.replace("{{language}}", language)


def init_vault(
    path: Path | str, *, language: str, today: dt.date | None = None, log: Log = lambda _: None
) -> Vault:
    """Create a new vault at `path`: folders, WIKI.md, index.md, log.md, git repo, commit."""
    root = Path(path)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise VaultError(f"{root} already exists and is not an empty folder")
    root.mkdir(parents=True, exist_ok=True)
    vault = Vault(root)
    day = today or dt.date.today()
    name = root.resolve().name

    for folder in VAULT_DIRS:
        vault.write_text(f"{folder}/.gitkeep", "")
    vault.write_text(".gitignore", VAULT_GITIGNORE)
    vault.write_text(".gitattributes", VAULT_GITATTRIBUTES)
    vault.write_text(SCHEMA_FILE, schema_template(language))
    vault.write_text("index.md", _index_text(day))
    vault.write_text("log.md", _log_text(day, name))
    log(f"Created vault structure in {vault.root}")

    if not vault.is_repo():
        vault.git("init", "-q")
    sha = vault.commit(f"init: {name}")
    log(f"Initialised git repository, commit {sha[:7] if sha else '-'}")
    return vault


def _index_text(day: dt.date) -> str:
    from .index_log import render_index_body  # index_log imports this module

    meta = {"title": "Index", "type": "index", "created": day, "updated": day}
    return fm.dump(fm.new_document(meta, render_index_body([])))


def _log_text(day: dt.date, name: str) -> str:
    from .index_log import LOG_INTRO, log_entry

    meta = {"title": "Log", "type": "log", "created": day, "updated": day}
    entry = log_entry("init", name, ["Vault created by `mneme-wiki init`."], day=day)
    return fm.dump(fm.new_document(meta, f"\n# Log\n\n{LOG_INTRO}\n\n{entry}"))
