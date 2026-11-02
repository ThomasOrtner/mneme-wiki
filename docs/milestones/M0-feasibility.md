# M0: Feasibility test — can qwen3:14b build a Karpathy wiki?

**Question:** before building any real architecture, does the staged pipeline from
TD-13 (extract → resolve → plan → patch → validate/apply) actually work on a 14B
local model, on real documents?

**Short answer:** yes, with one stage redesigned. Structured output is a
non-issue (100 % valid JSON in all ~950 model calls across the runs). Extract, summary and patch
are good enough. **Resolve** (deciding whether a mentioned thing already has a page)
was the weak stage and needed three iterations; the version that works asks the
model one yes/no question per candidate *with thinking on*. Linking pages to each
other is better done by code than by the model. Details and numbers below.

Everything in M0 is throwaway spike code (`spike/`). It is not tested and will not
be imported by the real package — M1+ rebuild it properly, informed by what is
written here.

---

See also the diagrams in [`docs/architecture.drawio`](../architecture.drawio) (page 2 shows this pipeline as revised by M0).

## 1. What was built

```
spike/
  make_packets.py    mneme store → 3 source packets in bench/corpus/ (git-ignored)
  spike.py           the whole pipeline in one file, + progress output + run report
  eval.py            scores a spike vault against bench/corpus/gold.json
  resolve_bench.py   micro-benchmark for the resolve decision (22 hand-made pairs)
  out/               one folder per run: vault/ (a git repo), logs, report (git-ignored)
bench/corpus/
  rocc-doc-1/  rfm-gis-ad3/  rfm-gis-ws1/   source packets (local only)
  gold.json                                  expected pages, reviewed by you
```

### 1.1 The corpus and why these three documents

You chose the "RFM small cluster": the ROCC glossary (2.8k words), the MMGIS
use cases AD3 (1.1k after cleaning) and the Fred Calef workshop notes WS1 (3k).
They are small (fast iterations) and overlap heavily — ROCC, DAR, MMGIS, RVP,
PRo3D, WISDOM, Target Keeper, targets and traverses appear in two or three of them —
so they exercise the hardest part of a wiki: **recognising that a later source talks
about something an earlier source already created a page for**. They are project
documents, so `bench/corpus/` is git-ignored (`.gitignore`) and stays on your machine.

Ingestion order is fixed (`spike/spike.py:34`): glossary first (it defines the
vocabulary), then use cases, then the messy workshop notes.

### 1.2 Source packets (`spike/make_packets.py`)

This prototypes the upstream contract TD-8. It reads mneme's `registry.db` and
`store/` **read-only** and never imports mneme code (TD-8: loose coupling). For each
document it writes `source.md` + `source.meta.json`.

The cleaning step (`clean`, `make_packets.py:52`) matters more than expected:
docling repeats merged table cells on every row, so AD3's use-case tables repeated
the full title and user story ~30 times. `compact_tables` (`make_packets.py:30`)
blanks a cell that equals the cell above it. **AD3 shrank from 20 KB to 6.4 KB** — a
third of the tokens for the same information. It also drops `<!-- image -->`
placeholders and unescapes `&amp;` / `\_`.

> Decision: this belongs **upstream** (the mneme exporter, M7), not in mneme-wiki. The
> wiki should receive clean Markdown; packet quality directly drives token cost.

### 1.3 The gold file (`bench/corpus/gold.json`)

33 pages the wiki *should* end up with, each with every name variant that should
resolve to it (`ROCC` / `Rover Operations Control Centre`, `Pro3D` / `PRo3D`,
`TK` / `Target Keeper`, …). 14 are marked `core`: they appear in 2+ sources, so they
test cross-source merging. Plus 9 `must_not_merge` pairs — related but different
things a careless resolver would fuse (Planning Target vs Local Target, Area of
Interest vs Forbidden Area, Tactical vs Strategic Planning Cycle, …).

I drafted it after reading all three documents in full; you reviewed and edited it.
Caveats: it is name-based (a correct page with an unexpected title counts as
"missing"), and three expansions (DAR, RVP, MMGIS) came from my background knowledge,
not from the documents.

### 1.4 The pipeline (`spike/spike.py`)

One function per stage, all driven by `main()` (`spike.py:728`). Read it top to
bottom in this order:

**`Run.llm()` (`spike.py:61`)** — the only place that talks to the model. Every
call passes a JSON schema as Ollama's `format=` parameter, so the model is
*constrained* to emit valid JSON of that shape. One retry on invalid JSON. Every call
is logged to `calls.jsonl` (stage, latency, tokens, thinking length, ok) and printed
as a progress line.

**Chunking (`chunk`, `spike.py:165`)** — split on headings, pack sections into
chunks of ≤ 500 words, split oversize sections by paragraph. The chunk's heading
becomes the claim's *locator* (where in the source a fact came from) — set by code,
not by the model, so it cannot be hallucinated.

**Stage 1 — extract (`stage_extract`, `spike.py:253`)** — one call per chunk. The
model returns *subjects*: name, entity-or-concept, aliases, a one-sentence
description, and 1–6 self-contained claims. Two prompt details came out of the
smoke run:
- an explicit entity/concept definition ("entity = one specific named thing that
  exists once; concept = a type with many instances");
- "field names, enum values, file names, plan steps are *not* subjects — put them as
  claims on their parent". Without it, `Load_Status` and `Plan_Option` got their own
  pages.

The prompt also includes the list of *known page titles*, so the model can reuse an
existing name — the cheapest form of resolution.

**Merge within source (`merge_within_source`, `spike.py:299`)** — code only: subjects
from different chunks with the same normalised name or alias become one group
(`norm()` lower-cases, strips punctuation and parentheses, folds a trailing "s").

**Stage 2 — resolve (`stage_resolve`, `spike.py:321`)** — the stage that needed
redesign; see §3. Final design:
1. exact match of any normalised name/alias against existing pages *and* against
   subjects already seen in this source (code);
2. candidate retrieval (code): **name-shape** candidates first — one name contains
   the other (`strategicplanning` ⊂ `strategicplanningcycle`) or is its initialism
   (`ROI` ↔ `Regions of Interest`, via `initials()`, `spike.py:293`) — then BM25 over
   title + aliases + description; at most 4;
3. for each candidate in order, one **pairwise yes/no call with thinking**: "are A
   and B the same thing, or is one a part / subtype / tool / role related to the
   other?"; first "same" wins.
Every decision, including each yes/no with the model's reason, is written to
`resolve_log.jsonl` — so a wrong merge can be audited.

**Stage 3 — plan (`stage_plan`, `spike.py:422`)** — code only: group claims by
target page; new pages get a path in `entities/` or `concepts/`.

**Stage 4 — patch (`stage_patch_apply`, `spike.py:528`)** — one call per page. The
model sees the current page, the new claims (with locators) and a list of linkable
pages, and returns a new lead paragraph plus *operations* (`append` to / `replace` a
section). It never returns a whole file.

**Stage 5 — validate & apply (same function)** — code checks every operation before
it touches the page:
- links to pages that don't exist are turned back into plain text (`fix_links`);
- every fact line must cite the source, otherwise the citation is added and counted
  (`ensure_citations`);
- `replace` may not drop an existing link or shrink a section below 60 %; violations
  are rejected and logged to `rejections.jsonl`;
- a new lead that loses links is discarded and the old lead kept;
- escaped `\n` inside strings is repaired (seen once in the smoke run).
Then front matter is updated (aliases unioned, source added to `sources:`) and the
page is written atomically (`save_page`, `spike.py:152`: write temp file, rename).

**Stage 6 — autolink (`autolink`, `spike.py:638`)** — added in M0, code only: on
every page, link the first plain-text mention of another page's title or alias.
Longest names first ("Integrated Activity Plan" before "Activity Plan"); names of
≤ 5 characters must match case-sensitively so `TIME` or `Task` don't fire on
ordinary words; existing links are never touched.

**Finish (`finish`, `spike.py:681`)** — the source page gets a "Pages updated from
this source" list (so links run both ways: page → source via citations, source →
page via this list), `index.md` is regenerated, `log.md` gets an entry, and the vault
commits: **one git commit per source**.

**Run report (`render_report`, `spike.py:808`)** — printed and saved as
`report.md`: per-source table, per-stage call stats, validation counters, most
connected pages, and what to look at next.

### 1.5 Scoring (`spike/eval.py`)

Loads a spike vault and compares it to the gold file: gold pages found / duplicated
/ missing, core subjects that ended up as **one** page fed by **2+ sources**, wrong
merges, broken links, orphans, links per page, citation coverage.

---

## 2. How to run it yourself

Prerequisites: Ollama running with `qwen3:14b`; the mneme repo next to this one.

```powershell
cd C:\_REPOS\mneme-wiki
python -m venv .venv
.venv\Scripts\python -m pip install ollama rank_bm25 pyyaml

# 1. build packets from the mneme store (writes bench/corpus/<id>/)
.venv\Scripts\python spike\make_packets.py

# 2. run the pipeline over all 3 sources (~10-15 min); watch the progress lines
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python spike\spike.py --label mytry --no-think

# 3. score against the gold file
.venv\Scripts\python spike\eval.py mytry

# 4. the resolve micro-benchmark (~3 min)
.venv\Scripts\python spike\resolve_bench.py
```

Then look at the result:
- open `spike\out\mytry\vault` as a vault in Obsidian — graph view and backlinks;
- `git -C spike\out\mytry\vault log --stat` — one commit per source, what each touched;
- `spike\out\mytry\report.md`, `resolve_log.jsonl`, `rejections.jsonl`.

`--no-think` turns thinking off for the patch stage (resolve always thinks).
`--label` names the output folder; it refuses to overwrite an existing one.

---

## 3. What happened — the runs in order

| Run | What changed | Time | Pages | Core merged across sources | Wrong merges | Links/page |
|---|---|---|---|---|---|---|
| smoke | first version, source 1 only, 900-word chunks | 10 min | 42 | — | — | — |
| v1 think | 500-word chunks, better extract prompt; patch thinking on | 28 min | 111 | 7/14 | 0 | 0.9 |
| v1 no-think | same, patch thinking off | 9 min | 118 | 8/14 | 0 | 0.16 |
| v2 no-think | resolve: name-shape candidates, in-source resolve, looser prompt; autolink | 9 min | 97 | 8/14 | **1** | 1.97 |
| v3 no-think | resolve: pairwise yes/no + thinking | 16 min | 102 | **9/14** | **0** | 1.75 |

### Smoke run — the bugs a first run finds
- **Silent drops:** 900-word chunks + a 12-subject cap per chunk → the first chunk
  had more than 12 subjects, so the Tactical and Strategic Planning Cycles never got
  pages. Fix: 500-word chunks, cap 15, "cover every subject the chunk defines".
- **Escaped newlines:** the model once wrote `\n` literally inside a JSON string,
  gluing two bullets together (and one lost its citation). Fix: repaired in code.
- **Arbitrary entity/concept split** and **over-fragmentation** (pages for field
  names and plan steps). Fix: definitions + "not a subject" rules in the prompt.

### v1 — infrastructure works, merging doesn't
100 % valid JSON, no broken links, every fact line cited, no rejected edits. But only
**7 of 14** core subjects became one page fed by several sources, and the model-
assisted resolve step matched **0 of 30** times. `RFM-EXM` became its own page next to
"ExoMars Rosalind Franklin Mission"; "Strategic Planning" next to "Strategic Planning
Cycle"; "Trajectory" next to "Traverse".

Diagnosis (by replaying cases by hand): the model *can* recognise these as the same
thing when shown the right candidate. Two failures in the code around it:
1. **retrieval** — BM25 compares words; `RFM-EXM` shares no word with "ExoMars
   Rosalind Franklin Mission", so the right page was never a candidate;
2. **scope** — duplicates *within* a source (Trajectory/Traverse both in AD3) were
   never compared, because resolve only looked at existing pages.

And linking was poor: 0.9 links per page with thinking, 0.16 without.

### v2 — better candidates, but the model over-merges
Added name-shape candidates, in-source resolution, a looser "same real-world thing"
prompt and the autolink pass. Links went to ~2 per page (182 added by code), and 10
in-source duplicates merged. But reading `resolve_log.jsonl` showed most of the
model's merges were **wrong**: User Authentication → ExoMars mission, Integrated Plan
→ Activity Plan, Planning Target and Local Target → Target, `dar_ci` → DAR. The
model's own reasons say "is related to", "is a type of". With several candidates in
one prompt, a 14B model without thinking picks the most related one.

So the strict prompt (v1) never merged, the loose one (v2) merged anything related.

### Resolve micro-benchmark — isolating the decision
`spike/resolve_bench.py`: 22 hand-made pairs from real cases (10 same, 12 different),
one yes/no question per pair, with a prompt that names the failure modes ("a part, a
subtype, an instance, a step, a related tool, a role related to it → different") and
asks for the reason *before* the answer.

| Variant | Precision | Recall | Latency/decision |
|---|---|---|---|
| pairwise, no thinking | 1.00 | 0.60 | 0.9 s |
| pairwise, thinking | **1.00** | **0.90** | 5.0 s |

The one miss (`Pro3D` vs `PRo3D`) never reaches the model — exact matching catches it.
Caveat: the pairs are mine, and `dar_ci` vs `DAR` is also one of the prompt's
examples, so these numbers are optimistic. They show the *shape* of the fix, not a
guarantee.

### v3 — the fix, end to end
Pairwise + thinking in the real pipeline (`spike/out/v3-nothink`): **31 of 33** gold
pages found, **9 of 14** core subjects merged across sources (best of all runs),
**zero wrong merges**, 0 broken links, 100 % citation coverage, 167 links added by
autolink. 304 model calls in 16 minutes; resolve is now the most expensive stage
(165 calls, 8.3 min) but each call is short.

Reading `resolve_log.jsonl`: every "different" decision is defensible (Planning
Target ≠ Target, Target Keeper ≠ Target, Executed ≠ Planned Trajectory). The only
debatable one is RSOWG vs SOWG, which your gold file treats as the same.

**The remaining 5 core misses are not resolve errors — they are extraction recall.**
Experiment Cycle, Vertical Survey and Symbology are only *mentioned in passing* in
the second source ("EC and VS"), so extraction never produced a subject for them and
resolve never saw them. WISDOM was folded into PanCam's aliases by the extractor.
So the next lever is extraction (passing mentions of *known* pages), not resolve.

---

## 4. Decisions made in M0, and why

| Decision | Why | Rejected alternative |
|---|---|---|
| **Resolve = pairwise yes/no with thinking**, ≤ 4 candidates, name-shape candidates before BM25 | Only variant with no false merges in the full run, and 9/10 true pairs in the micro-benchmark (§3). In the full run most true matches were already caught by exact/name matching; the model's job became mainly *rejecting* look-alikes. About 165 short calls for 3 sources (8 min), so thinking is affordable | Pick-one-of-many (failed both ways); no model at all (misses `RFM-EXM`) |
| **Resolve also runs within a source** | Duplicates arise inside one document (Trajectory / Traverse) | Only resolving against existing pages |
| **Linking is code (autolink)**, the model only adds links it is sure of | Code linking is free, deterministic, and gave ~2 links/page vs 0.16 from the model without thinking | Asking the model to link (needs thinking, still sparse) |
| **Patch thinking: open question for M4** | Thinking gives better section structure and fewer near-duplicate bullets, but costs 5× (28 vs 9 min). Not worth deciding on one page comparison | Fixing it now |
| **Locators and citations are set by code** | The model cannot invent where a claim came from; missing citations are added and counted | Trusting the model to cite |
| **Ollama `format=<schema>` for every call** | 100 % valid JSON across ~950 calls; retry logic never triggered | Free-text + parsing |
| **Packet cleaning belongs upstream** (M7) | Table compaction cut AD3 to a third; the wiki should get clean input | Cleaning inside mneme-wiki |
| **Spike code is throwaway** | It answered questions fast; M1+ rebuild with tests and structure | Growing the spike into the product |

## 5. What this changes in the plan

- TD-13 / plan "Integration stages": resolve becomes pairwise + thinking, runs
  in-source too, logs every decision; a new **autolink** stage (code) after apply.
- M3 gets a resolve gold test (the 22 pairs, extended) as a regression test.
- M4 bench must compare **patch thinking on vs off** on quality, not just speed, and
  re-check resolve precision/recall on a bigger pair set.
- M7 exporter: compact tables, drop image placeholders, unescape entities.

## 6. Known gaps (honest list)

- **Extraction varies between runs.** The same document gave 60, 71 and 56 subjects in
  three runs; page counts vary ±15 %. Bench runs need repetitions to be meaningful.
- **Recall gaps in extraction:** passing mentions of things that already have a page
  ("EC and VS") are not extracted, so those pages don't get the new source; some
  subjects get folded into another subject's aliases (WISDOM → PanCam). Idea for M3:
  a cheap code pass that finds mentions of *known* page titles/aliases in the source
  and attaches the surrounding sentence as a claim candidate.
- **Pages follow the source's structure**, not the subject's: MMGIS has sections
  "Use Case 3", "Use Case 4" because the claims came from there. Fine for now;
  a later lint/LLM "restructure page" step could fix it.
- **Over-fragmentation is reduced, not gone:** ~100 pages from 7k words of source,
  some thin (one or two claims). A "stub" status for single-claim pages is worth
  considering.
- **No contradiction detection** yet (deferred, as planned).
- **No larger-model reference run.** The plan listed it as optional; skipped because
  only qwen3:14b is pulled locally. The resolve micro-benchmark showed the failures
  were prompt/question design, not raw model ability. Moved to M4.
- **The gold file and resolve pairs are small and partly written by me.** They are a
  smoke alarm, not a benchmark.

## 7. Go / no-go

**Go for qwen3:14b as the default**, with the revised resolve stage. The model is
reliable at structured output and at faithful, cited writing; its weakness is
judgement calls between related concepts, and that is handled by narrowing the
question (pairwise), letting it think, and keeping every decision auditable.
