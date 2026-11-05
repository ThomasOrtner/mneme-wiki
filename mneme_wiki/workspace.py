"""An in-memory overlay on a vault: writes are collected, then flushed or shown as a diff.

`Workspace` is a `Vault` whose `write_text()` records the new text instead of
writing it, and whose reads see those pending changes. Everything written in terms
of a `Vault` (reindex, append_log, lint, the stages) works on it unchanged. This is
what makes `integrate --dry-run` possible: run every stage, then print the diff
and write nothing. `flush()` writes the changes through the real vault's atomic,
path-checked `write_text()`.
"""

from __future__ import annotations

import difflib

from .vault import CaseCollisionError, Vault


class Workspace(Vault):
    def __init__(self, vault: Vault) -> None:
        super().__init__(vault.root)
        self.base = vault
        self.changes: dict[str, str] = {}

    # -- reads see pending changes ------------------------------------------------
    def exists(self, rel: str) -> bool:
        return rel in self.changes or self.base.exists(rel)

    def read_text(self, rel: str) -> str:
        if rel in self.changes:
            return self.changes[rel]
        return self.base.read_text(rel)

    def files(self) -> list[str]:
        return sorted(set(self.base.files()) | set(self.changes))

    # -- writes are collected --------------------------------------------------------
    def write_text(self, rel: str, text: str) -> bool:
        self.abspath(rel, for_write=True)  # same path rules as a real write
        self._check_case(rel)
        for other in self.changes:
            if other != rel and other.casefold() == rel.casefold():
                raise CaseCollisionError(f"{rel!r} collides with pending {other!r}")
        current = self.read_text(rel) if self.exists(rel) else None
        if current == text:
            return False
        if self.base.exists(rel) and self.base.read_text(rel) == text:
            self.changes.pop(rel, None)  # changed back to what is on disk
        else:
            self.changes[rel] = text
        return True

    def path_for(self, page_type: str, title: str) -> str:
        rel = super().path_for(page_type, title)
        for other in self.changes:
            if other != rel and other.casefold() == rel.casefold():
                raise CaseCollisionError(f"{rel!r} collides with pending {other!r}")
        return rel

    # -- results -----------------------------------------------------------------------
    def created(self) -> list[str]:
        return sorted(p for p in self.changes if not self.base.exists(p))

    def modified(self) -> list[str]:
        return sorted(p for p in self.changes if self.base.exists(p))

    def diff(self) -> str:
        out: list[str] = []
        for rel in sorted(self.changes):
            old = self.base.read_text(rel) if self.base.exists(rel) else ""
            out.extend(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    self.changes[rel].splitlines(keepends=True),
                    fromfile=f"a/{rel}" if old else "/dev/null",
                    tofile=f"b/{rel}",
                )
            )
        return "".join(line if line.endswith("\n") else line + "\n" for line in out)

    def flush(self) -> list[str]:
        """Write every pending change to the vault. Returns the paths written."""
        written = [
            rel for rel, text in sorted(self.changes.items()) if self.base.write_text(rel, text)
        ]
        self.changes.clear()
        return written
