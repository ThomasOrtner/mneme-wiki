# Source Packets

← [Home](Home.md)

A source packet is the **only input contract** between a producer (mneme, a script, you)
and mneme-wiki. It is a folder in the vault's inbox:

```
inbox/<packet-name>/
  source.md            required: the content, already Markdown
  source.meta.json     required: metadata (below)
  summary.md           optional: upstream summary (saves one model call)
  toc.json             optional: section structure (not used yet)
```

## source.meta.json

| Key | Required | Example |
|---|---|---|
| `title` | yes | `"RFM GIS Workshop 1"` |
| `source_type` | yes | `"reference"`, `"talk"`, `"article"`, `"note"` |
| `origin` | yes | `"mneme:RFM-GIS-WS1"`, a URL, or `"manual"` |
| `date` | yes | `"2026-11-02"` (when it was ingested upstream) |
| `author` | no | `"Jane Doe"` |
| `published` | no | `"2024"` |
| `language` | no | `"de"` |

`origin` identifies the source: `integrate` refuses a packet whose `origin` is already
in the vault, so a source is never integrated twice.

## Writing source.md

- Plain Markdown. Use headings: the text is chunked at headings, and the heading a chunk
  starts under becomes the **locator** of every claim from that chunk.
- Remove noise before it reaches the wiki: repeated table cells, image placeholders,
  HTML entities. A cleaner source means fewer, better model calls.
- Any language: the `source` page keeps it, all other pages are written in
  `WIKI_LANGUAGE`.
- At most 2 MB.

## From mneme

```powershell
mneme-export-wiki-packet <doc_id> [<doc_id> ...] --inbox D:\wikis\inbox
```

The exporter (in the mneme repo) maps the registry metadata, sets
`origin = mneme:<doc_id>`, copies the summary and ToC, and cleans the Markdown (compact
tables, drop `<!-- image -->`, unescape entities). See the
[M7 tutorial](../milestones/M7-mneme-exporter.md).

## Integrating

```powershell
mneme-wiki status                       # lists inbox packets and whether each is integrated
mneme-wiki integrate <packet-name>      # name inside the inbox, or any folder path
mneme-wiki integrate a b c              # several, one commit each; stops at the first failure
```

Next: [Integration Pipeline](Integration-Pipeline.md).
