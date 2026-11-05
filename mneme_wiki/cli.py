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
from .lint import lint
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
