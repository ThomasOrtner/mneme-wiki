# CLI Reference

← [Home](Home.md)

```
mneme-wiki [--version] <command> [options]
```

All vault commands take `--vault <path>` (default: `WIKI_VAULT_DIR`) and `--json`
(one JSON object on stdout; progress goes to stderr). Exit codes: `0` ok, `1` the
operation failed (lint errors, failed integration, no answer), `2` bad input or setup.

## init

```
mneme-wiki init <path> [--language en] [--json]
```

Creates a vault in an empty or new folder: folders, `WIKI.md`, `index.md`, `log.md`,
`.gitignore`, `.gitattributes`, git repo, first commit.

## integrate

```
mneme-wiki integrate <packet> [<packet> ...] [--dry-run] [--stage S --out FILE] [--local-id-owner NAME]
```

| Option | Effect |
|---|---|
| `<packet>` | A folder path, or the name of a folder in the inbox |
| `--dry-run` | Run every stage, print the diff, write nothing |
| `--stage S` | Stop after `chunk`, `extract`, `resolve`, `plan` or `patch`; needs exactly one packet and `--out` |
| `--out FILE` | Write the stage's output as JSON |
| `--local-id-owner NAME` | The project that owns the local ids (`WP2`) of packets without a `local_id_owner` field ([Source Packets](Source-Packets.md#sourcemetajson)); a packet that declares a different project is an error, nothing written |

Several packets are integrated in order, one commit each, stopping at the first failure.
See [Integration Pipeline](Integration-Pipeline.md).

## lint

```
mneme-wiki lint [--json]
```

Exit 1 on errors. See [Lint, Search and Query](Lint-Search-Query.md).

## reindex

```
mneme-wiki reindex [--json]
```

Regenerates `index.md` and logs it if it changed.

## search

```
mneme-wiki search "<query>" [--limit 10] [--type source|entity|concept|synthesis ...]
```

## query

```
mneme-wiki query "<question>" [--file]
```

`--file` saves a cited answer as a synthesis page (one commit). Exit 2 if filing was refused.

## status

```
mneme-wiki status [--json]
```

Pages per type, unreadable pages, the glossary (terms and problems, if there is a
`glossary.md`), the domain rules (size, if `WIKI.md` has any), the ontology (kinds
and scoped kinds, if there is an `ontology.md`), git HEAD and whether there are uncommitted changes, the last log
entries, and the inbox packets with their integration state.

## bench

```
mneme-wiki bench --models <mapping.toml> [--label NAME] [--repeat 3]
                 [--corpus bench/corpus] [--packets a b c] [--out bench/results]
mneme-wiki bench --ask <result-dir> ... [--questions FILE] [--query-model REF]
mneme-wiki bench --compare <result-dir> ...
```

See [Benchmark](Benchmark.md).

## mneme-wiki-mcp

The MCP server is a separate command, also runnable as `python -m mneme_wiki.mcp_server`
(the recommended way to register it); see [MCP Server](MCP-Server.md).
