# Configuration

← [Home](Home.md)

All settings are environment variables, optionally from a `.env` file in the working
directory (copy `.env.example`). CLI flags such as `--vault` override them.

## Vault

| Variable | Default | Meaning |
|---|---|---|
| `WIKI_VAULT_DIR` | `examples/vault` | The vault to work on |
| `WIKI_INBOX_DIR` | `<vault>/../inbox` | Where source packets wait |
| `WIKI_LANGUAGE` | `en` | Language of every non-source page (source pages keep theirs) |

## Ollama

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server |
| `NUM_CTX` | `32768` | Context window requested per call |
| `MAX_OUTPUT_TOKENS` | `8192` | Hard cap on each answer; a cut-off answer counts as failed and is retried once |
| `CALL_TIMEOUT_S` | `600` | Hard cap on each call, in seconds |

## Models per role

Each pipeline stage has a **role**, and each role has its own model, as `backend:model`.
Ollama is the only backend for now.

| Variable | Default | Used by |
|---|---|---|
| `MODEL_EXTRACT` | `ollama:qwen3:14b` | Extract subjects and claims per chunk |
| `MODEL_RESOLVE` | `ollama:qwen3:14b` | Same thing or not (yes/no) |
| `MODEL_PATCH` | `ollama:qwen3:14b` | Rewrite one page |
| `MODEL_SUMMARY` | `ollama:qwen3:14b` | Source summary when the packet has none |
| `MODEL_QUERY` | `ollama:qwen3:14b` | Answer questions |
| `MODEL_JUDGE` | unset | Quality judge in the benchmark only |

## Thinking per role

`THINK_<ROLE>` = `1`/`0` switches qwen3's thinking mode.

| Variable | Default | Why |
|---|---|---|
| `THINK_RESOLVE` | `1` | Without thinking, resolve merged unrelated things |
| `THINK_PATCH` | `0` | 2.5× slower for no measurable gain |
| others | `0` | |

These defaults come from the [benchmark](Benchmark.md): `qwen3:14b` everywhere had the
best coverage and no wrong merges. Change them if you've measured something better on
your hardware.

## Example `.env`

```ini
WIKI_VAULT_DIR=D:\wikis\space-ops
WIKI_LANGUAGE=en
MODEL_PATCH=ollama:qwen3:30b-a3b
THINK_PATCH=0
```
