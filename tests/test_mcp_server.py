from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mneme_wiki import config, mcp_server
from mneme_wiki.jobs import JobQueue
from mneme_wiki.vault import Vault, init_vault

from .conftest import FIXTURES
from .fakes import Toy, fake_llm
from .test_vault import git_identity  # noqa: F401 - pytest fixture

KINDS = {"Rover Operations Control Centre": "entity", "Science Team": "entity"}
SRC = "sources/rover-operations-handbook"


@pytest.fixture
def server(tmp_path: Path, monkeypatch, git_identity):  # noqa: F811
    root = tmp_path / "vault"
    init_vault(root, language="en", today=dt.date(2026, 11, 5))
    inbox = tmp_path / "inbox"
    for name in ("ops-handbook", "planning-notes"):
        shutil.copytree(FIXTURES / "packets" / name, inbox / name)
    monkeypatch.setattr(config, "VAULT_DIR", root)
    monkeypatch.setattr(config, "INBOX_DIR", str(inbox))
    toy = Toy(kinds=KINDS, same=[("Tactical Planning", "Tactical Planning Cycle")])

    def handler(role, system, user, schema, thinking):
        if role == "query":
            return {"answer": f"The ROCC operates the rover ([[{SRC}]]).", "answerable": True,
                    "pages": ["entities/rover-operations-control-centre"]}  # fmt: skip
        return toy(role, system, user, schema, thinking)

    monkeypatch.setattr(mcp_server, "_llm", lambda log_fn=None: fake_llm(handler)[0])
    monkeypatch.setattr(mcp_server, "_jobs", JobQueue())
    return Vault(root)


def run_job(packet: str, **kw) -> dict:
    job = mcp_server.integrate(packet, **kw)
    assert mcp_server._jobs.wait(30)
    return mcp_server.job_status(job["job_id"])


def test_tools_are_registered() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {"status", "search", "read_page", "lint", "query", "integrate", "job_status"}
    assert not {n for n in names if "delete" in n or "rename" in n}


def test_integrate_job_then_read_tools(server: Vault) -> None:
    st = mcp_server.status()
    assert st["pages"] == {"index": 1, "log": 1}
    assert [p["packet"] for p in st["packets"]] == ["ops-handbook", "planning-notes"]
    assert all(p["integrated_as"] is None for p in st["packets"])

    dry = run_job("ops-handbook", dry_run=True)
    assert dry["status"] == "done" and "+++ b/entities/science-team.md" in dry["result"]["diff"]
    snap = run_job("ops-handbook")
    assert snap["status"] == "done" and snap["result"]["commit"]
    assert "diff" not in snap["result"] and any("committed" in ln for ln in snap["log"])

    st = mcp_server.status()
    assert st["packets"][0]["integrated_as"] == f"{SRC}.md"
    assert st["git_head"].endswith("integrate: Rover Operations Handbook")
    assert st["uncommitted_changes"] is False and len(st["jobs"]) == 2

    hits = mcp_server.search("science team observations")
    assert hits[0]["path"] == "entities/science-team.md"
    assert mcp_server.search("rover", type="source")[0]["type"] == "source"
    page = mcp_server.read_page("entities/science-team")
    assert (
        page["meta"]["type"] == "entity" and page["meta"]["created"] == dt.date.today().isoformat()
    )
    assert mcp_server.read_page("ROCC")["path"] == "entities/rover-operations-control-centre.md"
    assert mcp_server.lint()["ok"] is True

    answer = mcp_server.query("Who operates the rover?", file=True)
    assert answer["filed"] == "syntheses/who-operates-the-rover.md" and answer["commit"]


def test_tool_errors_are_messages(server: Vault) -> None:
    with pytest.raises(ToolError, match="no page"):
        mcp_server.read_page("nothing-like-this")
    with pytest.raises(ToolError, match="inside the inbox"):
        mcp_server.integrate("../vault")
    with pytest.raises(ToolError, match="not a packet folder"):
        mcp_server.integrate("missing")
    with pytest.raises(ToolError, match="no job"):
        mcp_server.job_status("nope")
    run_job("ops-handbook")
    failed = run_job("ops-handbook")  # already integrated: the job fails, the worker lives
    assert failed["status"] == "failed" and "already integrated" in failed["error"]
    assert run_job("planning-notes")["status"] == "done"


def test_stdio_round_trip(tmp_path: Path, git_identity) -> None:  # noqa: F811
    """The real server over stdio: stdout carries only the protocol."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    root = tmp_path / "vault"
    init_vault(root, language="en")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mneme_wiki.mcp_server"],
        env={**os.environ, "WIKI_VAULT_DIR": str(root)},
    )

    async def main() -> dict:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("status", {})
            return json.loads(result.content[0].text)

    data = asyncio.run(main())
    assert Path(data["vault"]) == root.resolve() and data["pages"] == {"index": 1, "log": 1}


def test_documented_registration_avoids_the_locked_exe() -> None:
    # Issue #11: on Windows a running mneme-wiki-mcp.exe is locked, so `pip install -e .`
    # fails halfway and leaves the venv without mneme_wiki. Every documented
    # registration must start the server through Python (`-m mneme_wiki.mcp_server`).
    repo = Path(__file__).resolve().parent.parent
    docs = [*sorted((repo / "docs" / "wiki").glob("*.md")), repo / "mneme_wiki" / "mcp_server.py"]
    commands = [
        line.strip()
        for doc in docs
        for line in doc.read_text(encoding="utf-8").splitlines()
        if "claude mcp add mneme-wiki" in line
    ]
    assert commands, "no documented registration found"
    for cmd in commands:
        server = cmd.split(" -- ", 1)[1]
        assert server.endswith("-m mneme_wiki.mcp_server"), cmd
