# Concepts

← [Home](Home.md)

## Compile once, read many times

RAG answers each question by finding raw text chunks and making the model re-derive
the answer from them, every time. Nothing is learned between questions, and facts spread
over several documents are never brought together.

A **compiled wiki** does the work when a source arrives: the facts are written into
pages about the things they describe (an entity page for the rover control centre, a
concept page for "activity plan"), merged with what earlier sources said, and linked.
A question then reads a few well-organised pages instead of a pile of chunks. The idea
comes from Andrej Karpathy's "LLM wiki" note.

## Three layers

| Layer | Where | Who changes it |
|---|---|---|
| Raw sources | upstream store, `sources/` pages | Nobody, once filed |
| Wiki pages | the rest of the vault | The LLM pipeline writes; you may edit |
| Schema | `WIKI.md` | You and the LLM, deliberately, logged |

## Page types

| Type | Folder | Holds |
|---|---|---|
| `source` | `sources/` | One page per ingested source: summary, metadata, the pages it touched. Keeps the source's language. |
| `entity` | `entities/` | One specific thing that exists once: a person, system, organisation, mission, document. |
| `concept` | `concepts/` | A type, idea or method with many instances. |
| `synthesis` | `syntheses/` | An answer to a question, filed back from `query --file`. |
| `index` | `index.md` | Every page, by type, one line each. Generated. |
| `log` | `log.md` | Append-only record of every operation. |

## Rules the pipeline enforces

- **Integrate, don't append.** A source updates existing pages and creates missing ones,
  with links in both directions.
- **Cite every claim.** Facts carry `([[sources/x]])`. An uncited claim is a lint finding.
- **Never drop content.** An edit that loses links or shrinks a section too much is rejected.
- **Contradictions are marked, never resolved silently**, as a `> [!warning] Contradiction`
  callout, and logged.
- **Every change is a git diff.** One commit per integrated source or filed answer.
  Delete, merge and rename are not automated.

## Why "the model proposes, code decides"

Local 14B models produce broken JSON, invent links and forget content. So the model is
only asked small questions: *which subjects appear in this chunk?*, *are these two the
same thing?*, *what should this one page say now?* Code does everything else: chunking,
candidate search, planning, validating links and citations, linking mentions, writing
files and committing. See [Integration Pipeline](Integration-Pipeline.md).

## mneme and mneme-wiki

mneme converts, transcribes and summarises
documents. mneme-wiki never imports its code: mneme writes a folder (a
[source packet](Source-Packets.md)), mneme-wiki reads it. Any other producer can do
the same.

## Many vaults

Each vault is self-contained with its own `WIKI.md`, inbox and git history, so separate
domains stay separate. Pick one with `WIKI_VAULT_DIR` or `--vault`.
