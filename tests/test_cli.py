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


def test_status(tmp_path: Path, capsys, git_identity) -> None:  # noqa: F811
    assert cli.main(["init", str(tmp_path / "v"), "--json"]) == 0
    capsys.readouterr()
    inbox = tmp_path / "inbox"
    (inbox / "new").mkdir(parents=True)
    meta = '{"title": "New", "source_type": "note", "origin": "manual", "date": "2026-11-07"}'
    (inbox / "new/source.meta.json").write_text(meta, encoding="utf-8")
    (inbox / "bad").mkdir()
    (inbox / "bad/source.meta.json").write_text("{", encoding="utf-8")

    assert cli.main(["status", "--vault", str(tmp_path / "v"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["pages"] and data["uncommitted_changes"] is False
    assert data["packets"][1] == {"packet": "new", "title": "New", "integrated_as": None}
    assert "error" in data["packets"][0]

    assert cli.main(["status", "--vault", str(tmp_path / "v")]) == 0
    out = capsys.readouterr().out
    assert "git:" in out and "new: not integrated yet" in out

    assert cli.main(["status", "--vault", str(tmp_path / "nope")]) == 2


def test_init_human_output(tmp_path: Path, capsys, git_identity) -> None:  # noqa: F811
    assert cli.main(["init", str(tmp_path / "v"), "--language", "de"]) == 0
    assert "Vault ready" in capsys.readouterr().out
    assert "language: de" in (tmp_path / "v/WIKI.md").read_text(encoding="utf-8")
