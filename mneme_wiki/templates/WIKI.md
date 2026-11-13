---
title: Wiki schema
schema_version: 1
language: {{language}}
---

# Wiki schema

This file is the contract for this vault, for humans and for an assistant that
writes wiki content over MCP. The mneme-wiki pipeline itself reads only the
`## Domain rules` section below (its other stages follow fixed rules in code and
prompts). Change it deliberately, and log the change in `log.md` as a `schema` entry.

## What this wiki is

A persistent, interlinked set of Markdown notes. Knowledge is **integrated once**,
when a source arrives: the source updates the pages it touches, instead of being
re-read on every question. Pages are written for a human reading in Obsidian.

## Layout

| Path | Contains |
|---|---|
| `sources/` | one page per ingested source: summary, metadata, what it touched |
| `entities/` | one specific named thing that exists once (a person, system, mission, organisation, document) |
| `concepts/` | a type, idea or method with many instances (a planning cycle, a target, a file format) |
| `syntheses/` | answers to questions, filed back from queries |
| `attachments/` | images and other files linked from pages |
| `index.md` | every page, one line each, by type. Generated: don't edit by hand |
| `log.md` | append-only record of every operation |
| `glossary.md` | optional: curated abbreviations and names (`Term \| Full name \| Kind \| Prefer \| Definition`). Code reads it; edit it deliberately and log a `schema` entry |

File names are the kebab-case slug of the title (`Rover Operations Control
Centre` → `entities/rover-operations-control-centre.md`). Never rename or delete
a page yourself; that is a gated operation.

## Front matter

```yaml
---
title: Retrieval-Augmented Generation   # required
type: concept          # required: source | entity | concept | synthesis | index | log
aliases: [RAG]         # other names; used to find and link the page
tags: [llm, retrieval]
created: 2026-11-02    # required on content pages
updated: 2026-11-02    # required on content pages
sources: ["[[sources/karpathy-llm-wiki]]"]   # every source that fed this page
status: active         # active | stub | stale | contested
---
```

Extra fields by type:

- `source`: `source_type` (required), `origin` (required: `mneme:<doc_id>`, a URL,
  or `manual`), `author`, `published`, `ingested`, `language`.
- `entity`: `entity_kind` (required: person, system, organisation, mission, …).
- `synthesis`: `question` (required): the question this page answers.
- any page: `contradicts: ["[[page]]"]` when it disagrees with another page.

Keep fields you don't recognise; humans and other tools may have added them.

## Page body

1. `# <title>` as the only H1.
2. A **lead paragraph** that makes sense on its own: what this is, in two or
   three sentences.
3. Sections (`##`) by topic. Prefer the subject's own structure over the
   structure of whichever source mentioned it.
4. Links mostly in the prose: `[[entities/rover-operations-control-centre|ROCC]]`.
   Link only to pages that exist.

## Rules for writing

- **Language:** `source` pages keep the language of the source. Every other page
  is written in **{{language}}**.
- **Cite every claim.** Each fact carries an inline citation to the source page
  it came from: `The ROCC is located in Turin ([[sources/rocc-glossary]]).`
  An uncited claim is a lint finding.
- **Integrate, don't append.** A new source updates the pages it touches and
  creates the ones that are missing, with links in both directions: the page
  cites the source, and the source page lists the pages it updated.
- **Never drop content.** Rewrites keep existing claims, citations and links.
  Text written by a human stays as it is.
- **Contradictions are marked, never resolved silently.** Keep both claims with
  their citations, add a callout, set `status: contested`, and log it:

  ```markdown
  > [!warning] Contradiction
  > [[sources/a]] says the cycle is 24 h; [[sources/b]] says 48 h.
  ```

- **One thing, one page.** Before creating a page, check titles and `aliases`
  of existing pages. A part, a subtype, a step or a tool *related to* something
  is a different thing and gets its own page.
- **Stubs are fine.** A page with only one or two claims gets `status: stub`.

## Domain rules

<!--
Everything in this section outside HTML comments is sent to the model that decides
what becomes a page (extract) and what is the same thing (resolve), with every one
of those calls. Write short bullets in plain language and stay under 1,500
characters (`lint` warns above). Names and abbreviations belong in glossary.md.
Examples:

- Sections every proposal has ("Gender aspects", "Budget table") are template
  structure, not subjects.
- 'AP' means 'Activity Plan', never 'work package'.
- A rover and its mission are different things.
-->

## Log format

Every operation appends one entry to `log.md`; never edit old entries.

```markdown
## [2026-11-02] integrate | ROCC Glossary

- created: [[entities/rocc]], [[concepts/tactical-planning-cycle]]
- updated: [[entities/mmgis]]
```

Operations: `init`, `integrate`, `query`, `lint`, `reindex`, `schema`, `edit`.
Find entries with `grep '^## \[' log.md`.
