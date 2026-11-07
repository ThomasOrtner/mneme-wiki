# mneme-wiki

A **local, LLM-maintained wiki** in the style of Karpathy's "LLM wiki": a persistent,
interlinked vault of Markdown notes that a local model compiles and keeps up to date,
and that you read in [Obsidian](https://obsidian.md).

Unlike RAG, which re-derives answers from raw chunks on every question, mneme-wiki
**integrates each source once**, when it arrives. The source updates the entity and
concept pages it touches, links go in both directions, and every claim cites its source.
Knowledge builds up over time.

- **Fully local:** all inference via [Ollama](https://ollama.com), default `qwen3:14b`.
- **Plain files:** Markdown + YAML front matter. The vault still works with the tool uninstalled.
- **Safe edits:** the model proposes, code validates and writes. Edits that drop
  claims or links are rejected. Each source becomes one git commit in the vault.
- **Agent-first:** every operation is available from the CLI (`--json`) and over MCP.

```
source packet ──► chunk ─► extract ─► resolve ─► plan ─► patch ─► validate ─► autolink ─► commit
 (from mneme       code     LLM        LLM+code   code    LLM      code         code        git
  or by hand)
```

## Quick start

```powershell
# 1. Install (Python ≥ 3.10, git, Ollama running locally)
ollama pull qwen3:14b
git clone https://github.com/ThomasOrtner/mneme-wiki.git
cd mneme-wiki
python -m venv .venv; .venv\Scripts\activate
pip install -e ".[dev]"

# 2. Create a vault
mneme-wiki init D:\wikis\space-ops
$env:WIKI_VAULT_DIR = "D:\wikis\space-ops"

# 3. Drop a source packet into D:\wikis\inbox\<name>\ and integrate it
mneme-wiki integrate my-first-source --dry-run   # see the diff, write nothing
mneme-wiki integrate my-first-source             # one git commit in the vault

# 4. Use it
mneme-wiki lint
mneme-wiki search "rover operations"
mneme-wiki query "Where is the ROCC located?" --file
```

Then open the vault folder in Obsidian.

## Documentation

The user documentation is a small wiki in [`docs/wiki/`](docs/wiki/Home.md):

| Page | What it covers |
|---|---|
| [Home](docs/wiki/Home.md) | Overview and map of the docs |
| [Getting Started](docs/wiki/Getting-Started.md) | Install, first vault, first source, first question |
| [Concepts](docs/wiki/Concepts.md) | Why a compiled wiki, page types, the three layers |
| [Vault Format](docs/wiki/Vault-Format.md) | Folders, front matter, page body, citations |
| [Source Packets](docs/wiki/Source-Packets.md) | The input contract and how to make packets |
| [Integration Pipeline](docs/wiki/Integration-Pipeline.md) | What happens to a source, stage by stage |
| [Lint, Search and Query](docs/wiki/Lint-Search-Query.md) | Keeping the vault healthy and asking it questions |
| [CLI Reference](docs/wiki/CLI-Reference.md) | Every command and flag |
| [MCP Server](docs/wiki/MCP-Server.md) | Using the wiki from Claude Code or other agents |
| [Configuration](docs/wiki/Configuration.md) | Environment variables and models per role |
| [Benchmark](docs/wiki/Benchmark.md) | How model choices are measured |
| [Development](docs/wiki/Development.md) | Code map, tests, design rules, milestones |
| [Troubleshooting](docs/wiki/Troubleshooting.md) | Common errors and what to do |

Design records: [`AGENTS.md`](AGENTS.md) (requirements, constraints, technical decisions),
[`docs/plan.md`](docs/plan.md) (MVP plan) and the milestone tutorials in
[`docs/milestones/`](docs/milestones/).

## Status

MVP complete (milestones M0–M7): integrate, lint, index/log, search, query with
file-back, benchmark, MCP server, and the exporter in the upstream
mneme project. Deferred: remote backends
(OpenRouter, opt-in), embedding search, LLM lint (contradictions, stale claims),
page merge/rename, inbox watching.
