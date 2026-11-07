# M7: mneme exporter

**Question:** can mneme hand its processed documents to the wiki without the two
projects depending on each other's code?

**Short answer:** yes. `mneme-export-wiki-packet <doc_id>… --inbox <path>` (in
the mneme repo, merged as PR #15, `1e3fecd`) writes
one source packet per document: the contract from TD-8, nothing more. On the
three corpus documents its output is identical to the M0 prototype
(`spike/make_packets.py`) apart from line endings, which the wiki normalises
anyway. Neither repo imports the other: mneme writes a folder, mneme-wiki reads
one.

---

## 1. What was built (in `../mneme`)

```
export_wiki_packet.py            the exporter (standalone script, like export_talk_note.py)
tests/test_export_wiki_packet.py table compaction, cleaning, metadata, files, overwrite guard
pyproject.toml                   + script mneme-export-wiki-packet, + module in py-modules
CLAUDE.md                        file map row
```

### 1.1 What a packet contains

```
<inbox>/<doc_id lower-case>/
  source.md          document.md (or transcript.md for talks), cleaned
  source.meta.json   title, source_type, origin "mneme:<doc_id>", date,
                     + author, published, language, project, url when known
  summary.md         store/<doc_id>/summary.md, if it exists and isn't empty
  toc.json           the document's ToC sidecar, if it isn't empty
```

`packet_meta()` (`export_wiki_packet.py:100`) maps the registry row:

- `doc_type` → `source_type` (`REF` → `reference`, `Talk` → `talk`, `notes` →
  `note`, …; anything unknown is lower-cased);
- `ingested_at` → `date`;
- for talks, the `metadata` JSON gives `author` (speaker, else channel),
  `published` (year), `language` and `url`.

`origin` is `mneme:<doc_id>`, which is what the wiki's "already integrated?"
check (TD-24) keys on.

### 1.2 Cleaning (`clean`, `:89`)

These are the rules M0 measured, which cut AD3 from 20 KB to 6.4 KB:

1. `compact_tables` (`:66`): a table cell that equals the cell above it in the
   same column is blanked. Docling repeats merged cells on every row, so a use
   case's title and user story appeared ~30 times. Only rows with the same
   column count are compared, and a new table starts fresh.
2. `<!-- image -->` placeholder lines are dropped.
3. HTML entities (`&amp;`, `&lt;`) and the `\_` escape are undone.
4. Runs of blank lines are collapsed.

Files are written as bytes (`_write`, `:165`): no newline translation on
Windows. That's the M1 lesson again, from the other side.

### 1.3 Safety

- The registry and the store are only read. The packet is a new folder.
- An existing packet folder is never overwritten silently: `--force` replaces it.
- An unknown `doc_id` is reported, and the other ids are still exported (exit 1).

---

## 2. How to run it yourself

```powershell
cd C:\_REPOS\mneme
mneme-export-wiki-packet ROCC-DOC-1 RFM-GIS-AD3 RFM-GIS-WS1 --inbox C:\_REPOS\mneme-wiki\examples\inbox

cd C:\_REPOS\mneme-wiki
mneme-wiki integrate rocc-doc-1 --vault examples/vault --dry-run   # a packet name in the inbox
```

Output per document: the files written and the shrinkage, e.g.
`rfm-gis-ad3: source.md, source.meta.json (1936 -> 1131 words, 20127 -> 6440 chars)`.

Tests (mneme's venv has no pytest; the exporter only needs `python-dotenv`):
`..\mneme-wiki\.venv\Scripts\python -m pytest tests/test_export_wiki_packet.py`.

---

## 3. What happened

The three corpus documents, exported and compared with the M0 packets in
`bench/corpus/`:

| Document | Words raw → packet | Chars raw → packet | vs M0 packet |
|---|---|---|---|
| ROCC-DOC-1 | 2864 → 2807 | 21968 → 21326 | identical text (LF instead of CRLF) |
| RFM-GIS-AD3 | 1936 → 1131 | 20127 → 6440 | identical text |
| RFM-GIS-WS1 | 3036 → 3028 | 23542 → 17381 | identical text |

Two intended differences:

- **Line endings:** the prototype wrote text mode (CRLF on Windows); the
  exporter writes LF. The wiki's packet loader reads either.
- **WS1's `source_type`** is now `reference`, taken from the registry (`REF`),
  where M0 had labelled it `note` by hand. The registry is mneme's source of
  truth; if the label is wrong, it should be fixed there.

---

## 4. Decisions made in M7, and why

| Decision | Why | Rejected alternative |
|---|---|---|
| **Exporter lives in mneme, as a standalone script** | Cleaning belongs upstream (M0 decision); mneme already has this pattern (`export_talk_note.py`) | A mneme-wiki importer reading mneme's store (couples the wiki to mneme's internals, TD-8) |
| **Packet folder = `doc_id` lower-cased** | Same names as the M0 corpus; no case collisions on NTFS | The doc_id as is |
| **Refuse to overwrite without `--force`** | A packet in the inbox may already have been edited by hand | Always overwrite |
| **`origin = mneme:<doc_id>`** | Stable, unique, and what the wiki's re-integration guard uses | The file path (changes when the store moves) |
| **Copy `summary.md` and `toc.json` only if non-empty** | An empty file would tell the wiki "there is a summary" | Always copy |
| **Work on a branch, merged by PR** | mneme is a separate project with its own review | Committing to its `main` |

---

## 5. Known gaps

- **mneme's venv has no pytest**; the tests ran with mneme-wiki's interpreter.
- **`toc.json` isn't used by the wiki yet** (planned for citation locators).
- **No MCP tool in mneme for the export**; an agent can only call it through a
  shell.
- **Talk transcripts go through as they are**: timestamps like `## [00:12:30]`
  become chunk locators in the wiki, which is useful, but long talks are many
  chunks (and many extract calls).
