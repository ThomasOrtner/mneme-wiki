from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mneme_wiki import cli
from mneme_wiki import frontmatter as fm
from mneme_wiki.index_log import append_log, log_entry, reindex
from mneme_wiki.lint import lint
from mneme_wiki.vault import Vault, init_vault

from .test_vault import git_identity  # noqa: F401 - pytest fixture

DAY = dt.date(2026, 11, 5)


def test_reindex_lists_every_page_by_type(fixture_vault) -> None:
    v = Vault(fixture_vault("clean"))
    assert reindex(v, today=DAY) is True
    doc = fm.parse(v.read_text("index.md"))
    assert doc.meta["created"] == dt.date(2026, 11, 2) and doc.meta["updated"] == DAY
    body = doc.body
    assert body.index("## Sources") < body.index("rocc-glossary") < body.index("## Entities")
    assert (
        "- [[concepts/activity-plan|Activity Plan]] — "
        "The commands the rover executes in one sol, made in the planning cycle." in body
    )
    concepts = body[body.index("## Concepts") : body.index("## Syntheses")]
    assert concepts.index("Activity Plan") < concepts.index("Tactical Planning Cycle")
    assert reindex(v, today=DAY + dt.timedelta(days=1)) is False  # idempotent, date kept
    assert fm.parse(v.read_text("index.md")).meta["updated"] == DAY
    assert lint(v).ok


def test_reindex_on_fresh_vault_is_a_no_op(tmp_path: Path, git_identity) -> None:  # noqa: F811
    v = init_vault(tmp_path / "v", language="en", today=DAY)
    before = v.read_text("index.md")
    assert reindex(v, today=DAY + dt.timedelta(days=3)) is False
    assert v.read_text("index.md") == before


def test_reindex_skips_broken_pages_and_recreates_index(fixture_vault) -> None:
    v = Vault(fixture_vault("broken-yaml"))
    assert reindex(v, today=DAY) is True
    body = v.read_text("index.md")
    assert "missing-type-fields" in body  # valid YAML, listed under its type
    assert "bad-syntax" not in body and "no-front-matter" not in body


def test_reindex_keeps_crlf(tmp_path: Path) -> None:
    (tmp_path / "index.md").write_bytes(b"---\r\ntitle: Index\r\ntype: index\r\n---\r\n\r\nold\r\n")
    v = Vault(tmp_path)
    reindex(v, today=DAY)
    raw = (tmp_path / "index.md").read_bytes()
    assert b"## Sources\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


def test_log_entry_format() -> None:
    assert log_entry("integrate", "ROCC  Glossary\n", ["- a", "- b  "], day=DAY) == (
        "## [2026-11-05] integrate | ROCC Glossary\n\n- a\n- b\n"
    )
    assert log_entry("lint", "x", day=DAY) == "## [2026-11-05] lint | x\n"
    for op in ("Integrate", "two words", "x|y", ""):
        with pytest.raises(ValueError):
            log_entry(op, "t", day=DAY)
    with pytest.raises(ValueError):
        log_entry("op", "  ", day=DAY)


def test_append_log_only_appends(fixture_vault) -> None:
    v = Vault(fixture_vault("clean"))
    before = v.read_text("log.md")
    append_log(
        v, "query", "Who plans a sol?", ["- filed: [[syntheses/who-plans-a-sol]]"], today=DAY
    )
    after = v.read_text("log.md")
    old_body = fm.parse(before).body
    new_doc = fm.parse(after)
    assert new_doc.body.startswith(old_body.rstrip("\n"))
    assert new_doc.body.endswith(
        "\n\n## [2026-11-05] query | Who plans a sol?\n\n- filed: [[syntheses/who-plans-a-sol]]\n"
    )
    assert new_doc.meta["updated"] == DAY


def test_append_log_creates_missing_log(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    append_log(v, "integrate", "First", today=DAY)
    doc = fm.parse(v.read_text("log.md"))
    assert doc.meta["type"] == "log"
    assert doc.body.endswith("## [2026-11-05] integrate | First\n")


def test_append_log_to_broken_front_matter_keeps_bytes(tmp_path: Path) -> None:
    (tmp_path / "log.md").write_bytes(b"---\ntitle: [broken\n---\r\n# Log\r\n")
    v = Vault(tmp_path)
    append_log(v, "lint", "x", today=DAY)
    raw = (tmp_path / "log.md").read_bytes()
    assert raw.startswith(b"---\ntitle: [broken\n---\r\n# Log\r\n")
    assert raw.endswith(b"\r\n\r\n## [2026-11-05] lint | x\r\n")


def test_cli_reindex(fixture_vault, capsys) -> None:
    root = fixture_vault("clean")
    assert cli.main(["reindex", "--vault", str(root), "--json"]) == 0
    assert '"changed": true' in capsys.readouterr().out
    assert "reindex | index" in (root / "log.md").read_text(encoding="utf-8")
    assert cli.main(["reindex", "--vault", str(root)]) == 0
    assert "already up to date" in capsys.readouterr().out
