# Vault Format

← [Home](Home.md) · The authoritative description of a vault is its own `WIKI.md`
(template: `mneme_wiki/templates/WIKI.md`).

## Layout

```
D:\wikis\
  space-ops\              the vault (a git repo; open it in Obsidian)
    WIKI.md               schema + rules for whoever writes content
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
