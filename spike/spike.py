"""M0 feasibility spike: staged integration of source packets on a local model.

Throwaway code - not production, no tests. Answers: can qwen3:14b drive
extract -> resolve -> plan -> patch -> validate/apply well enough?

Usage:
    python spike/spike.py [--model qwen3:14b] [--label NAME] [--no-think] [packet ...]

Defaults to all packets in bench/corpus/ in a fixed order. Writes to
spike/out/<label>/ : vault/ (git repo, one commit per source), calls.jsonl,
<packet>.extract.json, <packet>.plan.json, metrics.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import ollama
import yaml
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "bench" / "corpus"
ORDER = ["rocc-doc-1", "rfm-gis-ad3", "rfm-gis-ws1"]
TODAY = dt.date.today().isoformat()

CHUNK_WORDS = 500  # smoke run: 900-word chunks hit the per-chunk subject cap and dropped concepts
NUM_CTX = 16384

# ---------------------------------------------------------------------------
# LLM call with metrics
# ---------------------------------------------------------------------------


@dataclass
class Run:
    model: str
    out: Path
    think_patch: bool
    calls: list[dict] = field(default_factory=list)
    counters: dict = field(default_factory=lambda: defaultdict(int))
    client: ollama.Client = field(default_factory=lambda: ollama.Client(host="http://localhost:11434"))
    step: str = ""  # current progress label, set by the stage loops
    t_start: float = field(default_factory=time.time)
    per_source: dict = field(default_factory=dict)

    def say(self, msg: str) -> None:
        el = int(time.time() - self.t_start)
        print(f"[{el // 60:02d}:{el % 60:02d}] {msg}", flush=True)

    def llm(self, role: str, system: str, user: str, schema: dict, think: bool = False):
        """Schema-constrained call; one retry on invalid JSON. Returns parsed dict or None."""
        for attempt in (1, 2):
            t0 = time.time()
            try:
                r = self.client.chat(
                    model=self.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    format=schema,
                    think=think,
                    options={"num_ctx": NUM_CTX, "temperature": 0.2},
                )
                text = r.message.content or ""
                err = None
            except Exception as e:  # noqa: BLE001 - spike
                r, text, err = None, "", repr(e)
            latency = time.time() - t0
            data = None
            if err is None:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    err = f"json: {e}"
            rec = {
                "role": role, "attempt": attempt, "latency_s": round(latency, 2),
                "prompt_tokens": getattr(r, "prompt_eval_count", None) if r else None,
                "out_tokens": getattr(r, "eval_count", None) if r else None,
                "thinking_chars": len(getattr(r.message, "thinking", "") or "") if r else 0,
                "json_ok": data is not None, "error": err,
            }
            self.calls.append(rec)
            rec["step"] = self.step
            with (self.out / "calls.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            status = "ok " if data is not None else ("RETRY" if attempt == 1 else "FAIL")
            self.say(f"  {self.step:<55.55} {status} {latency:5.1f}s "
                     f"{rec['prompt_tokens'] or 0:>5}→{rec['out_tokens'] or 0:<5} tok")
            if data is not None:
                return data
        return None


# ---------------------------------------------------------------------------
# Names, slugs, pages
# ---------------------------------------------------------------------------


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s[:-1] if s.endswith("s") and len(s) > 4 else s  # crude plural folding


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "untitled"


FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.S)
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")


@dataclass
class Page:
    path: str  # vault-relative without .md, e.g. "concepts/activity-plan"
    fm: dict
    body: str

    @property
    def title(self) -> str:
        return self.fm.get("title", self.path)

    def render(self) -> str:
        return "---\n" + yaml.safe_dump(self.fm, sort_keys=False, allow_unicode=True) + "---\n\n" + self.body.strip() + "\n"


def load_vault(vault: Path) -> dict[str, Page]:
    pages = {}
    for p in vault.rglob("*.md"):
        rel = p.relative_to(vault).with_suffix("").as_posix()
        if rel in ("index", "log", "WIKI") or rel.startswith(".git"):
            continue
        text = p.read_text(encoding="utf-8")
        m = FM_RE.match(text)
        fm = yaml.safe_load(m.group(1)) if m else {}
        pages[rel] = Page(rel, fm or {}, text[m.end():] if m else text)
    return pages


def save_page(vault: Path, page: Page) -> None:
    p = vault / (page.path + ".md")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(page.render(), encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk(text: str) -> list[tuple[str, str]]:
    """Split on headings, pack into <= CHUNK_WORDS. Returns [(locator, text)]."""
    sections: list[tuple[str, list[str]]] = [("start", [])]
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            sections.append((m.group(1).strip(), [line]))
        else:
            sections[-1][1].append(line)
    chunks: list[tuple[str, str]] = []
    cur_loc, cur, cur_words = None, [], 0
    for loc, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        w = len(body.split())
        if cur and cur_words + w > CHUNK_WORDS:
            chunks.append((cur_loc, "\n\n".join(cur)))
            cur_loc, cur, cur_words = None, [], 0
        if w > CHUNK_WORDS:  # split oversize section by paragraphs
            buf, bw = [], 0
            for para in body.split("\n\n"):
                pw = len(para.split())
                if buf and bw + pw > CHUNK_WORDS:
                    chunks.append((loc, "\n\n".join(buf)))
                    buf, bw = [], 0
                buf.append(para)
                bw += pw
            if buf:
                cur_loc, cur, cur_words = loc, buf, bw
            continue
        cur_loc = cur_loc or loc
        cur.append(body)
        cur_words += w
    if cur:
        chunks.append((cur_loc, "\n\n".join(cur)))
    return chunks


# ---------------------------------------------------------------------------
# Stage 1: extract
# ---------------------------------------------------------------------------

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "subjects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["entity", "concept"]},
                    "entity_kind": {"type": "string", "enum": [
                        "person", "org", "team", "role", "project", "mission", "system",
                        "software", "instrument", "place", "document", "other"]},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                    "claims": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "kind", "entity_kind", "aliases", "description", "claims"],
            },
        }
    },
    "required": ["subjects"],
}

EXTRACT_SYSTEM = """You extract knowledge from one chunk of a document, for a personal wiki.

Return the important subjects the chunk says something substantive about:
- entities: people, organisations, teams, roles, projects, missions, systems, software tools, instruments, places, documents
- concepts: ideas, methods, processes, data types, terms

For each subject:
- name: the canonical full name (e.g. "Rover Operations Control Centre" rather than "ROCC") if the full form is given in the text or the known-pages list; otherwise the name as written. If the subject matches a known wiki page, use exactly that page's title.
- aliases: abbreviations and other spellings used for it.
- description: one neutral sentence saying what it is.
- claims: 1-6 self-contained factual statements from the chunk about this subject. Each claim must be understandable on its own (no "it", "this"), at most 35 words, and must be supported by the chunk.

entity vs concept:
- entity = one specific, named thing that exists once: a person, a team, an organisation, a mission, a software system, an instrument, a place. Set entity_kind accordingly (never "other" if one of the kinds fits).
- concept = a type, category, process, method, data type or term that can have many instances (e.g. "Activity Plan", "Target", "Waypoint", "Tactical Planning Cycle"). entity_kind "other".

Only subjects that deserve their own wiki page. Field names, attribute values, enumeration values, file names, examples and individual plan steps are NOT subjects: put them as claims on their parent subject (e.g. the field "Load_Status" is a claim about "Integrated Plan"; POWER/TIME/DATA VOLUME are claims about "Planning Resources").

Rules: use only information in the chunk. Skip passing mentions, URLs, file names, coordinates, shell commands, phone numbers. At most 15 subjects; cover every subject the chunk defines or explains."""


def stage_extract(run: Run, packet: str, meta: dict, text: str, known: dict[str, Page]) -> list[dict]:
    known_list = "\n".join(
        f"- {p.title}" + (f" (aka {', '.join(p.fm.get('aliases', []))})" if p.fm.get("aliases") else "")
        for p in known.values() if p.fm.get("type") in ("entity", "concept")
    )[:6000]
    subjects = []
    chunks = chunk(text)
    for i, (loc, body) in enumerate(chunks):
        run.step = f"extract {i + 1}/{len(chunks)} {loc}"
        user = (f"Document: {meta['title']} ({meta['source_type']})\nSection: {loc}\n\n"
                f"Known wiki pages:\n{known_list or '(none yet)'}\n\n--- CHUNK ---\n{body}\n--- END ---")
        data = run.llm("extract", EXTRACT_SYSTEM, user, EXTRACT_SCHEMA)
        if data is None:
            run.counters["extract_chunk_failed"] += 1
            continue
        for s in data.get("subjects", []):
            s["locator"] = loc
            s["chunk"] = i
            subjects.append(s)
    return subjects


# ---------------------------------------------------------------------------
# Stage 2: resolve
# ---------------------------------------------------------------------------

# v3: pairwise yes/no with thinking. v1 (pick-one, strict) never merged; v2 (pick-one, loose)
# merged related-but-different things. spike/resolve_bench.py: pairwise+think P=1.0 R=0.9.
RESOLVE_SCHEMA = {"type": "object", "properties": {"reason": {"type": "string"}, "same": {"type": "boolean"}},
                  "required": ["reason", "same"]}

RESOLVE_SYSTEM = """Decide whether two wiki subjects are the SAME thing, i.e. one page would describe both.
Same: the same thing under another name, abbreviation, short form, spelling, or plural.
Different: a part, a subtype, an instance, a step, a related tool, a role related to it, or something it is used with.
Examples: "Local Target" vs "Target" -> different (subtype). "dar_ci" vs "DAR" -> different (tool for it).
"AP" vs "Activity Plan" -> same (abbreviation). "Tactical Planning" vs "Tactical Planning Cycle" -> same (short form).
Give a short reason first, then the answer."""
RESOLVE_MAX_CANDIDATES = 4


def initials(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", re.sub(r"\(.*?\)", " ", name))
             if w.lower() not in ("of", "and", "the", "for", "to", "in")]
    return "".join(w[0] for w in words).lower() if len(words) >= 2 else ""


def merge_within_source(subjects: list[dict]) -> list[dict]:
    """Union subjects from different chunks by any shared normalised name/alias."""
    groups: list[dict] = []
    key_to_group: dict[str, int] = {}
    for s in subjects:
        keys = {norm(n) for n in [s["name"], *s.get("aliases", [])] if norm(n)}
        hit = next((key_to_group[k] for k in keys if k in key_to_group), None)
        if hit is None:
            groups.append({**s, "claims": [(c, s["locator"]) for c in s["claims"]],
                           "aliases": list(dict.fromkeys(s.get("aliases", [])))})
            hit = len(groups) - 1
        else:
            g = groups[hit]
            g["claims"] += [(c, s["locator"]) for c in s["claims"]]
            g["aliases"] = list(dict.fromkeys(g["aliases"] + s.get("aliases", []) + [s["name"]]))
        for k in keys:
            key_to_group[k] = hit
    for g in groups:
        g["aliases"] = [a for a in g["aliases"] if norm(a) != norm(g["name"])]
    return groups


def stage_resolve(run: Run, groups: list[dict], pages: dict[str, Page]) -> list[dict]:
    """Resolve each subject to an existing page, an earlier subject of the same source, or new.

    Candidates = existing entity/concept pages + subjects of this source already resolved as new.
    1. exact normalised name/alias match (code)
    2. candidate retrieval (code): BM25 over names+description, plus name-shape candidates
       (one name contains the other, or one is the initialism of the other)
    3. the model picks one candidate or "none"
    Subjects merged into an earlier subject of the same source are folded into it and dropped.
    """
    # candidate pool: id -> (title, aliases, description)
    pool: dict[str, tuple[str, list[str], str]] = {
        path: (p.title, p.fm.get("aliases", []), p.fm.get("description", ""))
        for path, p in pages.items() if p.fm.get("type") in ("entity", "concept")}
    key_to_id: dict[str, str] = {}
    for cid, (t, al, _) in pool.items():
        for n in [t, *al]:
            key_to_id.setdefault(norm(n), cid)
    kept: list[dict] = []
    new_by_id: dict[str, dict] = {}

    def add_new(g: dict) -> None:
        cid = f"new:{len(new_by_id)}"
        g["target"], g["resolved_by"], g["_cid"] = None, "new", cid
        new_by_id[cid] = g
        pool[cid] = (g["name"], g["aliases"], g["description"])
        for n in [g["name"], *g["aliases"]]:
            key_to_id.setdefault(norm(n), cid)
        kept.append(g)

    def fold(g: dict, cid: str, how: str) -> None:
        if cid.startswith("new:"):  # same thing as an earlier subject of this source
            t = new_by_id[cid]
            t["claims"] += g["claims"]
            t["aliases"] = list(dict.fromkeys(t["aliases"] + g["aliases"] + [g["name"]]))
            for n in [g["name"], *g["aliases"]]:
                key_to_id.setdefault(norm(n), cid)
            run.counters[f"resolve_{how}_within_source"] += 1
        else:
            g["target"], g["resolved_by"] = cid, how
            kept.append(g)
            run.counters[f"resolve_{how}"] += 1

    for g in groups:
        names = [g["name"], *g["aliases"]]
        keys = [norm(n) for n in names if norm(n)]
        exact = next((key_to_id[k] for k in keys if k in key_to_id), None)
        if exact:
            fold(g, exact, "exact")
            continue
        # candidate retrieval: name-shape candidates first (strong signal), then BM25
        ids = list(pool)
        cands: list[str] = []
        my_inits = {initials(n) for n in names} - {""}
        for cid in ids:
            their = [pool[cid][0], *pool[cid][1]]
            tk = {norm(n) for n in their if norm(n)}
            shape = any((len(a) >= 3 and len(b) >= 3 and (a in b or b in a)) for a in keys for b in tk)
            shape |= bool(my_inits & set(tk)) or bool({initials(n) for n in their} - {""} & set(keys))
            if shape:
                cands.append(cid)
        if ids:
            corpus = [re.findall(r"\w+", (pool[i][0] + " " + " ".join(pool[i][1]) + " " + pool[i][2]).lower())
                      for i in ids]
            scores = BM25Okapi(corpus).get_scores(re.findall(r"\w+", " ".join(names).lower()))
            cands += [ids[i] for i in sorted(range(len(ids)), key=lambda i: -scores[i])[:4]
                      if scores[i] > 0.5 and ids[i] not in cands]
        cands = cands[:RESOLVE_MAX_CANDIDATES]
        decision = {"name": g["name"], "aliases": g["aliases"], "candidates": [pool[c][0] for c in cands],
                    "answer": "new", "checks": []}
        matched = None
        for c in cands:  # pairwise, first "same" wins
            user = (f"A: {g['name']} (aliases: {g['aliases']})\n   {g['description']}\n"
                    f"B: {pool[c][0]} (aliases: {pool[c][1]})\n   {pool[c][2]}\n\nAre A and B the same thing?")
            run.step = f"resolve '{g['name']}' vs '{pool[c][0]}'"
            data = run.llm("resolve", RESOLVE_SYSTEM, user, RESOLVE_SCHEMA, think=True)
            run.counters["resolve_llm_calls"] += 1
            same = bool((data or {}).get("same"))
            decision["checks"].append({"candidate": pool[c][0], "same": same, "reason": (data or {}).get("reason", "")})
            if same:
                matched = c
                break
        if matched:
            decision["answer"] = pool[matched][0]
            run.say(f"    → same as '{pool[matched][0]}'")
            fold(g, matched, "llm")
        else:
            add_new(g)
        with (run.out / "resolve_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(decision, ensure_ascii=False) + "\n")
    for g in kept:
        g.pop("_cid", None)
        g["aliases"] = [a for a in g["aliases"] if norm(a) != norm(g["name"])]
    return kept


# ---------------------------------------------------------------------------
# Stage 3: plan (code only)
# ---------------------------------------------------------------------------


def stage_plan(groups: list[dict], pages: dict[str, Page]) -> dict[str, dict]:
    """Group claims by target page; assign paths for new pages."""
    plan: dict[str, dict] = {}
    for g in groups:
        if not g["claims"]:
            continue
        if g["target"]:
            path = g["target"]
        else:
            folder = "entities" if g["kind"] == "entity" else "concepts"
            path = f"{folder}/{slugify(g['name'])}"
            while path in pages and path not in plan:  # slug collision with unrelated page
                path += "-2"
        e = plan.setdefault(path, {"path": path, "new": path not in pages, "name": g["name"],
                                   "kind": g["kind"], "entity_kind": g.get("entity_kind", "other"),
                                   "aliases": [], "description": g["description"], "claims": []})
        e["aliases"] = list(dict.fromkeys(e["aliases"] + g["aliases"] + ([g["name"]] if path in pages else [])))
        e["claims"] += g["claims"]
    return plan


# ---------------------------------------------------------------------------
# Stage 4: patch, Stage 5: validate & apply
# ---------------------------------------------------------------------------

PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "lead": {"type": "string"},
        "ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "op": {"type": "string", "enum": ["append", "replace"]},
                    "text": {"type": "string"},
                },
                "required": ["section", "op", "text"],
            },
        },
    },
    "required": ["lead", "ops"],
}

PATCH_SYSTEM = """You maintain one page of a personal Markdown wiki (Obsidian style).
You get the current page and new claims from a source. Integrate the new claims into the page.

Output JSON:
- lead: the page's lead paragraph (1-3 sentences, defines the subject, stands alone). Keep the current lead if it is still right; improve it only if the new claims add something essential.
- ops: edits to sections (headings level 2, without the "## "). op "append" adds text to the end of a section (the section is created if missing). op "replace" rewrites a whole section; it must keep every fact, citation and link already in that section.

Rules:
- Every bullet or paragraph you write that states a fact ends with its citation, exactly: ([[{source}]])
- Link other pages only with [[id|Title]] using ids from the "Linkable pages" list. Never invent other links.
- Do not repeat facts already on the page, and do not repeat the lead in the sections. Prefer short bullet points, one per line. Group facts into sensible sections (e.g. Overview, Role in operations, Requirements, Open questions).
- Use only the given claims; add nothing from your own knowledge.
- Write in English."""


def section_map(body: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Split body into (h1, lead, [(section_name, section_text)])."""
    lines = body.strip().splitlines()
    h1 = lines[0] if lines and lines[0].startswith("# ") else ""
    rest = "\n".join(lines[1:] if h1 else lines)
    parts = re.split(r"(?m)^## +(.+)$", rest)
    lead = parts[0].strip()
    secs = [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts), 2)]
    return h1, lead, secs


def build_body(h1: str, lead: str, secs: list[tuple[str, str]]) -> str:
    out = [h1, "", lead]
    for name, text in secs:
        out += ["", f"## {name}", "", text]
    return "\n".join(out).strip() + "\n"


def tokens(text: str, rx: re.Pattern) -> set[str]:
    return {m.group(1).strip() for m in rx.finditer(text)}


def fix_links(text: str, allowed: set[str], run: Run) -> str:
    def repl(m: re.Match) -> str:
        target = m.group(1).strip()
        if target in allowed or target.startswith("sources/"):
            return m.group(0)
        run.counters["patch_invalid_link_removed"] += 1
        return m.group(2) or target.split("/")[-1].replace("-", " ")
    return LINK_RE.sub(repl, text)


def ensure_citations(text: str, src_link: str, run: Run) -> str:
    out = []
    for block in text.split("\n"):
        b = block.rstrip()
        is_fact = bool(re.match(r"^\s*([-*]|\d+\.)\s+\S", b)) or (b and not b.startswith(("#", ">", "|")))
        if is_fact and "[[sources/" not in b:
            run.counters["patch_missing_citation_added"] += 1
            b = f"{b} ({src_link})"
        elif is_fact:
            run.counters["patch_cited_lines"] += 1
        out.append(b)
    return "\n".join(out)


def stage_patch_apply(run: Run, plan: dict[str, dict], pages: dict[str, Page], source_path: str,
                      source_title: str, vault: Path) -> list[str]:
    src_link = f"[[{source_path}]]"
    linkable_paths = set(plan) | set(pages)
    touched = []
    for n, (path, e) in enumerate(plan.items(), 1):
        run.step = f"patch {n}/{len(plan)} {'+' if e['new'] else '~'} {path}"
        if e["new"]:
            fm = {"title": e["name"], "type": e["kind"], "aliases": e["aliases"], "tags": [],
                  "created": TODAY, "updated": TODAY, "sources": [], "status": "active",
                  "description": e["description"]}
            if e["kind"] == "entity":
                fm["entity_kind"] = e["entity_kind"]
            page = Page(path, fm, f"# {e['name']}\n\n{e['description']} ({src_link})\n")
        else:
            page = pages[path]
        h1, lead, secs = section_map(page.body)
        # linkable: pages touched in this source + already existing pages, minus self; cap for budget
        others = [p for p in plan if p != path][:60]
        linkable = "\n".join(f"- [[{p}|{plan[p]['name']}]]" for p in others)
        claims = "\n".join(f"- {c}  (section: {loc})" for c, loc in e["claims"])
        user = (f"Source id: {source_path}  (\"{source_title}\")\n\n--- CURRENT PAGE ({path}) ---\n"
                f"{page.body}\n--- END PAGE ---\n\nNew claims about \"{e['name']}\" from the source:\n{claims}\n\n"
                f"Linkable pages:\n{linkable or '(none)'}")
        data = run.llm("patch", PATCH_SYSTEM.replace("{source}", source_path), user, PATCH_SCHEMA,
                       think=run.think_patch)
        if data is None:
            run.counters["patch_failed"] += 1
            reject(run, path, "invalid json twice")
            continue
        allowed = linkable_paths - {path}
        new_lead = fix_links(data.get("lead", "").strip() or lead, allowed, run)
        old_lead_cites = tokens(lead, LINK_RE)
        if not old_lead_cites <= tokens(new_lead, LINK_RE):
            run.counters["patch_lead_lost_links_rejected"] += 1
            new_lead = lead
        sec_dict = dict(secs)
        for op in data.get("ops", []):
            name = op["section"].strip().lstrip("#").strip() or "Notes"
            raw = op["text"]
            if "\\n" in raw:  # smoke run: model sometimes emits escaped newlines inside the string
                run.counters["patch_escaped_newlines_fixed"] += 1
                raw = raw.replace("\\n", "\n")
            text = ensure_citations(fix_links(raw.strip(), allowed, run), src_link, run)
            if not text:
                continue
            if op["op"] == "replace" and name in sec_dict:
                lost = tokens(sec_dict[name], LINK_RE) - tokens(text, LINK_RE)
                if lost:
                    run.counters["patch_replace_rejected_lost_links"] += 1
                    reject(run, path, f"replace of '{name}' drops {sorted(lost)}")
                    continue
                if len(text) < 0.6 * len(sec_dict[name]):
                    run.counters["patch_replace_rejected_shrink"] += 1
                    reject(run, path, f"replace of '{name}' shrinks section {len(sec_dict[name])}->{len(text)}")
                    continue
                sec_dict[name] = text
                run.counters["patch_op_replace"] += 1
            else:
                sec_dict[name] = (sec_dict.get(name, "") + "\n" + text).strip()
                run.counters["patch_op_append"] += 1
        page.body = build_body(h1 or f"# {page.title}", new_lead, list(sec_dict.items()))
        page.fm["aliases"] = list(dict.fromkeys(page.fm.get("aliases", []) + e["aliases"]))
        page.fm["aliases"] = [a for a in page.fm["aliases"] if norm(a) != norm(page.title)]
        if src_link not in page.fm.get("sources", []):
            page.fm.setdefault("sources", []).append(src_link)
        page.fm["updated"] = TODAY
        pages[path] = page
        save_page(vault, page)
        touched.append(path)
        run.counters["pages_created" if e["new"] else "pages_updated"] += 1
    return touched


def reject(run: Run, path: str, reason: str) -> None:
    run.say(f"    ✗ rejected edit on {path}: {reason}")
    with (run.out / "rejections.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"page": path, "reason": reason}) + "\n")


# ---------------------------------------------------------------------------
# Source page, index, log, git
# ---------------------------------------------------------------------------

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "key_points": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "key_points"],
}
SUMMARY_SYSTEM = ("Summarise the document for a wiki source page. summary: 2-4 sentences, what the document "
                  "is and covers. key_points: 4-10 short bullet points with the most important content. "
                  "Use only the document. Write in English.")


def write_source_page(run: Run, packet: str, meta: dict, text: str, vault: Path) -> Page:
    words = text.split()
    run.step = f"summary {packet}"
    data = run.llm("summary", SUMMARY_SYSTEM, f"Title: {meta['title']}\n\n" + " ".join(words[:6000]),
                   SUMMARY_SCHEMA) or {"summary": "(summary failed)", "key_points": []}
    path = f"sources/{packet}"
    fm = {"title": meta["title"], "type": "source", "source_type": meta["source_type"],
          "origin": meta["origin"], "ingested": TODAY, "created": TODAY, "updated": TODAY,
          "tags": [], "status": "active"}
    kp = "\n".join(f"- {k}" for k in data["key_points"])
    body = f"# {meta['title']}\n\n{data['summary']}\n\n## Key points\n\n{kp}\n"
    page = Page(path, fm, body)
    save_page(vault, page)
    return page


def autolink(pages: dict[str, Page], vault: Path, run: Run) -> None:
    """Deterministic linking: on every entity/concept page, link the first plain-text mention of
    another page's title or alias. Short names (<= 5 chars) must match case-sensitively, so
    'TIME'/'Task' don't fire on ordinary words. Never touches existing links or headings."""
    wiki = {p: pg for p, pg in pages.items() if pg.fm.get("type") in ("entity", "concept")}
    names: list[tuple[str, str]] = []
    for path, pg in wiki.items():
        for n in {pg.title, *pg.fm.get("aliases", [])}:
            n = n.strip()
            if len(n) >= 3 and not n.endswith((".xlsx", ".docx")):
                names.append((n, path))
    names.sort(key=lambda x: -len(x[0]))  # longest first: "Integrated Activity Plan" before "Activity Plan"
    for path, pg in wiki.items():
        h1, lead, secs = section_map(pg.body)
        linked = {m.group(1).strip() for m in LINK_RE.finditer(pg.body)}
        added = 0

        def link_in(text: str) -> str:
            nonlocal added
            for n, target in names:
                if target == path or target in linked:
                    continue
                flags = 0 if len(n) <= 5 else re.I
                rx = re.compile(rf"(?<![\w\[|/-]){re.escape(n)}(?![\w\]-])", flags)
                parts = re.split(r"(\[\[[^\]]*\]\])", text)  # keep existing links intact
                for i in range(0, len(parts), 2):
                    m = rx.search(parts[i])
                    if m:
                        parts[i] = parts[i][:m.start()] + f"[[{target}|{m.group(0)}]]" + parts[i][m.end():]
                        linked.add(target)
                        added += 1
                        break
                text = "".join(parts)
            return text

        new_lead = link_in(lead)
        new_secs = [(name, link_in(t)) for name, t in secs]
        if added:
            pg.body = build_body(h1, new_lead, new_secs)
            save_page(vault, pg)
            run.counters["autolinks_added"] += added


def finish(vault: Path, source_page: Page, touched: list[str], pages: dict[str, Page], packet: str,
           run: Run | None = None) -> None:
    if run is not None:
        autolink(pages, vault, run)
    # bidirectional: source page lists every page it touched
    covered = "\n".join(f"- [[{p}|{pages[p].title}]]" for p in sorted(touched))
    source_page.body = source_page.body.rstrip() + f"\n\n## Pages updated from this source\n\n{covered}\n"
    save_page(vault, source_page)
    pages[source_page.path] = source_page
    # index
    by_type = defaultdict(list)
    for p in sorted(pages.values(), key=lambda p: p.title.lower()):
        by_type[p.fm.get("type", "other")].append(p)
    idx = ["---", "title: Index", "type: index", f"updated: {TODAY}", "---", "", "# Index", ""]
    for t in ("source", "entity", "concept", "synthesis"):
        if by_type.get(t):
            idx += [f"## {t.capitalize()} pages", ""]
            for p in by_type[t]:
                desc = p.fm.get("description") or section_map(p.body)[1].split("\n")[0][:140]
                desc = re.sub(r"\s*\(\[\[sources/[^\]]+\]\]\)", "", desc)
                idx.append(f"- [[{p.path}|{p.title}]] — {desc}")
            idx.append("")
    (vault / "index.md").write_text("\n".join(idx), encoding="utf-8")
    with (vault / "log.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## [{TODAY}] ingest | {source_page.title}\n\n- source: [[{source_page.path}]]\n"
                f"- pages touched: {len(touched)}\n")
    git(vault, "add", "-A")
    git(vault, "commit", "-q", "-m", f"ingest: {packet}")


def git(vault: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(vault), *args], check=True, capture_output=True)


def init_vault(vault: Path) -> None:
    for d in ("sources", "entities", "concepts", "syntheses"):
        (vault / d).mkdir(parents=True, exist_ok=True)
    (vault / "WIKI.md").write_text("# Wiki schema\n\n(spike vault)\n", encoding="utf-8")
    (vault / "log.md").write_text("---\ntitle: Log\ntype: log\n---\n\n# Log\n", encoding="utf-8")
    git(vault, "init", "-q")
    git(vault, "config", "user.name", "mneme-wiki spike")
    git(vault, "config", "user.email", "spike@localhost")


# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:14b")
    ap.add_argument("--label", default=None)
    ap.add_argument("--no-think", action="store_true", help="disable thinking for the patch stage")
    ap.add_argument("packets", nargs="*", default=ORDER)
    a = ap.parse_args()
    label = a.label or f"{a.model.replace(':', '-')}{'-nothink' if a.no_think else ''}"
    out = ROOT / "spike" / "out" / label
    if out.exists():
        sys.exit(f"{out} exists - pick another --label or delete it")
    out.mkdir(parents=True)
    vault = out / "vault"
    init_vault(vault)
    run = Run(model=a.model, out=out, think_patch=not a.no_think)
    timings = {}
    run.say(f"model {a.model} | patch thinking {'on' if run.think_patch else 'off'} | "
            f"{len(a.packets)} sources | output {out}")
    for si, packet in enumerate(a.packets, 1):
        t0 = time.time()
        rej_before = sum(1 for _ in open(out / "rejections.jsonl", encoding="utf-8")) if (out / "rejections.jsonl").exists() else 0
        pdir = CORPUS / packet
        meta = json.loads((pdir / "source.meta.json").read_text(encoding="utf-8"))
        text = (pdir / "source.md").read_text(encoding="utf-8")
        pages = load_vault(vault)
        n_chunks = len(chunk(text))
        run.say(f"━━ source {si}/{len(a.packets)}: {meta['title']} "
                f"({len(text.split())} words, {n_chunks} chunks, vault has {len(pages)} pages)")
        run.say("1/5 extract")
        subjects = stage_extract(run, packet, meta, text, pages)
        groups = merge_within_source(subjects)
        run.say(f"    {len(subjects)} subjects found, {len(groups)} after merging duplicates within the source")
        run.say("2/5 resolve against existing pages")
        groups = stage_resolve(run, groups, pages)
        by = Counter(g["resolved_by"] for g in groups)
        run.say(f"    exact name match {by['exact']}, model match {by['llm']}, new {by['new']}")
        (out / f"{packet}.extract.json").write_text(json.dumps(groups, indent=1, ensure_ascii=False), encoding="utf-8")
        plan = stage_plan(groups, pages)
        (out / f"{packet}.plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
        n_new = sum(e["new"] for e in plan.values())
        run.say(f"3/5 plan: {n_new} new pages, {len(plan) - n_new} existing pages to update")
        run.say("4/5 source summary + patch pages (+ new, ~ update)")
        src = write_source_page(run, packet, meta, text, vault)
        touched = stage_patch_apply(run, plan, pages, src.path, meta["title"], vault)
        run.say("5/5 index, log, git commit")
        finish(vault, src, touched, pages, packet, run)
        timings[packet] = round(time.time() - t0, 1)
        rej_after = sum(1 for _ in open(out / "rejections.jsonl", encoding="utf-8")) if (out / "rejections.jsonl").exists() else 0
        run.per_source[packet] = {
            "title": meta["title"], "chunks": n_chunks, "subjects": len(subjects), "merged": len(groups),
            "exact": by["exact"], "llm": by["llm"], "new_subjects": by["new"],
            "pages_new": n_new, "pages_updated": len(plan) - n_new, "pages_written": len(touched),
            "rejections": rej_after - rej_before, "seconds": timings[packet],
        }
        run.say(f"✓ {meta['title']}: {n_new} pages created, {len(plan) - n_new} updated, "
                f"{rej_after - rej_before} edits rejected, {timings[packet]:.0f}s")

    by_role = defaultdict(list)
    for c in run.calls:
        by_role[c["role"]].append(c)
    metrics = {
        "model": a.model, "think_patch": run.think_patch, "timings_s": timings,
        "counters": dict(run.counters),
        "roles": {r: {
            "calls": len(cs),
            "json_ok_rate": round(sum(c["json_ok"] for c in cs) / len(cs), 3),
            "retries": sum(c["attempt"] == 2 for c in cs),
            "latency_s_mean": round(sum(c["latency_s"] for c in cs) / len(cs), 1),
            "latency_s_total": round(sum(c["latency_s"] for c in cs), 1),
            "prompt_tokens_max": max((c["prompt_tokens"] or 0) for c in cs),
            "out_tokens_mean": round(sum((c["out_tokens"] or 0) for c in cs) / len(cs)),
        } for r, cs in by_role.items()},
    }
    metrics["per_source"] = run.per_source
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    report = render_report(run, metrics, vault, label)
    (out / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)


def render_report(run: Run, metrics: dict, vault: Path, label: str) -> str:
    """Human-readable end-of-run summary: what happened, what to look at next."""
    pages = load_vault(vault)
    wiki = [p for p in pages.values() if p.fm.get("type") in ("entity", "concept")]
    multi = sorted((p for p in wiki if len(p.fm.get("sources", [])) >= 2),
                   key=lambda p: -len(p.fm.get("sources", [])))
    total = sum(c["latency_s"] for c in run.calls)
    c = metrics["counters"]
    lines = [
        f"# Spike run `{label}`", "",
        f"Model `{metrics['model']}`, patch thinking {'on' if metrics['think_patch'] else 'off'}. "
        f"{len(run.calls)} model calls, {total / 60:.1f} min of model time, "
        f"{sum(metrics['timings_s'].values()) / 60:.1f} min wall time.", "",
        "## Per source", "",
        "| Source | Chunks | Subjects → merged | Matched existing (exact / model) | Pages new / updated | Rejected edits | Time |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in run.per_source.values():
        lines.append(f"| {s['title'][:40]} | {s['chunks']} | {s['subjects']} → {s['merged']} | "
                     f"{s['exact']} / {s['llm']} | {s['pages_new']} / {s['pages_updated']} | "
                     f"{s['rejections']} | {s['seconds']:.0f}s |")
    lines += ["", "## Model calls", "", "| Stage | Calls | Valid JSON | Retries | Mean latency | Total |",
              "|---|---|---|---|---|---|"]
    for r, m in metrics["roles"].items():
        lines.append(f"| {r} | {m['calls']} | {m['json_ok_rate']:.0%} | {m['retries']} | "
                     f"{m['latency_s_mean']}s | {m['latency_s_total'] / 60:.1f} min |")
    lines += [
        "", "## Validation (code checks on model output)", "",
        f"- links to unknown pages removed: {c.get('patch_invalid_link_removed', 0)}",
        f"- lines missing a citation (auto-added): {c.get('patch_missing_citation_added', 0)} "
        f"of {c.get('patch_missing_citation_added', 0) + c.get('patch_cited_lines', 0)}",
        f"- section rewrites rejected for losing links: {c.get('patch_replace_rejected_lost_links', 0)}, "
        f"for shrinking: {c.get('patch_replace_rejected_shrink', 0)}",
        f"- ops applied: {c.get('patch_op_append', 0)} append, {c.get('patch_op_replace', 0)} replace",
        f"- resolve: {c.get('resolve_llm_calls', 0)} model decisions, matched existing "
        f"{c.get('resolve_exact', 0)} exact / {c.get('resolve_llm', 0)} model; merged within source "
        f"{c.get('resolve_exact_within_source', 0)} exact / {c.get('resolve_llm_within_source', 0)} model "
        f"(all decisions: resolve_log.jsonl)",
        f"- links added by the code linking pass: {c.get('autolinks_added', 0)}",
        "", "## Result", "",
        f"- {len(pages)} pages ({len(wiki)} entity/concept), "
        f"{len(multi)} pages draw on 2+ sources",
    ]
    if multi:
        lines.append("- most connected: " + ", ".join(
            f"`{p.path}` ({len(p.fm['sources'])} sources)" for p in multi[:8]))
    lines += [
        "", "## Look at next", "",
        f"- open `{vault}` as a vault in Obsidian (graph view, backlinks)",
        f"- `git -C {vault} log --stat` — one commit per source",
        f"- `{run.out / 'rejections.jsonl'}` — every rejected edit with its reason",
        f"- `python spike/eval.py {label}` — score against bench/corpus/gold.json",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
