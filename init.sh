#!/usr/bin/env bash
# init.sh: bring mneme-wiki to a known-good state and prove it works.
# Run at the start and end of every agent session. Works on Linux/macOS
# and in Git Bash on Windows. Needs no Ollama: model paths are covered by
# pytest with a fake LLM; real runs stay opt-in (pytest -m ollama).
#
#   ./init.sh                  install + ruff + tests + end-to-end smoke
#   SKIP_INSTALL=1 ./init.sh   skip the pip install step (faster reruns)
#
# Exits non-zero on the first failure. A red init.sh means: fix the
# baseline before doing anything else.

set -euo pipefail

cd "$(dirname "$0")"
echo "== repo root: $(pwd)"

# --- Python + venv ----------------------------------------------------------
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || { echo "FAIL: need Python >= 3.10 on PATH"; exit 1; }

if [ ! -d .venv ]; then
  echo "== creating .venv"
  "$PY" -m venv .venv
fi

if [ -f .venv/Scripts/activate ]; then
  # shellcheck disable=SC1091
  source .venv/Scripts/activate   # Windows (Git Bash)
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
export PYTHONIOENCODING=utf-8

if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  echo "== installing (editable, with dev extras)"
  python -m pip install -q -e ".[dev]"
fi

# --- Lint + tests -----------------------------------------------------------
echo "== ruff"
python -m ruff check .
python -m ruff format --check . >/dev/null

echo "== pytest"
python -m pytest -q

# --- End-to-end smoke through the real CLI ----------------------------------
# Only fixtures and throwaway vaults; never the dev vault, a user vault or the
# private bench corpus.
SMOKE_DIR="$(mktemp -d)"
trap 'rm -rf "$SMOKE_DIR"' EXIT
VAULT="$SMOKE_DIR/vault"

echo "== smoke: init"
mneme-wiki init "$VAULT" --json >/dev/null
for f in WIKI.md index.md log.md; do
  [ -f "$VAULT/$f" ] || { echo "FAIL: init did not create $f"; exit 1; }
done
if [ -z "$(git -C "$VAULT" log --oneline 2>/dev/null)" ]; then
  echo "FAIL: init did not make a first commit"; exit 1
fi

echo "== smoke: lint on a fresh vault"
mneme-wiki lint --vault "$VAULT" | tail -1

echo "== smoke: status"
STATUS_OUT="$(mneme-wiki status --vault "$VAULT" --json)"
if ! echo "$STATUS_OUT" | grep -q '"uncommitted_changes": false'; then
  echo "FAIL: a fresh vault reports uncommitted changes"; exit 1
fi

echo "== smoke: integrate --stage chunk (no model call, nothing written)"
mneme-wiki integrate tests/fixtures/packets/ops-handbook --vault "$VAULT" \
  --stage chunk --out "$SMOKE_DIR/chunks.json" >/dev/null
if ! grep -q '"locator": "Rover Operations Handbook"' "$SMOKE_DIR/chunks.json"; then
  echo "FAIL: chunk stage output lacks the handbook locator"; exit 1
fi
if [ -n "$(git -C "$VAULT" status --porcelain)" ]; then
  echo "FAIL: --stage chunk wrote to the vault"; exit 1
fi

echo "== smoke: lint + search + reindex on the clean fixture vault"
FIXTURE="$SMOKE_DIR/clean"
cp -r tests/fixtures/clean "$FIXTURE"
mneme-wiki lint --vault "$FIXTURE" | tail -1
SEARCH_OUT="$(mneme-wiki search "operations control" --vault "$FIXTURE" --limit 1 --json)"
if ! echo "$SEARCH_OUT" | grep -q '"path": "entities/rover-operations-control-centre.md"'; then
  echo "FAIL: search did not rank the ROCC entity page first"; exit 1
fi
mneme-wiki reindex --vault "$FIXTURE" >/dev/null

# Add smoke steps for new commands here as features land.

echo
echo "OK: baseline is green."
