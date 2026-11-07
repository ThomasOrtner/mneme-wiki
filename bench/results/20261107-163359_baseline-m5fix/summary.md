# Bench `baseline-m5fix`

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
| time (min) | 14.7 ± 0.9 |
| pages | 108.3 ± 4.0 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 30.7 ± 0.6 |
| core merged across sources (of 14) | 8.3 ± 0.6 |
| wrong merges | 0.0 |
| gold duplicates | 3.0 ± 1.7 |
| links per page | 1.60 ± 0.14 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 0.3 ± 0.6 |
| sections per page | 1.39 ± 0.01 |
| bullets per page | 2.58 ± 0.04 |
| near-duplicate bullets | 1% ± 1% |
| headings copied from the source | 87% ± 1% |
| judge: structure (1-5) | 3.29 ± 0.10 |
| judge: redundancy (1-5) | 3.40 ± 0.13 |
| judge: clarity (1-5) | 4.00 ± 0.12 |
| questions answered (of 11) | 10.0 |
| answers citing a source | 100% |
| answers retried | 2.7 ± 1.2 |
| unbacked expansions in answers | 0.0 |
| invalid links removed | 0.0 |
| query seconds / question | 3.7 ± 0.4 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 3.4 ± 0.1 | 11.91 ± 0.22 | 2124 |
| patch | 125 ± 5 | 100% | 0.0 | 4.9 ± 0.1 | 2.33 ± 0.08 | 2199 ± 57 |
| resolve | 119 ± 14 | 100% | 0.0 | 6.2 ± 0.8 | 3.13 ± 0.04 | 247 ± 2 |
| summary | 3 | 100% | 0.0 | 0.2 ± 0.0 | 4.32 ± 0.23 | 5820 |
