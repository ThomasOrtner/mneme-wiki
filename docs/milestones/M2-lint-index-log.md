# M2: Lint, index, log

**Question:** can code alone tell whether a vault is healthy, keep `index.md` in
step with the pages, record every operation in `log.md`, and find pages by
keyword?

**Short answer:** yes. `mneme-wiki lint` reports exactly the planted defects in
five fixture vaults, no more and no less. `reindex` rebuilds the index from the
pages and is a no-op when nothing changed. `append_log()` appends and never
rewrites. `search` puts the page *titled* with a term above pages that only
mention it, which took a second try (§3). There is still no model in the loop:
196 tests, all deterministic.

M3 builds on all of this. The integration pipeline finishes each run with
lint → reindex → log, and its resolve stage gets BM25 candidates from
`search.py`.

---

## 1. What was built

```
mneme_wiki/
  text.py        Markdown blocks with line numbers, plain text, lead sentence, tokens
  lint.py        8 deterministic checks → Finding(path, line, check, level, message)
  index_log.py   reindex(): regenerate index.md;  append_log(): one log entry
  search.py      per-field BM25 (title+aliases / lead / body)
  cli.py         + `lint`, `reindex`, `search` (each with --vault and --json)
  vault.py       init now renders index.md / log.md through index_log (one source)
tests/
  fixtures/*/expected.json     the exact lint findings for each fixture vault
  fixtures/lint-defects/       new: duplicate names, uncited claims, headings in code, front-matter links
  test_text.py  test_lint.py  test_index_log.py  test_search.py
```

Dependencies run one way: `text → links`; `lint`, `index_log`, `search →
text, links, frontmatter, vault`; `cli` calls all of them. Nothing in M2
writes outside `Vault.write_text()`.

### 1.1 Markdown blocks (`mneme_wiki/text.py`)

Three of the four features need the *structure* of a page body: lint has to know
what a "claim" is, the index needs the lead paragraph, and search wants plain
words without link syntax. TD-9 rules out a Markdown AST library, so
`blocks()` (`text.py:37`) is a small line scanner. It returns `Block(kind,
text, line, level)` for `heading`, `paragraph`, `list_item`, `table`,
`quote` (this includes Obsidian callouts), `code`, `embed`, `html` and `rule`,
each with its 1-based start line.

- A fenced code block runs to its closing fence, or to the end if there isn't
  one. That's the same rule `links.mask_code()` uses, so a `## Hidden` line
  inside code is never a heading.
- A list item takes its continuation lines with it, so a claim that wraps
  over two lines is one block.
- Anything unrecognised becomes `paragraph`. For lint that's the strict choice:
  unknown text still has to be cited.

`lead()` (`text.py:106`) is the first paragraph before the first H2.
`plain()` (`text.py:122`) turns Markdown into readable text: it drops
`([[sources/…]])` citations, uses the alias (or the de-hyphenated page name) as
a link's text, removes embeds, emphasis, inline-code ticks and list marks.
`first_sentence()` cuts at a sentence end followed by an upper-case letter, so
"e.g. lower case" doesn't end a sentence. `tokens()` gives casefolded `\w+`
words: Unicode-aware, no stemming, and `casefold()` maps `ß` to `ss`, so
*Größe* matches *GROSSE*.

### 1.2 Lint (`mneme_wiki/lint.py`)

`lint(vault)` (`lint.py:84`) goes over the vault in four passes and returns a
`Report` with the findings sorted by path and line:

1. **Front matter.** Each page from `vault.iter_pages()`: if parsing fails, that's
   one `frontmatter` error, with PyYAML's multi-line message cut to one line
   plus its position (`_one_line`, `lint.py:179`). No front matter at all is
   also an error. Otherwise every `frontmatter.validate()` issue becomes its own
   finding. Pages that fail to parse take no further part; pages with *invalid*
   but readable meta are still checked for links.
2. **Case collisions** come straight from `vault.case_collisions()`.
3. **Links and claims, per page.** Body links get the file line number:
   the body's offset (`body_line`, `lint.py:78`) plus the line within the
   body. Links inside the `sources:` / `contradicts:` lists in the front matter
   are checked too, and reported on line 1. A link with 0 candidates is a
   `broken-link`, 2+ is an `ambiguous-link`, and a `#heading` that isn't among
   the target's headings is a `missing-heading`. Headings are compared like
   names: casefolded, whitespace collapsed. Every resolved link from a
   non-navigation page records an inbound edge (`lint.py:143`). Then, on
   entity/concept/synthesis pages, every paragraph or list item with ≥ 8 words
   of plain text needs a link that resolves into `sources/` (`lint.py:153`).
4. **Names and orphans.** `links.alias_map()` over all content pages: any
   title/alias claimed by two pages is a `duplicate-name` error on *each* of
   them (`lint.py:158`), because whichever one you open, you need to see it.
   Finally, every source/entity/concept page without an inbound edge is an
   `orphan`.

Every check has a fixed level in `CHECKS` (`lint.py:27`):

| Level | Checks |
|---|---|
| error | `frontmatter`, `broken-link`, `duplicate-name`, `case-collision` |
| warning | `ambiguous-link`, `missing-heading`, `orphan`, `uncited` |

`mneme-wiki lint` exits 1 if there are errors, 0 if there are only warnings,
and 2 if the vault folder is missing (`cli.py:67`).

### 1.3 Index and log (`mneme_wiki/index_log.py`)

`reindex()` (`index_log.py:63`) reads every page whose front matter parses,
groups them by type in a fixed order (Sources, Entities, Concepts, Syntheses),
sorts each group by title, and renders one line per page (`index_line`,
`index_log.py:37`):

```
- [[concepts/activity-plan|Activity Plan]] — The commands the rover executes in one sol, made in the planning cycle.
```

The description is `first_sentence(plain(lead))`, capped at 100 characters.
The whole body is regenerated, but the front matter of `index.md` is kept: if
the new body equals the old one (newline style ignored), the function returns
`False` and touches nothing, not even `updated`. Otherwise it writes the
body and sets `updated` to today. The file keeps its CRLF or LF style
(`frontmatter.dump` handles that).

`init` now renders its empty index through the same `render_index_body([])`
(`vault.py:330`), so **reindexing a fresh vault is a byte-for-byte no-op**.
`test_reindex_on_fresh_vault_is_a_no_op` holds this in place.

`append_log(vault, op, title, lines)` (`index_log.py:106`) adds

```
## [2026-11-05] integrate | ROCC Glossary

- created: [[entities/rover-operations-control-centre]]
```

at the end of `log.md`, after one blank line. `op` must be a lower-case word
and `title` is collapsed to one line, so `grep '^## \['` always works (BR-7).
The old body is kept as it was; only the entry is added and `updated` is set.
If `log.md` is missing it's created. If its front matter is broken, the entry is
appended to the raw text and the broken block is left exactly as it was, so a
log write never fails or "repairs" a human's file.

`mneme-wiki reindex` calls both: reindex, and a `reindex | index` log entry only
if something changed.

### 1.4 Search (`mneme_wiki/search.py`)

`SearchIndex.from_vault()` builds a `Doc` per source/entity/concept/synthesis
page with three fields: names (title + aliases), lead, body. Each field gets its
own `rank_bm25` index, and a query's score is `3·names + 2·lead + 1·body`
(`search.py:112`). IDF is the Lucene form `log((N − n + 0.5)/(n + 0.5) + 1)`
(`_BM25._calc_idf`, `search.py:74`), which is never negative. `search()` takes
`types=` and `exclude=` filters; M3's resolve stage uses those to look for
candidates of one kind without the subject's own page. The index is built in
memory on every call. At ~500 pages that takes milliseconds, and it can't
go stale (TD-4).

---

## 2. How to run it yourself

```powershell
# lint the fixtures (exit code 1 = errors, 0 = clean or warnings only)
mneme-wiki lint --vault tests/fixtures/broken-links
mneme-wiki lint --vault tests/fixtures/lint-defects --json

# rebuild an index in a scratch copy and look at the result
Copy-Item -Recurse tests/fixtures/clean $env:TEMP/mw
mneme-wiki reindex --vault $env:TEMP/mw
Get-Content $env:TEMP/mw/index.md
mneme-wiki reindex --vault $env:TEMP/mw     # "already up to date"
Get-Content $env:TEMP/mw/log.md -Tail 4     # the reindex entry

# search
mneme-wiki search "planning cycle" --vault tests/fixtures/clean
mneme-wiki search TPC --type concept --vault tests/fixtures/clean --json
```

Expected output from the first command:

```
warning concepts/orphan.md:1  orphan  no other page links here
error   concepts/orphan.md:10  broken-link  [[nowhere]]: no page 'nowhere'
warning concepts/orphan.md:10  uncited  no source citation: 'Nothing links here, and it links to nowhere.'
error   entities/rocc.md:11  broken-link  [[concepts/missing-page|page that doesn't exist]]: ...
warning entities/rocc.md:12  ambiguous-link  [[overview]]: could be concepts/overview.md, sources/overview.md
warning entities/rocc.md:12  missing-heading  [[concepts/overview#No such heading]]: no heading 'No such heading'
failed 4 pages, 2 errors, 4 warnings
```

Leave out `--vault` and the commands use `WIKI_VAULT_DIR`.

To add a lint case: plant the defect in a fixture vault, run lint, check that
the new finding is the one you meant, and add `[check, path, line]` to that
vault's `expected.json`. `test_every_check_is_covered_by_a_fixture` fails if a
check has no planted case at all.

---

## 3. What happened: the bugs found on the way

**BM25 ranked the wrong page first (found by trying it).** The first version
followed the plan literally: one BM25 index, with title tokens repeated three
times and lead tokens twice. On the clean fixture, `search "planning cycle"`
returned *Who plans a sol?* above *Tactical Planning Cycle*. There were two
causes:

1. `rank_bm25.BM25Okapi` uses `log((N − n + 0.5)/(n + 0.5))`, which is negative
   for any term found in more than half the pages, and floors those terms to a
   small epsilon. In a 5-page vault, "planning" is such a term, so the IDF
   no longer separated anything.
2. Repeating tokens doesn't add much weight: BM25's term-frequency
   saturation (`k1 = 1.5`) flattens it, and the extra length then penalises the
   page through length normalisation. The synthesis is very short and mentions
   the concept by name, so it won.

Switching to the Lucene IDF alone was not enough (0.317 vs 0.310, still wrong).
Scoring each field separately fixed it: in the *names* field "planning" occurs
in one title only, so its IDF there is high (8.3 vs 4.0). This is recorded as
TD-22. `test_title_match_ranks_first` covers it.

**Multi-line edits silently missed CRLF files (dev tooling, not the package).**
`docs/plan.md` and `AGENTS.md` are checked out with CRLF (`core.autocrlf=true`).
A script that replaced multi-line LF strings found no match and changed
nothing, without any error. Edits now assert that the match count is 1. This is
the same lesson as M1's newline-translation bug: on this machine, never assume
`\n`.

**Test expectations, not bugs.** `casefold()` turns `ß` into `ss`; that's
intended, so the test now expects `grösse`. A query meant to match nothing
matched "this" in a source page's "Pages updated from this source" heading. A
real-vault reminder that BM25 has no stop words; harmless, because every common
word gets a low IDF.

**A clean result double-checked.** Lint found *zero* issues on the 107-page vault the
M0 spike wrote (`spike/out/v3-nothink/vault`). A clean result can also mean a
check never ran, so I counted: 405 blocks qualified as claims, and all of them
cite a source. The spike's validator enforced exactly that rule, so the result
is believable.

---

## 4. Decisions made in M2, and why

| Decision | Why | Rejected alternative |
|---|---|---|
| **Uncited claim = paragraph/list item ≥ 8 words without a `sources/` link; warning** | Matches how pages are written ("each fact line cited") without an LLM; 8 words lets navigation lines ("See [[#Activity Plan]] above.") through | Sentence-level checking: needs a sentence splitter that works for German and English and would flag every multi-sentence paragraph with one citation at the end. Making it an error: a heuristic shouldn't block commits |
| **Callouts, quotes, tables, code exempt** | Callouts hold contradictions and notes whose claims are cited inside the quoted text or are meta; tables are often link indexes | Checking them: lots of false positives on the fixture's link tables |
| **Errors vs warnings as in §1.2** | Errors break later operations (a broken link becomes an invented page, a duplicate name breaks resolve); warnings are things a human may want | Everything an error: the M1 fixtures alone would never pass; `windows-hostile` has only human-made orphans |
| **Ambiguous bare links are warnings** (left open in M1) | Obsidian resolves them (nearest file), so they work for the reader; they're still worth fixing | Error: would flag links that work in Obsidian |
| **Index/log links don't count as inbound; syntheses are never orphans** | After `reindex`, every page is linked from the index, which would make the orphan check useless; syntheses are filed answers reached through the index | Counting every link |
| **`duplicate-name` reported on each page involved** | You see it whichever page you open | One finding per name |
| **Front-matter link lists (`sources`, `contradicts`) are link-checked** | A broken `sources:` entry is a broken citation (found on line 1) | Only body links |
| **Index description = first sentence of the lead, ≤ 100 chars** | Every page already has a lead that stands alone (WIKI.md rule), so no new field to keep in sync | A `summary:` front-matter key: one more thing the LLM has to maintain and validate |
| **`index.md` regenerated in full, front matter kept, untouched if unchanged** | Derived data can't drift; no churn in `updated` or git | Patching lines in place: harder, and the template already says "don't edit by hand" |
| **`init` and `reindex` share one renderer** | A fresh vault is already "reindexed"; no two templates to keep alike | Keeping `init`'s own string |
| **Log: append-only, title collapsed to one line, op = lower-case word** | Keeps `grep '^## \['` reliable (BR-7) | Free-form entries |
| **Broken `log.md` front matter: append to the raw text** | Logging must never fail or rewrite a human's file | Refusing to log, or regenerating the header |
| **No git in M2** | Commits belong to operations (`integrate`, `query --file`); a bare `reindex` leaves a normal working-tree diff | Committing in `reindex`: the M3 integrate run would then make two commits |
| **Per-field BM25 + Lucene IDF** (TD-22) | See §3 | Token repetition in one index (plan's first idea); `BM25Plus` (still one field) |
| **Search index rebuilt per call, no cache** | ms at MVP scale; nothing to invalidate (TD-4) | A pickled index in `.mneme-wiki/` |
| **No stemming, casefold only** | Vaults mix English and German (TD-17); a wrong stemmer is worse than none | Snowball stemmer per language: needs language detection per page |
| **`--vault` on every vault command, folder only has to exist** | Fixtures have no `WIKI.md`; one flag works the same everywhere | Requiring `WIKI.md` |

---

## 5. Known gaps

- **Uncited-claim check is a heuristic.** A paragraph with three facts and one
  citation passes; a 7-word uncited fact passes too. Sentence-level checking is
  part of the deferred LLM lint.
- **No check that a page's type matches its folder** (an `entity` under
  `concepts/`). It's cheap to add; it wasn't in the M2 list.
- **Heading anchors are matched by text,** not by Obsidian's exact anchor rules
  (which ignore some punctuation). Rare in practice; it shows up as a warning, never
  as an error.
- **Case collisions have no fixture** (NTFS can't hold two names that differ
  only in case); covered by a test that fakes the file list.
- **Lint doesn't check `index.md` against the pages.** `reindex` makes that
  unnecessary, and M3 runs it after every integration.
- **BM25 has no stop words**, so very common words get low IDF instead of being
  dropped. Fine for ranking, but they can produce weak matches (§3).
