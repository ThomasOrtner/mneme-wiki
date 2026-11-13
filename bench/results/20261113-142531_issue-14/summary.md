# Bench `issue-14`

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
| time (min) | 17.7 ± 0.5 |
| pages | 120.3 ± 1.2 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 31.3 ± 0.6 |
| core merged across sources (of 14) | 8.7 ± 1.2 |
| wrong merges | 0.0 |
| gold duplicates | 2.3 ± 0.6 |
| links per page | 1.66 ± 0.12 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 0.0 |
| sections per page | 1.30 ± 0.04 |
| bullets per page | 2.49 ± 0.09 |
| near-duplicate bullets | 0% |
| headings copied from the source | 88% ± 3% |
| judge: structure (1-5) | 2.71 ± 0.21 |
| judge: redundancy (1-5) | 3.38 ± 0.24 |
| judge: clarity (1-5) | 3.49 ± 0.34 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.6 ± 0.1 | 12.63 ± 0.28 | 2283 |
| patch | 138 ± 1 | 100% | 0.0 | 4.9 ± 0.1 | 2.12 ± 0.04 | 2217 ± 28 |
| resolve | 160 ± 1 | 100% | 0.0 | 8.9 ± 0.3 | 3.36 ± 0.15 | 261 ± 1 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.47 ± 0.12 | 5820 |
