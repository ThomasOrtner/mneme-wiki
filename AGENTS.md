# mneme-wiki — AGENTS.md

Stable rules for any coding agent (Claude Code, Codex, Cursor, …) in this repo.
`CLAUDE.md` only points here. **Build order, detailed designs and progress are
in [docs/plan.md](docs/plan.md).** If code and docs disagree, fix one of them in
the same change.

## 1. What this is

A **Karpathy-style LLM wiki**: a persistent, interlinked vault of Markdown notes
that an LLM compiles and maintains and a human reads (in Obsidian). Knowledge is
integrated once, when it is written, and builds up over time, instead of being
re-derived from raw chunks on every query, as in RAG.

mneme-wiki is the **sink**. Conversion, transcription and summarisation happen
upstream (mainly [`../mneme`](../mneme)), which delivers *source packets*.
mneme-wiki weaves them into the vault and keeps it healthy.

| Layer | Owner | Mutability |
|---|---|---|
| Raw sources (`vault/sources/`, upstream store) | upstream / human | immutable once filed |
| Wiki pages (rest of `vault/`) | LLM maintainer | LLM writes, human may edit |
| Schema (`vault/WIKI.md`) | human + LLM | changed deliberately, logged |

There are two agent audiences: this file is for agents that write **code**.
`mneme_wiki/templates/WIKI.md` (copied into each vault) is for the agent that maintains
**wiki content**.

## 2. Business requirements

- **BR-1** Plain `.md` files with YAML front matter are the source of truth;
  the vault works with the tool uninstalled.
- **BR-2** Obsidian-compatible: `[[wikilinks]]` (`|alias`, `#heading`), folders,
  tags, `aliases`.
- **BR-3** Typed pages: `source`, `entity`, `concept`, `synthesis`, plus `index`
  and `log`.
- **BR-4** Integrate, don't append: a source updates and creates the
  entity/concept pages it touches, with links in both directions.
- **BR-5** Claims cite their source pages; an uncited claim is a lint finding.
- **BR-6** `index.md` is the entry point: every page, by type, one line each.
- **BR-7** `log.md` is append-only, with greppable entries
  (`## [YYYY-MM-DD] <op> | <title>`).
- **BR-8** Contradictions are marked and logged, never resolved silently.
- **BR-9** Query answers can be filed back as `synthesis` pages.
- **BR-10** Lint: broken links, orphans, invalid front matter, uncited claims,
  duplicate entities, and later stale pages, contradictions and missing
  concepts.
- **BR-11** Every change can be reviewed as a git diff; delete/merge/rename are
  gated.
- **BR-12** Agent-first: every operation is available from the CLI (`--json`)
  and over MCP.

**Non-goals:** converting source formats (upstream does this), a custom UI
(Obsidian is the UI), multi-user sync, being a general RAG service.

## 3. Constraints

- **L-1 Fully local:** all inference via Ollama on localhost. A remote
  backend (OpenRouter) is deferred. When it is added, it must be opt-in per
  run or vault, never the default.
- **L-2 Small context:** default `qwen3:14b`. Budget about 8–12k input tokens
  per call; no call ever needs the whole vault.
- **L-3 Weak editors:** local models produce broken JSON/YAML, invent links
  and drop content. The model proposes, code validates and writes.
- **L-4 No silent data loss:** rewrites that drop claims or links are rejected.
- **L-5 MVP scale:** about 100 sources and 500 pages.
- **L-6 Windows first-class:** `pathlib`, explicit UTF-8, filenames safe on
  NTFS, case collisions handled.

## 4. Technical decisions

| # | Decision | Why |
|---|---|---|
| TD-1 | Python ≥ 3.10, `pyproject.toml`, `pip install -e .`, scripts `mneme-wiki`, `mneme-wiki-mcp` | Same as mneme |
| TD-2 | Thin `llm.py` over a small backend protocol (Ollama is the only backend for now); one `config.py` + `python-dotenv` | Same as mneme; a remote backend can be added later without touching stage code |
| TD-3 | No LLM frameworks (LangChain, LlamaIndex, Haystack) | Same as mneme |
| TD-4 | Files are the truth; caches/indexes are derived, rebuildable and git-ignored | BR-1 |
| TD-5 | **Propose → validate → apply:** LLM output is structured JSON edits; code validates (front matter, link targets, citations, no content loss) and applies them, or rejects to `inbox/rejected/` | L-3, L-4 |
| TD-6 | The vault is a git repo; one commit per operation | BR-11 |
| TD-7 | Search = `index.md` + BM25 (`rank_bm25`); embeddings only beyond L-5 | Keep the MVP small |
| TD-8 | Upstream contract = **source packet** in `inbox/` (see plan); never import mneme code | Loose coupling, any producer works |
| TD-9 | PyYAML + our own front-matter schema; our own wikilink regex, no Markdown AST library | Few deps, full control over Obsidian syntax |
| TD-10 | MCP over stdio (`mcp`): stdout is the protocol, logs go to stderr, long operations run as jobs | Proven in mneme |
| TD-11 | `rich` for humans, `--json` for machines | BR-12 |
| TD-12 | `mneme_wiki/` package layout | No module clashes with mneme |
| TD-13 | **Staged integration:** code orchestrates, the LLM makes small decisions (extract per chunk, resolve ambiguous matches, patch one page per call). No call plans across pages | Fits a 14B model; each stage can be tested and benchmarked |
| TD-14 | Models are chosen **per stage role** (`extract`, `resolve`, `patch`, `summary`, `query`) as `backend:model`, e.g. `ollama:qwen3:14b`. OpenRouter (via `httpx`) is deferred | Compare and mix models stage by stage |
| TD-15 | Benchmark harness (`mneme-wiki bench`) on a fixed corpus decides model choices; local models only for now | Measure, don't assume |
| TD-16 | Many vaults, each self-contained with its own `WIKI.md`. The dev vault lives in `examples/vault/`; user vaults live anywhere, set via `WIKI_VAULT_DIR` | Separate domains stay separate |
| TD-17 | `source` pages keep the source's language; all other pages are written in `WIKI_LANGUAGE` (default `en`) | Mixed-language sources (e.g. German talks) |
| TD-18 | **Resolve = pairwise yes/no with thinking:** exact name/alias match first (against existing pages *and* earlier subjects of the same source), then ≤ 4 candidates (name shape, then BM25), one yes/no call per candidate, every decision logged with its reason | M0: picking one of many candidates either never merged or merged anything related; pairwise + thinking had no false merges |
| TD-19 | **Linking is code (autolink),** the model only adds links it is sure of | M0: code gave ~2 links/page, the model without thinking 0.16 |
| TD-20 | **Front matter round trip:** the original front-matter block is kept verbatim and only re-serialised (PyYAML; existing key order kept, new keys in schema order, newline style and BOM kept) when `meta` actually changed. Comments in a *changed* block are lost | Unchanged files stay byte-identical, so diffs show only real edits; no own YAML emitter or `ruamel.yaml` needed |
| TD-21 | The inbox defaults to `<vault>/../inbox`; `WIKI_INBOX_DIR` overrides it | Many vaults (TD-16): each gets its own inbox, independent of the working directory |
| TD-22 | Search scores title+aliases, lead and body as **separate BM25 fields** (weights 3/2/1) with the always-positive Lucene IDF, built in memory per call | M2: rank_bm25's Okapi IDF floors terms found in > half the pages, and repeated title tokens saturate, so a short page that merely mentions a term outranked the page titled with it |
| TD-23 | **Integration writes into an in-memory `Workspace`** (a `Vault` overlay) and flushes only after every stage ran and lint shows no *new* errors; `--dry-run` prints the overlay's diff | All-or-nothing per source: a half-integrated vault never reaches disk or git; dry runs exercise exactly the code that writes |
| TD-24 | `integrate` refuses a vault with uncommitted changes and a source whose `origin` is already integrated | One commit = one source (BR-11); re-integrating would duplicate claims. Updating a changed source is a separate, later operation |
| TD-25 | Pages are edited **section by section**: untouched sections stay byte-identical; a final check rejects any edit that loses a link target of the old body | L-4 without trusting the model's `replace`; keeps human text and diffs small |
| TD-26 | Thinking is set per role (`THINK_<ROLE>`), default on for `resolve` only | M0: resolve needs it; patch thinking is 5× slower and is decided by the M4 bench |
| TD-27 | Every model call is bounded: `MAX_OUTPUT_TOKENS` (8192), `CALL_TIMEOUT_S` (600); a cut-off answer counts as failed and is retried once | M4: an uncapped patch call looped for 9 hours and 327k tokens |
| TD-28 | A query answer that cites no source, or spells out an abbreviation the pages don't, gets one retry naming the problem; an answer still uncited or still unbacked is shown with a warning and never filed | M5: 28% of answers cited nothing although the prompt asks for it; after the fix 30/30 cite at least one source. A filed uncited page would be read as fact by later queries (BR-5) |
| TD-29 | **Expansion check (code):** an abbreviation spelled out as `ABC (Long Name)`, `Long Name (ABC)` or `ABC stands for Long Name` must appear word for word in the evidence (source text, page names, the page's earlier text). Unbacked bracket forms are removed after patch, before autolink; text already in the vault is never touched | M5: every model invented expansions (DAR = "Data Archive and Retrieval" / "Data Archive Repository"), and citation checks can't see them because the sentence does cite its source. Explicit forms only: a bare phrase with no abbreviation beside it isn't detected, and page titles aren't checked |
| TD-30 | `qwen3:14b` for every role; thinking on for `resolve` only, off for `patch` | M4 bench: best gold coverage with no wrong merges; `qwen3:8b` loses ~5 of 33 gold pages, `gemma3:12b` makes wrong merges, patch thinking costs 2.5× the run time for fewer copied headings only. Mixed configurations were not measured |

Record new decisions as new `TD-n` rows; don't silently rewrite old ones.

## 5. Vault format

```
vault/
  WIKI.md  index.md  log.md
  sources/  entities/  concepts/  syntheses/  attachments/
inbox/            source packets (outside the vault)
  rejected/
```

Filenames are kebab-case slugs of the title. Links use the slug:
`[[retrieval-augmented-generation|RAG]]`.

```yaml
---
title: Retrieval-Augmented Generation
type: concept            # source | entity | concept | synthesis | index | log
aliases: [RAG]
tags: [llm, retrieval]
created: 2026-11-02
updated: 2026-11-02
sources: ["[[sources/karpathy-llm-wiki]]"]
status: active           # active | stub | stale | contested
---
```

Type-specific fields: `source` → `source_type`, `origin` (`mneme:<doc_id>` / URL),
`author`, `published`, `ingested`. `entity` → `entity_kind`. `synthesis` →
`question`. Any page → optional `contradicts`.

Body: H1 = title; a lead paragraph that makes sense on its own; inline
citations `([[sources/x]])`; contradictions as `> [!warning] Contradiction`
callouts; links mostly in the prose.

## 6. Coding standards

**General**
- Type hints on public functions, `from __future__ import annotations`.
- `ruff` (lint + format, line length 100), `pytest`.
- Small single-purpose modules; plain functions + dataclasses. Add an interface
  only when a second implementation exists.
- Config only via `config.py`; I/O always uses `encoding="utf-8"` and `pathlib.Path`.
- No `print` outside `cli.py`; library code reports through a `log` callable
  (mneme pattern).

**LLM code**
- Prompts live in one place per feature (module constants or `prompts/*.md`).
- Calls that lead to writes return schema-validated JSON (TD-5).
- Stage code gets its model through `llm.for_role(...)`, never a hard-coded name.
- LLM output is untrusted: paths must stay inside the vault; validate links,
  front matter and sizes.

**Vault safety**
- All writes go through `vault.py` (atomic: write a temp file, then replace),
  only inside the vault or inbox.
- No delete/rename without an explicit flag or gated tool.
- Keep unknown front-matter keys and human-written text.

**Tests**
- `tests/test_<module>.py`, fixture vaults in `tests/fixtures/`.
- Deterministic code is tested without a model. LLM paths use a fake `llm` with
  recorded responses; real runs are opt-in (`pytest -m ollama`).
- Every bug fix comes with a test that failed before the fix.

**Git & docs**
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- Update this file (rules), `docs/` (plans, designs, progress) or the user docs in
  `docs/wiki/` (anything a user sees: commands, flags, config, formats) in the same
  commit as the change.

**Working agreement**
- All documents for planning and executing this project live in `docs/`.
  The MVP plan is `docs/plan.md`.
- Follow the milestone order in `docs/plan.md`; don't build deferred features
  unprompted.
- **Milestone tutorial:** every milestone gets `docs/milestones/M<n>-<name>.md`,
  written for the user as a tutorial, not a changelog. It covers: what was built
  and how the pieces fit together (walk through the code paths with
  `file:line` references), how to run and try it yourself, every decision made
  and *why* (including alternatives rejected), what was learned or measured,
  and the known gaps. A reader should be able to understand the milestone
  without reading the diff first. Render it (and `docs/plan.md`) to PDF next to the
  `.md` (git-ignored):
  `pandoc X.md -o X.pdf --pdf-engine=xelatex -V geometry:margin=2cm -V mainfont="Segoe UI" -V monofont="Consolas"`.
- **One milestone at a time:** when a milestone's exit condition is met, tick
  its boxes in `docs/plan.md`, write the milestone tutorial, make one commit (`feat: M<n> <name>` or
  `docs: …`), report the result, and **wait for the user's confirmation**
  before starting the next milestone.
- When something is ambiguous or conflicts with reality, stop, ask, and propose
  the doc edit.
