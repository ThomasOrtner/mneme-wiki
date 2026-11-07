"""Benchmark harness (TD-15): which local model for which stage?

A *mapping file* (TOML) names a model per stage role, thinking per role, and
optionally a judge model:

```toml
label = "baseline"                      # optional; --label wins
[models]
extract = "ollama:qwen3:14b"            # roles not listed use the config default
patch   = "ollama:qwen3:14b"
[thinking]
patch = false
[judge]
model  = "ollama:qwen3:14b"             # optional page-quality score (1-5)
sample = 15
```

`run_bench()` integrates the corpus packets, in a fixed order, into a fresh
throwaway vault, `repeats` times (M0: ±15 % run-to-run variance), and measures:

- per role: calls, valid-JSON rate on the first try, retries, latency, tokens;
- per run: pages, rejected edits, lint, links per page, citation coverage, time;
- against `gold.json` (if the corpus has one): gold pages found, duplicates, core
  subjects merged across sources (resolve recall), wrong merges (resolve
  precision);
- page quality, for patch settings: sections and bullets per page, near-duplicate
  bullets, headings copied from the source's structure, optional judge score.

Output: `bench/results/<timestamp>_<label>/` with `metrics.json`, `summary.md`
and one `run<N>/` per repeat (vault + run reports). Only `summary.md` is meant
for git.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import config, expansions, links, packet, text
from .integrate import integrate
from .lint import CLAIM_MIN_WORDS, lint
from .llm import LLM, Call
from .prompts import load_prompt
from .stages.common import name_key
from .vault import Page, Vault, init_vault, slugify

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

Log = Callable[[str], None]
ROLES = ("extract", "resolve", "patch", "summary")
DUP_JACCARD = 0.7
JUDGE_SAMPLE = 15


class BenchError(ValueError):
    pass


@dataclass
class Mapping:
    label: str
    models: dict[str, str]
    thinking: dict[str, bool]
    judge: str | None = None
    judge_sample: int = JUDGE_SAMPLE
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "models": self.models,
            "thinking": self.thinking,
            "judge": self.judge,
            "judge_sample": self.judge_sample,
        }


def load_mapping(path: Path | str, label: str | None = None) -> Mapping:
    p = Path(path)
    try:
        data = tomllib.loads(p.read_bytes().decode("utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise BenchError(f"{p}: {exc}") from exc
    models = dict(config.MODELS)
    for role, ref in (data.get("models") or {}).items():
        if role not in config.ROLES:
            raise BenchError(f"{p}: unknown role {role!r}")
        models[role] = str(ref)
    thinking = dict(config.THINKING)
    for role, flag in (data.get("thinking") or {}).items():
        if role not in config.ROLES:
            raise BenchError(f"{p}: unknown role {role!r} in [thinking]")
        thinking[role] = bool(flag)
    judge = data.get("judge") or {}
    return Mapping(
        label=label or str(data.get("label") or p.stem),
        models=models,
        thinking=thinking,
        judge=judge.get("model") or models.get("judge"),
        judge_sample=int(judge.get("sample", JUDGE_SAMPLE)),
        source=p.read_bytes().decode("utf-8"),
    )


def corpus_packets(corpus: Path, names: list[str] | None = None) -> list[Path]:
    """Packet folders in benchmark order: `names`, else `order.txt`, else sorted."""
    if names:
        order = names
    elif (corpus / "order.txt").is_file():
        lines = (corpus / "order.txt").read_bytes().decode("utf-8").splitlines()
        order = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    else:
        order = sorted(p.name for p in corpus.iterdir() if (p / "source.md").is_file())
    paths = [corpus / n for n in order]
    missing = [str(p) for p in paths if not (p / "source.md").is_file()]
    if missing:
        raise BenchError(f"not packets: {', '.join(missing)}")
    if not paths:
        raise BenchError(f"no packets in {corpus}")
    return paths


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def call_metrics(calls: list[Call]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for role in dict.fromkeys(c.role for c in calls):
        cs = [c for c in calls if c.role == role]
        firsts = [c for c in cs if c.attempt == 1]
        out[role] = {
            "model": cs[0].model,
            "calls": len(cs),
            "json_ok_first_try": round(sum(c.ok for c in firsts) / max(len(firsts), 1), 3),
            "failed": sum(not c.ok for c in cs if c.attempt > 1),
            "retries": sum(c.attempt > 1 for c in cs),
            "latency_s_total": round(sum(c.latency_s for c in cs), 1),
            "latency_s_mean": round(sum(c.latency_s for c in cs) / len(cs), 2),
            "tokens_in_max": max(c.tokens_in for c in cs),
            "tokens_in_mean": round(sum(c.tokens_in for c in cs) / len(cs)),
            "tokens_out_mean": round(sum(c.tokens_out for c in cs) / len(cs)),
        }
    return out


def wiki_pages(vault: Vault) -> list[Page]:
    return [
        p
        for _, p in vault.iter_pages()
        if isinstance(p, Page) and p.meta.get("type") in ("entity", "concept")
    ]


def _names(page: Page) -> set[str]:
    aliases = page.meta.get("aliases") if isinstance(page.meta.get("aliases"), list) else []
    return {name_key(n) for n in [page.title, *aliases] if isinstance(n, str)} - {""}


def gold_metrics(pages: list[Page], gold: dict) -> dict:
    """Gold coverage and resolve quality (ported from spike/eval.py)."""
    names = {p.path: _names(p) for p in pages}
    by_path = {p.path: p for p in pages}
    found, dup, missing = [], [], []
    core = core_ok = 0
    for g in gold.get("pages", []):
        keys = {name_key(n) for n in g["names"]} - {""}
        hits = [path for path, ns in names.items() if ns & keys]
        (missing if not hits else found).append(g["title"])
        if len(hits) > 1:
            dup.append({"gold": g["title"], "pages": sorted(hits)})
        if g.get("core"):
            core += 1
            srcs = by_path[hits[0]].meta.get("sources") if len(hits) == 1 else []
            if len(hits) == 1 and isinstance(srcs, list) and len(srcs) >= 2:
                core_ok += 1
    wrong, pairs_present = [], 0
    for a, b in gold.get("must_not_merge", []):
        ka, kb = name_key(a), name_key(b)
        if any(ka in ns for ns in names.values()) and any(kb in ns for ns in names.values()):
            pairs_present += 1
        for path, ns in names.items():
            if ka in ns and kb in ns:
                wrong.append({"pair": [a, b], "page": path})
    total = len(gold.get("pages", []))
    return {
        "gold_found": len(found),
        "gold_total": total,
        "gold_missing": missing,
        "gold_duplicates": dup,
        "core_merged": core_ok,
        "core_total": core,
        "resolve_recall": round(core_ok / core, 3) if core else None,
        "wrong_merges": wrong,
        "resolve_precision": round(1 - len(wrong) / pairs_present, 3) if pairs_present else None,
    }


def _bullet_tokens(line: str) -> set[str]:
    return set(text.tokens(text.plain(line)))


def quality_metrics(pages: list[Page], locators: set[str]) -> dict:
    """Page-structure measures (M0: thinking gave better structure, fewer duplicates)."""
    sections = bullets = dups = copied = h2 = 0
    links_per_page, claims, cited = [], 0, 0
    loc_keys = {" ".join(loc.casefold().split()) for loc in locators}
    for page in pages:
        index_targets = set()
        page_bullets: list[set[str]] = []
        for block in text.blocks(page.body):
            if block.kind == "heading" and block.level == 2:
                sections += 1
                h2 += 1
                copied += " ".join(block.text.casefold().split()) in loc_keys
            if block.kind == "list_item":
                bullets += 1
                page_bullets.append(_bullet_tokens(block.text))
            if block.kind in ("paragraph", "list_item"):
                if text.word_count(text.plain(block.text)) >= CLAIM_MIN_WORDS:
                    claims += 1
                    cited += any(
                        lk.target.startswith("sources/") for lk in links.extract(block.text)
                    )
        for lk in links.extract(page.body):
            if lk.target and not lk.target.startswith("sources/"):
                index_targets.add(lk.target.casefold())
        links_per_page.append(len(index_targets))
        for i, a in enumerate(page_bullets):
            for b in page_bullets[:i]:
                if a and b and len(a & b) / len(a | b) >= DUP_JACCARD:
                    dups += 1
                    break
    n = max(len(pages), 1)
    return {
        "sections_per_page": round(sections / n, 2),
        "bullets_per_page": round(bullets / n, 2),
        "duplicate_bullet_rate": round(dups / max(bullets, 1), 3),
        "source_structure_headings": round(copied / max(h2, 1), 3),
        "links_per_page": round(sum(links_per_page) / n, 2),
        "citation_coverage": round(cited / max(claims, 1), 3),
        "stub_rate": round(sum(p.meta.get("status") == "stub" for p in pages) / n, 3),
    }


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "structure": {"type": "integer", "minimum": 1, "maximum": 5},
        "redundancy": {"type": "integer", "minimum": 1, "maximum": 5},
        "clarity": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "required": ["reason", "structure", "redundancy", "clarity"],
}
JUDGE_SYSTEM = load_prompt("judge")


def unbacked_expansions(vault: Vault, evidence: str) -> int:
    """Abbreviations spelled out in a way neither the sources nor the page's own names
    back up. M5: every model invented these, and no other metric can see them."""
    total = 0
    for _, page in vault.iter_pages():
        if isinstance(page, Page) and page.meta.get("type") in ("source", "entity", "concept"):
            aliases = page.meta.get("aliases")
            names = " ".join(
                map(str, [page.title, *(aliases if isinstance(aliases, list) else [])])
            )
            known = f"{evidence}\n{names}"
            for line in page.body.splitlines():  # plain() would run the H1 into the lead
                total += len(expansions.find(text.plain(line), known))
    return total


def judge_pages(llm: LLM, pages: list[Page], sample: int) -> dict | None:
    if not pages or sample <= 0:
        return None
    ordered = sorted(pages, key=lambda p: p.path)
    step = max(len(ordered) // sample, 1)
    chosen = ordered[::step][:sample]
    client = llm.for_role("judge")
    scores: dict[str, list[int]] = {"structure": [], "redundancy": [], "clarity": []}
    for i, page in enumerate(chosen, 1):
        data = client.json(JUDGE_SYSTEM, page.body[:8000], JUDGE_SCHEMA,
                           step=f"judge {i}/{len(chosen)} {page.path}")  # fmt: skip
        for key in scores:
            value = (data or {}).get(key)
            if isinstance(value, int) and 1 <= value <= 5:
                scores[key].append(value)
    out = {k: round(statistics.mean(v), 2) if v else None for k, v in scores.items()}
    out["pages"] = len(chosen)
    return out


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
@dataclass
class BenchResult:
    out_dir: Path
    label: str
    runs: list[dict] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)


MakeLLM = Callable[[dict[str, str | None], dict[str, bool], Log], LLM]


def _default_llm(models: dict, thinking: dict, log: Log) -> LLM:
    return LLM(models, thinking=thinking, log=log)


def run_once(
    mapping: Mapping,
    packets: list[Path],
    run_dir: Path,
    gold: dict | None,
    *,
    log: Log,
    make_llm: MakeLLM = _default_llm,
) -> dict:
    vault = init_vault(run_dir / "vault", language=config.LANGUAGE)
    llm = make_llm(mapping.models, mapping.thinking, log)
    t0 = time.monotonic()
    reports = []
    for pkt in packets:
        report = integrate(vault, pkt, llm=llm, inbox=run_dir / "inbox", log=log)
        reports.append(report)
        if not report.ok:
            log(f"✗ {pkt.name}: new lint errors, stopping this run")
            break
    seconds = round(time.monotonic() - t0, 1)
    integrate_calls = list(llm.calls)
    pages = wiki_pages(vault)
    locators = {loc for p in packets for loc, _ in packet.sections(packet.load(p).text)}
    report = lint(vault)
    result = {
        "seconds": seconds,
        "completed": all(r.ok for r in reports) and len(reports) == len(packets),
        "sources": [
            {
                "packet": r.packet,
                "created": len(r.created),
                "updated": len(r.updated),
                "rejected": len(r.rejected),
                "subjects": r.subjects,
                "merged": r.merged,
                "resolve": r.resolve,
                "autolinks": r.autolinks,
                "seconds": round(sum(r.seconds.values()), 1),
            }
            for r in reports
        ],
        "pages": len(pages),
        "rejected": sum(len(r.rejected) for r in reports),
        "lint_errors": len(report.errors),
        "lint_warnings": len(report.warnings),
        "roles": call_metrics(integrate_calls),
        "quality": quality_metrics(pages, locators),
        "unbacked_expansions": unbacked_expansions(
            vault, "\n".join(packet.load(p).text for p in packets)
        ),
        "gold": gold_metrics(pages, gold) if gold else None,
    }
    if mapping.judge:
        judge_llm = make_llm({"judge": mapping.judge}, {"judge": False}, log)
        result["judge"] = judge_pages(judge_llm, pages, mapping.judge_sample)
    return result


def _mean_sd(values: list[float]) -> dict:
    vals = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return {"mean": None, "sd": None}
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return {"mean": round(statistics.mean(vals), 3), "sd": round(sd, 3)}


def aggregate(runs: list[dict]) -> dict:
    def pick(fn):
        out = []
        for r in runs:
            try:
                out.append(fn(r))
            except (KeyError, TypeError):
                out.append(None)
        return _mean_sd(out)

    agg = {
        "runs": len(runs),
        "completed": sum(r["completed"] for r in runs),
        "minutes": pick(lambda r: r["seconds"] / 60),
        "pages": pick(lambda r: r["pages"]),
        "rejected": pick(lambda r: r["rejected"]),
        "lint_errors": pick(lambda r: r["lint_errors"]),
        "lint_warnings": pick(lambda r: r["lint_warnings"]),
        "unbacked_expansions": pick(lambda r: r.get("unbacked_expansions", 0)),
    }
    for key in ("sections_per_page", "bullets_per_page", "duplicate_bullet_rate",
                "source_structure_headings", "links_per_page", "citation_coverage"):  # fmt: skip
        agg[key] = pick(lambda r, k=key: r["quality"][k])
    if runs and runs[0].get("gold"):
        agg["gold_found"] = pick(lambda r: r["gold"]["gold_found"])
        agg["core_merged"] = pick(lambda r: r["gold"]["core_merged"])
        agg["wrong_merges"] = pick(lambda r: len(r["gold"]["wrong_merges"]))
        agg["duplicates"] = pick(lambda r: len(r["gold"]["gold_duplicates"]))
        agg["gold_total"] = runs[0]["gold"]["gold_total"]
        agg["core_total"] = runs[0]["gold"]["core_total"]
    roles = sorted({role for r in runs for role in r["roles"]})
    agg["roles"] = {
        role: {
            "model": next(r["roles"][role]["model"] for r in runs if role in r["roles"]),
            "calls": pick(lambda r, x=role: r["roles"][x]["calls"]),
            "json_ok_first_try": pick(lambda r, x=role: r["roles"][x]["json_ok_first_try"]),
            "failed": pick(lambda r, x=role: r["roles"][x]["failed"]),
            "minutes": pick(lambda r, x=role: r["roles"][x]["latency_s_total"] / 60),
            "latency_s_mean": pick(lambda r, x=role: r["roles"][x]["latency_s_mean"]),
            "tokens_in_max": pick(lambda r, x=role: r["roles"][x]["tokens_in_max"]),
        }
        for role in roles
    }
    if any(r.get("judge") for r in runs):
        for key in ("structure", "redundancy", "clarity"):
            agg[f"judge_{key}"] = pick(lambda r, k=key: r["judge"][k])
    return agg


def run_bench(
    mapping: Mapping,
    corpus: Path,
    *,
    out_root: Path,
    repeats: int = 3,
    packet_names: list[str] | None = None,
    log: Log = lambda _m: None,
    now: dt.datetime | None = None,
    make_llm: MakeLLM = _default_llm,
) -> BenchResult:
    packets = corpus_packets(corpus, packet_names)
    gold_file = corpus / "gold.json"
    gold = json.loads(gold_file.read_bytes().decode("utf-8")) if gold_file.is_file() else None
    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    out = out_root / f"{stamp}_{slugify(mapping.label, 40)}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "mapping.toml").write_bytes(mapping.source.encode("utf-8"))
    result = BenchResult(out, mapping.label)
    for n in range(1, repeats + 1):
        log(f"══ bench {mapping.label}: run {n}/{repeats}, {len(packets)} packets")
        run = run_once(mapping, packets, out / f"run{n}", gold, log=log, make_llm=make_llm)
        result.runs.append(run)
        _write(out, mapping, result, [p.name for p in packets])
    result.aggregate = aggregate(result.runs)
    _write(out, mapping, result, [p.name for p in packets])
    return result


def _write(out: Path, mapping: Mapping, result: BenchResult, packets: list[str]) -> None:
    result.aggregate = aggregate(result.runs) if result.runs else {}
    data = {
        "label": mapping.label,
        "mapping": mapping.to_dict(),
        "packets": packets,
        "aggregate": result.aggregate,
        "runs": result.runs,
    }
    (out / "metrics.json").write_bytes(
        (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    )
    (out / "summary.md").write_bytes(render_summary(data).encode("utf-8"))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def _fmt(stat: dict | None, digits: int = 2, pct: bool = False) -> str:
    if not stat or stat.get("mean") is None:
        return "–"
    mean, sd = stat["mean"], stat["sd"] or 0
    if pct:
        return f"{mean:.0%}" + (f" ± {sd:.0%}" if sd else "")
    return f"{mean:.{digits}f}" + (f" ± {sd:.{digits}f}" if sd else "")


def render_summary(data: dict) -> str:
    a = data["aggregate"]
    m = data["mapping"]
    lines = [
        f"# Bench `{data['label']}`",
        "",
        f"{a.get('runs', 0)} runs ({a.get('completed', 0)} completed) over "
        f"{', '.join(data['packets'])}. Values are mean ± sd over runs.",
        "",
        "| Role | Model | Thinking |",
        "|---|---|---|",
        *(
            f"| {role} | `{m['models'].get(role)}` | {'on' if m['thinking'].get(role) else 'off'} |"
            for role in ROLES
        ),
    ]
    if m.get("judge"):
        lines.append(f"| judge | `{m['judge']}` | off |")
    lines += ["", "## Result", "", "| Metric | Value |", "|---|---|"]
    rows = [
        ("time (min)", _fmt(a.get("minutes"), 1)),
        ("pages", _fmt(a.get("pages"), 1)),
        ("rejected edits", _fmt(a.get("rejected"), 1)),
        (
            "lint errors / warnings",
            f"{_fmt(a.get('lint_errors'), 1)} / {_fmt(a.get('lint_warnings'), 1)}",
        ),
    ]
    if "gold_found" in a:
        rows += [
            (f"gold pages found (of {a['gold_total']})", _fmt(a["gold_found"], 1)),
            (f"core merged across sources (of {a['core_total']})", _fmt(a["core_merged"], 1)),
            ("wrong merges", _fmt(a["wrong_merges"], 1)),
            ("gold duplicates", _fmt(a["duplicates"], 1)),
        ]
    rows += [
        ("links per page", _fmt(a.get("links_per_page"))),
        ("citation coverage", _fmt(a.get("citation_coverage"), pct=True)),
        ("unbacked abbreviation expansions", _fmt(a.get("unbacked_expansions"), 1)),
        ("sections per page", _fmt(a.get("sections_per_page"))),
        ("bullets per page", _fmt(a.get("bullets_per_page"))),
        ("near-duplicate bullets", _fmt(a.get("duplicate_bullet_rate"), pct=True)),
        ("headings copied from the source", _fmt(a.get("source_structure_headings"), pct=True)),
    ]
    for key in ("structure", "redundancy", "clarity"):
        if f"judge_{key}" in a:
            rows.append((f"judge: {key} (1-5)", _fmt(a[f"judge_{key}"])))
    q = data.get("questions_aggregate")
    if q:
        rows += [
            (f"questions answered (of {q['questions']})", _fmt(q["answered"], 1)),
            ("answers citing a source", _fmt(q["cited_rate"], pct=True)),
            ("answers retried", _fmt(q.get("retried"), 1)),
            ("unbacked expansions in answers", _fmt(q.get("unbacked"), 1)),
            ("invalid links removed", _fmt(q["invalid_links"], 1)),
            ("query seconds / question", _fmt(q["seconds_mean"], 1)),
        ]
    lines += [f"| {k} | {v} |" for k, v in rows]
    lines += [
        "",
        "## Model calls per role",
        "",
        "| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |",
        "|---|---|---|---|---|---|---|",
    ]
    for role, r in a.get("roles", {}).items():
        lines.append(
            f"| {role} | {_fmt(r['calls'], 0)} | {_fmt(r['json_ok_first_try'], pct=True)} | "
            f"{_fmt(r['failed'], 1)} | {_fmt(r['minutes'], 1)} | {_fmt(r['latency_s_mean'])} | "
            f"{_fmt(r['tokens_in_max'], 0)} |"
        )
    return "\n".join(lines) + "\n"


def load_questions(path: Path) -> list[str]:
    """Questions from a Markdown file: every list item (`- …`) is one question."""
    lines = path.read_bytes().decode("utf-8").splitlines()
    return [ln.strip()[2:].strip() for ln in lines if ln.strip().startswith(("- ", "* "))]


def run_questions(
    out_dir: Path,
    questions: list[str],
    *,
    query_model: str | None = None,
    log: Log = lambda _m: None,
    make_llm: MakeLLM = _default_llm,
) -> dict:
    """Ask `questions` against every run's vault in `out_dir` (M5); store the answers
    and metrics in `metrics.json` / `summary.md`."""
    from .query import ask  # query imports integrate; keep bench importable alone

    data = json.loads((out_dir / "metrics.json").read_bytes().decode("utf-8"))
    ref = query_model or config.MODELS["query"]
    per_run = []
    for n, run in enumerate(data["runs"], 1):
        vault = Vault(out_dir / f"run{n}" / "vault")
        llm = make_llm({"query": ref}, {"query": False}, log)
        answers = []
        for q in questions:
            t0 = time.monotonic()
            a = ask(vault, q, llm=llm)
            answers.append({
                "question": q,
                "answerable": a.answerable,
                "cited": bool(a.sources),
                "retried": a.counters.get("answer_retry", 0),
                "unbacked": len(a.unbacked),
                "pages": len(a.pages),
                "invalid_links": a.counters.get("invalid_link_removed", 0),
                "seconds": round(time.monotonic() - t0, 1),
                "answer": a.answer,
            })  # fmt: skip
        run["questions"] = answers
        per_run.append(answers)
    n_q = max(len(questions), 1)
    data["questions_model"] = ref
    data["questions_aggregate"] = {
        "questions": len(questions),
        "answered": _mean_sd([sum(a["answerable"] for a in r) for r in per_run]),
        "cited_rate": _mean_sd(
            [  # of the answers it could give: a refusal cites nothing
                sum(a["cited"] for a in r if a["answerable"])
                / max(sum(a["answerable"] for a in r), 1)
                for r in per_run
            ]
        ),
        "retried": _mean_sd([sum(a["retried"] for a in r) for r in per_run]),
        "unbacked": _mean_sd([sum(a["unbacked"] for a in r) for r in per_run]),
        "invalid_links": _mean_sd([sum(a["invalid_links"] for a in r) for r in per_run]),
        "seconds_mean": _mean_sd([sum(a["seconds"] for a in r) / n_q for r in per_run]),
    }
    (out_dir / "metrics.json").write_bytes(
        (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    )
    (out_dir / "summary.md").write_bytes(render_summary(data).encode("utf-8"))
    return data["questions_aggregate"]


def compare(dirs: list[Path]) -> str:
    """One Markdown table comparing several bench result folders."""
    datas = [json.loads((d / "metrics.json").read_bytes().decode("utf-8")) for d in dirs]
    cols = [d["label"] for d in datas]
    rows: list[tuple[str, list[str]]] = []

    def row(name: str, fn, key: str = "aggregate") -> None:
        cells = []
        for d in datas:
            try:
                cells.append(fn(d[key]))
            except (KeyError, TypeError):
                cells.append("–")
        rows.append((name, cells))

    row("runs", lambda a: str(a["runs"]))
    row("time (min)", lambda a: _fmt(a["minutes"], 1))
    row("pages", lambda a: _fmt(a["pages"], 1))
    row("gold found", lambda a: f"{_fmt(a['gold_found'], 1)} / {a['gold_total']}")
    row("core merged", lambda a: f"{_fmt(a['core_merged'], 1)} / {a['core_total']}")
    row("wrong merges", lambda a: _fmt(a["wrong_merges"], 1))
    row("gold duplicates", lambda a: _fmt(a["duplicates"], 1))
    row("rejected edits", lambda a: _fmt(a["rejected"], 1))
    row("lint errors", lambda a: _fmt(a["lint_errors"], 1))
    row("links per page", lambda a: _fmt(a["links_per_page"]))
    row("citation coverage", lambda a: _fmt(a["citation_coverage"], pct=True))
    row("unbacked expansions", lambda a: _fmt(a["unbacked_expansions"], 1))
    row("near-dup bullets", lambda a: _fmt(a["duplicate_bullet_rate"], pct=True))
    row("source headings", lambda a: _fmt(a["source_structure_headings"], pct=True))
    row("sections / page", lambda a: _fmt(a["sections_per_page"]))
    for key in ("structure", "redundancy", "clarity"):
        row(f"judge {key}", lambda a, k=key: _fmt(a[f"judge_{k}"]))
    row("questions answered", lambda q: f"{_fmt(q['answered'], 1)} / {q['questions']}",
        "questions_aggregate")  # fmt: skip
    row("answers citing a source", lambda q: _fmt(q["cited_rate"], pct=True), "questions_aggregate")
    for role in ROLES:
        row(
            f"{role}: valid JSON",
            lambda a, r=role: _fmt(a["roles"][r]["json_ok_first_try"], pct=True),
        )
        row(f"{role}: minutes", lambda a, r=role: _fmt(a["roles"][r]["minutes"], 1))
    out = ["| | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    out += [f"| {name} | " + " | ".join(cells) + " |" for name, cells in rows]
    return "\n".join(out) + "\n"
