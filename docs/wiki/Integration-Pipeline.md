# Integration Pipeline

← [Home](Home.md) · Full design: [plan.md → Integration stages](https://github.com/ThomasOrtner/mneme-wiki/blob/main/docs/archive/mvp-plan.md#integration-stages),
walkthrough with code references: [M3 tutorial](https://github.com/ThomasOrtner/mneme-wiki/blob/main/docs/milestones/M3-integrate.md).

`mneme-wiki integrate <packet>` turns one source packet into one git commit. Code
orchestrates; the model only makes small, checkable decisions.

| # | Stage | Who | What happens |
|---|---|---|---|
| 1 | **Source page** | code (+ LLM if no `summary.md`) | Writes `sources/<slug>.md` with metadata and summary. |
| 2 | **Chunk** | code | Splits `source.md` at headings into chunks of ≤ 500 words. The heading is the chunk's locator. |
| 3 | **Extract** | LLM, per chunk | Lists subjects (name, entity or concept, aliases, description, claims), ≤ 15 per chunk. Schema-constrained JSON. |
| 4 | **Merge** | code | Unions subjects of the same source with the same normalised **name**. A shared alias isn't enough: models list related names (a mission's rover, a sibling camera) as aliases, so those go to resolve's yes/no check. |
| 5 | **Resolve** | code + LLM | Is this subject an existing page? The subject's **name** matching a page's title or alias is an exact match. A match only through the subject's (model-made) aliases is not: that page becomes the first candidate. Neither is a name that looks like a document-local id (`WP2`, `D3`, `MS1`: 1–4 capitals and a number) matching a page from another source: work packages of two projects share such names. Then ≤ 4 candidates (alias matches, name shape, BM25), one **yes/no question per candidate**, with thinking. Every decision is logged with its reason. Finally, an alias that is another page's title or alias is dropped (`alias_conflict_dropped` in the run report). |
| 5b | **Names** | code | A **new** page title and every **new** alias must appear word for word in the source (title or text) or among the names of pages that existed before the run (case, hyphens, punctuation and a plural "s" ignored). One exception: an owner name in front of a backed name, "Project Alpha WP2" where the source only says "WP2" (extract is told to qualify local ids that way). The owner must itself be a name: an existing page, a backed subject of this source, or the start of the source's title. Models invent names, e.g. an acronym glued to a made-up expansion ("UPCUplink Processing Centre" where the source only says "UPC"). An unbacked alias is dropped (`alias_unbacked_dropped`); an unbacked title is replaced by the subject's first backed alias (`title_unbacked_replaced`); a subject with no backed name is skipped and listed under *Skipped subjects* in the run report (`subject_unbacked_skipped`). A new subject named like the source itself is skipped too: the source page is its page (`subject_is_source_skipped`). Every change is in `names.json` in the run folder. |
| 6 | **Plan** | code | Groups claims by target page, picks paths for new pages. Document-local ids: if a new page's title would be a bare id like `D1` that another page already has (resolve decided they differ), the source's title goes in front ("Project Beta Proposal D1", `local_id_title_qualified`). On a title that names an owner before the id ("Project Alpha WP2"), the alias `WP2` becomes `PA-WP2` if the owner has a short name like `PA`, otherwise it is dropped (`local_id_alias_qualified` / `local_id_alias_dropped`). Elsewhere `M20`-shaped names are left alone: they can be global names (a mission acronym). |
| 7 | **Patch** | LLM, one call per page | Gets the page, its new claims and the pages it may link to; returns a new lead and per-section `append`/`replace` operations. |
| 8 | **Validate & apply** | code | Links only to known pages; every fact cited (missing citations are added and counted); `replace` may only reword lines citing this source, may not drop links or shrink below 60 %; escaped newlines repaired. One retry, then the edit is **rejected** to `inbox/rejected/` with the reason. |
| 9 | **Abbreviations** | code | Removes `ABC (Long Name)` expansions that neither the source nor the page as it was before the run backs up (models invent them). A new page's own title and aliases are no evidence. |
| 10 | **Autolink** | code | Turns the first plain mention of another page's title or alias into a link. |
| 11 | **Finish** | code | Source page lists touched pages; `index.md`, `log.md`; lint; git commit; run report. |

## With a project

A packet can declare the project it belongs to (`project` in `source.meta.json`, or
`integrate --project`). Then extract is told the project, and before merge code renames
every subject whose name is a bare document-local id (`WP2`, `D3`: 1-4 capitals and a
number) to "<project> <id>" (`local_id_project_expanded`). Resolve finds the page the
project's other sources made by exact match, the names check accepts the project's
name as an owner, and plan uses the project's short name for the `PA-WP2` alias. If the names check has to fall back from an unbacked title to a bare local id ("Project Alpha Deliverable D2" where the text says "D2"), the title becomes "Project Alpha D2".
Without a project nothing changes.

## With a glossary

If the vault has a [`glossary.md`](Vault-Format.md#glossarymd), these stages read it;
without one they behave exactly as described above.

| Stage | What the glossary changes |
|---|---|
| Extract | Terms the chunk mentions are listed first among the known names, as `Full name (aka Term)` |
| Merge | Before merging, a subject named by a term or full name (or with one as alias) takes the full name as its name and the row's names as *curated* aliases (`glossary_matched`); `Kind` sets entity/concept for a new page. So "ROCC" and "Rover Operations Control Centre" of one source become one subject |
| Resolve | Curated names count for the exact match (no model call), also against an existing page titled with the short form |
| Names | The glossary's names are evidence, like the names of existing pages |
| Plan / patch | A page the run touches gets its row's names as aliases; the patch prompt's linkable pages show the `Prefer` form |
| Abbreviations | `Term (Full name)` from the glossary is evidence: a correct expansion stays, a wrong one is removed |
| Autolink | A row's names link to the one page that carries any of them; `Prefer` sets the link text (`[[…\|ROCC]]`) |

## How pages get linked

A link is an Obsidian wikilink to a page's slug path, e.g.
`[[concepts/activity-plan|activity plan]]` (see [Vault Format](Vault-Format.md)). The
pipeline has **no relationship stage**: extract lists subjects and claims, not relations
between subjects. Page A links to page B only because B is *mentioned* in A's text. Links
enter a page in five ways:

| # | Where | Who | What it adds |
|---|---|---|---|
| 1 | New page skeleton (patch) | code | The lead ends with a citation `([[sources/x]])`; the source goes into `sources:` in the front matter. |
| 2 | Patch | LLM | Links the model writes itself, but only to ids from the **Linkable pages** list in its prompt. |
| 3 | Validate & apply | code | A fact line without a citation gets `([[sources/x]])` appended. |
| 4 | Autolink | code | The first plain mention of another page's title or alias becomes a link. Most links come from here. |
| 5 | Finish | code | The source page's section *Pages updated from this source* links every page the run wrote. |

### The Linkable pages list (patch)

Each patch call shows the model up to 40 pages it may link to:

1. every other page planned in this run (new or updated), then
2. existing pages that BM25 finds for the page's title plus its new claims.

The prompt tells the model to use only these ids and never invent links. The model
doesn't have to link anything; autolink covers mentions it leaves plain.

### What validation does with links

- A link whose target doesn't resolve to **exactly one** page (existing or planned in
  this run) is unwrapped back to plain text (its alias, or the slug with spaces). It is
  counted as `patch_invalid_link_removed` under *Validation counters* in the run report. Validation checks that the target
  exists, not that it was on the Linkable list.
- A `replace` that drops a link or citation the section had is rejected, and the old
  section is kept.
- A `replace` may only reword lines that cite the source being integrated (and no other
  source). Every other line, citing another source or nothing (human text), must come
  back with the same words and at least the same citations; formatting may change (a
  reflow is fine), and such lines are written back exactly as they were. Otherwise the
  `replace` is rejected (`patch_replace_rejected_protected_lines`) and the model is asked
  once more: "lines citing other sources must stay as they are; use append". A new source
  that disagrees adds its own line next to the old one; it never rewrites the old claim.
- A new lead that loses a link of the old lead is discarded, and the old lead is kept.
- A lead that cites another source (or nothing) may only be extended: the new lead must
  contain the old one word for word. A rewrite is rejected
  (`patch_lead_rejected_protected`), retried once, and the old lead stays.
- A final check on the whole page rejects the edit if any link target of the old body
  is missing from the new one (no silent data loss).

### Autolink rules

Autolink runs after the abbreviation check, on the pages written in this run and on the
source page. For each page it looks for the names (title and aliases) of all entity and
concept pages, and links the first match:

- **Prose only:** paragraphs and list items. Never headings, tables, quotes/callouts,
  code, existing wikilinks, Markdown links or URLs.
- **One link per target per page**, and none if the page already links there.
- **Longest names first**, so "Integrated Activity Plan" wins over "Activity Plan".
- Names of **≤ 5 characters match case-sensitively** (`TIME` is not `time`); longer
  names ignore case. Names under 3 characters are never linked.
- A name that **two pages share** is skipped as ambiguous (lint reports it as
  `duplicate-name`).
- A page never links to itself. Only entity and concept pages are targets; source and
  synthesis pages are not.

Why code and not the model: in M0, code linking gave about 2 links per page, the model
without thinking 0.16 (TD-19).

### Links in both directions

When a source creates or updates page B:

- B links to the source (citation, `sources:`), and the source links back to B (5).
- Pages written **in the same run** that mention B get linked to it (2, 4).
- **Older pages that mention B are not linked in this run.** Autolink only edits pages
  the run wrote, so each run's diff stays its own. An older page gets the link only when
  a later source updates it. B is never an `orphan` (its source links to it), but in
  Obsidian's backlinks and graph it looks less connected than the text suggests.

### Seeing what happened

The run report (below) counts `autolinks`, the validation counters and rejected edits
with their reasons. `--dry-run` shows the exact links each page would get.

## All or nothing

Every stage writes into an in-memory overlay of the vault. Only when all stages ran and
lint shows no *new* errors is the overlay written to disk and committed. A failed run
leaves the vault untouched. `--dry-run` prints the overlay's diff instead.

`integrate` refuses to start when:

- the vault has uncommitted changes (one commit = one source), or
- a source with the same `origin` is already in the vault.

## Looking inside a stage

Each stage can be run on its own; nothing is written to the vault:

```powershell
mneme-wiki integrate my-packet --stage extract --out extract.json
mneme-wiki integrate my-packet --stage resolve --out resolve.json
```

Stages: `chunk`, `extract`, `resolve`, `plan`, `patch`.

## Run reports

Each run writes `.mneme-wiki/runs/<run-id>/report.md` in the vault: chunks, subjects,
matched vs new, pages created/updated, rejected edits, skipped subjects, per-stage call stats (latency,
tokens, retries), the most-connected pages. `--json` returns the same data.

## Speed

On `qwen3:14b`, three related sources took about 15 minutes in total (roughly 100 model
calls per source). Every call is bounded by `MAX_OUTPUT_TOKENS` and `CALL_TIMEOUT_S`; a
cut-off answer counts as failed and is retried once.
