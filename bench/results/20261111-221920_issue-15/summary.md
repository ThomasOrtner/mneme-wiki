# Bench `issue-15`

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
| time (min) | 15.7 ± 1.0 |
| pages | 113.3 ± 5.5 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 31.3 ± 1.2 |
| core merged across sources (of 14) | 8.0 |
| wrong merges | 0.0 |
| gold duplicates | 2.7 ± 0.6 |
| links per page | 1.57 ± 0.08 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 0.3 ± 0.6 |
| sections per page | 1.38 ± 0.11 |
| bullets per page | 2.50 ± 0.07 |
| near-duplicate bullets | 0% ± 0% |
| headings copied from the source | 84% ± 2% |
| judge: structure (1-5) | 3.16 ± 0.54 |
| judge: redundancy (1-5) | 3.02 ± 0.22 |
| judge: clarity (1-5) | 3.82 ± 0.52 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.3 ± 0.0 | 11.82 ± 0.05 | 2177 |
| patch | 130 ± 4 | 100% | 0.0 | 4.9 ± 0.1 | 2.28 ± 0.05 | 2186 ± 71 |
| resolve | 138 ± 18 | 100% | 0.0 | 7.2 ± 1.0 | 3.11 ± 0.06 | 246 ± 5 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.14 ± 0.10 | 5820 |
