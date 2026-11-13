# Bench `issue-16`

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
| time (min) | 17.0 ± 2.0 |
| pages | 112.3 ± 12.7 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 31.0 ± 1.0 |
| core merged across sources (of 14) | 8.7 ± 1.2 |
| wrong merges | 0.0 |
| gold duplicates | 2.3 ± 0.6 |
| links per page | 1.82 ± 0.16 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 0.0 |
| sections per page | 1.37 ± 0.11 |
| bullets per page | 2.54 ± 0.21 |
| near-duplicate bullets | 0% ± 0% |
| headings copied from the source | 86% ± 3% |
| judge: structure (1-5) | 3.18 ± 0.39 |
| judge: redundancy (1-5) | 3.82 ± 0.17 |
| judge: clarity (1-5) | 3.87 ± 0.17 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.7 ± 0.3 | 12.97 ± 0.95 | 2283 |
| patch | 133 ± 7 | 100% | 0.0 | 4.7 ± 0.3 | 2.12 ± 0.05 | 2171 ± 53 |
| resolve | 159 ± 39 | 100% | 0.0 | 8.4 ± 2.0 | 3.16 ± 0.03 | 262 ± 4 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.41 ± 0.14 | 5820 |
