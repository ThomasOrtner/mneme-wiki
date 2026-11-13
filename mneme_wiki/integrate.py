"""Integrate one source packet into a vault: the stage orchestration (M3).

chunk → extract → merge in source → resolve → names (#25) → plan → source page → patch + apply
(per page) → autolink → touched-pages list → reindex → lint → log → one git commit.

Every write goes into a `Workspace` first. Nothing reaches the vault until all
stages have run and lint shows no *new* errors; then the workspace is flushed and
committed. `dry_run` stops before the flush and returns the diff instead.
`stop_after` ends after a named stage and returns that stage's output (the CLI's
`--stage S --out F`).

Run artifacts (calls, resolve decisions, stage outputs, report) go to
`<vault>/.mneme-wiki/runs/<run-id>/` (git-ignored, TD-4). Rejected edits go to
`<inbox>/rejected/<run-id>/`.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, edits, expansions, glossary, links, packet
from . import frontmatter as fm
from .index_log import append_log, reindex
from .lint import lint
from .llm import LLM, Call
from .stages import autolink as autolink_stage
from .stages import extract as extract_stage
from .stages import names as names_stage
from .stages import patch as patch_stage
from .stages import plan as plan_stage
from .stages import resolve as resolve_stage
from .stages import source as source_stage
from .stages.common import known_pages, name_key
from .vault import SCHEMA_FILE, Vault, VaultError, slugify
from .workspace import Workspace

STAGES = ("chunk", "extract", "resolve", "plan", "patch")
RUNS_DIR = ".mneme-wiki/runs"
Log = Callable[[str], None]


class IntegrateError(VaultError):
    pass


@dataclass
class Report:
    run_id: str
    packet: str
    title: str
    dry_run: bool
    run_dir: str
    source_page: str | None = None
    words: int = 0
    chunks: int = 0
    subjects: int = 0
    merged: int = 0
    resolve: dict[str, int] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # subjects with no backed name (#25)
    autolinks: int = 0
    counters: dict[str, int] = field(default_factory=dict)
    calls: dict[str, dict] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)
    lint_errors: int = 0
    lint_warnings: int = 0
    new_lint_errors: list[str] = field(default_factory=list)
    commit: str | None = None
    rejected_dir: str | None = None
    stopped_after: str | None = None
    stage_output: object = None
    diff: str = ""

    @property
    def ok(self) -> bool:
        return not self.new_lint_errors

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


def run_id_for(name: str, now: dt.datetime) -> str:
    return f"{now:%Y%m%d-%H%M%S}-{slugify(name, 40)}"


def vault_language(vault: Vault) -> str:
    try:
        meta = fm.parse(vault.read_text(SCHEMA_FILE)).meta
    except (FileNotFoundError, fm.FrontMatterError):
        return config.LANGUAGE
    return str(meta.get("language") or config.LANGUAGE)


def _call_stats(calls: list[Call]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for role in dict.fromkeys(c.role for c in calls):
        cs = [c for c in calls if c.role == role]
        out[role] = {
            "calls": len(cs),
            "ok_rate": round(sum(c.ok for c in cs) / len(cs), 3),
            "retries": sum(c.attempt > 1 for c in cs),
            "latency_s_total": round(sum(c.latency_s for c in cs), 1),
            "latency_s_mean": round(sum(c.latency_s for c in cs) / len(cs), 2),
            "tokens_in_max": max(c.tokens_in for c in cs),
            "tokens_out_mean": round(sum(c.tokens_out for c in cs) / len(cs)),
        }
    return out


def _strip_expansions(
    ws: Workspace, vault: Vault, paths: list[str], source_text: str, counters: dict[str, int]
) -> None:
    """Remove abbreviation expansions this run invented (runs before autolink, whose links
    would split the phrases). What the page already said or was named before this run is
    evidence, so text that was in the vault before this run is left alone. A new page's
    own title and aliases are not (#25): they come from this run's model output."""
    for rel in paths:
        page = ws.read_page(rel)
        evidence = [source_text]
        if vault.exists(rel):
            old = vault.read_page(rel)
            aliases = old.meta.get("aliases") if isinstance(old.meta.get("aliases"), list) else []
            evidence += [old.title, *map(str, aliases), old.body]
        evidence = "\n".join(evidence)
        body = expansions.strip(page.body, evidence, counters)
        if body != page.body:
            page.body = body
            ws.write_page(page)


def _merge_counters(into: dict[str, int], more: dict[str, int], prefix: str = "") -> None:
    for k, v in more.items():
        into[prefix + k] = into.get(prefix + k, 0) + v


def integrate(
    vault: Vault,
    packet_dir: Path | str,
    *,
    llm: LLM | None = None,
    inbox: Path | None = None,
    dry_run: bool = False,
    stop_after: str | None = None,
    today: dt.date | None = None,
    log: Log = lambda _m: None,
) -> Report:
    if stop_after is not None and stop_after not in STAGES:
        raise IntegrateError(f"unknown stage {stop_after!r} (one of {', '.join(STAGES)})")
    pkt = packet.load(packet_dir)
    now = dt.datetime.now()
    day = today or now.date()
    run_id = run_id_for(pkt.name, now)
    writes_vault = not dry_run and stop_after is None
    if writes_vault:
        if not vault.is_repo():
            raise IntegrateError(f"{vault.root} is not a git repository (run `mneme-wiki init`)")
        if not vault.is_clean():
            raise IntegrateError(
                "the vault has uncommitted changes; commit or discard them first, so this "
                "integration is one reviewable commit (BR-11)"
            )
    ws = Workspace(vault)
    existing = source_stage.find_existing(ws, str(pkt.meta["origin"]))
    if existing:
        raise IntegrateError(f"{pkt.meta['origin']} is already integrated as {existing}")

    run_dir = f"{RUNS_DIR}/{run_id}"
    report = Report(run_id, pkt.name, pkt.title, not writes_vault, run_dir, words=pkt.words)
    calls_lines: list[str] = []

    def on_call(call: Call) -> None:
        calls_lines.append(json.dumps(call.to_dict(), ensure_ascii=False))

    llm = llm or LLM(log=log)
    llm.log, llm.on_call = log, on_call
    first_call = len(llm.calls)

    def artifact(name: str, data: object) -> None:
        body = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1)
        vault.write_text(f"{run_dir}/{name}", body if body.endswith("\n") else body + "\n")

    def flush_calls() -> None:
        if calls_lines:
            artifact("calls.jsonl", "\n".join(calls_lines))

    clock = {"t": time.monotonic()}

    def lap(stage: str) -> None:
        now_t = time.monotonic()
        report.seconds[stage] = round(now_t - clock["t"], 1)
        clock["t"] = now_t

    def stop(stage: str, output: object) -> Report:
        report.stopped_after = stage
        report.stage_output = output
        artifact(f"{stage}.json", output)
        return _finish_report(report, llm.calls[first_call:], artifact, flush_calls)

    counters: dict[str, int] = {}
    language = vault_language(vault)
    log(f"━━ {pkt.title} ({pkt.words} words) → {vault.root}   run {run_id}")

    # -- chunk ---------------------------------------------------------------------
    chunks = packet.chunk(pkt.text)
    report.chunks = len(chunks)
    lap("chunk")
    log(f"chunk: {len(chunks)} chunks of ≤ {packet.CHUNK_WORDS} words")
    if stop_after == "chunk":
        return stop("chunk", [asdict(c) for c in chunks])

    # -- extract + merge ---------------------------------------------------------------
    known = known_pages(ws)
    gl = glossary.load(ws)  # empty without glossary.md: every stage behaves as before
    log(f"extract: {len(chunks)} calls, vault has {len(known)} entity/concept pages")
    subjects = extract_stage.extract(
        llm, pkt, chunks, known, log=log, counters=counters, glossary=gl
    )
    glossary.canonicalise(subjects, gl, counters)
    groups = extract_stage.merge_within_source(subjects)
    report.subjects, report.merged = len(subjects), len(groups)
    artifact("extract.json", [g.to_dict() for g in groups])
    flush_calls()
    lap("extract")
    log(f"    {len(subjects)} subjects, {len(groups)} after merging within the source")
    if stop_after == "extract":
        return stop("extract", [g.to_dict() for g in groups])

    # -- resolve -------------------------------------------------------------------------
    log("resolve: exact names, then pairwise yes/no per candidate")
    resolved, decisions = resolve_stage.resolve(llm, groups, known, log=log, counters=counters)
    artifact("resolve_log.jsonl", "\n".join(json.dumps(d.to_dict(), ensure_ascii=False)
                                            for d in decisions))  # fmt: skip
    flush_calls()
    by_how = Counter(r.how for r in resolved)
    report.resolve = {
        "exact": by_how["exact"],
        "model": by_how["llm"],
        "new": by_how["new"],
        "merged_in_source": counters.get("resolve_exact_within_source", 0)
        + counters.get("resolve_llm_within_source", 0),
        "model_calls": counters.get("resolve_llm_calls", 0),
    }
    lap("resolve")
    log(f"    matched {by_how['exact']} exact + {by_how['llm']} by model, {by_how['new']} new")
    if stop_after == "resolve":
        return stop("resolve", [r.to_dict() for r in resolved])

    # -- names: new titles and aliases must be in the source (#25) ------------------------
    curated = [n for t in gl.terms for n in t.names()]
    evidence = names_stage.Evidence(pkt.text, known, pkt.title, curated)
    resolved, changes = names_stage.check(resolved, known, evidence, log=log, counters=counters)
    report.skipped = [c.subject for c in changes if c.change == "subject_skipped"]
    artifact("names.json", [c.to_dict() for c in changes])
    if changes:
        log(f"names: {len(changes)} unbacked names fixed, {len(report.skipped)} subjects skipped")

    # -- plan ------------------------------------------------------------------------------
    plans = plan_stage.plan(resolved, ws, owner=pkt.title, counters=counters, glossary=gl)
    artifact("plan.json", [p.to_dict() for p in plans])
    lap("plan")
    n_new = sum(p.new for p in plans)
    log(f"plan: {n_new} new pages, {len(plans) - n_new} existing pages to update")
    if stop_after == "plan":
        return stop("plan", [p.to_dict() for p in plans])

    # -- source page -------------------------------------------------------------------------
    source_path = _source_path(ws, pkt.title)
    summary = source_stage.summarise(llm, pkt)
    src_page = source_stage.source_page(pkt, source_path, summary, day)
    ws.write_page(src_page)
    report.source_page = source_path
    source_link = source_path.removesuffix(".md")

    # -- patch + apply -------------------------------------------------------------------------
    ctx = edits.Context(source_link, links.LinkIndex([*ws.files(), *(p.path for p in plans)]))
    reserved = _reserved_names(ws, plans)
    results: list[patch_stage.PatchResult] = []
    for n, entry in enumerate(plans, 1):
        step = f"patch {n}/{len(plans)} {'+' if entry.new else '~'} {entry.path}"
        res = patch_stage.patch_page(
            llm, ws, entry, plans, known, ctx, source_title=pkt.title, language=language,
            today=day, step=step, reserved_names=reserved, glossary=gl,
        )  # fmt: skip
        results.append(res)
        _merge_counters(counters, res.counters, "patch_")
        for rej in res.rejected:
            log(f"    ✗ {entry.path}: {rej.reason}")
        if res.error:
            log(f"    ✗ {entry.path}: {res.error}")
    flush_calls()
    lap("patch")
    written = [r for r in results if r.written]
    report.created = sorted(r.path for r in written if r.new)
    report.updated = sorted(r.path for r in written if not r.new)
    report.rejected = [{"page": r.path, **rej.to_dict()} for r in results for rej in r.rejected] + [
        {"page": r.path, "reason": r.error, "retry": False} for r in results if r.error
    ]

    # -- abbreviations, autolink, source page list ------------------------------------------------
    touched = [r.path for r in written]
    evidence_text = f"{pkt.title}\n{pkt.text}\n{gl.evidence()}"
    _strip_expansions(ws, vault, [*touched, source_path], evidence_text, counters)
    added = autolink_stage.autolink(ws, [*touched, source_path], gl)
    report.autolinks = sum(added.values())
    src_page = ws.read_page(source_path)
    # The page's own title, not the subject name it was matched under.
    source_stage.set_touched(src_page, [(p, ws.read_page(p).title) for p in touched])
    ws.write_page(src_page)
    lap("autolink")
    log(f"autolink: {report.autolinks} links added on {len(added)} pages")

    # -- reindex, lint, log ------------------------------------------------------------------------
    before = {_finding_key(f) for f in lint(vault).errors}
    reindex(ws, today=day)
    after_report = lint(ws)
    report.lint_errors = len(after_report.errors)
    report.lint_warnings = len(after_report.warnings)
    report.new_lint_errors = sorted(
        f"{f.path}:{f.line} {f.check} {f.message}"
        for f in after_report.errors
        if _finding_key(f) not in before
    )
    report.counters = counters
    keep = writes_vault and report.rejected  # dry runs leave the inbox alone
    rejected_dir = _save_rejections(inbox, run_id, report, results) if keep else None
    report.rejected_dir = str(rejected_dir) if rejected_dir else None
    append_log(ws, "integrate", pkt.title, _log_lines(report, source_link), today=day)
    lap("finish")
    report.diff = ws.diff()
    if stop_after == "patch":
        return stop("patch", {"pages": [r.to_dict() for r in results], "diff": report.diff})
    if report.new_lint_errors:
        artifact("diff.patch", report.diff)
        log(f"✗ lint found {len(report.new_lint_errors)} new errors; nothing was written")
        for line in report.new_lint_errors[:20]:
            log(f"    {line}")
        return _finish_report(report, llm.calls[first_call:], artifact, flush_calls)
    if dry_run:
        artifact("diff.patch", report.diff)
        log(f"dry run: {len(ws.changes)} files would change; nothing was written")
        return _finish_report(report, llm.calls[first_call:], artifact, flush_calls)

    ws.flush()
    report.commit = vault.commit(_commit_message(report))
    sha = report.commit[:7] if report.commit else "-"
    log(
        f"✓ committed {sha}: {len(report.created)} created, {len(report.updated)} updated, "
        f"{len(report.rejected)} edits rejected"
    )
    return _finish_report(report, llm.calls[first_call:], artifact, flush_calls)


def _finish_report(report: Report, calls: list[Call], artifact, flush_calls) -> Report:
    report.calls = _call_stats(calls)
    flush_calls()
    data = report.to_dict()
    data.pop("diff", None)
    artifact("report.json", data)
    artifact("report.md", render_report(report))
    return report


def _source_path(ws: Vault, title: str) -> str:
    base = slugify(title)
    for n in range(1, 50):
        try:
            rel = ws.path_for("source", base if n == 1 else f"{base}-{n}")
        except VaultError:
            continue
        if not ws.exists(rel):
            return rel
    raise IntegrateError(f"no free source page path for {title!r}")


def _reserved_names(ws: Vault, plans: list[plan_stage.PagePlan]) -> dict[str, str]:
    """name_key → page path for every title and alias in the vault and every new page."""
    out: dict[str, str] = {}
    for rel, page in ws.iter_pages():
        if isinstance(page, fm.FrontMatterError) or page.meta.get("type") not in fm.CONTENT_TYPES:
            continue
        aliases = page.meta.get("aliases") if isinstance(page.meta.get("aliases"), list) else []
        for n in [page.title, *aliases]:
            if isinstance(n, str) and name_key(n):
                out.setdefault(name_key(n), rel)
    for p in plans:
        if p.new:
            out.setdefault(name_key(p.title), p.path)
    return out


def _finding_key(f) -> tuple[str, str, str]:
    return (f.check, f.path, f.message)


def _save_rejections(
    inbox: Path | None, run_id: str, report: Report, results: list[patch_stage.PatchResult]
) -> Path | None:
    if inbox is None:
        return None
    box = Vault(inbox) if inbox.exists() else None
    if box is None:
        inbox.mkdir(parents=True, exist_ok=True)
        box = Vault(inbox)
    for r in results:
        if not r.rejected and not r.error:
            continue
        record = {
            "run": run_id,
            "packet": report.packet,
            "page": r.path,
            "error": r.error,
            "rejected": [x.to_dict() for x in r.rejected],
            "proposal": r.proposal,
        }
        name = slugify(r.path.removesuffix(".md").replace("/", "-")) + ".json"
        box.write_text(
            f"rejected/{run_id}/{name}", json.dumps(record, ensure_ascii=False, indent=1) + "\n"
        )
    return inbox / "rejected" / run_id


def _log_lines(report: Report, source_link: str) -> list[str]:
    def listing(paths: list[str]) -> str:
        return ", ".join(links.format_link(p) for p in paths) or "none"

    lines = [
        f"- source: [[{source_link}]]",
        f"- created: {listing(report.created)}",
        f"- updated: {listing(report.updated)}",
    ]
    if report.rejected:
        lines.append(f"- rejected edits: {len(report.rejected)} (`{report.rejected_dir}`)")
    lines.append(f"- run: `{report.run_dir}/`")
    return lines


def _commit_message(report: Report) -> str:
    return (
        f"integrate: {report.title}\n\n"
        f"created {len(report.created)}, updated {len(report.updated)} pages; "
        f"{len(report.rejected)} edits rejected; {report.autolinks} autolinks\n"
        f"run: {report.run_dir}\n"
    )


def render_report(r: Report) -> str:
    total = sum(r.seconds.values())
    lines = [
        f"# Integration run `{r.run_id}`",
        "",
        f"**{r.title}** (`{r.packet}`, {r.words} words, {r.chunks} chunks)"
        + (" — dry run, nothing written" if r.dry_run else ""),
        "",
        "| | |",
        "|---|---|",
        f"| subjects → merged in source | {r.subjects} → {r.merged} |",
        f"| resolved | {r.resolve.get('exact', 0)} exact, {r.resolve.get('model', 0)} by model, "
        f"{r.resolve.get('new', 0)} new ({r.resolve.get('model_calls', 0)} model decisions) |",
        f"| pages | {len(r.created)} created, {len(r.updated)} updated |",
        f"| rejected edits | {len(r.rejected)} |",
        f"| autolinks | {r.autolinks} |",
        f"| lint after | {r.lint_errors} errors ({len(r.new_lint_errors)} new), "
        f"{r.lint_warnings} warnings |",
        f"| commit | {r.commit or '-'} |",
        f"| time | {total / 60:.1f} min |",
        "",
        "## Stages",
        "",
        "| Stage | Seconds |",
        "|---|---|",
        *(f"| {k} | {v} |" for k, v in r.seconds.items()),
        "",
        "## Model calls",
        "",
        "| Role | Calls | Valid | Retries | Mean | Total | Max tokens in |",
        "|---|---|---|---|---|---|---|",
        *(
            f"| {role} | {s['calls']} | {s['ok_rate']:.0%} | {s['retries']} | "
            f"{s['latency_s_mean']}s | {s['latency_s_total'] / 60:.1f} min | {s['tokens_in_max']} |"
            for role, s in r.calls.items()
        ),
        "",
        "## Validation counters",
        "",
        *(f"- {k}: {v}" for k, v in sorted(r.counters.items())),
    ]
    if r.skipped:
        lines += ["", "## Skipped subjects (none of their names is in the source)", ""]
        lines += [f"- {name}" for name in r.skipped]
    if r.rejected:
        lines += ["", "## Rejected edits", ""]
        lines += [f"- `{x['page']}`: {x['reason']}" for x in r.rejected]
    if r.new_lint_errors:
        lines += ["", "## New lint errors (nothing was written)", ""]
        lines += [f"- {e}" for e in r.new_lint_errors]
    lines += [
        "",
        "## Look at next",
        "",
        f"- `git log --stat -1` in the vault{'' if r.commit else ' (no commit made)'}",
        f"- `{r.run_dir}/resolve_log.jsonl`: every resolve decision with the model's reason",
    ]
    if r.rejected_dir:
        lines.append(f"- `{r.rejected_dir}`: rejected edits with the model's proposal")
    return "\n".join(lines) + "\n"
