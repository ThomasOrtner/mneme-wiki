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

from . import __version__, config
from .vault import VaultError, init_vault

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
