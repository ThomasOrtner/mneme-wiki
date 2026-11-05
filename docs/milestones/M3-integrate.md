# M3: Integrate

**Question:** can a source packet go into the vault, automatically and locally,
as one reviewable commit, with pages that are cited, linked both ways and pass
lint, while the model only *proposes* and code decides what is written?

**Short answer:** yes. The three corpus sources integrate on `qwen3:14b` in 16 minutes, in
three commits (one per source), and `mneme-wiki lint` reports **0 errors and 0
warnings** on the resulting 119 pages. Against the M0 gold file the result equals
M0's best run (31/33 gold pages, 9/14 core subjects merged across sources,
**0 wrong merges**) with slightly more links per page (1.9 vs 1.75), 100 %
citation coverage, and not one rejected edit in 291 model calls. 251 tests run
without a model; the opt-in real-model tests pass (resolve P = 1.00, R = 0.79 on
32 pairs).

M3 turns the M0 spike into tested production code. The design is the one M0
arrived at (pairwise resolve with thinking, code linking, citations set by code).
What's new is the safety around it: every write goes through an in-memory
workspace and reaches the vault only if lint shows no new error. Edits are
applied section by section, so text nobody touched stays byte-identical. Every
model decision is logged.

---

## 1. What was built

```
mneme_wiki/
  backends.py        Backend protocol + Ollama backend (the only one, L-1)
  llm.py             model per role, schema-constrained JSON, retry, call records
  packet.py          load + check a source packet; chunk at headings (≤ 500 words)
  workspace.py       Vault overlay: collect writes, diff, flush
  edits.py           validate + apply one page edit, section by section
  integrate.py       the orchestration for one packet; run report
  stages/common.py   Claim, Subject, KnownPage; name_key(), initials()
  stages/extract.py  3a: one call per chunk → subjects; merge within the source
  stages/resolve.py  3b: exact → name shape → BM25 → pairwise yes/no (thinking)
  stages/plan.py     3c: claims grouped by target page, paths for new pages
  stages/patch.py    3d: one call per page → proposal → edits.apply (+1 retry)
  stages/source.py   source page: upstream summary or one call; touched-pages list
  stages/autolink.py code linking of the first plain mention of other pages
  prompts/*.md       the system prompts (extract, resolve, patch)
  cli.py             + `integrate <packet>... [--dry-run] [--stage S --out F] [--json]`
tests/
  fakes.py                 scripted backend + a toy "model" that drives the whole pipeline
  fixtures/packets/        two small public packets (one with an upstream summary.md)
  data/resolve_pairs.json  32 resolve regression pairs (M0's 22 + 10)
  test_packet.py test_llm.py test_workspace.py test_edits.py test_stages.py
  test_integrate.py        end to end with the toy model, real git
  test_ollama.py           opt-in real-model tests (`pytest -m ollama`)
```

### 1.1 The path of one packet

`integrate()` (`integrate.py:123`) runs these steps, in this order:

1. **Preconditions.** Load and check the packet (`packet.load`, `packet.py:62`:
   `source.md` and `source.meta.json` with title, source_type, origin and date).
   For a real run the vault must be a git repo with **no uncommitted changes**
   (`integrate.py:144`), so the commit holds this source and nothing else. A
   source whose `origin` already has a source page is refused
   (`integrate.py:150`, TD-24).
2. **Chunk** (`packet.chunk`, `packet.py:119`): sections at headings, outside
   code fences; sections packed into chunks of ≤ 500 words, an oversize section
   split at paragraphs. The heading becomes the chunk's *locator*.
3. **Extract** (`stages/extract.py:130`): one call per chunk, no thinking,
   Ollama's `format=<schema>`. The prompt lists up to 40 known pages *for this
   chunk*: those mentioned in it, then subjects found earlier in this source,
   then BM25 matches (`known_for_chunk`, `extract.py:62`). M0 sent one
   global, truncated list. `parse_subjects` (`extract.py:99`) validates and
   clips: empty names and subjects without claims are dropped, an unknown kind
   becomes `concept`/`other`, and there are caps on subjects, claims and aliases.
   `merge_within_source` (`extract.py:156`) joins subjects that share a
   normalised name or alias.
4. **Resolve** (`stages/resolve.py:157`): see §1.3.
5. **Plan** (`stages/plan.py:27`, code): claims grouped by target page. A new
   page gets `vault.path_for(kind, name)`; if that slug is taken, or differs only
   in case from an existing file (NTFS), it gets `-2`, `-3`, ….
6. **Source page** (`stages/source.py`): the upstream `summary.md` if the packet has
   one (saves a call), otherwise one `summary` call, written in the source's
   language (TD-17).
7. **Patch + apply**, one page at a time (`stages/patch.py:154`): see §1.4.
8. **Autolink** (`stages/autolink.py:103`) on every page written in this run,
   plus the source page. Then the source page's *Pages updated from this source*
   section is rewritten with the page titles (`set_touched`, `source.py:100`).
9. **Reindex, lint, log.** `reindex(ws)` and `lint(ws)` run on the workspace.
   Any lint *error* that wasn't there before the run (`integrate.py:285`) stops
   the integration: nothing is written, and the diff is saved in the run folder.
   Otherwise `append_log(ws, "integrate", …)` adds the entry.
10. **Flush + commit** (`integrate.py:315`): the workspace writes its files
    through `Vault.write_text()` (atomic, path-checked) and `vault.commit()` makes
    **one commit** `integrate: <title>`.

Each step writes its output to `<vault>/.mneme-wiki/runs/<run-id>/`
(git-ignored): `extract.json`, `resolve_log.jsonl`, `plan.json`, `calls.jsonl`,
`report.md`/`report.json`, plus `diff.patch` for dry runs. Rejected edits go to
`<inbox>/rejected/<run-id>/<page>.json`, together with the model's full
proposal.

### 1.2 Models, calls, the fake (`llm.py`, `backends.py`, `tests/fakes.py`)

`LLM.for_role(role)` (`llm.py:65`) reads `MODEL_<ROLE>` (`backend:model`, TD-14)
and returns a `RoleClient`. Its `.json(system, user, schema)` (`llm.py:90`)
is the only way stage code talks to a model. It sends the schema as Ollama's
`format`, parses the answer, and retries once on invalid JSON, a non-object
answer or a backend error. Every attempt becomes a `Call` record (role, model,
step, attempt, ok, latency, tokens, thinking length, error). The records stream
to `calls.jsonl` and give the progress lines

```
  patch 6/19 + entities/pro3d.md                               ok      1.5s   642→123   tok
```

Thinking is set per role (`THINK_<ROLE>`, TD-26): on for `resolve`, off for
everything else.

Tests never need a server. `tests/fakes.py` registers a `ScriptedBackend` under
the backend name `fake`, so retries, logging and call records run the real
code. `Toy` is a rule-based "model" that is good enough to drive the whole
pipeline: subjects are the `**bold**` names in a chunk, resolve says "same" for
listed pairs, patch appends each claim as a cited bullet. Tests can override
single answers (`patch_answer`) to provoke rejections or broken JSON.

### 1.3 Resolve (`stages/resolve.py`)

Same design as M0 (TD-18), with one bug fixed:

1. **Exact:** any `name_key()` of the subject's names (ASCII-folded, no
   punctuation or parentheses, trailing plural `s` folded) matches a title/alias
   of an existing page *or* of a subject of this source already kept as new.
   An in-source match folds the claims into that subject.
2. **Candidates** (`_Pool.candidates`, `resolve.py:136`): first *name shape*: one
   key contains the other (≥ 3 chars), or one name is the other's initialism.
   Shape matches are ranked by BM25 score, then up to 2 BM25-only matches with a
   score ≥ 2.0 are added; at most 4 in total.
3. **Pairwise yes/no with thinking**, one call per candidate, and the first
   "same" wins. The prompt is M0's: it names the failure modes ("a part, a subtype, a
   related tool … → different") and asks for the reason before the answer.

Every subject produces a `Decision` (`resolve.py:58`) with its candidates and
every yes/no with the model's reason → `resolve_log.jsonl`.

**The bug:** M0's `initials()` dropped stop words, so *Regions of Interest*
became `ri`, and `ROI` never matched it by shape, although the M0 tutorial lists
exactly this case as working. Now `initials()` (`common.py:93`) returns both
forms, `{ri, roi}`. Found by `test_shape_match`.

### 1.4 Patch, validate, apply (`stages/patch.py`, `edits.py`)

`patch_page()` builds the prompt: the current page (or, for a new page, a
skeleton `# Title` + description + citation), the new claims with locators,
and up to 40 linkable pages (this run's planned pages first, then existing pages
by BM25 over the claims). The model answers `{lead, ops[{section, op, text}]}`.

`edits.apply()` (`edits.py:241`) decides what reaches the page:

- The body is split at `##` headings into `Parts` (`edits.py:116`, fence-aware).
  `split(body).render() == body` always. Only the sections an op touches are
  rebuilt; **every other byte stays as it was** (TD-25). A human's oddly
  spaced notes survive (`test_append_keeps_other_sections_byte_identical`).
- Op text is cleaned (`clean_text`, `edits.py:214`): escaped `\n` repaired (seen
  in M0), an echoed `## Section` line dropped, other H1/H2 lines demoted to H3 so
  they can't split the page.
- Links that don't resolve to exactly one file (existing or planned this run)
  are unwrapped to their text (`fix_links`, `edits.py:158`).
- Every fact line (a list item or prose line with ≥ 4 words) that cites no
  `sources/` page gets `([[sources/this]])` appended and counted
  (`ensure_citations`, `edits.py:184`).
- `append` skips lines the page already has (same plain text). `replace` is
  rejected if it drops a link target of the section or shrinks it below 60 %.
- A new lead is used only if it keeps every link of the old lead.
- **Final check** (`edits.py:305`): every link target of the old body must still
  be there, or the whole edit is rejected (L-4). The checks above should make
  this impossible; it's the last line of defence.

If a rejection is something the model can fix (a lossy `replace`), the model
is asked once more, with the reasons appended to the prompt. Whatever is still
rejected after that is reported, and the valid rest is applied. If the model
gives no valid answer at all, an existing page is left alone, and a new page
keeps its skeleton (so planned links to it stay valid).

Front matter (`_finish_meta`, `patch.py:209`): the source is added to
`sources:`, `updated` is set, and new names are added to `aliases` **unless
another page already claims that name**. That would be a `duplicate-name` lint
error and would break exact resolve later. New pages with ≤ 2 claims get
`status: stub` (the WIKI.md rule).

### 1.5 Workspace and dry runs (`workspace.py`)

`Workspace(vault)` (`workspace.py:18`) is a `Vault` whose `write_text()` stores
the new text in memory (after the same path and case checks as a real write), and
whose reads see the pending changes. Because it *is* a `Vault`, reindex,
append_log, lint and every stage run on it unchanged. `--dry-run` therefore runs
exactly the code of a real run, then prints `ws.diff()` and writes nothing to the
vault (TD-23). The same mechanism gives the all-or-nothing guarantee: a run that
fails half-way leaves no trace in the vault.

### 1.6 Autolink (`stages/autolink.py`)

Ported from M0 (TD-19) with stricter masking: links go only into paragraphs and
list items. Headings, tables, quotes/callouts, code, existing wikilinks,
Markdown links and URLs are masked out (`_mask`, `autolink.py:56`). Rules as
in M0: longest names first, one link per target, names of ≤ 5 characters
case-sensitive, < 3 never. A name that two pages claim is skipped. Only pages
written in this run are linked, so a run's diff contains only that run's pages.

---

## 2. How to run it yourself

```powershell
# a fresh dev vault (TD-16; git-ignored by the repo)
mneme-wiki init examples/vault

# look at single stages first: nothing is written to the vault
mneme-wiki integrate bench/corpus/rfm-gis-ad3 --vault examples/vault --stage chunk --out chunk.json
mneme-wiki integrate bench/corpus/rfm-gis-ad3 --vault examples/vault --stage resolve --out resolve.json

# the whole pipeline, as a diff
mneme-wiki integrate bench/corpus/rfm-gis-ad3 --vault examples/vault --dry-run

# for real: one commit per packet, in this order
mneme-wiki integrate bench/corpus/rocc-doc-1 bench/corpus/rfm-gis-ad3 bench/corpus/rfm-gis-ws1 --vault examples/vault
git -C examples/vault log --stat
mneme-wiki lint --vault examples/vault
```

A packet can also be given by name if it sits in the vault's inbox
(`<vault>/../inbox/<name>`). Then look at:

- `examples/vault` in Obsidian (graph view, backlinks);
- `examples/vault/.mneme-wiki/runs/<run>/report.md`, then `resolve_log.jsonl` for
  why something was or wasn't merged;
- `examples/inbox/rejected/<run>/`, if anything was rejected.

Tests: `pytest` (no model needed) and `pytest -m ollama` (real model: resolve
regression set, plus one fixture packet end to end).

---

## 3. What happened

### 3.1 Bugs found on the way

**`initials()` (inherited from the spike).** See §1.3: `ROI` never matched
*Regions of Interest* by name shape. Found by a unit test, not by a run.

**The touched-pages list used the subject's name.** When a subject resolved to an
existing page under another name ("Tactical Planning" → *Tactical Planning
Cycle*), the source page listed it as `[[…|Tactical Planning]]`. It now reads the
page's own title. Found by `test_second_source_updates_existing_pages`.

**cp1252 pipes.** The first smoke run crashed on the `━` progress glyph when
output was piped. On Windows, Python encodes pipes with the ANSI code page. The
CLI now switches piped stdout/stderr to UTF-8 (`cli.py`, `_utf8_pipes`). This
also protects `--json` output with non-Latin titles.

**Lead insertion added a blank line**, and **a toy-model test expected
links that the packet text never implied**. Both were caught by tests and fixed
(in the code and in the fixture, respectively).

### 3.2 The real run (exit condition)

Fresh dev vault, `ollama:qwen3:14b`, resolve with thinking, patch without, the
M0 order:

| Source | Words | Chunks | Subjects → merged | Resolved: exact / model / new | Pages new / updated | Rejected | Autolinks | Time |
|---|---|---|---|---|---|---|---|---|
| ROCC glossary | 2807 | 6 | 63 → 50 | 0 / 0 / 50 | 50 / 0 | 0 | 87 | 5.9 min |
| AD3 use cases | 1131 | 3 | 34 → 24 | 4 / 0 / 20 | 20 / 4 | 0 | 77 | 2.8 min |
| WS1 workshop notes | 3028 | 8 | 79 → 58 | 13 / 0 / 44 | 44 / 13 | 0 | 68 | 7.6 min |

291 model calls, all valid JSON on the first attempt (no retries). Resolve is
the biggest cost again: 139 yes/no calls, 7 min of 16. The largest prompt was
5.8k tokens (the glossary summary), well inside the 8–12k budget (L-2); patch
prompts stayed under 2.1k.

Validation counters over all three sources: 310 fact lines written, **every one
already cited by the model** (0 citations added), 0 links unwrapped, 1 duplicate
line skipped, 1 `replace` accepted, 10 new leads discarded because they dropped a
link of the old lead. The schema plus the stricter prompts left code little to
repair. The checks are still what makes that a guarantee rather than luck.

Scored with M0's `spike/eval.py` against `bench/corpus/gold.json`:

| | M0 v3 (best) | M3 |
|---|---|---|
| gold pages found | 31/33 | 31/33 |
| core subjects merged across sources | 9/14 | 9/14 |
| wrong merges (must_not_merge) | 0 | 0 |
| links per page | 1.75 | 1.9 |
| citation coverage | 100 % | 100 % |
| broken links / orphans | 0 / – | 0 / 0 |
| lint (errors / warnings) | – | 0 / 0 |

Missing: *CAMP* and *RAPDL* (never extracted). Duplicated: Traverse
(`notional-traverse` + `trajectory`), RSOWG/SOWG and Draw Tool/drawfile. The
first two are pairs the model judged *different*, with defensible reasons; your
gold file treats them as the same. The model merged **nothing** in this run:
every match came from exact names (17), and every one of the 139 pairwise
questions was answered "different". Example: `RFM-EXM` was extracted with the
wrong alias `rfm-gis` and a GIS description, so the model correctly refused to
merge it into the mission page. As in M0, the remaining misses are **extraction**
quality, not resolve decisions.

### 3.3 Resolve regression (`pytest -m ollama`)

On the 32 pairs: precision 1.00, recall 0.79 (thresholds 0.95 / 0.75). The
three misses are all spellings: `SKP-FT`/`SKP Field Trials`, `Pro3D`/`PRo3D` (in
the pipeline, exact matching catches this one before the model is asked) and
`Rover Operation Control Center`/`Rover Operations Control Centre`. None of the
14 "different" pairs was merged.

---

## 4. Decisions made in M3, and why

| Decision | Why | Rejected alternative |
|---|---|---|
| **All writes into a `Workspace`, flushed only if lint shows no new error** (TD-23) | A source is integrated completely or not at all; `--dry-run` is the real code path | Writing page by page (the spike): a crash mid-run leaves a half-integrated vault |
| **Refuse a dirty vault; refuse an already-integrated origin** (TD-24) | One commit holds one source and nothing a human was doing; re-integrating would add every claim twice | `git stash` around the run (hides human work in a stash); "update" semantics (needs claim-level diffing, later) |
| **Section-level apply, untouched sections byte-identical** (TD-25) | Diffs show only real edits; human text in other sections can't be harmed by a model rewrite | Re-rendering the whole body from parsed sections (the spike: normalised whitespace in every page it touched) |
| **Final "no link target lost" check on the whole page** | L-4 as an invariant, independent of the per-op rules | Trusting the per-op checks alone |
| **One retry with the rejection reasons, then partial apply** | The model can usually fix a lossy `replace` when told why; the valid rest of the answer shouldn't be lost | No retry (spike); rejecting the whole page on one bad op |
| **New page keeps its skeleton if patching fails** | Other pages of this run may already link to it; removing it would create broken links | Dropping the page (then every link to it would have to be unwrapped again) |
| **Aliases only if no other page claims the name** | A shared alias is a `duplicate-name` lint error and breaks exact resolve | Adding every alias the model found |
| **Known pages per chunk (mentioned, earlier subjects, BM25), ≤ 40** | Scales to 500 pages within the token budget (L-2); the relevant names come first | One global list cut at 6000 chars (spike): at 500 pages it would cut arbitrary names |
| **`initials()` with and without stop words** | `ROI` ↔ `Regions of Interest` (§1.3) | — |
| **Shape candidates ranked by BM25** | With a common word like "Target" in many titles, the 4-candidate cap must keep the closest ones | Pool order (spike): arbitrary |
| **Prompts in `prompts/*.md`** | Prompts are text: easy to read and diff, and the bench can compare versions; line-length lint doesn't apply | Module constants (they hit the 100-char limit, and wrapping would change the prompt) |
| **Thinking per role via `THINK_<ROLE>`** (TD-26) | The M4 bench must switch patch thinking without code changes | A hard-coded flag per stage |
| **Fake LLM = scripted rules, not recorded responses** | M0 never stored raw model answers, and the corpus is private (git-ignored), so recordings couldn't be committed anyway; rules keep tests readable and robust to prompt changes | Replaying recorded responses (breaks on every prompt change) |
| **Rejected edits to `inbox/rejected/<run>/`, run artifacts to `.mneme-wiki/runs/`** | Rejections need a human (next to the packets); run logs are derived data (TD-4) | Everything in the vault (rejections would end up in git) |
| **Piped CLI output is UTF-8** | Windows defaults pipes to cp1252, which crashed on `━` and would corrupt `--json` with non-Latin text | Requiring `PYTHONIOENCODING=utf-8` (M0's workaround) |

---

## 5. Known gaps

- **The model merged nothing in the real run.** Pairwise + thinking is very
  conservative: good for precision, but real matches that aren't exact
  names are lost (spelling variants like *Center*/*Centre*, and expansions the
  extractor got wrong). Candidates for M4: a spelling-tolerant exact step
  (British/American endings, hyphens), and comparing thinking/prompt variants on
  the regression set.
- **Extraction recall** is still the main limit (CAMP, RAPDL missing; wrong
  aliases like `RFM-EXM` → `rfm-gis`). M0's idea of a code pass that attaches
  passing mentions of *known* pages is not built.
- **No re-integration.** A changed source can't be integrated again (TD-24);
  updating needs claim-level diffing.
- **Pages follow the source's structure** (MMGIS has "Use Case 3", "Use Case 4"
  sections), as in M0.
- **Pages over the budget** (~24k chars) get only their section headings in the
  prompt and should only be appended to. That path is untested with a real model
  (no page in the corpus is that big).
- **Autolink only touches this run's pages,** so an older page that mentions a
  newly created subject isn't linked to it until that page is updated.
- **`--stage` stops after a stage but can't start from one**: a stage's
  JSON input can be inspected, not edited and fed back.
- **Progress is plain lines**, not `rich` progress bars (the plan mentions both);
  lines work the same in a terminal, a pipe and the MCP server.
- **Run artifacts accumulate** in `.mneme-wiki/runs/` (git-ignored); nothing
  prunes them.
