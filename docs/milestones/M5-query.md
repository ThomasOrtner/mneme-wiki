# M5: Query

**Question:** can the wiki answer a question from what it already knows, with
citations, and keep a good answer as a new page?

**Short answer:** yes, after a real-model run showed that the first version
wasn't good enough. `mneme-wiki query "<q>"` retrieves pages by BM25, makes one
model call, and checks the answer in code. With `--file` it saves a `synthesis`
page in one commit. On the bench vaults, 30 of 30 real answers now cite at least
one source (before the fix: 79 %), the trick question was refused every time, and
an answer takes about 3.7 seconds.

The most useful result of this milestone wasn't planned. Running the fixed
question set against real vaults showed that **models invent what abbreviations
stand for**, that this text was already in the vaults, and that every existing
check passed it. Fixing that changed `integrate`, not just `query`.

---

## 1. What was built

```
mneme_wiki/
  query.py            retrieve, answer, check, file back
  prompts/query.md    the answer prompt
  expansions.py       abbreviation expansions the evidence doesn't back (TD-29)
  status.py           vault overview, shared by the CLI and MCP
  integrate.py        + _strip_expansions, after patch
  stages/source.py    summary prompt: don't spell out abbreviations
  cli.py              + mneme-wiki query, mneme-wiki status
tests/
  test_query.py, test_expansions.py, + cases in test_integrate.py and test_cli.py
```

### 1.1 One question (`ask`, `query.py:148`)

1. **Retrieve (code).** `retrieve` (`query.py:72`) runs the M2 BM25 search. The
   best pages go in whole while they fit `BUDGET_CHARS` (24,000 characters, about
   6k tokens, L-2), at most 8. The next ones appear as one-line index entries, so
   the model knows they exist. With no hit at all there's no model call: "The wiki
   has no page about this."
2. **Answer (one `query` call).** The model returns JSON:
   `{answer, answerable, pages}`.
3. **Check (code).** `_read_reply` (`query.py:121`) unwraps links that don't resolve
   and finds the cited sources. `pages` is reduced to pages the model was actually
   given.
4. **Retry once if needed.** An answer that cites no source, or spells out an
   abbreviation the pages don't, goes back to the model with the problem named
   (`_retry_prompt`, `query.py:130`). The retry lists the sources it may cite,
   taken from the shown pages (`_citable`, `query.py:113`), and includes its previous
   answer to repair. The retry replaces the first answer only if it's strictly better.
   A refusal is never retried, because a correct "not in the wiki" needs no citation.
5. **Final clean-up.** Expansions still in brackets are removed. What's left over is
   recorded in `result.unbacked`.

### 1.2 Filing (`file_answer`, `query.py:258`)

The answer becomes a `synthesis` page with a `question` field, its `sources`, and a
"Based on" section; then reindex, log and one commit, through a `Workspace` like
integrate (TD-23). It refuses when:

- the answer isn't an answer (`answerable` is false, or the call failed);
- it cites no source (TD-28);
- it holds an unbacked expansion;
- the vault has uncommitted changes (one commit = one operation);
- the same question was filed before;
- filing would add a lint error.

A refused filing doesn't lose the answer: `cmd_query` (`cli.py:221`) prints it,
then the reason, and exits with 2. `--json` returns it with `ok: false` and
`file_error`.

### 1.3 The expansion check (`expansions.py`, TD-29)

`find` (`expansions.py:64`) looks for three explicit forms and checks each against
the evidence, word for word and case-insensitive:

| Form | Example | What happens |
|---|---|---|
| `ABC (Long Name)` | `MMGIS (Mission Management Geospatial Interface)` | bracket removed |
| `Long Name (ABC)` | `The Data Archive and Retrieval (DAR)` | becomes `The DAR` |
| `ABC stands for Long Name` | | can't be cut from a sentence: reported, retried, blocks filing |

A bracket can hold anything, so `_plausible` (`expansions.py:47`) only treats
several words starting with the abbreviation's letter as an expansion. `MMGIS (2
tools)` is left alone. `_split_lead` (`expansions.py:54`) separates words in front
of the phrase, so `Uses Data Archive and Retrieval (DAR)` becomes `Uses DAR`.

In integration, `_strip_expansions` (`integrate.py:118`, called at `:292`) checks
every page the run touched, after patch and **before autolink**, because a link
would split the phrase ("[[concepts/mission|Mission]] Management…" is exactly how
one survived in the dev vault). Its evidence is the source text, the page's title
and aliases, **and the page's previous text**. That last part is what keeps the
rule "keep human-written text": whatever was in the vault before this run is left
alone. One place covers the summary, the claims and the patch text, so no stage
needs its own check.

### 1.4 `mneme-wiki status`

`overview` (`status.py:31`) was inside the MCP server. It's now shared, and
`cmd_status` (`cli.py:193`) prints it, because BR-12 says every operation exists in
both. It reports page counts, the last log entries, git state and inbox packets.

---

## 2. How to run it yourself

```powershell
mneme-wiki query "What does the Target Keeper do, and in which tool?" --vault examples/vault
mneme-wiki query "What does the Target Keeper do, and in which tool?" --vault examples/vault --file
mneme-wiki query "What is the launch mass of the rover?" --vault examples/vault --file   # refused
mneme-wiki status --vault examples/vault
```

Then look at `syntheses/` in Obsidian, or `git log -p` in the vault. Tests need
no model: `pytest tests/test_query.py tests/test_expansions.py`.

---

## 3. What happened

### 3.1 The first real run

The first version passed its tests against a fake model. Then the 11 questions ran
against all 3 vaults of 4 configurations: 132 calls, all valid, 3.4 seconds on
average, no invalid links, and the trick question ("launch mass") refused 12 of 12.
That looks fine until you read the answers.

**Citations were missing.** Of the answers the model called answerable, only 81 of
112 cited a source (72 %), though the prompt asks for it. Nothing in code enforced
it. An uncited answer could even be filed, with the front matter quietly filled from
the pages it used.

**Details were invented.** An answer said MMGIS is the "Mission Management Geospatial
Interface". The corpus has no such phrase. Tracing it led to the source pages, and
scanning all vaults showed the pattern:

| Abbreviation | `qwen3:14b` | `gemma3:12b` |
|---|---|---|
| DAR | Data Archive and Retrieval | Data Archive Repository |
| MMGIS | Mission Management Geospatial Interface System | Mission Management Geographic Information System; Mars Mission Geospatial Information System |
| ROCC | Rover Operations Control Center | Rover Operations and Communications Controller |

The sources never spell these out, and the models disagree with each other. Each
one invented a plausible expansion from general knowledge. **No check could see
it**: the sentence cites its source, so citation coverage stays at 100 %, lint is
clean, and the judge reads fluent text. Once written, later answers repeat it, since
query trusts the pages.

This is the case for running a real model before calling something done. The tests
were right about the code and silent about what the code was for.

### 3.2 After the fixes

A new `qwen3:14b` baseline (3 runs), integrated and queried with the fixes:

| | Before | After |
|---|---|---|
| Real answers citing a source | 79 % (22/28) | **100 % (30/30)** |
| Invented expansions per vault | 4.0 | **0.3** |
| Unbacked expansions in answers | not measured | **0** |
| Retries | – | 8 of 33 questions |
| Seconds per question | 3.4 | 3.7 |
| Wrong merges | 0 | 0 |
| Core merged (of 14) | 8.3 | 8.3 |
| Integration (min) | 15.2 | 14.7 |

The fix cost nothing measurable. The dev vault was cleaned by hand in one reviewable
commit, because the check deliberately leaves existing text alone.

### 3.3 Reading those numbers honestly

- **100 % means at least one source per answer, not one per fact.** A real answer
  about the DAR cited sources in the text but backed its bullets with links to entity
  pages.
- **"Answered" rose from 9.3 to 10 of 11, and that isn't an improvement.** The extra
  answers are the WISDOM question. The corpus mentions WISDOM only in passing and
  never says what it's for, so the earlier "not in the pages" was the honest answer,
  and the 3 of 3 answers now stretch thin evidence. An earlier note blamed extraction
  for this, which was wrong: the information isn't there.
- **The remaining 0.3 is one real case.** "The Rover Operations Control Centre,
  responsible for…" came from a first source with no abbreviation beside it, so the
  check couldn't see it. A second source added `(ROCC)`, and by then the phrase counted
  as earlier text.

### 3.4 Smaller things

- The check first missed `Uses Data Archive and Retrieval (DAR)`: the match began at
  "Uses", which failed the first-letter test. Found while reviewing the scan,
  fixed with a test before the new baseline ran.
- The new metric first counted a heading as part of the next line, because `plain()`
  flattens a page. It now counts line by line.
- Citation rate was first computed over all questions, so correct refusals counted
  against it. It now covers real answers only. All result folders were recomputed, so
  old and new values compare directly. The earlier 70 % for the baseline is 79 % on this
  definition.
- A rule against stray links ("visualising targets [[entities/mmgis|MMGIS]]") was added
  to the prompt. The new answers contain none, but they weren't counted before, so that
  proves little.

---

## 4. Decisions made in M5, and why

| Decision | Why | Rejected alternative |
|---|---|---|
| **One retry, naming the problem** (TD-28) | 8 extra calls of 33 took citations to 100 % | Prompt wording alone: it already asked. Adding citations in code: would attach sources to claims the model didn't take from them |
| **Uncited answers are shown, but never filed** | A filed page becomes input for later queries, so a weak answer would turn into a fact (BR-5) | Filling `sources` from the used pages, as the first version did: it looks cited and isn't |
| **Retry only if strictly better** | A retry can make things worse | Always taking the second answer |
| **Remove unbacked bracket expansions in code** | Deterministic, keeps the sentence, needs no model call (L-3) | Rejecting the whole edit: loses good claims over a parenthesis |
| **One check after patch, in integrate** | The scan found expansions on source *and* entity pages; one place covers every stage | One check per stage |
| **Existing text counts as evidence** | "Keep human-written text" outranks tidying; integrate must not edit what it didn't write | Checking whole pages: would rewrite human notes |
| **Word-for-word evidence** | Simple, explainable, testable | Fuzzy matching: "Centre" vs "Center" would pass, but so would near-misses |
| **Only explicit forms** | They can be detected reliably | Finding any phrase that might be an expansion: too many false positives |
| **`query` is one call** | L-2: one retrieval plus one answer | Multi-step retrieval |
| **Correct refusals excluded from the citation rate** | A refusal has nothing to cite | Counting all questions, which understated it |

---

## 5. Known gaps

- **Citations are per answer, not per fact.** `ensure_citations` does per-line
  citing in patch, but for query that would claim more than the model said.
- **No groundedness check.** Only abbreviations are checked. Other invented details
  pass; citing a source doesn't prove the source says it.
- **Over-answering.** The WISDOM case: no metric catches an answer stretched from thin
  evidence.
- **Bare phrases and page titles aren't checked**, for example the entity
  `ERCORover Command and Operations Centre`.
- **`stands for` during integration isn't caught.** It can't be removed in place, and
  only query acts on it.
- **Older vaults keep their expansions** until a person removes them, by design. There's
  no lint rule, because lint doesn't have the source text.
- **Exact-text evidence fails across spelling variants.** "Centre" and "Center" count as
  different, so a correct expansion can be removed. That loses a phrase, not a fact.
