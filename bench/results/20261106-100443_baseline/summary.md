# Bench `baseline`

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
| time (min) | 15.2 ± 1.0 |
| pages | 106.3 ± 4.9 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 29.7 ± 0.6 |
| core merged across sources (of 14) | 8.3 ± 0.6 |
| wrong merges | 0.0 |
| gold duplicates | 2.7 ± 1.2 |
| links per page | 1.61 ± 0.10 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 4.0 ± 1.0 |
| sections per page | 1.38 ± 0.04 |
| bullets per page | 2.73 ± 0.23 |
| near-duplicate bullets | 1% ± 1% |
| headings copied from the source | 87% ± 1% |
| judge: structure (1-5) | 3.38 ± 0.33 |
| judge: redundancy (1-5) | 3.29 ± 0.60 |
| judge: clarity (1-5) | 3.62 ± 0.41 |
| questions answered (of 11) | 9.3 ± 0.6 |
| answers citing a source | 79% ± 10% |
| answers retried | – |
| unbacked expansions in answers | – |
| invalid links removed | 0.0 |
| query seconds / question | 3.4 ± 0.3 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.5 ± 0.0 | 12.35 ± 0.04 | 2124 |
| patch | 125 ± 6 | 100% | 0.0 | 5.1 ± 0.1 | 2.46 ± 0.07 | 2203 ± 69 |
| resolve | 121 ± 19 | 100% | 0.0 | 6.3 ± 0.8 | 3.16 ± 0.11 | 245 ± 1 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.52 ± 0.15 | 5801 |
