"""MCP server for mneme-wiki: an agent can read, search, lint, query and integrate.

Run over stdio. Register with Claude Code through the venv's Python:

    claude mcp add mneme-wiki -- <venv>/Scripts/python.exe -m mneme_wiki.mcp_server

`mneme-wiki-mcp` works too, but on Windows the running .exe is locked and breaks
`pip install -e .` (see docs/wiki/Troubleshooting.md).

The vault is `WIKI_VAULT_DIR` (one vault per server). The MCP protocol runs over
stdout, so nothing here prints; logs go to stderr (TD-10). `integrate` runs as a
background job (minutes per source); poll it with `job_status`. There are no
delete or rename tools (BR-11): those stay gated, outside MCP.
"""

from __future__ import annotations

import functools
import json
import logging
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import config, links
from .vault import Page, Vault, VaultError

log = logging.getLogger("mneme_wiki.mcp")

mcp = MCPServer(
    "mneme-wiki",
    instructions=(
        "A local, LLM-maintained Markdown wiki (Obsidian vault). Pages are entity, concept, "
        "source and synthesis pages; claims cite their source pages as [[sources/...]]. "
        "Use search or query to find knowledge, read_page to read a page, lint to check "
        "the vault. integrate adds a source packet from the inbox and runs as a job: poll "
        "job_status. query with file=true saves the answer as a synthesis page."
    ),
)

_jobs = None


def _job_queue():
    global _jobs
    if _jobs is None:
        from .jobs import JobQueue

        _jobs = JobQueue(on_log=log.info)
    return _jobs


def _llm(log_fn=None):
    """The LLM for tools; replaced in tests."""
    from .llm import LLM

    return LLM(log=log_fn or log.info)


def vault() -> Vault:
    root = config.VAULT_DIR
    if not Path(root).is_dir():
        raise ValueError(f"vault folder {root} does not exist; set WIKI_VAULT_DIR")
    return Vault(root)


def tool(fn):
    """Register a tool; anticipated errors reach the agent as messages, not as a
    generic 'Error executing tool'."""

    @functools.wraps(fn)
    def guarded(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, VaultError, FileNotFoundError) as exc:
            raise ToolError(str(exc)) from exc

    return mcp.tool()(guarded)


# ---------------------------------------------------------------------------
# read-only tools
# ---------------------------------------------------------------------------
@tool
def status() -> dict:
    """Vault overview: page counts by type, last log entries, git state, inbox packets
    (and whether each is integrated yet), running jobs."""
    from .status import overview

    jobs = _job_queue().list() if _jobs is not None else []
    return {**overview(vault()), "jobs": jobs}


@tool
def search(query: str, limit: int = 10, type: str | None = None) -> list[dict]:
    """BM25 search over page titles, aliases, leads and bodies. `type` limits to
    source, entity, concept or synthesis pages."""
    from .search import search as bm25

    types = [type] if type else None
    return [h.to_dict() for h in bm25(vault(), query, limit=max(1, min(limit, 50)), types=types)]


@tool
def read_page(page: str) -> dict:
    """A page's front matter and Markdown body. `page` is a path (`concepts/x`,
    `.md` optional) or a title/file name as in a [[wikilink]]."""
    v = vault()
    index = links.LinkIndex(v.files())
    candidates = index.candidates(page)
    if len(candidates) > 1:
        raise ValueError(f"{page!r} is ambiguous: {', '.join(candidates)}")
    path = candidates[0] if candidates else None
    if path is None:  # try title / alias
        hits = sorted(links.alias_map(_metas(v)).get(links.normalise_name(page), set()))
        if len(hits) > 1:
            raise ValueError(f"{page!r} names several pages: {', '.join(hits)}")
        path = hits[0] if hits else None
    if path is None or not path.endswith(".md"):
        raise ValueError(f"no page {page!r}")
    p = v.read_page(path)
    return {"path": path, "meta": json.loads(json.dumps(p.meta, default=str)), "body": p.body}


def _metas(v: Vault) -> dict[str, dict]:
    return {rel: p.meta for rel, p in v.iter_pages() if isinstance(p, Page)}


@tool
def lint() -> dict:
    """Check the vault: broken links, front matter, duplicate names (errors); orphans,
    uncited claims, ambiguous links, missing headings (warnings)."""
    from .lint import lint as run_lint

    return run_lint(vault()).to_dict()


@tool
def query(question: str, file: bool = False) -> dict:
    """Answer a question from the wiki with citations. With file=true the answer is
    saved as a synthesis page (reindex, log, one git commit)."""
    from .query import ask, file_answer

    v = vault()
    result = ask(v, question, llm=_llm())
    if file:
        file_answer(v, result)
    return result.to_dict()


# ---------------------------------------------------------------------------
# integration (background job)
# ---------------------------------------------------------------------------
@tool
def integrate(packet: str, dry_run: bool = False, local_id_owner: str = "") -> dict:
    """Integrate a source packet (a folder name in the inbox) into the vault, as a
    background job: one git commit per source; dry_run=true only computes the diff.
    local_id_owner: the project that owns the packet's document-local ids (WP2 becomes
    "<owner> WP2"), if its source.meta.json has no `local_id_owner` field; a different
    one than the packet's field is an error. Returns a job_id; poll job_status."""
    from .packet import load

    v = vault()
    inbox = config.inbox_dir(v.root).resolve()
    folder = (inbox / packet).resolve()
    if not folder.is_relative_to(inbox) or folder == inbox:
        raise ValueError("packet must be a folder name inside the inbox")
    pkt = load(folder)  # check the packet now, so a bad one fails here and not in the job
    declared = pkt.project
    owner = local_id_owner.strip()
    if owner and declared and declared.name.casefold() != owner.casefold():
        raise ValueError(f"the packet declares local_id_owner {declared.name!r}; {owner!r} differs")

    def run(job_log) -> dict:
        from .integrate import integrate as run_integrate

        report = run_integrate(v, folder, llm=_llm(job_log), inbox=inbox, dry_run=dry_run,
                               log=job_log, project=local_id_owner or None)  # fmt: skip
        data = report.to_dict()
        data.pop("stage_output", None)
        if not dry_run:
            data.pop("diff", None)
        return data

    job = _job_queue().submit("integrate", packet, run)
    return {"job_id": job.id, "packet": packet, "status": job.status}


@tool
def job_status(job_id: str) -> dict:
    """Status of a job (queued, running, done, failed): progress, recent log lines,
    and the run report or the error."""
    snap = _job_queue().snapshot(job_id)
    if snap is None:
        raise ValueError(f"no job {job_id!r} (jobs are kept in memory until the server restarts)")
    return snap


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="[mneme-wiki-mcp] %(levelname)s %(message)s"
    )
    mcp.run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
