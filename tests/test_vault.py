from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from pathlib import Path

import pytest

from mneme_wiki import frontmatter as fm
from mneme_wiki import vault as vlt
from mneme_wiki.vault import CaseCollisionError, UnsafePathError, Vault, VaultError

from .conftest import FIXTURES


# --- slugs ------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Retrieval-Augmented Generation", "retrieval-augmented-generation"),
        ("Rover Operations Control Centre (ROCC)", "rover-operations-control-centre-rocc"),
        ("Größe des Rovers", "groesse-des-rovers"),
        ("Café Crème", "cafe-creme"),
        ('What? A: <test> | "x" *y*', "what-a-test-x-y"),
        ("a/b\\c", "a-b-c"),
        ("  --Trailing dots...  ", "trailing-dots"),
        ("CON", "con-page"),
        ("lpt1", "lpt1-page"),
        ("Con Air", "con-air"),
        ("PRo3D", "pro3d"),
        ("dar_ci", "dar-ci"),
    ],
)
def test_slugify(title: str, slug: str) -> None:
    assert vlt.slugify(title) == slug


def test_slugify_non_latin_is_stable_and_safe() -> None:
    slug = vlt.slugify("火星探测器")
    assert re.fullmatch(r"page-[0-9a-f]{8}", slug)
    assert slug == vlt.slugify("火星探测器") != vlt.slugify("月球")


def test_slugify_length_cut_at_word() -> None:
    slug = vlt.slugify("word " * 40)
    assert len(slug) <= vlt.SLUG_MAX and not slug.endswith("-")
    assert slug.endswith("word")


def test_slugs_are_safe_names() -> None:
    for title in ["CON", "aux.txt", "x: y", "a. ", "nul"]:
        vlt.check_name(vlt.slugify(title) + ".md")


# --- path confinement ---------------------------------------------------------------
@pytest.mark.parametrize(
    "rel",
    ["../outside.md", "concepts/../../x.md", "/etc/passwd", "C:/Windows/x.md", "C:x.md",
     "\\\\server\\share\\x.md", "..", ""],
)  # fmt: skip
def test_paths_outside_vault_are_rejected(tmp_path: Path, rel: str) -> None:
    with pytest.raises(UnsafePathError):
        Vault(tmp_path).abspath(rel)


@pytest.mark.parametrize(
    "rel", ["concepts/CON.md", "a:b.md", "x.md.", "dir /x.md", "q?.md", "nul.txt", "a\x01.md"]
)
def test_hostile_names_are_rejected_for_write(tmp_path: Path, rel: str) -> None:
    with pytest.raises(UnsafePathError):
        Vault(tmp_path).write_text(rel, "x")


def test_backslashes_are_normalised(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    assert v.abspath("concepts\\a.md") == v.abspath("concepts/a.md")


# --- writing ------------------------------------------------------------------------
def test_write_is_atomic_and_exact(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    text = "\ufeff---\r\ntitle: Ä\r\n---\r\nbody\r\n"
    assert v.write_text("concepts/a.md", text) is True
    assert (tmp_path / "concepts/a.md").read_bytes() == text.encode("utf-8")
    assert v.read_text("concepts/a.md") == text
    assert v.write_text("concepts/a.md", text) is False  # unchanged → no write
    assert os.listdir(tmp_path / "concepts") == ["a.md"]  # no temp files left behind


def test_failed_write_leaves_no_temp_file(tmp_path: Path, monkeypatch) -> None:
    v = Vault(tmp_path)
    v.write_text("a.md", "old")

    def boom(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(vlt.os, "replace", boom)
    with pytest.raises(OSError):
        v.write_text("a.md", "new")
    assert os.listdir(tmp_path) == ["a.md"]
    assert v.read_text("a.md") == "old"


def test_page_round_trip_through_vault(fixture_vault) -> None:
    root = fixture_vault("clean")
    v = Vault(root)
    before = {p: (root / p).read_bytes() for p in v.files()}
    for _rel, page in v.iter_pages():
        assert not isinstance(page, Exception)
        assert v.write_page(page) is False  # nothing changed → nothing written
    assert {p: (root / p).read_bytes() for p in v.files()} == before


def test_page_edit_through_vault(fixture_vault) -> None:
    v = Vault(fixture_vault("clean"))
    page = v.read_page("concepts/activity-plan.md")
    page.meta["status"] = "active"
    assert v.write_page(page) is True
    again = v.read_page("concepts/activity-plan.md")
    assert again.meta["status"] == "active" and again.body == page.body


# --- case collisions (NTFS is case-insensitive) --------------------------------------
def test_case_collision_on_new_page(fixture_vault) -> None:
    v = Vault(fixture_vault("windows-hostile"))
    with pytest.raises(CaseCollisionError, match="entities/ROCC.md"):
        v.path_for("entity", "ROCC")
    with pytest.raises(CaseCollisionError):
        v.write_text("entities/rocc.md", "x")
    with pytest.raises(CaseCollisionError, match="'entities'"):
        v.write_text("Entities/new.md", "x")
    assert v.path_for("entity", "Rover Ops") == "entities/rover-ops.md"


def test_existing_human_names_still_work(fixture_vault) -> None:
    v = Vault(fixture_vault("windows-hostile"))
    page = v.read_page("concepts/Größe des Rovers.md")
    page.body += "\nmore\n"
    assert v.write_page(page) is True  # same exact name → no collision
    assert v.write_text("entities/ROCC.md", v.read_text("entities/ROCC.md")) is False


def test_case_collisions_pure() -> None:
    paths = ["entities/ROCC.md", "entities/rocc.md", "concepts/a.md", "Concepts/A.md", "b.md"]
    assert vlt.case_collisions(paths) == [
        ["entities/ROCC.md", "entities/rocc.md"],
        ["Concepts/A.md", "concepts/a.md"],
    ]


def test_path_for_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(VaultError):
        Vault(tmp_path).path_for("index", "Index")


# --- listing ------------------------------------------------------------------------
def test_page_paths_skip_schema_attachments_hidden(fixture_vault) -> None:
    root = fixture_vault("clean")
    (root / ".obsidian").mkdir()
    (root / ".obsidian/app.md").write_text("x", encoding="utf-8")
    (root / "attachments/note.md").write_text("x", encoding="utf-8")
    v = Vault(root)
    pages = v.page_paths()
    assert "WIKI.md" not in pages and "index.md" in pages
    assert not any(p.startswith((".obsidian", "attachments")) for p in pages)
    assert "attachments/diagram.png" in v.files()


def test_iter_pages_reports_broken_front_matter() -> None:
    results = dict(Vault(FIXTURES / "broken-yaml").iter_pages())
    errors = {p for p, r in results.items() if isinstance(r, fm.FrontMatterError)}
    assert errors == {
        "concepts/bad-syntax.md",
        "concepts/duplicate-key.md",
        "concepts/not-a-mapping.md",
        "concepts/unterminated.md",
    }


# --- git & init ---------------------------------------------------------------------
@pytest.fixture
def git_identity(monkeypatch) -> None:
    for key, value in {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,  # ignore the user's hooks, signing, etc.
    }.items():
        monkeypatch.setenv(key, value)


def test_init_vault(tmp_path: Path, git_identity) -> None:
    root = tmp_path / "my-vault"
    lines: list[str] = []
    v = vlt.init_vault(root, language="de", today=dt.date(2026, 11, 2), log=lines.append)
    assert lines
    for folder in vlt.VAULT_DIRS:
        assert (root / folder).is_dir()
    schema = fm.parse(v.read_text("WIKI.md"))
    assert schema.meta["language"] == "de" and "{{language}}" not in schema.body
    for rel in ("index.md", "log.md"):
        page = v.read_page(rel)
        assert fm.validate(page.meta) == []
        assert page.meta["created"] == dt.date(2026, 11, 2)
    log_text = v.read_text("log.md")
    assert re.search(r"^## \[2026-11-02\] init \| my-vault$", log_text, re.M)
    assert v.git("log", "--format=%s").stdout.strip() == "init: my-vault"
    assert v.git("status", "--porcelain").stdout == ""
    assert v.git("check-attr", "text", "--", "concepts/x.md").stdout.strip().endswith("unset")


def test_vault_git_keeps_crlf_bytes(tmp_path: Path, git_identity) -> None:
    v = vlt.init_vault(tmp_path / "v", language="en")
    v.git("config", "core.autocrlf", "true")  # the Windows default that rewrites endings
    text = "---\r\ntitle: A\r\n---\r\nbody\r\n"
    v.write_text("concepts/a.md", text)
    sha = v.commit("a")
    stored = subprocess.run(
        ["git", "-C", str(v.root), "show", f"{sha}:concepts/a.md"], capture_output=True, check=True
    ).stdout  # raw bytes: text mode would translate CRLF itself
    assert stored == text.encode("utf-8")


def test_init_refuses_non_empty(tmp_path: Path, git_identity) -> None:
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(VaultError, match="not an empty folder"):
        vlt.init_vault(tmp_path, language="en")


def test_init_into_empty_existing_folder(tmp_path: Path, git_identity) -> None:
    vlt.init_vault(tmp_path, language="en")
    assert (tmp_path / ".git").is_dir()


def test_commit(tmp_path: Path, git_identity) -> None:
    v = vlt.init_vault(tmp_path / "v", language="en")
    assert v.commit("noop") is None  # nothing to commit
    v.write_text("concepts/a.md", "x\n")
    sha = v.commit("feat: a")
    assert sha and re.fullmatch(r"[0-9a-f]{40}", sha)
    assert v.git("show", "--name-only", "--format=", sha).stdout.split() == ["concepts/a.md"]


def test_commit_requires_repo(tmp_path: Path) -> None:
    with pytest.raises(VaultError, match="not a git repository"):
        Vault(tmp_path).commit("x")
