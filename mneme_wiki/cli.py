"""Command-line interface (thin): parse arguments, call library code, print.

Humans get `rich` output; `--json` prints one JSON object on stdout (TD-11).
This is the only module that prints.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from . import __version__, config
from .index_log import append_log, reindex
from .integrate import STAGES, integrate
from .lint import lint
from .packet import PacketError
from .search import search
from .vault import Vault, VaultError, init_vault

console = Console(highlight=False, soft_wrap=True)
err_console = Console(stderr=True, highlight=False, soft_wrap=True)


def _emit_json(data: dict) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def cmd_init(args: argparse.Namespace) -> int:
    log = (lambda _msg: None) if args.json else (lambda msg: console.print(msg))
    try:
        vault = init_vault(Path(args.path), language=args.language, log=log)
    except VaultError as exc:
        if args.json:
            _emit_json({"ok": False, "error": str(exc)})
        else:
            err_console.print(f"[red]error:[/red] {exc}")
        return 1
    inbox = config.inbox_dir(vault.root)
    if args.json:
        _emit_json({"ok": True, "vault": str(vault.root), "inbox": str(inbox)})
    else:
        console.print(f"[green]Vault ready:[/green] {vault.root}")
        console.print(f"  open it in Obsidian as a vault; source packets go to {inbox}")
        console.print(f"  use it by default: set WIKI_VAULT_DIR={vault.root}")
    return 0


def _vault(args: argparse.Namespace) -> Vault:
    root = Path(args.vault) if args.vault else config.VAULT_DIR
    if not root.is_dir():
        raise VaultError(f"vault folder {root} does not exist; set WIKI_VAULT_DIR or pass --vault")
    return Vault(root)


def _fail(args: argparse.Namespace, exc: Exception) -> int:
    if getattr(args, "json", False):
        _emit_json({"ok": False, "error": str(exc)})
    else:
        err_console.print(f"[red]error:[/red] {exc}")
    return 2


def cmd_lint(args: argparse.Namespace) -> int:
    try:
        report = lint(_vault(args))
    except VaultError as exc:
        return _fail(args, exc)
    if args.json:
        _emit_json(report.to_dict())
    else:
        for f in report.findings:
            colour = "red" if f.level == "error" else "yellow"
            console.print(
                f"[{colour}]{f.level:7}[/{colour}] {f.path}:{f.line}  [bold]{f.check}[/bold]  "
                f"{escape(f.message)}"
            )
        summary = (
            f"{report.pages} pages, {len(report.errors)} errors, {len(report.warnings)} warnings"
        )
        console.print(("[green]ok[/green] " if report.ok else "[red]failed[/red] ") + summary)
    return 0 if report.ok else 1


def cmd_reindex(args: argparse.Namespace) -> int:
    try:
        vault = _vault(args)
        changed = reindex(vault)
        if changed:
            append_log(vault, "reindex", "index", ["`index.md` regenerated."])
    except VaultError as exc:
        return _fail(args, exc)
    if args.json:
        _emit_json({"ok": True, "changed": changed})
    else:
        console.print("index.md regenerated" if changed else "index.md already up to date")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    try:
        hits = search(_vault(args), args.query, limit=args.limit, types=args.type or None)
    except VaultError as exc:
        return _fail(args, exc)
    if args.json:
        _emit_json({"ok": True, "query": args.query, "hits": [h.to_dict() for h in hits]})
    else:
        if not hits:
            console.print("no matches")
        for h in hits:
            console.print(f"{h.score:7.2f}  [bold]{escape(h.title)}[/bold]  ({h.path})")
            if h.snippet:
                console.print(f"         {escape(h.snippet)}")
    return 0


def _packet_dir(arg: str, vault: Vault) -> Path:
    """A packet folder given as a path, or as a name inside the vault's inbox."""
    path = Path(arg)
    if path.is_dir():
        return path
    in_inbox = config.inbox_dir(vault.root) / arg
    if in_inbox.is_dir():
        return in_inbox
    raise PacketError(
        f"no packet folder {arg!r} (not a path, not in {config.inbox_dir(vault.root)})"
    )


def cmd_integrate(args: argparse.Namespace) -> int:
    if args.stage and (len(args.packets) != 1 or not args.out):
        return _fail(args, ValueError("--stage needs exactly one packet and --out FILE"))
    # Progress goes to stderr when stdout carries JSON.
    out = err_console if args.json else console

    def log(msg: str) -> None:
        out.print(escape(msg))

    reports = []
    try:
        vault = _vault(args)
        inbox = config.inbox_dir(vault.root)
        for arg in args.packets:
            report = integrate(
                vault, _packet_dir(arg, vault), inbox=inbox, dry_run=args.dry_run,
                stop_after=args.stage, log=log, project=args.project,
            )  # fmt: skip
            reports.append(report)
            if args.stage:
                data = json.dumps(report.stage_output, ensure_ascii=False, indent=1)
                Path(args.out).write_bytes((data + "\n").encode("utf-8"))
                log(f"stage {args.stage} output written to {args.out}")
            elif args.dry_run and not args.json:
                console.print(escape(report.diff) if report.diff else "(no changes)")
            if not report.ok:
                break
    except (VaultError, PacketError, ValueError) as exc:
        if reports and args.json:
            _emit_json({"ok": False, "error": str(exc), "runs": [_run_json(r) for r in reports]})
            return 2
        return _fail(args, exc)
    ok = all(r.ok for r in reports)
    if args.json:
        _emit_json({"ok": ok, "runs": [_run_json(r, args.dry_run) for r in reports]})
    else:
        for r in reports:
            if r.stopped_after:
                console.print(f"stopped after stage {r.stopped_after}; nothing was written")
                continue
            state = "[green]ok[/green]" if r.ok else "[red]failed[/red]"
            verb = "would be" if r.dry_run else "were"
            console.print(
                f"{state} {escape(r.title)}: {len(r.created)} pages {verb} created, "
                f"{len(r.updated)} updated, {len(r.rejected)} edits rejected; "
                f"report {r.run_dir}/report.md"
            )
    return 0 if ok else 1


def _run_json(report, with_diff: bool = False) -> dict:
    data = report.to_dict()
    data.pop("stage_output", None)
    if not with_diff:
        data.pop("diff", None)
    return data


def cmd_status(args: argparse.Namespace) -> int:
    from .status import overview

    try:
        data = overview(_vault(args))
    except (VaultError, OSError) as exc:
        return _fail(args, exc)
    if args.json:
        _emit_json({"ok": True, **data})
        return 0
    pages = ", ".join(f"{n} {t}" for t, n in data["pages"].items()) or "no pages"
    console.print(f"[bold]{escape(data['vault'])}[/bold]: {pages}")
    if data["unreadable_pages"]:
        console.print(f"[red]{data['unreadable_pages']} unreadable pages[/red]")
    gl = data["glossary"]
    if gl["active"] or gl["problems"]:
        problems = f", {gl['problems']} problems (see lint)" if gl["problems"] else ""
        console.print(f"glossary: {gl['terms']} terms{problems}")
    if data["git_head"] is None:
        console.print("git: not a repository")
    else:
        dirty = "[yellow]uncommitted changes[/yellow]" if data["uncommitted_changes"] else "clean"
        console.print(f"git: {escape(data['git_head'])} ({dirty})")
    for entry in data["last_log_entries"]:
        console.print(f"  {escape(entry)}")
    console.print(f"inbox: {escape(data['inbox'])}")
    for item in data["packets"]:
        state = item.get("error") or item.get("integrated_as") or "not integrated yet"
        console.print(f"  {escape(item['packet'])}: {escape(str(state))}")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    from .query import ask, file_answer

    out = err_console if args.json else console

    def log(msg: str) -> None:
        out.print(escape(msg))

    try:
        vault = _vault(args)
        result = ask(vault, args.question, log=log)
    except (VaultError, ValueError) as exc:
        return _fail(args, exc)
    file_error = None
    if args.file:  # a refused filing must not cost the user the answer
        try:
            file_answer(vault, result, log=log)
        except VaultError as exc:
            file_error = str(exc)
    if args.json:
        ok = result.error is None and file_error is None
        _emit_json({"ok": ok, **result.to_dict(), "file_error": file_error})
    else:
        console.print(escape(result.answer or f"(no answer: {result.error})"))
        if result.pages:
            console.print("\n[dim]pages used:[/dim] " + ", ".join(result.pages))
        if result.filed:
            console.print(f"[green]filed as[/green] {result.filed}")
        if result.answerable and not result.sources:
            err_console.print("[yellow]warning:[/yellow] this answer cites no source")
        for item in result.unbacked:
            err_console.print(f"[yellow]warning:[/yellow] not backed by the pages: {escape(item)}")
        if file_error:
            err_console.print(f"[red]not filed:[/red] {escape(file_error)}")
    if file_error:
        return 2
    return 0 if result.error is None else 1


def cmd_bench(args: argparse.Namespace) -> int:
    from . import bench  # heavy imports only when benchmarking

    if args.compare:
        try:
            console.print(bench.compare([Path(d) for d in args.compare]), markup=False)
        except (OSError, ValueError, KeyError) as exc:
            return _fail(args, exc)
        return 0
    if args.ask:
        qfile = Path(args.questions or Path(args.corpus) / "questions.md")
        try:
            questions = bench.load_questions(qfile)
            for d in args.ask:
                agg = bench.run_questions(
                    Path(d), questions, query_model=args.query_model,
                    log=lambda m: err_console.print(escape(m)),
                )  # fmt: skip
                console.print(f"{d}: {json.dumps(agg)}", markup=False)
        except (OSError, ValueError, KeyError, VaultError) as exc:
            return _fail(args, exc)
        return 0
    if not args.models:
        return _fail(args, ValueError("--models MAPPING.toml is required (or --compare DIR...)"))
    out = err_console if args.json else console

    def log(msg: str) -> None:
        out.print(escape(msg))

    try:
        mapping = bench.load_mapping(args.models, args.label)
        result = bench.run_bench(
            mapping, Path(args.corpus), out_root=Path(args.out), repeats=args.repeat,
            packet_names=args.packets or None, log=log,
        )  # fmt: skip
    except (bench.BenchError, VaultError, PacketError, ValueError) as exc:
        return _fail(args, exc)
    if args.json:
        _emit_json({"ok": True, "out": str(result.out_dir), "aggregate": result.aggregate})
    else:
        console.print((result.out_dir / "summary.md").read_text(encoding="utf-8"), markup=False)
        console.print(f"results: {result.out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mneme-wiki", description="Local, LLM-maintained wiki of interlinked Markdown notes."
    )
    parser.add_argument("--version", action="version", version=f"mneme-wiki {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a new vault (folders, WIKI.md, index, log, git)")
    p.add_argument("path", help="folder for the new vault (must not exist or be empty)")
    p.add_argument(
        "--language",
        default=config.LANGUAGE,
        help=f"language of non-source pages (default: {config.LANGUAGE})",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_init)

    def vault_cmd(name: str, help_text: str, func) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "--vault", help=f"vault folder (default: WIKI_VAULT_DIR = {config.VAULT_DIR})"
        )
        p.add_argument("--json", action="store_true", help="machine-readable output")
        p.set_defaults(func=func)
        return p

    p = vault_cmd(
        "integrate", "integrate source packets into the vault (one commit each)", cmd_integrate
    )
    p.add_argument("packets", nargs="+", help="packet folder, or a packet name in the inbox")
    p.add_argument(
        "--dry-run", action="store_true", help="run every stage, print the diff, write nothing"
    )
    p.add_argument("--stage", choices=STAGES, help="stop after this stage (nothing is written)")
    p.add_argument("--out", help="with --stage: write the stage's output to this JSON file")
    p.add_argument(
        "--project",
        help="the project the packets belong to, for packets without a `project` field; "
        "their document-local ids (WP2) are expanded to it",
    )
    vault_cmd("lint", "check links, front matter, citations; exit 1 on errors", cmd_lint)
    vault_cmd("reindex", "regenerate index.md from the pages", cmd_reindex)
    p = vault_cmd("search", "BM25 search over pages", cmd_search)
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument(
        "--type",
        action="append",
        choices=("source", "entity", "concept", "synthesis"),
        help="only pages of this type (repeatable)",
    )

    vault_cmd("status", "pages, recent log entries, git state, inbox packets", cmd_status)
    p = vault_cmd("query", "answer a question from the wiki, with citations", cmd_query)
    p.add_argument("question")
    p.add_argument(
        "--file", action="store_true", help="save the answer as a synthesis page (one commit)"
    )

    p = sub.add_parser("bench", help="benchmark models per stage role on a fixed corpus")
    p.add_argument("--models", help="mapping file (TOML): model + thinking per role")
    p.add_argument("--label", help="name of this configuration (default: from the mapping)")
    p.add_argument("--repeat", type=int, default=3, help="runs per configuration (default 3)")
    p.add_argument("--corpus", default="bench/corpus", help="folder with packets + gold.json")
    p.add_argument("--packets", nargs="*", help="packet names in order (default: order.txt)")
    p.add_argument("--out", default="bench/results", help="results folder")
    p.add_argument("--compare", nargs="+", metavar="DIR", help="compare finished result folders")
    p.add_argument(
        "--ask", nargs="+", metavar="DIR", help="ask the question set against finished results"
    )
    p.add_argument("--questions", help="question file (default: <corpus>/questions.md)")
    p.add_argument("--query-model", help="model for --ask (default: MODEL_QUERY)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_bench)
    return parser


def _utf8_pipes() -> None:
    """Piped output on Windows defaults to the ANSI code page (cp1252), which can't
    encode page titles in other scripts, or the progress glyphs. A terminal is
    fine (Python uses the console API there), so only pipes are switched."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_pipes()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
