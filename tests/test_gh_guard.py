"""scripts/gh_guard.py: the PreToolUse hook that keeps denylisted terms off GitHub."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gh_guard.py"
_spec = importlib.util.spec_from_file_location("gh_guard", SCRIPT)
gh_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gh_guard)


def _payload(command: str, cwd: Path) -> dict:
    return {"tool_input": {"command": command}, "cwd": str(cwd)}


def _root(tmp_path: Path, terms: str = "Secret Project  # a codename\nACME-42\n") -> Path:
    (tmp_path / ".gh-denylist").write_text(terms, encoding="utf-8")
    return tmp_path


def test_non_gh_commands_pass(tmp_path):
    root = _root(tmp_path)
    assert gh_guard.check(_payload("echo secret project", root), root) == []
    assert gh_guard.check(_payload("git commit -m 'Secret Project'", root), root) == []


def test_denylisted_term_in_command_is_blocked(tmp_path):
    root = _root(tmp_path)
    problems = gh_guard.check(_payload('gh issue create -t "about secret project"', root), root)
    assert problems == ["term from .gh-denylist line 1"]


def test_match_is_whole_word(tmp_path):
    root = _root(tmp_path)
    assert gh_guard.check(_payload('gh issue create -t "ACME-421"', root), root) == []
    assert gh_guard.check(_payload('gh issue create -t "ACME-42."', root), root) == [
        "term from .gh-denylist line 2"
    ]


def test_body_file_is_checked(tmp_path):
    root = _root(tmp_path)
    (tmp_path / "body.md").write_text("Results for ACME-42\n", encoding="utf-8")
    for cmd in (
        "gh pr create --body-file body.md",
        "gh pr create --body-file=body.md",
        "gh issue comment 3 -F body.md",
        "gh api repos/x/y/issues -F body=@body.md",
    ):
        assert gh_guard.check(_payload(cmd, root), root), cmd


def test_unreadable_body_file_blocks(tmp_path):
    root = _root(tmp_path)
    problems = gh_guard.check(_payload("gh pr create --body-file missing.md", root), root)
    assert problems and "can't read body file" in problems[0]


def test_no_denylist_passes(tmp_path):
    assert gh_guard.check(_payload('gh issue create -t "anything"', tmp_path), tmp_path) == []


def test_hook_exit_codes_and_term_not_echoed(tmp_path):
    root = _root(tmp_path)
    script = tmp_path / "scripts" / "gh_guard.py"
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())  # ROOT = the script's parent's parent

    def run_raw(stdin: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script)], input=stdin, capture_output=True, text=True
        )

    def run(command: str) -> subprocess.CompletedProcess:
        return run_raw(json.dumps(_payload(command, root)))

    assert run('gh issue create -t "fine"').returncode == 0
    blocked = run('gh issue create -t "Secret Project"')
    assert blocked.returncode == 2
    assert "line 1" in blocked.stderr
    assert "secret project" not in blocked.stderr.lower()
    assert run_raw("{not json; gh issue list").returncode == 2  # fail closed
    assert run_raw("{not json; ls").returncode == 0
