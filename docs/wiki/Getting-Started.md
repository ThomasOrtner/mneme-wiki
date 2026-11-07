# Getting Started

← [Home](Home.md)

## Requirements

- Python ≥ 3.10
- git (each vault is a git repository)
- [Ollama](https://ollama.com) running on `localhost:11434`, with the default model:

  ```powershell
  ollama pull qwen3:14b
  ```

  `qwen3:14b` needs about 10 GB of VRAM (or a lot of patience on CPU).
- Optional: [Obsidian](https://obsidian.md) to read the vault.

Windows is a first-class platform; the examples use PowerShell. On macOS or Linux,
use `source .venv/bin/activate` and `export VAR=value`.

## Install

```powershell
git clone https://github.com/ThomasOrtner/mneme-wiki.git
cd mneme-wiki
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
mneme-wiki --version
```

This installs two commands: `mneme-wiki` (the CLI) and `mneme-wiki-mcp` (the MCP server).

## 1. Create a vault

```powershell
mneme-wiki init D:\wikis\space-ops
```

This creates the folder structure, `WIKI.md` (the vault's schema and the rules for
whoever writes content), `index.md`, `log.md`, and a git repository with a first commit.
The inbox for this vault is `D:\wikis\inbox` (next to the vault).

Make it the default vault, either per shell:

```powershell
$env:WIKI_VAULT_DIR = "D:\wikis\space-ops"
```

or in a `.env` file (copy `.env.example`). Every command also takes `--vault <path>`.
See [Configuration](Configuration.md).

## 2. Add a source

A source arrives as a **source packet**: a folder in the inbox with the content as
Markdown and a small metadata file. See [Source Packets](Source-Packets.md) for the
format. The smallest possible packet:

```
D:\wikis\inbox\karpathy-llm-wiki\
  source.md
  source.meta.json
```

```json
{
  "title": "LLM Wiki",
  "source_type": "article",
  "origin": "https://example.org/llm-wiki",
  "date": "2026-11-07"
}
```

If you use mneme, export a processed document instead:

```powershell
mneme-export-wiki-packet <doc_id> --inbox D:\wikis\inbox
```

## 3. Integrate it

Look first, write later:

```powershell
mneme-wiki integrate karpathy-llm-wiki --dry-run
```

This runs every stage and prints the diff that would be written, without touching the
vault. If it looks right:

```powershell
mneme-wiki integrate karpathy-llm-wiki
```

A source takes a few minutes on `qwen3:14b`; progress is printed per stage and per model
call. The result is **one git commit** in the vault, with a `log.md` entry and a run
report under `.mneme-wiki/runs/`. Review it like code:

```powershell
cd D:\wikis\space-ops
git show --stat
```

## 4. Check and use it

```powershell
mneme-wiki lint                       # errors and warnings, exit 1 on errors
mneme-wiki status                     # pages per type, git state, inbox packets
mneme-wiki search "rover operations"  # BM25 search
mneme-wiki query "Where is the ROCC located?"
mneme-wiki query "Where is the ROCC located?" --file   # save as a synthesis page
```

Open the vault folder in Obsidian ("Open folder as vault"). Start at `index.md`.

## Next

- [Concepts](Concepts.md) explains the ideas.
- [MCP Server](MCP-Server.md) lets Claude Code read, search, query and integrate.
- [Troubleshooting](Troubleshooting.md) if something refuses to run.
