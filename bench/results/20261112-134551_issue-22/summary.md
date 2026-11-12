# Bench `issue-22`

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
| time (min) | 17.5 ± 0.3 |
| pages | 122.3 ± 1.5 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 31.0 ± 2.0 |
| core merged across sources (of 14) | 8.3 ± 0.6 |
| wrong merges | 0.0 |
| gold duplicates | 2.3 ± 0.6 |
| links per page | 1.75 ± 0.13 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 1.7 ± 2.9 |
| sections per page | 1.29 ± 0.04 |
| bullets per page | 2.53 ± 0.06 |
| near-duplicate bullets | 0% |
| headings copied from the source | 86% ± 2% |
| judge: structure (1-5) | 3.06 ± 0.12 |
| judge: redundancy (1-5) | 3.78 ± 0.24 |
| judge: clarity (1-5) | 3.71 ± 0.10 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.6 ± 0.1 | 12.78 ± 0.36 | 2283 |
| patch | 141 ± 1 | 100% | 0.0 | 5.1 ± 0.1 | 2.16 ± 0.04 | 2252 ± 46 |
| resolve | 155 ± 5 | 100% | 0.0 | 8.5 ± 0.4 | 3.30 ± 0.07 | 264 ± 2 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.48 ± 0.35 | 5820 |
