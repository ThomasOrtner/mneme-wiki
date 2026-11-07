# M6: MCP server

**Question:** can an agent such as Claude Code use the wiki the way a human
uses the CLI (look things up, check it, ask it, feed it new sources) without
being able to damage it?

**Short answer:** yes. `mneme-wiki-mcp` is a stdio MCP server with seven
tools: `status`, `search`, `read_page`, `lint`, `query`, `integrate` and
`job_status`. Integration runs as a background job, because it takes minutes.
There are deliberately no delete or rename tools: the agent can only add to
the vault, and only through the same validated path as the CLI (one commit
per operation). A real stdio round trip is covered by a test, so stdout really
does carry nothing but the protocol.

---

## 1. What was built

```
mneme_wiki/
  mcp_server.py   the MCP tools (mcp 2.x MCPServer, stdio)
  jobs.py         in-memory, single-worker job queue for integrate
pyproject.toml    + script mneme-wiki-mcp
tests/
  test_mcp_server.py   tools against a real vault (fake model), a failing job, stdio round trip
```

### 1.1 The tools (`mcp_server.py`)

| Tool | What it does | Writes? |
|---|---|---|
| `status()` (`:84`) | page counts by type, last 5 log entries, git HEAD, uncommitted changes, inbox packets and whether each is integrated yet, jobs (shared with `mneme-wiki status`, `status.py:31`) | no |
| `search(query, limit, type)` (`:94`) | BM25 search (M2, TD-22) | no |
| `read_page(page)` (`:104`) | front matter + body. `page` is a path, a `[[wikilink]]` target or a title/alias; ambiguity is an error, not a guess | no |
| `lint()` (`:129`) | the M2 report | no |
| `query(question, file)` (`:138`) | M5: answer with citations; `file=true` files it as a synthesis page (one commit) | only with `file` |
| `integrate(packet, dry_run)` (`:154`) | M3, as a job: a packet *name inside the inbox* | yes, one commit |
| `job_status(job_id)` (`:183`) | queued / running / done / failed, last log lines, the run report or the error | no |

The vault is `WIKI_VAULT_DIR` (one vault per server, TD-16) and the inbox is its
inbox (TD-21).

**Errors reach the agent as messages.** The SDK hides every exception except
`ToolError` behind "Error executing tool". The `tool` decorator (`:66`, the
mneme pattern) turns the errors we expect (`ValueError`, `VaultError`, …) into
`ToolError`, so the agent reads "already integrated as sources/…" or "no page
'x'" and can act on it.

**`integrate` checks before it queues.** The packet name must resolve to a
folder *inside* the inbox (`../vault` is refused), and `packet.load()` runs
immediately. A broken packet fails in the call, not minutes later in a job.

### 1.2 Jobs (`jobs.py`)

`JobQueue` (`jobs.py:56`) has one worker thread, so jobs run in submission
order. That is a requirement, not a simplification: every integration needs a
clean vault and makes one commit, and the GPU runs one model at a time anyway.
A job's log lines are the same progress lines the CLI prints
(`patch 12/40 ~ concepts/…`). The last 60 are kept, `job_status` shows the
last 20, and every line also goes to stderr. A failing job is reported
(`status: failed`, `error`) and the worker keeps going
(`test_tool_errors_are_messages` integrates the same packet twice and then a
third one).

Jobs live in memory. A restarted server forgets them, but not their effects:
those are commits in the vault.

### 1.3 stdout is the protocol

Nothing in `mcp_server.py` or `jobs.py` prints. Progress goes through `log`
callables into the job and to `logging` on stderr. M3's integrate already took
a `log` callable for exactly this reason. `test_stdio_round_trip` starts the
server as a subprocess (`python -m mneme_wiki.mcp_server`), connects with the
real MCP client, and calls `status`; a single stray `print` would break the
JSON-RPC stream.

---

## 2. How to run it yourself

```powershell
# register with Claude Code (the vault comes from WIKI_VAULT_DIR)
claude mcp add mneme-wiki --env WIKI_VAULT_DIR=C:\_REPOS\mneme-wiki\examples\vault -- mneme-wiki-mcp
```

Then, in Claude Code: "What does the wiki say about the DAR?" (→ `search` /
`query`), "lint the wiki", "integrate the packet rfm-gis-ad3 from the inbox"
(→ `integrate`, then `job_status` until it is done). Put packets into the inbox
with mneme's `mneme-export-wiki-packet` (M7).

Tests: `pytest tests/test_mcp_server.py` (no model needed: the tools run with
the fake model of M3).

---

## 3. What happened

**mcp 2.x.** The installed SDK is 2.3, where `FastMCP` is now `MCPServer`
(`mcp.server.mcpserver`). mneme already uses that API, so the server follows
mneme's structure (lazy job queue, `ToolError` wrapping, `main()` with
logging on stderr).

**A cleared PATH made `status` fail inside the round-trip test.** The first
version of the stdio test started the server with a minimal environment
(`PATH=""`), and `status` failed with WinError 2: `git` wasn't found. The
protocol itself worked (the failure came back as a proper tool error, which
is reassuring). The test now passes the real environment.

**A bug in `read_page`'s alias lookup** (a comprehension reused its own loop
variable) was caught while writing the code, before the tests ran. It's now a
plain `alias_map().get()`, and ambiguous names are reported, not guessed.

---

## 4. Decisions made in M6, and why

| Decision | Why | Rejected alternative |
|---|---|---|
| **No delete, rename or edit tools** | BR-11: destructive operations stay gated; an agent's only write paths are integrate and filing a query, both validated and committed | A gated delete as in mneme (elicitation + token): not needed for the MVP; pages are removed by a human in git |
| **`integrate` takes an inbox folder name, not a path** | The agent can't point the pipeline at arbitrary files; the inbox is where packets are meant to be | Any path (the CLI allows it, because a human types it) |
| **Packet checked before the job is queued** | Fast, clear failure for the common mistakes | Failing inside the job |
| **One worker, jobs in memory** | Integrations must be serial (clean vault, one commit each); results survive in git | A persistent job store: more state to keep consistent, nothing gained |
| **`query` is synchronous** | One retrieval + one model call (seconds to a minute); a job would add a round trip for the agent | A job like integrate |
| **`read_page` accepts titles and aliases, refuses ambiguity** | Agents see names in text, not paths; a wrong page is worse than an error | Paths only |
| **One vault per server (`WIKI_VAULT_DIR`)** | Matches TD-16; a second vault is a second registration | A `vault` argument on every tool (every call could hit the wrong vault) |

---

## 5. Known gaps

- **No job cancellation.** A running integration can only be stopped by stopping
  the server (the workspace means nothing half-written reaches the vault, TD-23).
- **No progress notifications**: the agent polls `job_status`. MCP progress
  notifications would save the polling, but not every client shows them.
- **`status` scans the whole vault** on every call. Fine at MVP scale (L-5).
- **Not yet driven by a real agent session in this milestone**: the tools are
  tested directly and over stdio with the MCP client, not through Claude Code.
