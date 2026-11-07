# Troubleshooting

← [Home](Home.md)

**`vault folder … does not exist; set WIKI_VAULT_DIR or pass --vault`**
No vault configured. Run `mneme-wiki init <path>` and set `WIKI_VAULT_DIR`, or pass `--vault`.

**`integrate` refuses: uncommitted changes**
Each integration is exactly one commit, so the vault must be clean first. Commit or
discard your own edits (`git -C <vault> status`).

**`integrate` refuses: source already integrated**
A page with the same `origin` exists. Re-integrating would duplicate claims; updating a
changed source isn't supported yet.

**`no packet folder '…'`**
The argument is neither a folder path nor a folder name in the inbox. `mneme-wiki status`
shows which inbox it looks in.

**Packet errors (missing `source.md`, missing metadata keys)**
See [Source Packets](Source-Packets.md): `title`, `source_type`, `origin`, `date` are required.

**Connection refused / model not found**
Start Ollama and pull the model: `ollama pull qwen3:14b`. Check `OLLAMA_BASE_URL`
and the `MODEL_*` variables.

**Integration is slow**
Expect a few minutes per source on `qwen3:14b` with a GPU. Thinking is costly: keep
`THINK_PATCH=0`. A smaller model (`qwen3:8b`) is faster but finds fewer pages.

**Edits were rejected**
The validator refused a model edit (invented link, lost content, …) after one retry. The
rest of the source was still integrated. The edit and its reason are in
`inbox/rejected/<run-id>/`; the run report lists them too.

**`query` warns "this answer cites no source" or "not backed by the pages"**
The model failed the citation or abbreviation check twice. The answer is shown but
can't be filed. Rephrase, or check with `search` that the wiki covers the topic.

**Garbled characters in piped output on Windows**
mneme-wiki switches pipes to UTF-8 itself; if another tool in the pipe mangles them, set
`$env:PYTHONIOENCODING = "utf-8"`.

**MCP client sees no tools / the server exits**
Run `mneme-wiki-mcp` in a terminal to see errors on stderr. Make sure the client starts
the venv's executable and passes `WIKI_VAULT_DIR`.
