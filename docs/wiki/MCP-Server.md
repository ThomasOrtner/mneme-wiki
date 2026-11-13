# MCP Server

← [Home](Home.md) · Details: [M6 tutorial](https://github.com/ThomasOrtner/mneme-wiki/blob/main/docs/milestones/M6-mcp-server.md)

`mneme-wiki-mcp` exposes the vault to any [MCP](https://modelcontextprotocol.io) client
over stdio. One server serves one vault: `WIKI_VAULT_DIR`.

## Register with Claude Code

Start the server through the venv's Python:

```powershell
claude mcp add mneme-wiki -e WIKI_VAULT_DIR=D:\wikis\space-ops -- C:\path\to\mneme-wiki\.venv\Scripts\python.exe -m mneme_wiki.mcp_server
```

On Linux/macOS the interpreter is `.venv/bin/python`.

**Why not `mneme-wiki-mcp`?** The `mneme-wiki-mcp` command works too, but on Windows a
running `.exe` is locked: while any client runs the server from `mneme-wiki-mcp.exe`,
`pip install -e .` (and so `init.sh`) can't replace that file, fails halfway and leaves
the venv without `mneme_wiki`. pip never rewrites `python.exe` on an editable install,
so `python -m` avoids the lock. Every open client session starts its own server.

To switch an existing registration:

```powershell
claude mcp remove mneme-wiki -s user
claude mcp add mneme-wiki -s user -e WIKI_VAULT_DIR=... -- C:\path\to\mneme-wiki\.venv\Scripts\python.exe -m mneme_wiki.mcp_server
```

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `status` | — | Page counts, glossary terms, last log entries, git state, inbox packets, running jobs |
| `search` | `query`, `limit` (≤ 50), `type` | BM25 hits with snippets |
| `read_page` | `page`: a path (`concepts/x`), file name or title/alias | Front matter and body |
| `lint` | — | The lint report |
| `query` | `question`, `file` | Answer, cited pages, warnings; with `file=true` saved as a synthesis page |
| `integrate` | `packet` (a folder name in the inbox), `dry_run`, `local_id_owner` (for a packet without the field) | A `job_id`, at once |
| `job_status` | `job_id` | `queued` / `running` / `done` / `failed`, progress, recent log lines, the run report or error |

`integrate` takes minutes, so it runs as a **background job**, one at a time; poll
`job_status`. Jobs live in memory until the server restarts.

There are **no delete, rename or merge tools**: those stay manual and reviewable.

## Notes

- stdout is the MCP protocol; all logs go to stderr.
- `integrate` only accepts folder names inside the inbox, not arbitrary paths.
- The same rules apply as on the CLI: uncommitted changes or an already-integrated
  `origin` make `integrate` fail.

## Example session

> **You:** What does our wiki know about the ROCC?
>
> **Agent:** calls `search("ROCC")`, then `read_page("entities/rover-operations-control-centre")`,
> and answers with the page's citations.
>
> **You:** Integrate the new workshop notes.
>
> **Agent:** calls `status()`, sees `rfm-gis-ws2: not integrated yet`, calls
> `integrate("rfm-gis-ws2")`, polls `job_status(...)` until `done`, and summarises the
> run report.
