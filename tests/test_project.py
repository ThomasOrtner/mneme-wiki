"""#27: a source declares its project; its bare document-local ids are expanded to it."""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path

import pytest

from mneme_wiki import cli
from mneme_wiki.integrate import IntegrateError, integrate
from mneme_wiki.lint import lint
from mneme_wiki.packet import PacketError, Project, load, project_of
from mneme_wiki.vault import Vault, init_vault

from .conftest import FIXTURES
from .fakes import Toy, fake_llm
from .test_vault import git_identity  # noqa: F401 - pytest fixture

PACKETS = FIXTURES / "packets"
DAY = dt.date(2026, 11, 5)
LOCAL_ID = re.compile(r"\b(WP\d|D\d)\b")


class WorkPackages(Toy):
    """Extract sees only work packages and deliverables. Like the real prompt asks (#13),
    it qualifies an id with the owner the document title names, and leaves it bare when
    the title names none."""

    def extract(self, user: str) -> dict:
        title = re.search(r"^Document: (.+?) \(", user, re.MULTILINE).group(1)
        owner = "Project Alpha" if title.startswith("Project Alpha") else ""
        chunk = user.split("--- CHUNK ---", 1)[1].split("--- END ---", 1)[0]
        subjects: dict[str, dict] = {}
        for sentence in re.split(r"(?<=[.!?])\s+", chunk):
            for local in LOCAL_ID.findall(sentence):
                name = f"{owner} {local}".strip()
                s = subjects.setdefault(name, {
                    "name": name, "kind": "entity", "entity_kind": "document",
                    "aliases": [], "description": f"{name}.", "claims": [],
                })  # fmt: skip
                if sentence.strip() not in s["claims"]:
                    s["claims"].append(sentence.strip())
        return {"subjects": list(subjects.values())}


@pytest.fixture
def vault(tmp_path: Path, git_identity) -> Vault:  # noqa: F811
    return init_vault(tmp_path / "vault", language="en", today=DAY)


def run(vault: Vault, packet: Path, **kwargs):
    llm, backend = fake_llm(WorkPackages())
    report = integrate(vault, packet, llm=llm, inbox=vault.root.parent / "inbox", today=DAY,
                       **kwargs)  # fmt: skip
    return report, backend


def without_project(tmp_path: Path) -> Path:
    """`progress-report-1` without its `local_id_owner` field."""
    dest = tmp_path / "progress-report-1"
    shutil.copytree(PACKETS / "progress-report-1", dest)
    meta_file = dest / "source.meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    del meta["local_id_owner"]
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    return dest


def resolve_log(vault: Vault, report) -> list[dict]:
    text = vault.read_text(f"{report.run_dir}/resolve_log.jsonl")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# -- the packet field -------------------------------------------------------------------
def test_project_field_takes_both_forms() -> None:
    assert project_of({}) is None and project_of({"local_id_owner": ""}) is None
    assert project_of({"project": "RFM-GIS"}) is None  # mneme's collection label: ignored
    assert project_of({"local_id_owner": " Project  Alpha "}) == Project("Project Alpha")
    assert project_of({"local_id_owner": {"name": "Project Alpha", "short": "PA"}}) == Project(
        "Project Alpha", "PA"
    )
    for bad in (3, ["Project Alpha"], {"short": "PA"}, {"name": "X", "short": 1}):
        with pytest.raises(PacketError):
            project_of({"local_id_owner": bad})
    assert load(PACKETS / "progress-report-1").project == Project("Project Alpha")


# -- integrate (fake model) ---------------------------------------------------------------
def test_bare_ids_go_to_the_projects_pages_by_exact_match(vault: Vault) -> None:
    first, _ = run(vault, PACKETS / "proposal-alpha")
    assert "entities/project-alpha-wp2.md" in first.created
    report, backend = run(vault, PACKETS / "progress-report-1")
    assert report.ok and report.created == []  # no new WP/D page
    assert {"entities/project-alpha-wp2.md", "entities/project-alpha-d2.md",
            "entities/project-alpha-wp3.md"} <= set(report.updated)  # fmt: skip
    decisions = {d["name"]: d for d in resolve_log(vault, report)}
    assert decisions["Project Alpha WP2"]["how"] == "exact"
    assert decisions["Project Alpha WP2"]["checks"] == []
    assert not any(r["role"] == "resolve" for r in backend.requests)
    assert "month 17" in vault.read_text("entities/project-alpha-wp2.md")
    assert report.counters["local_id_project_expanded"] == 3
    extract_prompt = next(r["user"] for r in backend.requests if r["role"] == "extract")
    assert "Project: " not in extract_prompt  # code expands; the model is not told
    assert lint(vault).ok


def test_without_a_project_bare_ids_are_checked_as_before(vault: Vault, tmp_path: Path) -> None:
    run(vault, PACKETS / "proposal-alpha")
    report, backend = run(vault, without_project(tmp_path))
    decisions = {d["name"]: d for d in resolve_log(vault, report)}
    assert decisions["WP2"]["how"] == "new" and decisions["WP2"]["checks"]  # the yes/no check
    assert any(r["role"] == "resolve" for r in backend.requests)
    extract_prompt = next(r["user"] for r in backend.requests if r["role"] == "extract")
    assert "Project:" not in extract_prompt


def test_source_page_records_the_project(vault: Vault, tmp_path: Path) -> None:
    report, _ = run(vault, PACKETS / "progress-report-1")  # no project page yet (D3)
    assert vault.read_page(report.source_page).meta["project"] == "Project Alpha"
    assert report.created  # its ids are expanded all the same
    assert "entities/project-alpha-wp2.md" in report.created


def test_source_page_links_the_project_page_when_it_exists(vault: Vault) -> None:
    vault.write_text("entities/project-alpha.md", "---\ntitle: Project Alpha\ntype: entity\n"
                     "aliases: [PA]\n---\n\n# Project Alpha\n\nA project.\n")  # fmt: skip
    vault.git("add", "-A")
    vault.git("commit", "-q", "-m", "page")
    report, _ = run(vault, PACKETS / "progress-report-1")
    assert vault.read_page(report.source_page).meta["project"] == "[[entities/project-alpha]]"
    # the project's short name (from its page) makes the PA-WP2 alias (#13 D3)
    assert "PA-WP2" in vault.read_page("entities/project-alpha-wp2.md").meta["aliases"]


def test_project_flag_sets_and_conflicts(vault: Vault, tmp_path: Path) -> None:
    run(vault, PACKETS / "proposal-alpha")
    report, _ = run(vault, without_project(tmp_path), project="Project Alpha")
    assert report.created == [] and "entities/project-alpha-wp2.md" in report.updated
    head = vault.git("rev-parse", "HEAD").stdout
    with pytest.raises(IntegrateError, match="declares local_id_owner"):
        run(vault, PACKETS / "progress-report-1", project="Project Beta")
    assert vault.git("rev-parse", "HEAD").stdout == head and vault.is_clean()


def test_cli_project_flag_conflict_writes_nothing(vault: Vault, capsys) -> None:
    code = cli.main(["integrate", str(PACKETS / "progress-report-1"), "--vault",
                     str(vault.root), "--local-id-owner", "Project Beta", "--json"])  # fmt: skip
    out = json.loads(capsys.readouterr().out)
    assert code != 0 and "declares local_id_owner" in json.dumps(out)
    assert vault.is_clean() and len(vault.git("log", "--format=%h").stdout.split()) == 1
