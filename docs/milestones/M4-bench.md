# M4: Bench (local models)

**Question:** which local model should run which stage, and is thinking worth
it for the patch stage? Measured, not assumed (TD-15).

**Short answer:** keep `qwen3:14b` for every role, with thinking on for `resolve`
only. It is the only configuration without a wrong merge that also finds the
gold pages, and a wrong merge is the most expensive error a wiki can make.
`qwen3:8b` is faster but misses about 5 of 33 gold pages. `gemma3:12b` merges
more across sources, but also merges things that are different. Patch thinking
makes the whole run 2.5× slower for no measurable gain in quality except fewer
copied headings. The bench also found a bug nobody was looking for: one model
call ran for **9 hours**, so every call is now bounded (TD-27).

---

## 1. What was built

```
mneme_wiki/
  bench.py            the harness: run, measure, aggregate, summarise, compare
  backends.py         + output-token cap and timeout on every call
  config.py           + MAX_OUTPUT_TOKENS, CALL_TIMEOUT_S
  prompts/judge.md    the page-quality judge
  cli.py              + mneme-wiki bench
bench/
  mappings/*.toml     one file per configuration
  README.md           the comparison and the decision
  corpus/             packets, gold.json, questions.md (private, git-ignored)
  results/            <timestamp>_<label>/ (only summary.md goes into git)
tests/
  test_bench.py       a whole bench run with the fake model
  test_backends.py    calls are bounded, a cut-off answer is an error
```

### 1.1 One bench run

`run_bench` (`bench.py:436`) takes a mapping and repeats `run_once`
(`bench.py:321`). Each repeat is a real integration:

1. a fresh throwaway vault (`init_vault`), so runs can't influence each other;
2. the corpus packets in the fixed `order.txt` order, through the same
   `integrate()` as the CLI. Nothing is mocked or shortened, so the bench measures
   the code you actually run;
3. the metrics, then an optional judge pass.

A mapping file (`load_mapping`, `bench.py:87`) names a model and thinking per
role. A role it doesn't list uses the config default.

### 1.2 What is measured

| Level | Metrics | Function |
|---|---|---|
| Per role | calls, valid JSON on the first try, retries, failures, latency, tokens | `call_metrics` (`bench.py:135`) |
| Against gold | gold pages found, core subjects merged across sources (recall), wrong merges (precision), duplicates | `gold_metrics` (`bench.py:168`) |
| Page quality | sections and bullets per page, near-duplicate bullets, headings copied from the source, links per page, citation coverage | `quality_metrics` (`bench.py:211`) |
| Provenance | abbreviations spelled out in a way the sources don't back (added in M5) | `unbacked_expansions` (`bench.py:267`) |
| Judge | structure, redundancy, clarity (1–5) on a fixed sample of 15 pages | `judge_pages` (`bench.py:283`) |

`aggregate` (`bench.py:387`) turns the runs into mean ± sd. `render_summary`
(`bench.py:492`) writes `summary.md`, and `compare` (`bench.py:631`) prints one
table over several result folders.

**"Headings copied from the source"** needs a word of explanation. It's the share
of headings that repeat a section title of the source, so a low value means the
page is organised around its subject, not around the document it came from. M0
saw thinking improve exactly this, which is why it's a metric.

**The judge is fixed.** Every configuration is scored by `qwen3:14b`, whichever
model wrote the pages. A judge that changed with the configuration would make the
scores incomparable. It's still a local model scoring a small sample, so treat its
numbers as a weak signal.

### 1.3 Every call is bounded (`backends.py`)

`OllamaBackend` (`backends.py:44`) passes `num_predict` (`MAX_OUTPUT_TOKENS`,
`config.py:37`) and a client timeout (`CALL_TIMEOUT_S`, `config.py:38`). An answer
that stops because it hit the cap (`done_reason == "length"`, `backends.py:84`) is
raised as a `BackendError`, so it counts as a failed attempt and is retried once,
instead of being parsed as if it were complete.

---

## 2. How to run it yourself

```powershell
# one configuration, 3 runs: about 15 minutes per run on qwen3:14b
mneme-wiki bench --models bench/mappings/baseline.toml --label baseline

# compare finished runs
mneme-wiki bench --compare bench/results/20261107-163359_baseline-m5fix bench/results/20261106-105116_qwen3-8b

# ask the question set against finished vaults (M5)
mneme-wiki bench --ask bench/results/20261107-163359_baseline-m5fix
```

Tests need no model: `pytest tests/test_bench.py tests/test_backends.py`. The
corpus is built from private documents and stays local, so a fresh clone has
the harness but no corpus; bring your own packets and `gold.json`.

---

## 3. What happened

### 3.1 The 9-hour call

The first `qwen3:8b` bench took 10.4, 10.0 and **560.4 minutes**. One patch call
in the third run went into a loop and produced 327k tokens. Nothing was wrong
with the code in the usual sense: no call had an upper limit, so a model that
never stops was simply waited for. That run is kept in
`bench/results/_superseded/`. With the limits in place, the re-run took 11.0 min on
average. The cap of 8192 tokens is several times the largest real answer (~1.9k)
plus thinking, so it doesn't touch normal calls.

The lesson matches L-3: model output is untrusted, and that includes its *length*.

### 3.2 Models

Three runs per configuration over the three corpus sources. Values are means.

| | `qwen3:14b` | `qwen3:8b` | `gemma3:12b` | 14b + patch thinking |
|---|---|---|---|---|
| Time (min) | 15.2 | **11.0** | 12.6 | 37.9 |
| Pages | 106 | 101 | 87 | 109 |
| Gold pages found (of 33) | **29.7** | 24.3 | 29.3 | 29.3 |
| Core merged across sources (of 14) | 8.3 | 6.7 | **10.3** | 8.3 |
| Wrong merges | **0** | 0.3 | 1.7 | **0** |
| Gold duplicates | 2.7 | 1.3 | **1.0** | 2.3 |
| Links per page | 1.61 | 2.08 | **2.22** | 1.79 |
| Rejected edits | 0 | 0 | 0 | 0 |
| Lint errors | 0 | 0 | 0 | 0 |
| Citation coverage | 100 % | 100 % | 100 % | 100 % |
| Headings copied from source | 87 % | 79 % | 95 % | **63 %** |
| Judge structure / redundancy / clarity | 3.4 / 3.3 / 3.6 | 3.5 / 2.9 / 3.8 | 3.3 / 2.7 / 3.7 | 3.2 / 3.4 / 3.6 |
| Invented expansions per vault (M5) | 4.0 | 2.7 | 8.7 | 1.7 |

What to read from this:

- **The safety net holds for every model.** Zero rejected edits, zero lint
  errors and full citation coverage in all configurations: those numbers come from
  code, not from the model, so they don't separate models at all. That's the design
  working (TD-5), and also a warning that they can't be used to choose one.
- **`qwen3:8b` loses content.** About 5 fewer gold pages of 33, an 18 % loss, for
  a 28 % time saving.
- **`gemma3:12b` trades precision for recall.** It merges two more core subjects,
  and it also makes 1.7 wrong merges per run. A missed merge leaves two pages a
  human can join. A wrong merge mixes two subjects' claims in one page, which is
  harder to notice and to undo. So precision wins. It also invents the most
  expansions.

**A caveat on `gemma3:12b`:** it has no thinking mode, so its `resolve` ran without
thinking. TD-18 depends on thinking there, so this measures the model *and* the
missing mode together. Its resolve stage took 0.8 min against 6.3 min.

### 3.3 Patch thinking

`TD-26` left this decision to M4. The result:

- **Cost:** the patch stage goes from 5.1 to 25.9 minutes. That's M0's 5× per
  call, and 2.5× on the whole run (37.9 vs 15.2 min).
- **Quality:** fewer copied headings (87 % → 63 %), which is the one clear gain.
  Judge scores differ by less than their own spread, and near-duplicate bullets
  are the same.

Verdict: **off**. A real but single gain doesn't pay for 2.5× the run time.

The first `patch-think` run took 86.9 minutes, with patch calls about 2.6× slower than
in the three runs that followed. The reason wasn't recorded (other load on the
machine is the likely cause, but that's a guess). It's the reason that result
folder has one run and was repeated, and it isn't used above.

### 3.4 What M5 added afterwards

The `unbacked_expansions` metric came from M5, after the real query run exposed
invented abbreviation expansions. All result folders were recomputed from their
stored vaults, so the row above is comparable. With M5's fixes in place,
`baseline-m5fix` reaches 0.3 (see the
[M5 tutorial](M5-query.md)); everything else about that run matches the baseline
within noise.

---

## 4. Decisions made in M4, and why

| Decision | Why | Rejected alternative |
|---|---|---|
| **`qwen3:14b` for every role** (TD-30) | Best gold coverage with zero wrong merges | `qwen3:8b` for speed: loses gold pages. A mix per stage: not measured (see gaps) |
| **Patch thinking off** (TD-30) | 2.5× the run time for one clear gain | On: 38 minutes for three sources |
| **Precision over recall in resolve** | A wrong merge is worse than a duplicate: see 3.2 | Choosing by core-merged count alone |
| **Bound every call** (TD-27) | The 9-hour call | A watchdog around whole runs: leaves a stuck call running, and doesn't help outside the bench |
| **A cut-off answer is an error** | Truncated JSON is at best invalid and at worst parses as something else | Trying to repair it |
| **Real `integrate()` in the bench** | Measures what actually runs | A special bench pipeline, which would drift from production |
| **A fixed judge for all configurations** | Comparable scores | Each model judging itself |
| **Result folders kept whole, only `summary.md` in git** | Vaults are large and hold private text; summaries are enough for history | Committing everything |

---

## 5. Known gaps

- **No mixed configuration was measured.** `qwen3:8b` for `extract` alone, for
  example, could save time without touching resolve. The exit condition is met by
  data for one model across all stages, not for every combination.
- **`qwen3:30b-a3b` wasn't run.** The plan named it as an option; two other models
  meet the goal.
- **Three runs, three sources.** Differences smaller than the spread mean little.
  The sample is small and from one domain.
- **The judge is weak evidence:** one local model, 15 pages, large spread.
- **The cause of the 86.9-minute run is unknown.**
- **The bench reports no failure when a config silently degrades a metric**: it
  is a comparison tool, not a regression gate.
