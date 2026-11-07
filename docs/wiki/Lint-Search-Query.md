# Lint, Search and Query

← [Home](Home.md)

## Lint

```powershell
mneme-wiki lint          # exit 0 = no errors, 1 = errors
mneme-wiki lint --json
```

Deterministic checks, no model involved:

| Check | Level | Finds |
|---|---|---|
| `broken-link` | error | `[[links]]` (body or front-matter lists) to pages that don't exist |
| `frontmatter` | error | Missing, unparsable or invalid front matter (required keys, types, `status` values) |
| `duplicate-name` | error | Two pages with the same title or alias |
| `case-collision` | error | Paths that differ only by case (break on Windows/macOS) |
| `orphan` | warning | Content pages nothing links to |
| `uncited` | warning | A paragraph or list item of ≥ 8 words in an entity/concept/synthesis page with no link to `sources/` |
| `ambiguous-link` | warning | A bare `[[name]]` that matches several pages |
| `missing-heading` | warning | `[[page#Heading]]` where the heading doesn't exist |

Headings, callouts, quotes, tables and code are exempt from `uncited`, as are `source`,
`index` and `log` pages.

## Index

```powershell
mneme-wiki reindex
```

Regenerates `index.md`: every page by type, one line each:
`[[path|Title]] — <first sentence of the lead>`. Integration and filed queries do this
automatically.

## Search

```powershell
mneme-wiki search "activity plan"
mneme-wiki search "activity plan" --type concept --type entity --limit 5 --json
```

BM25 with three fields weighted separately: title + aliases (×3), lead (×2), body (×1).
A page *titled* with your term ranks above a page that merely mentions it. The index is
built in memory per call; there is nothing to rebuild.

## Query

```powershell
mneme-wiki query "Who operates the rover on Mars?"
mneme-wiki query "Who operates the rover on Mars?" --file
```

1. Search and `index.md` pick the most relevant pages that fit the token budget.
2. The `query` model answers **only from those pages**, citing them as `[[links]]`.
3. Code checks that every cited page exists.
4. An answer that cites no source, or spells out an abbreviation the pages don't, gets
   one retry naming the problem. If it is still uncited or unbacked, it is shown with a
   warning and is **never filed**.
5. With `--file`, a good answer is saved as `syntheses/<slug>.md` (with a `question`
   field), the index is rebuilt, `log.md` gets an entry, and the vault gets one commit.

Filed syntheses are pages like any other: later queries can use them, so the wiki gets
better at the questions you actually ask.

If the pages don't contain the answer, the model says so instead of guessing.
