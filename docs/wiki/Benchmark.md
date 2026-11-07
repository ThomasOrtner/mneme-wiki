# Benchmark

← [Home](Home.md) · Results: [bench/README.md](../../bench/README.md) ·
Method: [M4 tutorial](../milestones/M4-bench.md)

Which local model should run which stage? `mneme-wiki bench` answers that with data
instead of guesses.

## How it works

1. A **mapping file** says which model (and thinking setting) each role uses.
2. The bench integrates a fixed **corpus** of source packets into a fresh, throwaway vault,
   several times (`--repeat`, default 3: run-to-run variance is about ±15 %).
3. It measures each run against a hand-labelled **gold file**: which pages should exist,
   which mentions are the same thing.
4. Optionally a fixed `judge` model scores page quality, and `--ask` runs a question set.

## Mapping file

```toml
# bench/mappings/baseline.toml
label = "baseline"
[models]
extract = "ollama:qwen3:14b"
resolve = "ollama:qwen3:14b"
patch   = "ollama:qwen3:14b"
summary = "ollama:qwen3:14b"
[thinking]
resolve = true
patch   = false
[judge]
model = "ollama:qwen3:14b"
sample = 15
```

## Corpus

```
bench/corpus/
  <packet>/ ...        source packets
  order.txt            integration order
  gold.json            expected pages and merges
  questions.md         question set for --ask
```

The project's own corpus is built from private documents and is git-ignored; bring
your own to benchmark your domain.

## Running

```powershell
mneme-wiki bench --models bench/mappings/baseline.toml
mneme-wiki bench --ask bench/results/<folder>
mneme-wiki bench --compare bench/results/<a> bench/results/<b>
```

Results land in `bench/results/<timestamp>_<label>/`: `metrics.json`, `summary.md`
(only this file is committed) and the produced vaults.

## Metrics

Time, pages, gold pages found, core subjects merged across sources, **wrong merges**,
duplicates, rejected edits, lint errors, links per page, headings copied from the source,
invented abbreviation expansions, questions answered, answers citing a source.

## Current result

`qwen3:14b` for every role, thinking on for `resolve` only: the best gold coverage with
zero wrong merges. `qwen3:8b` is faster but loses about 5 of 33 gold pages; `gemma3:12b`
makes wrong merges. Mixed configurations haven't been measured.
