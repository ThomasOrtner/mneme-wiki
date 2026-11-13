"""The vault ontology (#16): kinds, `part_of`/`has`, scoped kinds and their id patterns.

`ontology.md` in the vault root (D1) holds one ```` ```yaml ```` block:

    kinds:
      mission:      {part_of: programme}
      rover:        {part_of: mission, has: [instrument]}
      project:      {has: [work_package, deliverable, milestone]}
      work_package: {part_of: project, scoped: true, id: "WP{n}"}
      task:         {part_of: work_package, scoped: true, id: "T{n}.{m}"}

What code does with it (first version = steps 1 + 2, D5):

- **Kinds.** Extract picks `entity_kind` from these kinds instead of the built-in list.
  Resolve never asks the model whether two subjects of different kinds are the same
  (D11: exact name matches still merge; names are trusted, TD-31).
- **Scoped kinds** (`scoped: true`) are only unique within their owner. Their `id`
  pattern (D9: placeholders, `{n}` = a number) says which names are local ids of that
  kind; with an ontology the patterns replace the hardcoded shape of TD-32 everywhere
  (`local_id_test`). A new page for such an id gets the kind, and `part_of` its owner
  (the source's `local_id_owner`, #27) when the kind is part of a top-level kind.

Without `ontology.md` nothing changes (D3, D7): the built-in kinds and the hardcoded
local-id shape stay. Like `glossary.md` it is a vault file, not a wiki page.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import yaml

from .stages.common import ENTITY_KINDS, looks_local_id
from .vault import ONTOLOGY_FILE, Vault

_BLOCK = re.compile(r"^```ya?ml[ \t]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
_PLACEHOLDER = re.compile(r"\{([a-z])\}")
_KIND_NAME = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class Kind:
    name: str
    part_of: tuple[str, ...] = ()
    has: tuple[str, ...] = ()
    scoped: bool = False
    id: str = ""  # placeholder pattern, e.g. "WP{n}"
    pattern: re.Pattern[str] | None = field(default=None, compare=False)


@dataclass
class Problem:
    line: int
    message: str


@dataclass
class Ontology:
    kinds: dict[str, Kind] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.kinds)

    def entity_kinds(self) -> list[str]:
        """The kinds extract may choose from; "other" stays for concepts."""
        return [*self.kinds, *(["other"] if "other" not in self.kinds else [])]

    def scoped(self) -> list[Kind]:
        return [k for k in self.kinds.values() if k.scoped and k.pattern]

    def local_kind(self, name: str) -> Kind | None:
        """The scoped kind whose id pattern the whole name matches (`WP2`)."""
        name = name.strip()
        return next((k for k in self.scoped() if k.pattern.fullmatch(name)), None)

    def kind_of_qualified(self, name: str) -> Kind | None:
        """The scoped kind of a bare id or of an owner-qualified one ("Project Alpha WP2")."""
        last = name.strip().rsplit(" ", 1)[-1]
        return self.local_kind(name) or self.local_kind(last)

    def is_local(self, name: str) -> bool:
        return self.local_kind(name) is not None

    def owner_part_of(self, kind: Kind) -> bool:
        """Whether a page of `kind` is `part_of` the source's owner: its kind is part of
        exactly one kind, and that one isn't scoped itself (a deliverable is part of the
        project; a task is part of a work package, which the owner isn't)."""
        if len(kind.part_of) != 1:
            return False
        parent = self.kinds.get(kind.part_of[0])
        return parent is not None and not parent.scoped


def local_id_test(ontology: Ontology | None) -> Callable[[str], bool]:
    """Which names are document-local ids: the ontology's id patterns if the vault has
    an ontology with scoped kinds (#16 D7), else the hardcoded shape (TD-32)."""
    if ontology and ontology.scoped():
        return ontology.is_local
    return looks_local_id


def compile_id(pattern: str) -> re.Pattern[str]:
    """`WP{n}` → `WP[ -]?\\d+`, `T{n}.{m}` → `T[ -]?\\d+\\.\\d+` (D9). A placeholder right
    after a letter may follow a space or hyphen ("WP 2", "WP-2"), as TD-32 allows."""
    out, pos = [], 0
    for m in _PLACEHOLDER.finditer(pattern):
        literal = pattern[pos : m.start()]
        out.append(re.escape(literal))
        if literal[-1:].isalpha():
            out.append("[ -]?")
        out.append(r"\d+")
        pos = m.end()
    out.append(re.escape(pattern[pos:]))
    return re.compile("".join(out))


def load(vault: Vault) -> Ontology:
    """The vault's ontology; empty if there is no `ontology.md`."""
    if not vault.exists(ONTOLOGY_FILE):
        return Ontology()
    return parse(vault.read_text(ONTOLOGY_FILE))


def parse(markdown: str) -> Ontology:
    """The first ```yaml block's `kinds`. Problems are reported, never raised."""
    ont = Ontology()
    m = _BLOCK.search(markdown)
    if not m:
        ont.problems.append(Problem(1, "no ```yaml block with `kinds:` found"))
        return ont
    line0 = markdown[: m.start(1)].count("\n") + 1
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        ont.problems.append(Problem(line0 + (mark.line if mark else 0), f"YAML: {exc}"))
        return ont
    kinds = data.get("kinds") if isinstance(data, dict) else None
    if not isinstance(kinds, dict):
        ont.problems.append(Problem(line0, "the yaml block has no `kinds:` mapping"))
        return ont
    lines = m.group(1).splitlines()

    def line_of(name: str) -> int:
        for n, text in enumerate(lines):
            if text.strip().startswith(f"{name}:"):
                return line0 + n
        return line0

    for name, spec in kinds.items():
        name = str(name)
        if not _KIND_NAME.fullmatch(name):
            ont.problems.append(Problem(line_of(name), f"kind {name!r}: use lower_snake_case"))
            continue
        spec = spec or {}
        if not isinstance(spec, dict):
            ont.problems.append(Problem(line_of(name), f"kind {name!r}: expected a mapping"))
            continue
        ident = str(spec.get("id") or "")
        scoped = bool(spec.get("scoped"))
        if ident and not scoped:
            ont.problems.append(Problem(line_of(name), f"kind {name!r}: `id` needs `scoped: true`"))
            ident = ""
        if ident and not _PLACEHOLDER.search(ident):
            ont.problems.append(Problem(line_of(name), f"kind {name!r}: id {ident!r} has no {{n}}"))
            ident = ""
        ont.kinds[name] = Kind(
            name,
            _names(spec.get("part_of")),
            _names(spec.get("has")),
            scoped,
            ident,
            compile_id(ident) if ident else None,
        )
    for k in ont.kinds.values():
        for ref in (*k.part_of, *k.has):
            if ref not in ont.kinds:
                message = f"kind {k.name!r} refers to undefined kind {ref!r}"
                ont.problems.append(Problem(line_of(k.name), message))
    return ont


def known_kinds(ontology: Ontology) -> set[str]:
    """Kinds a page may have without a lint warning (D4): the ontology's and the built-in."""
    return set(ontology.kinds) | set(ENTITY_KINDS)


def _names(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return (str(value),)
