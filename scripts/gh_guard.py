"""PreToolUse hook: keep private document content off GitHub.

Claude Code runs this before every Bash / PowerShell tool call (see
`.claude/settings.json`) and passes the call as JSON on stdin. Commands that
don't run `gh` pass untouched. For a `gh` command, the command text plus any
file it reads a body from (`--body-file`, `-F`, `--input`, `--field k=@file`)
is checked against `.gh-denylist` in the repo root: gitignored, maintained by
the human, one term per line, `#` starts a comment, matched case-insensitively
as whole words. Typical terms: names, projects and identifiers from the private
bench corpus or private vaults.

On a hit the script exits 2, which blocks the call; the message names the
denylist line but never echoes the term, so the agent doesn't see it either.
Fails closed if a gh command can't be checked. Stdlib only.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DENYLIST = ROOT / ".gh-denylist"

GH_COMMAND = re.compile(r"(?:^|[\s;&|(`$\"'])gh(?:\.exe)?\s+[a-z]")
BODY_FILE_FLAGS = ("--body-file", "-F", "--input", "--field")


def load_denylist(path: Path = DENYLIST) -> list[tuple[int, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    terms = []
    for number, line in enumerate(lines, start=1):
        term = line.split("#", 1)[0].strip()
        if term:
            terms.append((number, term))
    return terms


def body_files(command: str, cwd: Path) -> list[Path]:
    """Files a gh command reads its body from. `-` (stdin) is part of the command text."""
    try:
        args = shlex.split(command, posix=True)
    except ValueError:
        args = command.split()
    values = []
    for i, arg in enumerate(args):
        for flag in BODY_FILE_FLAGS:
            if arg == flag and i + 1 < len(args):
                values.append((flag, args[i + 1]))
            elif arg.startswith(flag + "="):
                values.append((flag, arg[len(flag) + 1 :]))
    files = []
    for flag, value in values:
        if flag in ("-F", "--field"):
            # gh issue/pr: -F is --body-file. gh api: -F key=value, or key=@file.
            if "=@" in value:
                value = value.split("=@", 1)[1]
            elif "=" in value:
                continue  # plain field, already in the command text
        if value and value != "-":
            path = Path(value)
            files.append(path if path.is_absolute() else cwd / path)
    return files


def find_problems(text: str, denylist: list[tuple[int, str]]) -> list[str]:
    return [
        f"term from .gh-denylist line {number}"
        for number, term in denylist
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE)
    ]


def check(payload: dict, root: Path = ROOT) -> list[str]:
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not GH_COMMAND.search(command):
        return []
    cwd = Path(payload.get("cwd") or root)
    text = command
    for path in body_files(command, cwd):
        try:
            text += "\n" + path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [f"can't read body file {path} to check it"]
    return find_problems(text, load_denylist(root / ".gh-denylist"))


def main() -> int:
    raw = sys.stdin.read()
    try:
        problems = check(json.loads(raw))
    except Exception as exc:  # fail closed, but only for something that looks like gh
        if not GH_COMMAND.search(raw):
            return 0
        print(f"gh_guard: could not check the command ({exc}); blocked.", file=sys.stderr)
        return 2
    if problems:
        print("gh_guard: blocked, this would put private content on GitHub:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("Rewrite it with fixture-style names (tests/fixtures).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
