"""M0 spike: score a spike vault against bench/corpus/gold.json.

Usage: python spike/eval.py <label> [<label> ...]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from spike import LINK_RE, load_vault, norm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GOLD = json.loads((ROOT / "bench" / "corpus" / "gold.json").read_text(encoding="utf-8"))


def evaluate(label: str) -> dict:
    out = ROOT / "spike" / "out" / label
    vault = out / "vault"
    pages = load_vault(vault)
    wiki = {p: pg for p, pg in pages.items() if pg.fm.get("type") in ("entity", "concept")}
    names = {p: {norm(n) for n in [pg.title, *pg.fm.get("aliases", [])]} for p, pg in wiki.items()}

    # gold coverage: which vault pages carry any of a gold entry's names
    found, dup, missing, cross_ok, cross_n = [], [], [], 0, 0
    for g in GOLD["pages"]:
        keys = {norm(n) for n in g["names"]}
        hits = [p for p, ns in names.items() if ns & keys]
        # prefer pages whose title matches; alias-only hits still count as found
        if not hits:
            missing.append(g["title"])
        elif len(hits) > 1:
            dup.append(f"{g['title']}: {hits}")
            found.append(g["title"])
        else:
            found.append(g["title"])
        if g["core"]:
            cross_n += 1
            srcs = {s for h in hits for s in wiki[h].fm.get("sources", [])} if hits else set()
            if len(hits) == 1 and len(srcs) >= 2:
                cross_ok += 1

    # wrongly merged pairs
    merged = []
    for a, b in GOLD["must_not_merge"]:
        for p, ns in names.items():
            if norm(a) in ns and norm(b) in ns:
                merged.append(f"{a} + {b} -> {p}")

    # structure
    all_paths = set(pages)
    broken, link_counts, inbound = [], [], Counter()
    fact_lines = cited = 0
    for p, pg in pages.items():
        links = [m.group(1).strip() for m in LINK_RE.finditer(pg.body)]
        for t in links:
            if t not in all_paths:
                broken.append(f"{p} -> {t}")
            elif t != p:
                inbound[t] += 1
        if p in wiki:
            link_counts.append(len({t for t in links if not t.startswith("sources/")}))
            for line in pg.body.splitlines():
                s = line.strip()
                if s and not s.startswith(("#", "|", ">")):
                    fact_lines += 1
                    cited += "[[sources/" in s
    orphans = [p for p in wiki if inbound[p] == 0]
    multi_src = sum(len(pg.fm.get("sources", [])) >= 2 for pg in wiki.values())

    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8")) if (out / "metrics.json").exists() else {}
    return {
        "label": label,
        "pages_total": len(pages), "entity_concept_pages": len(wiki),
        "pages_with_2plus_sources": multi_src,
        "gold_found": f"{len(found)}/{len(GOLD['pages'])}",
        "gold_core_merged_across_sources": f"{cross_ok}/{cross_n}",
        "gold_duplicates": dup, "gold_missing": missing, "wrong_merges": merged,
        "broken_links": len(broken), "broken_examples": broken[:5],
        "orphans": len(orphans),
        "mean_wiki_links_per_page": round(sum(link_counts) / max(len(link_counts), 1), 2),
        "citation_coverage": round(cited / max(fact_lines, 1), 3),
        "timings_s": metrics.get("timings_s"), "counters": metrics.get("counters"),
        "roles": metrics.get("roles"),
    }


if __name__ == "__main__":
    for label in sys.argv[1:]:
        print(json.dumps(evaluate(label), indent=2, ensure_ascii=False))
