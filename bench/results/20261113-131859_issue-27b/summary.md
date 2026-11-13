# Bench `issue-27b`

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
| time (min) | 16.3 ± 0.9 |
| pages | 115.7 ± 4.9 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 31.7 ± 1.5 |
| core merged across sources (of 14) | 8.3 ± 0.6 |
| wrong merges | 0.0 |
| gold duplicates | 2.3 ± 0.6 |
| links per page | 1.70 ± 0.19 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 0.0 |
| sections per page | 1.32 ± 0.06 |
| bullets per page | 2.58 ± 0.18 |
| near-duplicate bullets | 0% ± 0% |
| headings copied from the source | 87% ± 2% |
| judge: structure (1-5) | 3.31 ± 0.04 |
| judge: redundancy (1-5) | 3.35 ± 0.20 |
| judge: clarity (1-5) | 3.89 ± 0.28 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.5 ± 0.1 | 12.31 ± 0.24 | 2283 |
| patch | 132 ± 4 | 100% | 0.0 | 4.7 ± 0.1 | 2.16 ± 0.10 | 2218 ± 61 |
| resolve | 143 ± 18 | 100% | 0.0 | 7.8 ± 0.9 | 3.27 ± 0.03 | 267 ± 7 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.50 ± 0.41 | 5820 |
