# Bench `issue-24`

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
| time (min) | 16.5 ± 0.5 |
| pages | 113.7 ± 1.2 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 32.0 ± 1.0 |
| core merged across sources (of 14) | 8.3 ± 0.6 |
| wrong merges | 0.0 |
| gold duplicates | 3.7 ± 0.6 |
| links per page | 1.79 ± 0.12 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 0.0 |
| sections per page | 1.37 ± 0.06 |
| bullets per page | 2.60 ± 0.05 |
| near-duplicate bullets | 0% |
| headings copied from the source | 88% ± 0% |
| judge: structure (1-5) | 3.16 ± 0.15 |
| judge: redundancy (1-5) | 3.44 ± 0.45 |
| judge: clarity (1-5) | 3.89 ± 0.17 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.6 ± 0.1 | 12.64 ± 0.31 | 2283 |
| patch | 133 ± 2 | 100% | 0.0 | 5.0 ± 0.1 | 2.24 ± 0.03 | 2236 ± 50 |
| resolve | 141 ± 15 | 100% | 0.0 | 7.7 ± 0.7 | 3.29 ± 0.06 | 261 ± 3 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.52 ± 0.16 | 5820 |
