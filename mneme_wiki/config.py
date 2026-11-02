"""All configuration: environment variables (optionally from `.env`) and defaults.

Nothing else in the package reads `os.environ`. Values are read at import time,
as in mneme; CLI flags override them by passing explicit arguments.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


# ---------------------------------------------------------------------------
# Vault & inbox
# ---------------------------------------------------------------------------
VAULT_DIR = Path(_env("WIKI_VAULT_DIR", "examples/vault"))
# Empty means "inbox next to the vault" — see inbox_dir().
INBOX_DIR = os.getenv("WIKI_INBOX_DIR", "").strip()
LANGUAGE = _env("WIKI_LANGUAGE", "en")

# ---------------------------------------------------------------------------
# Models (TD-14): one `backend:model` ref per stage role
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = _env("OLLAMA_BASE_URL", "http://localhost:11434")
NUM_CTX = int(_env("NUM_CTX", "32768"))

DEFAULT_MODEL = "ollama:qwen3:14b"
ROLES = ("extract", "resolve", "patch", "summary", "query", "judge")
MODELS: dict[str, str | None] = {
    role: _env(f"MODEL_{role.upper()}", DEFAULT_MODEL) for role in ROLES if role != "judge"
}
MODELS["judge"] = os.getenv("MODEL_JUDGE", "").strip() or None


def inbox_dir(vault: Path) -> Path:
    """The inbox for `vault`: WIKI_INBOX_DIR if set, else `<vault>/../inbox`.

    Many vaults can coexist (TD-16), so the default inbox belongs to the vault,
    not to the current working directory.
    """
    if INBOX_DIR:
        return Path(INBOX_DIR)
    return vault.resolve().parent / "inbox"
