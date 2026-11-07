# Integration Pipeline

← [Home](Home.md) · Full design: [plan.md → Integration stages](../plan.md#integration-stages),
walkthrough with code references: [M3 tutorial](../milestones/M3-integrate.md).

`mneme-wiki integrate <packet>` turns one source packet into one git commit. Code
orchestrates; the model only makes small, checkable decisions.

| # | Stage | Who | What happens |
|---|---|---|---|
| 1 | **Source page** | code (+ LLM if no `summary.md`) | Writes `sources/<slug>.md` with metadata and summary. |
| 2 | **Chunk** | code | Splits `source.md` at headings into chunks of ≤ 500 words. The heading is the chunk's locator. |
| 3 | **Extract** | LLM, per chunk | Lists subjects (name, entity or concept, aliases, description, claims), ≤ 15 per chunk. Schema-constrained JSON. |
| 4 | **Merge** | code | Unions subjects of the same source by normalised name/alias. |
| 5 | **Resolve** | code + LLM | Is this subject an existing page? Exact name/alias first; otherwise ≤ 4 candidates (name shape, then BM25), one **yes/no question per candidate**, with thinking. Every decision is logged with its reason. |
| 6 | **Plan** | code | Groups claims by target page, picks paths for new pages. |
| 7 | **Patch** | LLM, one call per page | Gets the page, its new claims and the pages it may link to; returns a new lead and per-section `append`/`replace` operations. |
| 8 | **Validate & apply** | code | Links only to known pages; every fact cited (missing citations are added and counted); `replace` may not drop links or shrink below 60 %; escaped newlines repaired. One retry, then the edit is **rejected** to `inbox/rejected/` with the reason. |
| 9 | **Abbreviations** | code | Removes `ABC (Long Name)` expansions that neither the source nor the page backs up (models invent them). |
| 10 | **Autolink** | code | Turns the first plain mention of another page's title or alias into a link. |
| 11 | **Finish** | code | Source page lists touched pages; `index.md`, `log.md`; lint; git commit; run report. |

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
matched vs new, pages created/updated, rejected edits, per-stage call stats (latency,
tokens, retries), the most-connected pages. `--json` returns the same data.

## Speed

On `qwen3:14b`, three related sources took about 15 minutes in total (roughly 100 model
calls per source). Every call is bounded by `MAX_OUTPUT_TOKENS` and `CALL_TIMEOUT_S`; a
cut-off answer counts as failed and is retried once.
