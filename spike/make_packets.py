"""M0 spike: build source packets for bench/corpus/ from the mneme store.

Throwaway code. Reads ../mneme (registry.db + store/) read-only; never imports mneme.
Cleans docling artefacts that would waste model context:
  - drops `<!-- image -->` lines, unescapes HTML entities and `\\_`
  - blanks table cells that repeat the cell above (docling repeats merged cells per row)

Usage: python spike/make_packets.py
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
from pathlib import Path

MNEME = Path(__file__).resolve().parents[2] / "mneme"
CORPUS = Path(__file__).resolve().parents[1] / "bench" / "corpus"

# Integration order: glossary first (concept base), then use cases, then workshop notes.
DOCS = {
    "ROCC-DOC-1": "reference",
    "RFM-GIS-AD3": "reference",
    "RFM-GIS-WS1": "note",
}


def compact_tables(text: str) -> str:
    out: list[str] = []
    prev: list[str] | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            if re.fullmatch(r"\|[\s\-:|]+\|", s):
                out.append("|---" * (s.count("|") - 1) + "|")
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if prev is not None and len(prev) == len(cells):
                shown = ["" if c == p and c else c for c, p in zip(cells, prev)]
            else:
                shown = cells
            prev = cells
            out.append("| " + " | ".join(shown) + " |")
        else:
            prev = None
            out.append(line)
    return "\n".join(out)


def clean(text: str) -> str:
    text = "\n".join(l for l in text.splitlines() if l.strip() != "<!-- image -->")
    text = html.unescape(text).replace("\\_", "_")
    text = compact_tables(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def main() -> None:
    db = sqlite3.connect(MNEME / "registry.db")
    db.row_factory = sqlite3.Row
    for doc_id, source_type in DOCS.items():
        row = db.execute("select * from documents where doc_id = ?", (doc_id,)).fetchone()
        md_path = MNEME / row["markdown_path"]
        packet = CORPUS / doc_id.lower()
        packet.mkdir(parents=True, exist_ok=True)
        raw = md_path.read_text(encoding="utf-8")
        cleaned = clean(raw)
        (packet / "source.md").write_text(cleaned, encoding="utf-8")
        meta = {
            "title": " ".join(row["title"].split()),
            "source_type": source_type,
            "origin": f"mneme:{doc_id}",
            "date": row["ingested_at"][:10],
            "project": row["project"],
        }
        (packet / "source.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"{packet.name}: {len(raw.split())} -> {len(cleaned.split())} words, "
              f"{len(raw)} -> {len(cleaned)} chars")


if __name__ == "__main__":
    main()
