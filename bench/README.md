# Benchmark

Which local model should run which stage? Each configuration in `mappings/`
integrates the corpus three times into throwaway vaults. The method, the story
and the reasoning are in the [M4 tutorial](../docs/milestones/M4-bench.md).

## Result

**Default: `qwen3:14b` for every role, thinking on for `resolve` only.**

Three sources, three runs each, means. The judge is always `qwen3:14b`.

| | `qwen3:14b` | `qwen3:8b` | `gemma3:12b` | 14b + patch thinking | `qwen3:14b` after M5 fixes |
|---|---|---|---|---|---|
| Time (min) | 15.2 | 11.0 | 12.6 | 37.9 | 14.7 |
| Pages | 106 | 101 | 87 | 109 | 108 |
| Gold pages found (of 33) | 29.7 | 24.3 | 29.3 | 29.3 | 30.7 |
| Core merged across sources (of 14) | 8.3 | 6.7 | 10.3 | 8.3 | 8.3 |
| Wrong merges | 0 | 0.3 | 1.7 | 0 | 0 |
| Gold duplicates | 2.7 | 1.3 | 1.0 | 2.3 | 3.0 |
| Rejected edits / lint errors | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Links per page | 1.61 | 2.08 | 2.22 | 1.79 | 1.60 |
| Headings copied from the source | 87 % | 79 % | 95 % | 63 % | 87 % |
| Invented expansions per vault | 4.0 | 2.7 | 8.7 | 1.7 | 0.3 |
| Questions answered (of 11) | 9.3 | 9.7 | 9.0 | 9.3 | 10.0 |
| Real answers citing a source | 79 % | 69 % | 70 % | 72 % | 100 % |

The first four columns are all queried by `qwen3:14b` with the code from before
the M5 fixes.

## Why

- **`qwen3:14b`:** the best gold coverage with no wrong merges.
- **`qwen3:8b`:** 28 % faster, but loses about 5 gold pages.
- **`gemma3:12b`:** merges more, but merges wrongly too, and invents the most.
  It has no thinking mode, so its `resolve` isn't a fair test of the model alone.
- **Patch thinking:** 2.5× the run time for fewer copied headings and nothing else
  measurable. Off.

## Limits

Three runs and three sources from one domain; differences within the spread mean
little. No mixed configuration was measured, and `summary.md` in each result folder
has the spreads.

Answering "10 of 11" isn't better than 9.3: the added answers stretch thin
evidence on a question the corpus barely covers (see the
[M5 tutorial](../docs/milestones/M5-query.md)).

## Running

```powershell
mneme-wiki bench --models bench/mappings/baseline.toml --label baseline
mneme-wiki bench --ask bench/results/<folder>
mneme-wiki bench --compare bench/results/<a> bench/results/<b>
```

`corpus/` holds private documents and is git-ignored. In `results/`, only each
folder's `summary.md` is in git.
