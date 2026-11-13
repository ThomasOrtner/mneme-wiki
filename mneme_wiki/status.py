"""Vault overview, shared by `mneme-wiki status` and the MCP `status` tool (BR-12)."""

from __future__ import annotations

import json
from collections import Counter

from . import config, glossary, ontology, rules
from .stages.source import find_existing
from .vault import Page, Vault


def pending_packets(v: Vault) -> list[dict]:
    """Packets in the inbox, and whether each is integrated yet."""
    inbox = config.inbox_dir(v.root)
    if not inbox.is_dir():
        return []
    out: list[dict] = []
    for d in sorted(p for p in inbox.iterdir() if (p / "source.meta.json").is_file()):
        try:
            meta = json.loads((d / "source.meta.json").read_bytes().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            out.append({"packet": d.name, "error": "source.meta.json is not valid JSON"})
            continue
        origin = str(meta.get("origin") or "")
        done = find_existing(v, origin) if origin else None
        out.append({"packet": d.name, "title": meta.get("title"), "integrated_as": done})
    return out


def overview(v: Vault) -> dict:
    types: Counter[str] = Counter()
    broken = 0
    for _, page in v.iter_pages():
        if isinstance(page, Page):
            types[str(page.meta.get("type") or "none")] += 1
        else:
            broken += 1
    log_text = v.read_text("log.md") if v.exists("log.md") else ""
    entries = [ln[3:] for ln in log_text.splitlines() if ln.startswith("## [")][-5:]
    head = v.git("log", "-1", "--format=%h %s").stdout.strip() if v.is_repo() else None
    gl = glossary.load(v)
    return {
        "vault": str(v.root),
        "pages": dict(sorted(types.items())),
        "unreadable_pages": broken,
        "glossary": {"active": bool(gl), "terms": len(gl.terms), "problems": len(gl.problems)},
        "rules": {"active": bool(r := rules.load(v)), "chars": len(r)},
        "ontology": {
            "active": bool(o := ontology.load(v)),
            "kinds": len(o.kinds),
            "scoped": len(o.scoped()),
        },
        "last_log_entries": entries,
        "git_head": head,
        "uncommitted_changes": (not v.is_clean()) if v.is_repo() else None,
        "inbox": str(config.inbox_dir(v.root)),
        "packets": pending_packets(v),
    }
