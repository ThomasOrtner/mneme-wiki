from __future__ import annotations

import json
from pathlib import Path

import pytest

from mneme_wiki import cli
from mneme_wiki.lint import CHECKS, lint
from mneme_wiki.vault import Vault

from .conftest import FIXTURES

VAULTS = sorted(p.parent.name for p in FIXTURES.glob("*/expected.json"))


@pytest.mark.parametrize("name", VAULTS)
def test_lint_finds_exactly_the_planted_defects(name: str) -> None:
    expected = json.loads((FIXTURES / name / "expected.json").read_text(encoding="utf-8"))
    report = lint(Vault(FIXTURES / name))
    got = sorted([f.check, f.path, f.line] for f in report.findings)
    assert got == sorted(expected["findings"])
    for f in report.findings:
        assert f.level == CHECKS[f.check]


def test_every_check_is_covered_by_a_fixture() -> None:
    planted = {
        f[0]
        for name in VAULTS
        for f in json.loads((FIXTURES / name / "expected.json").read_text("utf-8"))["findings"]
    }
    assert planted == set(CHECKS) - {"case-collision"}  # NTFS can't hold that fixture


def test_case_collision(tmp_path: Path, monkeypatch) -> None:
    v = Vault(tmp_path)
    monkeypatch.setattr(v, "case_collisions", lambda: [["entities/A.md", "entities/a.md"]])
    found = [(f.check, f.path) for f in lint(v).findings]
    assert found == [("case-collision", "entities/A.md"), ("case-collision", "entities/a.md")]


def test_yaml_error_is_one_line() -> None:
    report = lint(Vault(FIXTURES / "broken-yaml"))
    bad = next(f for f in report.findings if f.path == "concepts/bad-syntax.md")
    assert "\n" not in bad.message and "line 1, column 11" in bad.message


def test_index_links_do_not_rescue_orphans(fixture_vault) -> None:
    root = fixture_vault("broken-links")
    (root / "index.md").write_bytes(
        b"---\ntitle: Index\ntype: index\n---\n\n- [[concepts/orphan]]\n"
    )
    checks = {(f.check, f.path) for f in lint(Vault(root)).findings}
    assert ("orphan", "concepts/orphan.md") in checks


def test_report_and_exit_code(capsys) -> None:
    assert cli.main(["lint", "--vault", str(FIXTURES / "clean"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": True, "pages": 7, "errors": 0, "warnings": 0, "findings": []}

    assert cli.main(["lint", "--vault", str(FIXTURES / "broken-links")]) == 1
    human = capsys.readouterr().out
    assert "broken-link" in human and "2 errors, 4 warnings" in human

    assert cli.main(["lint", "--vault", str(FIXTURES / "windows-hostile")]) == 0  # warnings only
    capsys.readouterr()
    assert cli.main(["lint", "--vault", str(FIXTURES / "nope"), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
