from __future__ import annotations

import json
from pathlib import Path

from mneme_wiki import cli

from .test_vault import git_identity  # noqa: F401 - pytest fixture


def test_init_json(tmp_path: Path, capsys, git_identity) -> None:  # noqa: F811
    root = tmp_path / "vault"
    assert cli.main(["init", str(root), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert Path(out["vault"]) == root.resolve()
    assert Path(out["inbox"]).name == "inbox"
    assert (root / "WIKI.md").is_file()

    assert cli.main(["init", str(root), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "not an empty folder" in out["error"]


def test_init_human_output(tmp_path: Path, capsys, git_identity) -> None:  # noqa: F811
    assert cli.main(["init", str(tmp_path / "v"), "--language", "de"]) == 0
    assert "Vault ready" in capsys.readouterr().out
    assert "language: de" in (tmp_path / "v/WIKI.md").read_text(encoding="utf-8")
