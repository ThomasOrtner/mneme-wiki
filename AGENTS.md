# mneme-wiki — AGENTS.md

Stable rules for any coding agent (Claude Code, Codex, Cursor, …) in this repo.
`CLAUDE.md` only points here. **Work is tracked in GitHub issues** (§ 7), in the
order set by [docs/plan.md](docs/plan.md). The MVP plan and its detailed designs
are archived in [docs/archive/mvp-plan.md](docs/archive/mvp-plan.md). If code
and docs disagree, fix one of them in the same change.

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
| TD-31 | **Exact match trusts names, not model aliases** (refines TD-18): only the subject's *name* against page titles/aliases (and earlier subjects' names) is an exact match; a match through a subject's alias, or a new subject's alias, makes that page the first yes/no candidate. Merge within a source unions on the name only. An alias that is another page's title/alias is dropped | #15: extract lists related names (a mission's rover and camera) as aliases, and the alias exact match merged a mission into a camera page with no model check |
| TD-32 | **Local-id guard:** a subject name of 1–4 capitals and a number (`WP2`, `D3`, `MS1`, `T2.1`) never exact-matches an existing page; that page becomes a yes/no candidate. Within one source the exact match stays. Extract is told to qualify such ids with their owner ("Project Alpha WP2") | #13: two proposals' `WP2` shared one page. A fixed pattern list (`WP`, `D`, `MS`, `Task`) is language-dependent and ambiguous; acronyms without a number (`ROCC`) are not affected. Vault-specific patterns come with #14 |
| TD-33 | **Local ids are qualified only where there is evidence they are local:** a new page whose bare local-id title (`D1`) another page already has gets the source's title in front ("Project Beta Proposal D1"); on a title with an owner before the id ("Project Alpha WP2") the alias `WP2` becomes `<owner short>-<id>` (`PA-WP2`) or is dropped. Elsewhere `M20`-shaped titles and aliases stay. The `PA-WP2` handle is made up on purpose; checks that aliases appear in the source exempt it | #13 D3: a bare `WP2` alias linked every "WP2" of project Beta to project Alpha's page (6 wrong links in one `qwen3:14b` run), and two bare `D1` titles made lint reject a run. Applying both rules to every id-shaped name renamed a global mission acronym (letter + number) and cost a gold page in every bench run; the shape can't tell `M20` from `WP2`, the title can. The rest needs vault knowledge (#24, #27) |
| TD-34 | **A `replace` or new lead only rewrites what this source said:** lines citing another source, or none (human text), must come back with the same `_line_key` and at least the same citations, and are written back byte for byte; a lead citing another source may only be extended. A violation rejects the whole `replace` (or lead) with one retry: "use append" | #22: a `replace` kept source A's citation but changed its fact to source B's, a silent contradiction resolution with the wrong source cited (BR-5, BR-8). Code only, no model judge; `_line_key` drops citations, so citations are compared separately |
| TD-35 | **Names check (code, after resolve, before plan):** a new page title and every new alias must appear word for word (case, punctuation, hyphens ignored, plural "s" folded) in the source's title or text or among the names of pages that existed before the run, or be an *owner name* (a page name from before the run, a backed name of a subject of this source, or the start of the source's title) followed by a backed name ("Project Alpha WP2" where the source says "WP2", TD-32). An unbacked alias is dropped; an unbacked title becomes the subject's first backed alias; a subject with no backed name is skipped and reported. Names code builds later (`PA-WP2`, owner-qualified titles, TD-33) are not checked. The expansion check (TD-29) no longer counts a new page's own title and aliases as evidence. Closes TD-29's "page titles aren't checked" gap | #25: extract glued an invented expansion onto an acronym ("UPCUplink Processing Centre"), which became title and slug, and then backed its own expansion in the lead. Whole source as evidence (D2), so a glossary at the end still backs a name; looser matching would let glued and reordered names through (D3). The owner exception (D3 amended 2026-11-12): with D3 strict, 3 `qwen3:14b` fixture runs skipped 27 subjects, all owner-qualified names TD-32 asks for; any two backed parts would let reordered words through, so the first part must be a name. Full names no source spells out need the glossary (#24) |

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

**Documents**
- Design documents live in `docs/`: `docs/plan.md` (the order of open issues),
  `docs/archive/mvp-plan.md` (the MVP plan, M0–M7, done), `docs/milestones/` (one
  tutorial per milestone), `docs/wiki/` (user docs).
- **Tutorials for large features:** an issue that adds a stage, an operation or a
  measured model decision gets a tutorial `docs/milestones/<n>-<name>.md` (`<n>`
  = issue number) as part of its Definition of done, when the issue says so. It is
  written for the user, not as a changelog: what was built and how the pieces fit
  together (code paths with `file:line` references), how to run it, every decision
  and *why* (including alternatives rejected), what was measured, the known gaps.
  Render it to PDF next to the `.md` (git-ignored):
  `pandoc X.md -o X.pdf --pdf-engine=xelatex -V geometry:margin=2cm -V mainfont="Segoe UI" -V monofont="Consolas"`.
- The deferred features of the MVP plan are draft issues; don't build them
  unless their issue is `ready`.

## 7. Workflow

### Start of every session

1. Run `git status` and `git log --oneline -5` in the repository root. If you are
   on `main`, switch to the branch for your issue before changing anything.
   Nothing is ever committed on `main`.
2. If you are continuing an issue, read it with `gh issue view <n> --comments`:
   the body is the spec, the comments say where the work stands. Otherwise read
   [docs/plan.md](docs/plan.md) first, then the issues of its current phase.
3. Run `bash ./init.sh` (from Git Bash on Windows, not PowerShell). If it fails,
   fixing the baseline is your task; don't start feature work on a red baseline.
4. Pick the next issue **in plan order**: the first issue of the current phase that
   is `ready` and not labeled `blocked` or `decision-needed`. If none can be started,
   stop and ask; don't jump to a later phase. Work only on that one.

### Work is tracked in GitHub issues

Every feature, behavior change and bug is a GitHub issue, written with the
templates in `.github/ISSUE_TEMPLATE/`. The issues hold the specs and their state;
`docs/plan.md` holds only the order (phases) and why. A new issue gets its place in
the plan when it is created.

**Labels.** `p1`–`p4` set priority (`p1` highest) and **follow the plan**: current
phase `p1`, next `p2`, the one after `p3`, everything later `p4`. The agent may set
and update them, in the same change that edits the plan; if labels and plan
disagree, the plan wins. `ready` means the issue text
is stable and work may start; only the human sets it. `decision-needed` means a
question in the issue is open. `blocked` means it waits on something else (say
what in a comment, e.g. "blocked by #12"). `bug` marks a bug report.

**Writing an issue.** The human and the agent write it together. The body holds
the user-visible behavior, the verification steps as a checklist (expected
results on fixtures where possible; model-dependent steps name the model and the
number of runs), the decisions the human made, and anything still open marked
`DECISION NEEDED` (plus the `decision-needed` label). Create it with
`gh issue create`, and edit it with the human until they set `ready`. Never start
implementing an issue that isn't `ready`.

**Working on an issue.**
1. Branch from `main` as `issue/<n>-<short-slug>`, or from the branch of an open
   PR the issue builds on (see "Merging and stacked PRs").
2. Treat the issue body as the spec. If the human changes it after work has
   started, they say so in a comment; follow the comment.
3. Comment on the issue at meaningful checkpoints and at the end of every
   session: what is done, what was verified, what is next, and any new question.
   Not a running narration.
4. Tick the verification checklist in the issue body as steps pass.
5. If a question comes up that the issue doesn't answer, comment it, add
   `decision-needed`, and stop until it is answered.

A request that comes up mid-session ("also make it do X") is a new issue: draft
it with the human, commit the current branch's work, and wait for `ready` before
starting it. Bug fixes get a `bug` issue too, and a regression test.

### Private content stays off GitHub

The bench corpus (`bench/corpus/`, git-ignored) and user vaults hold private
documents. Never paste their text, names or identifiers into code, tests, docs,
commit messages, issues, comments or PR descriptions; describe problems with
fixture-style pages (`tests/fixtures/`). `scripts/gh_guard.py` enforces part of
this: a `PreToolUse` hook (`.claude/settings.json`) blocks any `gh` command whose
text or body file contains a term from `.gh-denylist` (gitignored, maintained by
the human). Never read, print or edit `.gh-denylist`, and don't work around a
block: rewrite the text. The hook only knows the listed terms, so the rule above
still applies in full. Bench `summary.md` files in git hold numbers only.

### Git workflow

- Never commit to `main`. Changes reach `main` only through a pull request.
- One branch per issue, named `issue/<n>-<short-slug>`. Harness, tooling or docs
  changes without an issue go on `chore/<topic>`.
- One line of work at a time. A new issue either branches from `main` (no PR
  open) or is stacked on the open one. Don't start a parallel line unless the
  human asks for it.
- Commit on the branch as you go (conventional commits); unfinished work is fine
  there as long as the latest issue comment says what state it is in.
- When the issue is done (see "Definition of done"), push the branch and open a
  PR with `gh pr create`. The description starts with `Closes #<n>` and covers
  what changed and why, how it was verified (the `init.sh` result and the
  evidence for every verification step: commands run plus the relevant output
  lines, with a date), and any open questions or known risks. Then comment on the
  issue with the PR link. Don't merge the PR yourself; the human reviews and
  merges.

**Merging and stacked PRs.** The repo merges PRs with merge commits only and
deletes the head branch after a merge. That keeps commit hashes intact, which is
what makes stacking safe:

- Branch from `main` by default. When an issue depends on code in a PR that
  isn't merged yet, branch from that PR's branch and open the PR with
  `gh pr create --base <that branch>` (a stacked PR). Say so at the top of the
  description, and name the PR it waits for.
- The base PR is merged first. GitHub then deletes its branch and retargets the
  stacked PR to `main` on its own. Never merge a stacked PR while its base is
  still open: it would land in the base branch, not in `main`.
- Before relying on the retarget, check the PR's base with
  `gh pr view N --json baseRefName`. If the base branch still exists after its PR
  merged, retarget with `gh pr edit N --base main`.
- If an open PR conflicts with `main`, merge `main` into the branch
  (`git fetch && git merge origin/main`) and resolve locally. If the resolution
  isn't obvious, stop and ask the human.
- Don't rebase or force-push a branch that has an open PR; the human may have
  pushed to it. Rerun `./init.sh` after the merge and before pushing.

### Stop and ask the human when

- an issue has the `decision-needed` label or a `DECISION NEEDED` note
- the issue you would work on isn't labeled `ready`
- the change would break a business requirement or constraint (§ 2, § 3) or
  overturn a technical decision (§ 4)
- the plan's current phase has no issue that can be started
- `docs/wiki/`, `AGENTS.md`, `docs/plan.md` and the code disagree about intended
  behavior; propose the doc edit

Don't guess on model choices: measure them with `mneme-wiki bench` and record the
result as a `TD-n` row.

### Definition of done

An issue is done only when all of these hold:
1. `./init.sh` passes (install, ruff, full pytest, end-to-end CLI smoke).
2. Every step in the issue's verification checklist was run and ticked, and its
   evidence (commands run plus the relevant output lines, with a date) is in the
   PR description. Steps that need Ollama say which model ran them.
3. User-visible changes (commands, flags, config, formats, MCP tools) are in
   `docs/wiki/` and, if relevant, the README; new technical decisions are `TD-n`
   rows in § 4; a tutorial exists if the issue asks for one.
4. New commands get a smoke step in `init.sh`.

"Tests pass" alone is not done. Unit tests that pass while the CLI path is broken
don't count.

### End of every session

1. Run `./init.sh` one last time; it must be green, or the breakage is recorded
   as a blocker in the issue comment.
2. Commit to the issue branch with a descriptive message. Leave nothing half-done
   that the issue comment doesn't mention.
3. Comment on the issue: what was done, what was verified, what is next, open
   questions. No optimistic claims; the comment must match reality.
4. If the issue is done, push and open the PR (see Git workflow).
