from __future__ import annotations

import pytest

from mneme_wiki.vault import CaseCollisionError, UnsafePathError, Vault
from mneme_wiki.workspace import Workspace


def test_overlay_reads_writes_diff_flush(fixture_vault) -> None:
    root = fixture_vault("clean")
    vault = Vault(root)
    ws = Workspace(vault)
    before = vault.read_text("concepts/activity-plan.md")
    assert ws.write_text("concepts/activity-plan.md", before + "extra\n") is True
    assert ws.write_text("concepts/new-page.md", "# New\n") is True
    assert ws.read_text("concepts/activity-plan.md").endswith("extra\n")
    assert vault.read_text("concepts/activity-plan.md") == before  # disk untouched
    assert "concepts/new-page.md" in ws.page_paths()
    assert ws.created() == ["concepts/new-page.md"]
    assert ws.modified() == ["concepts/activity-plan.md"]
    diff = ws.diff()
    assert "+extra" in diff and "--- /dev/null" in diff and "+++ b/concepts/new-page.md" in diff

    assert ws.write_text("concepts/activity-plan.md", before) is True  # changed back
    assert ws.modified() == []
    assert ws.flush() == ["concepts/new-page.md"]
    assert (root / "concepts/new-page.md").read_bytes() == b"# New\n" and ws.changes == {}


def test_overlay_keeps_path_rules(fixture_vault) -> None:
    ws = Workspace(Vault(fixture_vault("windows-hostile")))
    with pytest.raises(UnsafePathError):
        ws.write_text("../outside.md", "x")
    with pytest.raises(CaseCollisionError):
        ws.write_text("entities/rocc.md", "x")  # entities/ROCC.md exists on disk
    ws.write_text("concepts/Pending.md", "x")
    with pytest.raises(CaseCollisionError):
        ws.write_text("concepts/pending.md", "y")
    with pytest.raises(CaseCollisionError):
        ws.path_for("concept", "pending")
