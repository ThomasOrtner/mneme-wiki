# Bench `patch-think`

3 runs (3 completed) over rocc-doc-1, rfm-gis-ad3, rfm-gis-ws1. Values are mean ± sd over runs.

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
| time (min) | 37.9 ± 2.0 |
| pages | 108.7 ± 3.5 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 29.3 ± 1.2 |
| core merged across sources (of 14) | 8.3 ± 0.6 |
| wrong merges | 0.0 |
| gold duplicates | 2.3 ± 1.5 |
| links per page | 1.79 ± 0.18 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 1.7 ± 1.2 |
| sections per page | 1.46 ± 0.03 |
| bullets per page | 2.74 ± 0.12 |
| near-duplicate bullets | 1% ± 0% |
| headings copied from the source | 63% ± 5% |
| judge: structure (1-5) | 3.20 ± 0.24 |
| judge: redundancy (1-5) | 3.40 ± 0.18 |
| judge: clarity (1-5) | 3.62 ± 0.10 |
| questions answered (of 11) | 9.3 ± 0.6 |
| answers citing a source | 72% ± 6% |
| answers retried | – |
| unbacked expansions in answers | – |
| invalid links removed | 0.0 |
| query seconds / question | 6.3 ± 5.4 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.9 ± 0.6 | 13.85 ± 1.95 | 2124 |
| patch | 125 ± 4 | 100% ± 0% | 0.0 | 25.9 ± 1.9 | 12.39 ± 0.52 | 2092 ± 70 |
| resolve | 128 ± 10 | 100% | 0.0 | 7.2 ± 0.8 | 3.38 ± 0.18 | 252 ± 11 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.68 ± 0.20 | 5801 |
