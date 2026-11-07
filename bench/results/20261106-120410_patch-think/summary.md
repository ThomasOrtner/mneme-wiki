# Bench `patch-think`

1 runs (1 completed) over rocc-doc-1, rfm-gis-ad3, rfm-gis-ws1. Values are mean ± sd over runs.

| Role | Model | Thinking |
|---|---|---|
| extract | `ollama:qwen3:14b` | off |
| resolve | `ollama:qwen3:14b` | on |
| patch | `ollama:qwen3:14b` | on |
| summary | `ollama:qwen3:14b` | off |
| judge | `ollama:qwen3:14b` | off |

## Result

| Metric | Value |
|---|---|
| time (min) | 86.9 |
| pages | 115.0 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 31.0 |
| core merged across sources (of 14) | 9.0 |
| wrong merges | 0.0 |
| gold duplicates | 5.0 |
| links per page | 1.72 |
| citation coverage | 100% |
| sections per page | 1.49 |
| bullets per page | 2.68 |
| near-duplicate bullets | 1% |
| headings copied from the source | 67% |
| judge: structure (1-5) | 3.40 |
| judge: redundancy (1-5) | 3.53 |
| judge: clarity (1-5) | 3.87 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.6 | 12.82 | 2124 |
| patch | 137 | 99% | 0.0 | 74.1 | 32.47 | 2115 |
| resolve | 135 | 100% | 0.0 | 7.1 | 3.15 | 239 |
| summary | 3 | 100% | 0.0 | 0.2 | 4.63 | 5801 |
