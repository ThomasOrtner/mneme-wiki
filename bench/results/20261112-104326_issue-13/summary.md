# Bench `issue-13`

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
| time (min) | 18.9 ± 0.8 |
| pages | 123.3 ± 1.2 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 32.0 |
| core merged across sources (of 14) | 8.0 |
| wrong merges | 0.0 |
| gold duplicates | 2.7 ± 0.6 |
| links per page | 1.71 ± 0.09 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 3.7 ± 3.5 |
| sections per page | 1.35 ± 0.04 |
| bullets per page | 2.50 ± 0.18 |
| near-duplicate bullets | 0% ± 0% |
| headings copied from the source | 83% ± 5% |
| judge: structure (1-5) | 3.16 ± 0.07 |
| judge: redundancy (1-5) | 3.24 ± 0.67 |
| judge: clarity (1-5) | 3.60 ± 0.24 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.7 ± 0.1 | 13.15 ± 0.47 | 2283 |
| patch | 142 ± 3 | 100% | 0.0 | 5.6 ± 0.3 | 2.35 ± 0.09 | 2173 ± 31 |
| resolve | 162 ± 10 | 100% | 0.0 | 9.3 ± 0.5 | 3.45 ± 0.04 | 270 ± 4 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.36 ± 0.37 | 5820 |
