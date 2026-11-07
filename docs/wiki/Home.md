# mneme-wiki documentation

mneme-wiki turns documents into a **persistent, interlinked Markdown wiki** that a
local LLM maintains and you read in Obsidian. Each source is integrated once: it
updates the pages about the things it mentions, creates the missing ones, links
them both ways and cites itself on every claim.

## Start here

1. [Getting Started](Getting-Started.md): install, create a vault, integrate a source, ask a question.
2. [Concepts](Concepts.md): what a "compiled" wiki is and why it beats re-reading chunks.

## Using it

- [Vault Format](Vault-Format.md): what the files look like
- [Source Packets](Source-Packets.md): how documents get in
- [Integration Pipeline](Integration-Pipeline.md): what happens to a source
- [Lint, Search and Query](Lint-Search-Query.md): healthy vault, good answers
- [CLI Reference](CLI-Reference.md): all commands
- [MCP Server](MCP-Server.md): use it from Claude Code or any MCP client
- [Configuration](Configuration.md): environment variables, models, thinking

## Behind the scenes

- [Benchmark](Benchmark.md): how model choices are measured
- [Development](Development.md): code map, tests, design rules
- [Troubleshooting](Troubleshooting.md): common errors

## The big picture

```
 upstream (mneme, or by hand)          mneme-wiki                         you
┌────────────────────────┐   ┌───────────────────────────────┐   ┌──────────────────┐
│ PDF, talk, web page →  │   │ integrate: extract, resolve,  │   │ Obsidian (read,  │
│ Markdown + metadata    │──►│ patch, validate, autolink,    │──►│ edit)            │
│ = source packet in     │   │ commit   ·  lint · query      │   │ CLI / MCP agent  │
│ inbox/                 │   │                               │   │ (ask, maintain)  │
└────────────────────────┘   └───────────────────────────────┘   └──────────────────┘
```

mneme-wiki is the **sink**: converting formats, transcribing and summarising happen
upstream. It only weaves finished Markdown into the vault and keeps the vault healthy.
