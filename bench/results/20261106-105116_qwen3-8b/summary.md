# Bench `qwen3-8b`

3 runs (3 completed) over rocc-doc-1, rfm-gis-ad3, rfm-gis-ws1. Values are mean ± sd over runs.

| Role | Model | Thinking |
|---|---|---|
| extract | `ollama:qwen3:8b` | off |
| resolve | `ollama:qwen3:8b` | on |
| patch | `ollama:qwen3:8b` | off |
| summary | `ollama:qwen3:8b` | off |
| judge | `ollama:qwen3:14b` | off |

## Result

| Metric | Value |
|---|---|
| time (min) | 11.0 ± 1.3 |
| pages | 101.3 ± 7.5 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 24.3 ± 1.5 |
| core merged across sources (of 14) | 6.7 ± 2.1 |
| wrong merges | 0.3 ± 0.6 |
| gold duplicates | 1.3 ± 0.6 |
| links per page | 2.08 ± 0.27 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 2.7 ± 1.5 |
| sections per page | 1.36 ± 0.05 |
| bullets per page | 4.66 ± 0.07 |
| near-duplicate bullets | 3% ± 0% |
| headings copied from the source | 79% ± 2% |
| judge: structure (1-5) | 3.51 ± 0.04 |
| judge: redundancy (1-5) | 2.93 ± 0.54 |
| judge: clarity (1-5) | 3.82 ± 0.14 |
| questions answered (of 11) | 9.7 ± 0.6 |
| answers citing a source | 69% ± 10% |
| answers retried | – |
| unbacked expansions in answers | – |
| invalid links removed | 0.3 ± 0.6 |
| query seconds / question | 3.2 ± 0.2 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 2.3 ± 0.1 | 8.04 ± 0.34 | 2124 |
| patch | 123 ± 10 | 100% | 0.0 | 3.8 ± 0.3 | 1.84 ± 0.04 | 1714 ± 13 |
| resolve | 124 ± 28 | 100% | 0.0 | 4.7 ± 1.0 | 2.28 ± 0.09 | 251 ± 6 |
| summary | 3 | 100% | 0.0 | 0.1 ± 0.0 | 2.89 ± 0.13 | 5801 |
