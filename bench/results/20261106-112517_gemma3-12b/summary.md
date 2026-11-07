# Bench `gemma3-12b`

3 runs (3 completed) over rocc-doc-1, rfm-gis-ad3, rfm-gis-ws1. Values are mean ± sd over runs.

| Role | Model | Thinking |
|---|---|---|
| extract | `ollama:gemma3:12b` | off |
| resolve | `ollama:gemma3:12b` | off |
| patch | `ollama:gemma3:12b` | off |
| summary | `ollama:gemma3:12b` | off |
| judge | `ollama:qwen3:14b` | off |

## Result

| Metric | Value |
|---|---|
| time (min) | 12.6 ± 0.6 |
| pages | 86.7 ± 3.2 |
| rejected edits | 0.0 |
| lint errors / warnings | 0.0 / 0.0 |
| gold pages found (of 33) | 29.3 ± 0.6 |
| core merged across sources (of 14) | 10.3 ± 1.2 |
| wrong merges | 1.7 ± 1.2 |
| gold duplicates | 1.0 ± 1.0 |
| links per page | 2.22 ± 0.19 |
| citation coverage | 100% |
| unbacked abbreviation expansions | 8.7 ± 0.6 |
| sections per page | 1.74 ± 0.05 |
| bullets per page | 4.07 ± 0.13 |
| near-duplicate bullets | 2% ± 1% |
| headings copied from the source | 95% ± 0% |
| judge: structure (1-5) | 3.31 ± 0.17 |
| judge: redundancy (1-5) | 2.71 ± 0.21 |
| judge: clarity (1-5) | 3.73 ± 0.07 |
| questions answered (of 11) | 9.0 |
| answers citing a source | 70% ± 17% |
| answers retried | – |
| unbacked expansions in answers | – |
| invalid links removed | 0.0 |
| query seconds / question | 3.3 ± 0.1 |

## Model calls per role

| Role | Calls | Valid JSON (1st try) | Failed | Minutes | Mean s | Max tokens in |
|---|---|---|---|---|---|---|
| extract | 17 | 100% | 0.0 | 4.0 ± 0.1 | 14.19 ± 0.35 | 2166 |
| patch | 109 ± 4 | 100% | 0.0 | 7.5 ± 0.4 | 4.09 ± 0.11 | 2195 ± 98 |
| resolve | 77 ± 10 | 100% | 0.0 | 0.8 ± 0.1 | 0.63 ± 0.01 | 242 ± 4 |
| summary | 3 | 100% | 0.0 | 0.3 ± 0.0 | 5.44 ± 0.05 | 5833 |
