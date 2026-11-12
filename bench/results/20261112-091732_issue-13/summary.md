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
| time (min) | 17.4 ± 1.1 |
| pages | 118.7 ± 7.5 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 30.0 ± 1.7 |
| core merged across sources (of 14) | 8.3 ± 0.6 |
| wrong merges | 0.0 |
| gold duplicates | 2.7 ± 0.6 |
| links per page | 1.65 ± 0.05 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 0.3 ± 0.6 |
| sections per page | 1.29 ± 0.04 |
| bullets per page | 2.50 ± 0.15 |
| near-duplicate bullets | 1% ± 1% |
| headings copied from the source | 82% ± 2% |
| judge: structure (1-5) | 3.20 ± 0.35 |
| judge: redundancy (1-5) | 2.98 ± 0.34 |
| judge: clarity (1-5) | 4.04 ± 0.32 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.5 ± 0.1 | 12.41 ± 0.41 | 2283 |
| patch | 134 ± 4 | 100% | 0.0 | 5.2 ± 0.2 | 2.34 ± 0.06 | 2200 ± 114 |
| resolve | 153 ± 13 | 100% | 0.0 | 8.4 ± 0.7 | 3.29 ± 0.11 | 271 ± 4 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.54 ± 0.25 | 5820 |
