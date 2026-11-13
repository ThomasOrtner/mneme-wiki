"""#16: the vault ontology (kinds, kind guard, scoped kinds and their id patterns)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mneme_wiki import glossary, ontology
from mneme_wiki.integrate import integrate
from mneme_wiki.lint import lint
from mneme_wiki.stages import extract as extract_stage
from mneme_wiki.stages import resolve
from mneme_wiki.stages.common import ENTITY_KINDS, Claim, KnownPage, Subject, looks_local_id
from mneme_wiki.status import overview
from mneme_wiki.vault import ONTOLOGY_FILE, Vault, init_vault

from .conftest import FIXTURES
from .fakes import Toy, fake_llm
from .test_project import WorkPackages
from .test_vault import git_identity  # noqa: F401 - pytest fixture

PACKETS = FIXTURES / "packets"
DAY = dt.date(2026, 11, 13)
ONTOLOGY = """# Ontology

```yaml
kinds:
  programme:    {}
  mission:      {part_of: programme}
  rover:        {part_of: mission, has: [instrument]}
  instrument:   {part_of: [rover, mission]}
  project:      {has: [work_package, deliverable, milestone]}
  work_package: {part_of: project, scoped: true, id: "WP{n}", has: [task, deliverable]}
  task:         {part_of: work_package, scoped: true, id: "T{n}.{m}"}
  deliverable:  {part_of: project, scoped: true, id: "D{n}"}
  milestone:    {part_of: project, scoped: true, id: "MS{n}"}
```
"""


def subj(name: str, entity_kind: str, *aliases: str) -> Subject:
    return Subject(name, "entity", entity_kind, list(aliases), f"{name}.",
                   [Claim(f"{name} exists.", "x")])  # fmt: skip


@pytest.fixture
def vault(tmp_path: Path, git_identity) -> Vault:  # noqa: F811
    return init_vault(tmp_path / "vault", language="en", today=DAY)


def with_ontology(vault: Vault, text: str = ONTOLOGY) -> None:
    vault.write_text(ONTOLOGY_FILE, text)
    vault.git("add", "-A")
    vault.git("commit", "-q", "-m", "schema: ontology")


# -- parsing and id patterns --------------------------------------------------------------
def test_id_patterns_replace_the_hardcoded_shape() -> None:
    ont = ontology.parse(ONTOLOGY)
    is_local = ontology.local_id_test(ont)
    for name in ("WP2", "WP 2", "T2.1", "D3", "MS1"):
        assert is_local(name), name
    for name in ("P20", "M20", "ROCC", "WP"):  # a global acronym is an ordinary name
        assert not is_local(name), name
    assert looks_local_id("P20")  # what a vault without an ontology still does (D7)
    assert ontology.local_id_test(ontology.Ontology()) is looks_local_id
    assert ont.kind_of_qualified("Project Alpha WP2").name == "work_package"


def test_kinds_and_owner_part_of() -> None:
    ont = ontology.parse(ONTOLOGY)
    assert ont.entity_kinds()[:2] == ["programme", "mission"] and "other" in ont.entity_kinds()
    assert ont.owner_part_of(ont.kinds["deliverable"])  # part of the project (the owner)
    assert not ont.owner_part_of(ont.kinds["task"])  # part of a WP, which the owner isn't
    assert not ontology.parse("no yaml here").kinds


def test_glossary_names_beat_id_patterns() -> None:
    """D10: a name the glossary knows is never a local id, even if a pattern matches."""
    ont = ontology.parse(ONTOLOGY.replace('id: "MS{n}"', 'id: "P{n}"'))
    table = "| Term | Full name | Kind | Prefer | Definition |\n|---|---|---|---|---|\n"
    g = glossary.parse(table + "| P20 | Probe Twenty | mission | | |\n", tuple(ont.entity_kinds()))
    probe = subj("P20", "mission")
    glossary.canonicalise([probe], g)
    extract_stage.expand_local_ids([probe], "Project Alpha", is_local=ont.is_local)
    assert probe.name == "Probe Twenty"
    bare = subj("P20", "mission")
    extract_stage.expand_local_ids([bare], "Project Alpha", is_local=ont.is_local)
    assert bare.name == "Project Alpha P20"  # the pattern alone would expand it


# -- the kind guard (D11) ---------------------------------------------------------------------
def test_kind_guard_skips_the_model_check_across_kinds() -> None:
    pages = [KnownPage("entities/probe-alpha.md", "Probe Alpha", "entity", (), "A mission.",
                       "mission")]  # fmt: skip
    toy = Toy(same=[("Probe Alpha Rover", "Probe Alpha")])  # the model would merge them
    llm, backend = fake_llm(toy)
    resolved, decisions = resolve.resolve(
        llm, [subj("Probe Alpha Rover", "rover")], pages, kind_guard=True
    )
    assert resolved[0].target is None and resolved[0].how == "new"
    assert decisions[0].checks[0].via == "kind" and not decisions[0].checks[0].same
    assert not any(r["role"] == "resolve" for r in backend.requests)
    llm, _ = fake_llm(toy)  # without the guard (no ontology) the model check runs
    resolved, _ = resolve.resolve(llm, [subj("Probe Alpha Rover", "rover")], pages)
    assert resolved[0].target == "entities/probe-alpha.md"


def test_exact_name_match_across_kinds_still_merges() -> None:
    pages = [KnownPage("entities/cam-a.md", "Cam A", "entity", (), "A camera.", "instrument")]
    llm, _ = fake_llm(Toy())
    counters: dict[str, int] = {}
    resolved, _ = resolve.resolve(llm, [subj("Cam A", "rover")], pages, kind_guard=True,
                                  counters=counters)  # fmt: skip
    assert (resolved[0].target, resolved[0].how) == ("entities/cam-a.md", "exact")
    assert counters["resolve_kind_mismatch_exact"] == 1


# -- integrate (fake model) ---------------------------------------------------------------------
class SchemaRecorder(WorkPackages):
    def __init__(self) -> None:
        super().__init__()
        self.schemas: list[dict] = []

    def __call__(self, role, system, user, schema, thinking):
        if role == "extract":
            self.schemas.append(schema)
        return super().__call__(role, system, user, schema, thinking)


def run(vault: Vault, name: str, owner: str | None = None, toy: Toy | None = None):
    toy = toy or WorkPackages()
    llm, backend = fake_llm(toy)
    report = integrate(vault, PACKETS / name, llm=llm, inbox=vault.root.parent / "inbox",
                       today=DAY, project=owner)  # fmt: skip
    return report, backend


def test_scoped_ids_of_two_owners_get_two_pages_with_part_of(vault: Vault) -> None:
    with_ontology(vault)
    run(vault, "proposal-alpha", "Project Alpha")
    run(vault, "proposal-beta", "Project Beta")
    alpha = vault.read_page("entities/project-alpha-wp2.md")
    beta = vault.read_page("entities/project-beta-wp2.md")
    assert alpha.meta["entity_kind"] == beta.meta["entity_kind"] == "work_package"
    assert alpha.meta["part_of"] == "Project Alpha"  # no page for the project: its name
    assert beta.meta["part_of"] == "Project Beta"
    assert vault.read_page("entities/project-alpha-d2.md").meta["entity_kind"] == "deliverable"
    assert lint(vault).ok


def test_extract_chooses_from_the_ontologys_kinds(vault: Vault, tmp_path: Path) -> None:
    toy = SchemaRecorder()
    _, backend = run(vault, "proposal-alpha", toy=toy)  # no ontology: the built-in kinds
    enum = toy.schemas[0]["properties"]["subjects"]["items"]["properties"]["entity_kind"]["enum"]
    assert enum == list(ENTITY_KINDS) and toy.schemas[0] is extract_stage.SCHEMA
    extract_users = [r["user"] for r in backend.requests if r["role"] == "extract"]
    assert not any(extract_stage.KINDS_HEADING in u for u in extract_users)
    other = init_vault(tmp_path / "other", language="en", today=DAY)
    with_ontology(other)
    toy = SchemaRecorder()
    _, backend = run(other, "proposal-alpha", toy=toy)
    kinds = ontology.parse(ONTOLOGY).entity_kinds()
    enum = toy.schemas[0]["properties"]["subjects"]["items"]["properties"]["entity_kind"]["enum"]
    assert enum == kinds
    extract_users = [r["user"] for r in backend.requests if r["role"] == "extract"]
    assert all(u.endswith(f"{extract_stage.KINDS_HEADING} {', '.join(kinds)}")
               for u in extract_users)  # fmt: skip


def test_status_reports_the_ontology(vault: Vault) -> None:
    assert overview(vault)["ontology"] == {"active": False, "kinds": 0, "scoped": 0}
    with_ontology(vault)
    assert overview(vault)["ontology"] == {"active": True, "kinds": 9, "scoped": 4}
