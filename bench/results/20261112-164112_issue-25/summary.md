# Bench `issue-25`

3 runs (3 completed) over rocc-doc-1, rfm-gis-ad3, rfm-gis-ws1. Values are mean ± sd over runs.

| Role | Model | Thinking |
|---|---|---|
| extract | `ollama:qwen3:14b` | off |
| resolve | `ollama:qwen3:14b` | on |
| patch | `ollama:qwen3:14b` | off |
| summary | `ollama:qwen3:14b` | off |
| judge | `ollama:qwen3:14b` | off |

## Result

| Metric | Value |
|---|---|
| time (min) | 17.6 ± 0.7 |
| pages | 116.0 ± 2.0 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 31.7 ± 1.2 |
| core merged across sources (of 14) | 8.7 ± 0.6 |
| wrong merges | 0.0 |
| gold duplicates | 3.3 ± 1.2 |
| links per page | 1.80 ± 0.08 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 0.0 |
| sections per page | 1.35 ± 0.02 |
| bullets per page | 2.60 ± 0.06 |
| near-duplicate bullets | 0% ± 0% |
| headings copied from the source | 86% ± 2% |
| judge: structure (1-5) | 3.06 ± 0.12 |
| judge: redundancy (1-5) | 3.54 ± 0.23 |
| judge: clarity (1-5) | 3.91 ± 0.16 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.6 ± 0.1 | 12.76 ± 0.21 | 2283 |
| patch | 135 ± 5 | 100% | 0.0 | 4.9 ± 0.0 | 2.18 ± 0.07 | 2325 ± 109 |
| resolve | 157 ± 10 | 100% | 0.0 | 8.8 ± 0.7 | 3.36 ± 0.14 | 268 ± 2 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.36 ± 0.31 | 5820 |
