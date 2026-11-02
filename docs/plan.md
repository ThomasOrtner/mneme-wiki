# mneme-wiki: MVP plan

The implementation plan for the MVP. [AGENTS.md](../AGENTS.md) holds the
stable rules (requirements, constraints, decisions, coding standards). This
file holds the build order, the detailed designs, and progress. Tick off the
checkboxes as work lands, in the same commit. Each milestone ends with a
tutorial in `docs/milestones/M<n>-<name>.md` (what was built, how to run it,
the decisions and why), one commit, and then work stops until the user
confirms the next milestone.

## Goal

**Source packet in → correctly integrated, linted, committed vault out**,
reachable from the CLI and over MCP, **fully local** on `ollama:qwen3:14b` by
default, with a benchmark that shows how each stage performs per local model.

### Definition of done

- [ ] Integrating 3 related real sources produces shared entity/concept pages
      with links in both directions and citations on claims (BR-4, BR-5).
- [ ] `mneme-wiki lint` reports zero errors on the resulting vault.
- [ ] Each integration is one reviewable git commit in the vault, with a
      `log.md` entry.
- [ ] `mneme-wiki query --file` answers with citations and saves a synthesis page.
- [ ] All of the above is available as MCP tools.
- [ ] A bench run compares qwen3:14b with at least 2 other local models on the
      fixture corpus.

---

## Milestones

Deterministic parts first, LLM parts after. Each milestone ends in a
working, tested state.

### M0: Feasibility test

Check that the staged pipeline works on qwen3:14b before any architecture is
built on it.

- [x] Pick 3 related real sources from `../mneme/store/` (non-sensitive,
      overlapping entities/concepts). Copy them as source packets to
      `bench/corpus/`.
- [x] Throwaway scripts in `spike/` (not production code, no tests) run
      extract → resolve → patch by hand on qwen3:14b.
- [ ] ~~Optional: run the same prompts once on a larger local model~~ —
      skipped: not pulled locally; the resolve micro-benchmark answered
      "model too weak vs prompt badly designed" instead (it was the prompt).
      Moved to M4.
- [x] Hand-label a small gold file (`bench/corpus/gold.json`): expected
      entities/concepts and which mentions are the same entity.
- [x] Write `docs/milestones/M0-feasibility.md` (tutorial + findings): JSON
      validity, entity-merge quality, whether patches keep existing content,
      latency per call, and recommended changes to the stage design below.

**Exit:** the stage design is confirmed or revised (update this file).
Go/no-go for qwen3:14b as the default.

**Result (2026-11-02):** go, with resolve redesigned (pairwise + thinking) and a
code autolink stage added. See [M0 tutorial](milestones/M0-feasibility.md).

### M1: Scaffold & vault model

- [x] `pyproject.toml` (deps: `pyyaml`, `ollama`, `python-dotenv`,
      `rich`, `rank_bm25`, `mcp`; dev: `pytest`, `ruff`), `mneme_wiki/`
      package, `config.py`, `.env.example`, `.gitignore`.
- [x] `mneme_wiki/templates/WIKI.md`: vault schema and maintainer instructions
      (inside the package so it ships with a non-editable install).
- [x] `frontmatter.py`: parse/serialise/validate, keeps unknown keys (TD-20).
- [x] `links.py`: extract/resolve `[[page]]`, `[[page|alias]]`,
      `[[page#heading]]`, alias map, backlink map.
- [x] `vault.py`: page I/O (atomic writes), slugging that is safe on
      Windows/NTFS, case-collision detection, path confinement, git commit.
- [x] `mneme-wiki init <path>`.
- [x] Fixture vaults in `tests/fixtures/` (clean, broken YAML, broken links,
      Windows-hostile names).

**Exit:** round-trip tests pass (parse → serialise leaves files unchanged byte for byte when nothing changed).

**Result (2026-11-02):** done. Every parsable fixture file (LF, CRLF + BOM,
comments, quoting, no front matter) round-trips byte for byte; 152 tests pass.
See [M1 tutorial](milestones/M1-scaffold.md).

### M2: Lint, index, log

- [ ] `lint.py` deterministic checks: broken links, orphans, invalid or missing
      front matter, uncited claims, duplicate aliases.
      `mneme-wiki lint [--json]`, exits non-zero on errors.
- [ ] `index_log.py`: `mneme-wiki reindex` regenerates `index.md`; `append_log()`
      used by every write operation.
- [ ] `search.py`: BM25 over pages (title, aliases, lead paragraph, body),
      `mneme-wiki search "<q>" [--json]`.

**Exit:** lint finds every planted defect in the fixture vaults.

### M3: Integrate

Built stage by stage. Each stage can be run on its own and has a JSON
input/output that can be inspected:
`mneme-wiki integrate <packet> --stage <name> --out x.json`.

- [ ] Packet loader + source page writer (uses upstream `summary.md` if
      present, otherwise one summary call).
- [ ] 3a `stages/extract.py`
- [ ] 3b `stages/resolve.py`
- [ ] 3c `stages/plan.py` (code only)
- [ ] 3d `stages/patch.py`
- [ ] 3e `edits.py`: validate and apply, reject to `inbox/rejected/`
- [ ] Orchestration in `integrate.py`: reindex, log, commit; `--dry-run`
      prints the plan and diff.
- [ ] Tests with a fake LLM (recorded responses from M0); opt-in real
      run via `pytest -m ollama`.
- [ ] Resolve regression test: the M0 pairs (`spike/resolve_bench.py`), extended,
      as a `pytest -m ollama` test with precision/recall thresholds.
- [ ] `autolink` stage (code) after apply.

**Exit:** the 3 corpus sources integrate cleanly on qwen3:14b, and lint is clean.

### M4: Bench (local models)

- [ ] Mapping from stage role to model in config (`MODEL_<ROLE>`), overridable
      by a bench mapping file.
- [ ] `bench.py` + `mneme-wiki bench --models <mapping.toml> --label <name>`.
- [ ] Baseline run (all qwen3:14b) plus 2–3 other local models (e.g.
      `qwen3:8b`, `qwen3:30b-a3b`, `gemma3:12b`, whatever fits the hardware);
      write a short comparison to `bench/README.md`.
- [ ] Patch stage: thinking on vs off, judged on page *quality* (structure,
      duplicate bullets), not only speed (M0: 5× slower, visibly better structure).
- [ ] Repeat each configuration ≥ 3× — M0 showed ±15 % run-to-run variance in
      extraction.

**Exit:** the model choice per stage is backed by data.

### M5: Query

- [ ] `query.py`: BM25 + index → top pages within the token budget → answer
      with `[[citations]]`; checks that every cited page exists.
- [ ] `--file` saves the answer as a `synthesis` page (with a `question` field),
      reindex, log, commit.

### M6: MCP server

- [ ] `mcp_server.py` (stdio, logs only to stderr): `status`, `search`,
      `read_page`, `lint`, `query`, `integrate` (background job + `job_status`).
- [ ] No delete/rename tools in the MVP.

### M7: mneme exporter (in the mneme repo, separate change)

- [ ] `mneme-export-wiki-packet <doc_id> --inbox <path>`: `store/{doc_id}` →
      source packet (`source.md`, `source.meta.json`, `summary.md`, `toc.json`).
- [ ] Clean on export (prototype: `spike/make_packets.py`): blank table cells that
      repeat the cell above, drop `<!-- image -->`, unescape HTML entities and `\_`
      (M0: cut one document to a third of its size).

---

## Design details

### Source packet (input contract)

```
inbox/<packet-name>/
  source.md            required: content, already in Markdown
  source.meta.json     required: title, source_type, origin, date; optional author, published, language
  summary.md           optional: upstream summary
  toc.json             optional: section structure, used for citation locators
```

`origin` examples: `mneme:<doc_id>`, a URL, `manual`.

### Integration stages

Revised by M0 (see [M0 tutorial](milestones/M0-feasibility.md)):

| Stage | Who | Input → output | Mode |
|---|---|---|---|
| Chunk | code | packet → chunks ≤ 500 words, split at headings; heading = locator | — |
| Extract | LLM, per chunk | chunk + known page titles → `subjects[{name, kind, entity_kind, aliases, description, claims[]}]`, ≤ 15 per chunk | no thinking, schema-constrained JSON |
| Merge in source | code | union subjects by normalised name/alias | — |
| Resolve | code + LLM | exact match vs existing pages *and* earlier subjects of this source; else ≤ 4 candidates (name shape: containment/initialism, then BM25); **pairwise yes/no per candidate**, first "same" wins; every decision logged with reason | **thinking** |
| Plan | code | claims grouped by target page, new page paths | — |
| Patch | LLM, one call per page | page + its new claims + linkable pages → `{lead, ops[{section, op: append\|replace, text}]}` | thinking on/off decided in M4 |
| Validate & apply | code | links only to known pages, every fact line cited (added + counted if missing), `replace` may not drop links or shrink < 60 %, lead may not lose links, escaped `\n` repaired. Retry once, then reject with the reason | — |
| Autolink | code | first plain mention of another page's title/alias → `[[link]]`, longest first, short names case-sensitive | — |
| Finish | code | source page lists touched pages, `index.md`, `log.md`, git commit, run report | — |

Token budget per LLM call: about 8–12k input tokens on qwen3:14b (M0 maximum
was ~6k). A page that doesn't fit gets patched section by section.

Contradiction detection is not part of the MVP stages (deferred LLM lint).

### Progress & run reports

Integration takes minutes per source, so a silent command is unusable.

- **While running:** one line per stage and per model call, with elapsed
  time, stage and position (`patch 12/40 ~ concepts/activity-plan`), ok / retry /
  fail, latency and tokens; rejected edits are printed as they happen.
  `rich` progress bars when attached to a terminal, plain lines when piped.
  Progress goes through the `log` callable, so the MCP server sends it to stderr
  and job status.
- **When done:** a run report printed and saved next to the run (and summarised
  in the `log.md` entry): per-source table (chunks, subjects, matched vs new,
  pages created/updated, rejected edits, time), per-stage call stats,
  validation counters, the most-connected pages, and what to look at next
  (vault path, `git log`, rejection file). `--json` returns the same data.
- The spike (`spike/spike.py`) prototypes this format (`report.md`).

### Backend protocol

```python
complete(messages, *, schema=None, thinking=False) -> Result
# Result: text, json, usage (tokens in/out), latency_s, cost_usd
```

- **Ollama** (the only backend in the MVP): `ollama` package,
  `format=<json schema>`, qwen3 thinking switched by the `thinking` flag.
  `cost_usd` is always 0.
- Model refs are `backend:model`, e.g. `ollama:qwen3:14b`.
- Roles: `extract`, `resolve`, `patch`, `summary`, `query`, `judge`.
- Later: an OpenRouter backend (`httpx`, OpenAI-compatible) plugs in behind the
  same protocol, opt-in via `WIKI_ALLOW_REMOTE`.

### Benchmark

- Input: `bench/corpus/` (packets + `gold.json`) and a mapping file
  (role → model ref).
- Each run integrates the corpus into a fresh, throwaway vault and runs a fixed
  question set (`bench/corpus/questions.md`).
- Metrics per stage and model: JSON validity, rejection rate, retries,
  latency, tokens, cost.
- Metrics for the whole run: pages created/updated, links per page, citation
  coverage, lint errors, entity-resolution precision/recall against gold.
- Optional quality score from a fixed local `judge` model and/or by a human.
- Output: `bench/results/<timestamp>_<label>/` → `metrics.json`,
  `summary.md`, the produced `vault/`. Results are git-ignored except
  `summary.md`.

### Module map

| Module | Role |
|---|---|
| `config.py` | Env vars & defaults |
| `llm.py` | `chat`, `chat_json`, `for_role(role)` → backend + model |
| `backends.py` | Backend protocol + Ollama backend |
| `frontmatter.py` | Front-matter parse/serialise/validate |
| `links.py` | Wikilink parsing/resolution, alias & backlink maps |
| `vault.py` | Page I/O, slugs, path confinement, git |
| `index_log.py` | `index.md` generation, `log.md` appends |
| `search.py` | BM25 page search |
| `lint.py` | Deterministic checks |
| `stages/extract.py`, `stages/resolve.py`, `stages/plan.py`, `stages/patch.py` | Integration stages |
| `edits.py` | Edit data model, validation, apply |
| `integrate.py` | Stage orchestration for one packet |
| `query.py` | Answer + file-back |
| `bench.py` | Benchmark harness |
| `cli.py` | CLI (thin) |
| `mcp_server.py` | MCP tools |

### CLI surface

```
mneme-wiki init <path>
mneme-wiki integrate <packet> [--stage S --out F] [--dry-run]
mneme-wiki lint [--json]
mneme-wiki reindex
mneme-wiki search "<q>" [--json]
mneme-wiki query "<q>" [--file] [--json]
mneme-wiki bench --models <mapping.toml> --label <name>
mneme-wiki status [--json]
```

### Configuration (`.env`)

| Var | Default |
|---|---|
| `WIKI_VAULT_DIR` | `examples/vault` |
| `WIKI_INBOX_DIR` | `<vault>/../inbox` (TD-21) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `NUM_CTX` | `32768` |
| `MODEL_EXTRACT`, `MODEL_RESOLVE`, `MODEL_PATCH`, `MODEL_SUMMARY`, `MODEL_QUERY` | `ollama:qwen3:14b` |
| `MODEL_JUDGE` | unset |
| `WIKI_LANGUAGE` | `en` |

---

## Risks

| Risk | Mitigation |
|---|---|
| qwen3:14b can't do patching well enough | M0 detects this early; fallbacks: smaller patch units (section by section), a larger local model for the `patch` role, or later an opt-in remote model |
| Entity duplication (same thing, several pages) | Aliases + gold-labelled resolve metrics; a lint check for duplicate aliases |
| Patches slowly wear down human-written content | No-content-loss validation; every change is a git diff |
| Integration too slow (many calls per source) | Batch use is acceptable; measure in the bench; parallelise per-page patches later |
| Structured-output reliability varies by model | Validate + retry; record validity per model in the bench |

## Deferred (not MVP)

OpenRouter / remote backends (opt-in, for benchmarking against stronger
models and hybrid vault profiles), embedding search, LLM lint (contradictions,
stale claims, missing concepts), page merge/rename, watching `inbox/` for new
packets, generated views, image handling, parallel patching.

## Decisions taken (formerly open questions)

- Integration (the "compile" step) lives here; upstream delivers processed
  sources, not finished notes.
- Many vaults, each with its own `WIKI.md`; dev vault in `examples/vault/`
  (TD-16).
- `source` pages keep the source language; other pages use `WIKI_LANGUAGE`
  (TD-17).
- Fully local for the MVP; OpenRouter later.
