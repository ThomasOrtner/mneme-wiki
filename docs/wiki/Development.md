# Development

← [Home](Home.md) · Rules for coding agents and contributors: [AGENTS.md](../../AGENTS.md)

## Setup

```powershell
pip install -e ".[dev]"
pytest                 # deterministic tests, a fake LLM, no Ollama needed
pytest -m ollama       # opt-in: real runs against a local Ollama
ruff check . ; ruff format --check .
```

## Code map

| Module | Role |
|---|---|
| `config.py` | Environment variables and defaults (the only reader of `os.environ`) |
| `llm.py`, `backends.py` | `for_role(role)` → model; backend protocol; Ollama backend |
| `frontmatter.py` | Parse, validate and round-trip YAML front matter |
| `links.py` | Wikilink parsing and resolution, alias and backlink maps |
| `vault.py` | Page I/O (atomic writes), slugs, path confinement, git |
| `workspace.py` | In-memory overlay of the vault: collect writes, diff, flush |
| `text.py` | Markdown blocks with line numbers, lead sentence, search tokens |
| `packet.py` | Load and check source packets, chunk them |
| `stages/` | `source`, `extract`, `resolve`, `plan`, `patch`, `autolink`, `common` |
| `prompts/*.md` | One system prompt per stage |
| `edits.py` | Edit model, validation, apply |
| `expansions.py` | Remove abbreviation expansions the evidence doesn't back |
| `integrate.py` | Orchestrates the stages for one packet |
| `index_log.py` | `index.md` generation, `log.md` appends |
| `lint.py`, `search.py`, `query.py`, `status.py` | The read-side operations |
| `bench.py` | Benchmark harness |
| `cli.py` | Thin CLI; the only module that prints |
| `mcp_server.py`, `jobs.py` | MCP tools; single-worker job queue |

An architecture diagram is in `docs/architecture.drawio`.

## Design rules (short version)

- **Files are the truth.** Caches and indexes are derived and git-ignored.
- **Propose → validate → apply.** LLM output is untrusted JSON; code checks paths,
  links, citations and content loss before writing.
- **Staged, small calls.** No model call plans across pages; ~8–12k input tokens max.
- **All writes go through `vault.py`**: atomic, confined to the vault or inbox, UTF-8,
  `pathlib`.
- **No frameworks** (LangChain & co.), no Markdown AST library: our own wikilink regex.
- **Library code doesn't print**; it reports through a `log` callable.

The full list, with the reasoning behind each choice, is the TD table in
[AGENTS.md](../../AGENTS.md#4-technical-decisions).

## Tests

- `tests/test_<module>.py`; fixture vaults in `tests/fixtures/`, each lint fixture with an
  `expected.json` of its exact findings.
- LLM paths use a scripted fake model (`tests/fakes.py`).
- Every bug fix comes with a test that failed before the fix.

## Docs

- `AGENTS.md`: stable rules (requirements, constraints, decisions, standards).
- `docs/plan.md`: MVP plan, designs, progress.
- `docs/milestones/M<n>-*.md`: one tutorial per milestone, with `file:line` walkthroughs.
- `docs/wiki/`: this user documentation. Update it in the same commit as a user-visible change.

## History

| Milestone | Delivered |
|---|---|
| [M0](../milestones/M0-feasibility.md) | Feasibility spike on `qwen3:14b`; resolve redesigned as pairwise yes/no |
| [M1](../milestones/M1-scaffold.md) | Package, front matter round trip, links, vault I/O, `init` |
| [M2](../milestones/M2-lint-index-log.md) | Lint, index, log, BM25 search |
| [M3](../milestones/M3-integrate.md) | The integration pipeline |
| [M4](../milestones/M4-bench.md) | Benchmark harness and model choice |
| [M5](../milestones/M5-query.md) | Query with citations and file-back |
| [M6](../milestones/M6-mcp-server.md) | MCP server |
| [M7](../milestones/M7-mneme-exporter.md) | Packet exporter in mneme |
