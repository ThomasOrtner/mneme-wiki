# Vault Format

← [Home](Home.md) · The authoritative description of a vault is its own `WIKI.md`
(template: `mneme_wiki/templates/WIKI.md`).

## Layout

```
D:\wikis\
  space-ops\              the vault (a git repo; open it in Obsidian)
    WIKI.md               schema + rules for whoever writes content
    glossary.md           optional: curated abbreviations and names that code reads
    index.md              generated: every page by type, one line each
    log.md                append-only operation log
    sources\  entities\  concepts\  syntheses\  attachments\
    .mneme-wiki\runs\     run reports (git-ignored)
  inbox\                  source packets waiting to be integrated
    rejected\             edits the validator refused, with reasons
```

The inbox defaults to `<vault>/../inbox`; set `WIKI_INBOX_DIR` to put it elsewhere.

## File names and links

File names are kebab-case slugs of the title, safe on Windows:
`Rover Operations Control Centre` → `entities/rover-operations-control-centre.md`.

Links are Obsidian wikilinks to the slug path, optionally with an alias or heading:

```markdown
[[entities/rover-operations-control-centre|ROCC]]
[[concepts/activity-plan#Inputs]]
```

How `integrate` decides which links a page gets: [Integration Pipeline → How pages get
linked](Integration-Pipeline.md#how-pages-get-linked).

## Front matter

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

Extra fields by type:

| Type | Fields |
|---|---|
| `source` | `source_type` (required), `origin` (required: `mneme:<doc_id>`, URL or `manual`), `author`, `published`, `ingested`, `language` |
| `entity` | `entity_kind` (required: person, system, organisation, mission, …) |
| `synthesis` | `question` (required) |
| any | `contradicts: ["[[page]]"]` |

### `status`

`status` is a label for readers. It is **not a review gate**: integrate, search, query,
the index and MCP don't act on it, and lint only checks that the value is one of the four.

| Value | Meaning | Who sets it |
|---|---|---|
| `stub` | Thin page, few claims | `integrate`, when it creates an entity/concept page from ≤ 2 claims |
| `active` | Normal page | `integrate` for larger new pages, source pages and filed query answers |
| `contested` | Holds a marked contradiction | You, when you add a `> [!warning] Contradiction` callout (not detected automatically yet) |
| `stale` | Outdated | You (planned for a later LLM lint) |

Integrate sets `status` only when it **creates** a page and never changes it afterwards,
so a page that started as a `stub` stays one even after later sources add to it
(tracked in [#19](https://github.com/ThomasOrtner/mneme-wiki/issues/19)).

### `entity_kind`

Every `entity` page needs an `entity_kind`. Concept pages don't have one. An entity is
one specific, named thing that exists once; a concept is a type, process or term that
can have many instances.

`integrate` uses a fixed list:

`person` · `organisation` · `team` · `role` · `project` · `mission` · `system` ·
`software` · `instrument` · `place` · `document` · `other`

- **Set by the extract model,** limited to this list by the JSON schema; anything else
  becomes `other`. When a source mentions a subject several times, a specific kind wins
  over `other`.
- **Written only when the page is created.** Later sources don't change it; correct it by
  hand if it's wrong.
- **Nothing acts on it yet.** Resolve, search, query, the index and `status` ignore it.
  Lint only checks that the field exists, so a kind you add by hand (e.g.
  `entity_kind: spacecraft`) is accepted.

There is no CLI command or MCP tool that lists pages by kind yet
([#20](https://github.com/ThomasOrtner/mneme-wiki/issues/20)). In Obsidian, the
[Dataview](https://github.com/blacksmithgu/obsidian-dataview) plugin gives you the
overview:

````markdown
```dataview
TABLE rows.file.link AS Pages, length(rows) AS Count
FROM "entities"
GROUP BY entity_kind
```
````

Unknown keys are kept. A file whose front matter didn't change stays **byte-identical**
(key order, comments, line endings, BOM), so diffs only show real edits.

## Page body

```markdown
# Rover Operations Control Centre

The Rover Operations Control Centre (ROCC) runs surface operations for the rover
([[sources/rocc-glossary]]).

## Location

The ROCC is located in Turin ([[sources/rocc-glossary]]).

> [!warning] Contradiction
> [[sources/old-brochure]] places it in Rome.
```

1. One H1, equal to the title.
2. A **lead paragraph** that makes sense on its own (it becomes the `index.md` line).
3. `##` sections by topic.
4. Inline citations on every claim; links mostly in the prose.

## Domain rules in WIKI.md

`WIKI.md` describes the vault for humans and for an assistant working over MCP. The
pipeline reads one part of it: an optional `## Domain rules` section (#14). Its text,
without HTML comments, is appended to the system prompt of **extract** (what becomes
a page) and **resolve** (what is the same thing) under the heading "Rules for this
vault". Patch doesn't get it.

```markdown
## Domain rules

- Sections every proposal has ("Gender aspects", "Budget table") are template
  structure, not subjects.
- 'AP' means 'Activity Plan', never 'work package'.
```

- Short bullets in plain language. They are sent with every extract and resolve call
  (about 120 per source), so `lint` warns above 1,500 characters (`rules-too-long`).
- Free text only: names and abbreviations belong in `glossary.md`, kinds and
  relations in the ontology (#16).
- A new vault's section holds only a commented example, so it is inactive. Without
  the section, every prompt is exactly as before.
- Each run records a short hash of the rules it used (`report.md`, `rules_hash`), so
  you can tell which runs ran under which rules.
- Change it deliberately, commit it, and log a `schema` entry in `log.md`.

## glossary.md

An optional, curated list of abbreviations and names that are known to mean one thing
in this vault (#24). Like `WIKI.md` it is a vault file, not a wiki page: no front
matter, not in `index.md`. The pipeline reads one Markdown table with these columns
(more tables with the same header are read too; everything else in the file is free
text):

```markdown
| Term | Full name | Kind | Prefer | Definition |
|---|---|---|---|---|
| ROCC | Rover Operations Control Centre | organisation | short | Centre that operates the rover. |
| TPC | Tactical Planning Cycle | concept | full | The daily planning loop. |
```

| Column | Meaning |
|---|---|
| `Term` | the short form, usually the abbreviation. A cell may be a link, `[[entities/rocc\|ROCC]]`; its text counts |
| `Full name` | the long form; a page created for the term gets it as title (and slug) |
| `Kind` | `concept`, `entity`, or an `entity_kind` (`organisation`, `system`, …). Sets the kind of a **new** page; for an existing page a mismatch is a lint warning. Empty = whatever extract says |
| `Prefer` | `short` or `full`: the form links show (`[[entities/rover-operations-control-centre\|ROCC]]`). Empty = as the text has it |
| `Definition` | context for the model only; it never becomes page text (it isn't a source) |

What it changes:

- **No pages by itself.** A page is created only when a source mentions a term, so
  every claim still cites a source.
- A subject named by a term or full name (or with one as alias) goes to the term's page
  by exact match, with no model call: "ROCC" and "Rover Operations Control Centre" in one
  source become one page. Curated names are trusted; model-made aliases are still
  checked.
- A page a run touches gets its row's names as aliases, also pages made before the
  glossary existed.
- The names check and the abbreviation check accept the glossary's names and
  expansions; a wrong expansion is still removed.
- Lint: `glossary-format` (a row it can't use), `glossary-conflict` (a name in two rows,
  or on a page whose title isn't in the row), `glossary-kind`, and `duplicate-name` for
  two pages the glossary says are one thing (merge them by hand, #6).

Change it deliberately, commit it, and log it as a `schema` entry in `log.md`. Without
`glossary.md` nothing changes.

## Editing by hand

You can edit any page in Obsidian. The pipeline edits pages **section by section**:
sections it doesn't touch stay exactly as you wrote them. Commit your edits before
the next `integrate`; it refuses a vault with uncommitted changes.

Don't edit `index.md` (run `mneme-wiki reindex`) or past `log.md` entries.

## log.md

Every operation appends a greppable entry:

```markdown
## [2026-11-07] integrate | RFM GIS Workshop 1
```
