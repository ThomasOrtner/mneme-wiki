# M1: Scaffold & vault model

**Question:** can the package read, change and write vault files *safely*, and leave
files it didn't change exactly as they were?

**Short answer:** yes. Every parsable fixture file (LF, CRLF + BOM, YAML comments,
odd quoting, no front matter at all) goes through parse → serialise byte for byte,
and a changed page only differs where it was changed. 153 tests, no model needed.
Along the way two Windows traps turned up that would have broken this later: git's
`core.autocrlf`, and Python's newline translation. Both are now covered by tests.

M1 has no LLM code. It is the layer that every later milestone writes *through*,
so it has to be correct before any model output reaches the disk (TD-5, L-4).

---

## 1. What was built

```
pyproject.toml          package + scripts (mneme-wiki), ruff, pytest config
.env.example            every config variable with its default
.gitattributes          tests/fixtures/** -text  (fixtures are byte-exact test data)
mneme_wiki/
  config.py             the only place that reads environment variables
  frontmatter.py        parse / serialise / validate YAML front matter
  links.py              wikilinks: extract, resolve, alias map, backlinks
  vault.py              page I/O, slugs, path confinement, case collisions, git, init
  cli.py                `mneme-wiki init`
  templates/WIKI.md     schema + rules for the agent that writes wiki content
tests/
  fixtures/clean/            a small valid vault (one page CRLF + BOM, one with comments)
  fixtures/broken-yaml/      unterminated, not a mapping, bad syntax, duplicate key, schema errors
  fixtures/broken-links/     missing target, ambiguous name, missing heading, orphan
  fixtures/windows-hostile/  `entities/ROCC.md` (upper case), `concepts/Größe des Rovers.md`
  test_frontmatter.py  test_links.py  test_vault.py  test_cli.py
```

The pieces depend on each other in one direction only:
`cli → vault → frontmatter`, and `links` is pure (strings and path lists in, results
out). Lint (M2) will combine `vault.iter_pages()`, `frontmatter.validate()` and
`links.LinkIndex`. No module but `cli.py` prints anything.

### 1.1 Front matter (`mneme_wiki/frontmatter.py`)

The central type is `Document` (`frontmatter.py:56`): `meta` (a dict), `body` (a
string), and what is needed to write the file back exactly: the original
front-matter block as text (`raw_front`), the newline style, whether the file had
a BOM, and a deep copy of `meta` and `body` as they were read.

**`parse()` (`frontmatter.py:142`)** strips a BOM, notes whether the first line
ends in `\n` or `\r\n`, and checks whether the file starts with a `---` line. If it
doesn't, the whole file is body and `meta` is `{}`; a horizontal rule further
down is not mistaken for front matter. Otherwise it scans line by line
(`frontmatter.py:155`) for the closing `---` (or `...`, which YAML also allows).
The text in between goes to `_load()` (`frontmatter.py:171`), which raises
`FrontMatterError` for invalid YAML, a list instead of a mapping, a missing closing
line, or a **duplicate key**. PyYAML silently keeps the last of two `title:` lines;
the custom loader (`frontmatter.py:93`) refuses, because a duplicate key in a page
is almost always a bad merge or a model mistake.

**`dump()` (`frontmatter.py:195`)** is where the round-trip guarantee lives:

```python
if doc.meta_changed:  # meta != the copy taken at parse time
    front = _serialise_front(doc)
else:
    front = doc.raw_front or ""  # the original bytes, untouched
```

So an unchanged page is never re-serialised, and comments, quoting
(`title: "Rover…"`), block-vs-inline lists and spacing all survive. The body is
never touched either. If it was edited in a CRLF file, new bare `\n` are
converted to `\r\n` so the file doesn't end up with mixed line endings.

When `meta` *did* change, `_serialise_front()` (`frontmatter.py:207`) writes keys
the page already had in their **original order** (`frontmatter.py:210`), then new
keys in schema order (`KEY_ORDER`), then any other new keys. Unknown keys, such as
`reviewed_by:` in the fixture, are kept. The YAML dumper is configured for files
people read: block mappings, scalar lists inline (`aliases: [RAG, TPC]`),
multi-line strings as `|` blocks, no line folding, and **no anchors**
(`frontmatter.py:107`).

**`validate()` (`frontmatter.py:228`)** checks a `meta` dict against AGENTS.md §5
and returns `Issue`s rather than raising, so lint can report all problems at once:
`title`/`type` required, `type` and `status` from their enums, `created`/`updated`
required on content pages, type-specific fields (`source_type` + `origin`,
`entity_kind`, `question`), list fields that must be lists of strings, `sources`
and `contradicts` entries that must be `[[wikilinks]]`, and dates in `YYYY-MM-DD`
form. A `datetime` is rejected on purpose, since a timestamp would become noise in
diffs.

### 1.2 Wikilinks (`mneme_wiki/links.py`)

**`extract()` (`links.py:71`)** finds `[[…]]` and `![[…]]` with one regex
(`links.py:22`) and splits each into `target`, `heading`, `alias` and `embed`
(`_parse`, `links.py:77`). Two Obsidian details matter:

- **Code is not prose.** Links inside fenced blocks (``` and ~~~, longer fences
  closing only on an equal or longer one) and inside inline code are ignored.
  `mask_code()` (`links.py:47`) replaces code with spaces *of the same length*, so
  the regex runs on the masked text while offsets still point into the original.
  Later stages need those offsets to rewrite one exact link.
- **Tables escape the pipe:** `[[page\|alias]]` inside a Markdown table is still an
  alias (`links.py:79`).

**`LinkIndex` (`links.py:123`)** resolves targets the way Obsidian does:
case-insensitive and `.md` optional. A target with a `/` matches a path exactly,
then as a path suffix (`[[b/deep]]` → `a/b/deep.md`). A bare name matches the file
name anywhere in the vault. `candidates()` returns every file a target could mean:
an empty list means a broken link, two or more mean an ambiguous one (like
`[[overview]]` in the broken-links fixture). `resolve()` returns a path only when
there is exactly one candidate. Attachments must be linked with their extension
(`[[diagram.png]]`), as in Obsidian.

**`alias_map()` (`links.py:157`)** maps every normalised title and alias to the
pages claiming it. Two pages under one name is the "duplicate entity" lint in M2,
and the exact-match step of resolve in M3. **`backlinks()` (`links.py:171`)**
inverts the link graph and skips self-links and unresolved links.

### 1.3 The vault (`mneme_wiki/vault.py`)

`Vault` (`vault.py:132`) wraps a root folder. Everything is addressed by
**vault-relative POSIX paths** (`concepts/rag.md`), which are what links,
`index.md` and git show, on Windows too.

**Reading and writing are bytes**, decoded and encoded as UTF-8, never through
`open(…, "w")` in text mode (see §3: that translation bit me during this
milestone). `write_text()` (`vault.py:217`) is the only write path in the package:

1. `abspath(rel, for_write=True)` (`vault.py:137`) rejects absolute paths, drive
   letters, UNC paths and `..`. It then checks every path part with `check_name()`
   (`vault.py:88`): no `<>:"|?*\`, no control characters, no trailing dot or space,
   no reserved Windows names (`CON`, `NUL`, `COM1`, … including `nul.txt`). Finally
   it resolves the path and checks it is still inside the root (`vault.py:147`),
   which also stops a symlink or junction from pointing out.
2. `_check_case()` (`vault.py:154`) lists each existing folder on the way and
   refuses `entities/rocc.md` if `entities/ROCC.md` exists, or `Entities/x.md` if
   `entities/` exists. On NTFS those are the same file, so the write would
   silently replace a human's page.
3. If the file already has exactly these bytes, nothing is written and the
   method returns `False` (`vault.py:222`). That keeps file timestamps and
   Obsidian's change detection quiet.
4. `_atomic_write()` (`vault.py:259`) writes a temp file *in the same folder*,
   `fsync`s it and `os.replace`s it over the target. A crash leaves either the old
   file or the new one, never half a page. The replace is retried briefly on
   `PermissionError`, because on Windows a virus scanner or Obsidian can hold the
   file for a moment (`vault.py:266`). The temp file is removed if anything fails.

**Slugs.** `slugify()` (`vault.py:68`) turns a title into a kebab-case ASCII
stem: German umlauts are transliterated (`Größe` → `groesse`), other accents
dropped (`Café` → `cafe`), and anything else becomes `-`. Long titles are cut at
a word boundary near 80 characters; a reserved name gets a suffix (`CON` →
`con-page`); a title with no Latin letters at all (`火星探测器`) gets a stable
`page-<hash>` instead of an empty name. `path_for(type, title)` (`vault.py:166`)
combines folder and slug and runs the case check, so a new page can never land on
an existing file.

**Listing.** `files()` (`vault.py:185`) lists everything except hidden folders
(`.git`, `.obsidian`, `.trash`). `page_paths()` (`vault.py:195`) also leaves out
`WIKI.md` (it is instructions, not a page) and `attachments/`. `iter_pages()`
(`vault.py:205`) yields `(path, Page)`, or `(path, FrontMatterError)` for a broken
page, so one bad file never stops a lint run.

**Git.** `commit()` (`vault.py:246`) stages everything in the vault and commits.
It returns the sha, or `None` when there was nothing to commit. This is the "one
commit per operation" of TD-6; M3 calls it once per integrated source.

**`init_vault()` (`vault.py:302`)** refuses a folder that exists and isn't empty,
then creates the five folders (with `.gitkeep`, since git doesn't track empty
folders), `.gitignore` (Obsidian's per-device state and our caches),
`.gitattributes` (§3), `WIKI.md` from the template with the language filled in,
`index.md` and `log.md` (both valid typed pages, and the log's first entry in the
`## [YYYY-MM-DD] init | <name>` format), runs `git init` and makes the first
commit.

### 1.4 Config, CLI, template

- `config.py` reads `.env` and the environment once, as in mneme. The model refs
  per role (`MODELS`) are already defined there, but nothing uses them until M3/M4.
  `inbox_dir(vault)` implements TD-21: `WIKI_INBOX_DIR`, else `<vault>/../inbox`.
- `cli.py` is thin: `init` calls `init_vault()` and prints either `rich` lines or,
  with `--json`, one JSON object (`{"ok": true, "vault": …, "inbox": …}`); errors
  exit with 1.
- `templates/WIKI.md` is the rulebook for whoever writes *content*: layout,
  front-matter fields, page body shape, the writing rules (cite every claim,
  integrate don't append, never drop content, mark contradictions, one thing one
  page, stubs) and the log format. It lives **inside the package**
  (`mneme_wiki/templates/`, not a top-level `templates/` as the plan first said),
  so it ships with a normal `pip install`, not only an editable one.

---

## 2. How to run it yourself

```powershell
cd C:\_REPOS\mneme-wiki
.venv\Scripts\python -m pip install -e ".[dev]"

# the test suite (no Ollama needed; LLM tests are opt-in with -m ollama)
.venv\Scripts\python -m pytest

# create a vault and look at it
.venv\Scripts\mneme-wiki init C:\temp\my-wiki
.venv\Scripts\mneme-wiki init C:\temp\my-wiki --json     # → exits 1: not empty
git -C C:\temp\my-wiki log --stat
```

Open `C:\temp\my-wiki` as a vault in Obsidian: the empty folders, `WIKI.md`,
`index.md` and `log.md` are there. The dev vault is meant to live at
`examples/vault` (`mneme-wiki init examples/vault`). It is its own git repository,
so the outer repo ignores it.

To see the round trip in action:

```powershell
.venv\Scripts\python -c "from mneme_wiki import frontmatter as fm; t=open('tests/fixtures/clean/entities/rover-operations-control-centre.md','rb').read().decode(); d=fm.parse(t); print(fm.dump(d)==t); d.meta['status']='stub'; print(fm.dump(d)[:400])"
```

The first line prints `True`. The second shows the re-serialised block: same key
order, `reviewed_by` kept, and the comment gone (it was in a block that changed;
see §5).

---

## 3. What happened: the bugs found on the way

**PyYAML's defaults (found by the first `init` smoke run).** With
`default_flow_style=None`, PyYAML wrote the whole mapping on one line
(`{title: Log, type: log, …}`), and because `created` and `updated` were the *same*
`date` object it emitted an anchor and an alias (`&id001 2026-11-02` / `*id001`).
Both are valid YAML, and both are unreadable in Obsidian's properties view. Fix:
block mappings, a list representer that inlines only scalar lists, and
`ignore_aliases()`. The tests assert `aliases: [ROCC, …]` and no `&id`.

**git `core.autocrlf=true` (this machine's setting, and a common Windows default).**
Git converts line endings when it stores or checks out files. In a vault that
would turn a CRLF page into an LF blob and back, so what git stores is not what is
on disk, diffs fill with whitespace noise, and the byte-exact guarantee only holds
until the next checkout. Fix: `init` writes `.gitattributes` with `* -text`, so
git stores exactly the bytes on disk. The repo's own fixtures get the same
treatment (`tests/fixtures/** -text`). `test_vault_git_keeps_crlf_bytes` commits a
CRLF page with `autocrlf=true` and compares the stored blob byte for byte. I
checked that it fails without the attribute.

**Python's newline translation (my own tooling, same root cause).** While
patching files with small scripts I used `Path.write_text()`, which on Windows
silently turns `\n` into `\r\n`. Three source files became CRLF and a test string
got `\r\r\n`. The bug was in the dev tooling, not in the package, but it is the
exact failure `vault.py` is built to avoid: never write through text mode. Also
seen: subprocess output in text mode translates `\r\n` back, so the git test reads
raw bytes.

---

## 4. Decisions made in M1, and why

| Decision | Why | Rejected alternative |
|---|---|---|
| **Keep the raw front-matter block; re-serialise only on change** (TD-20) | Byte-exact round trip with plain PyYAML; unchanged pages never show up in diffs | `ruamel.yaml` round-trip mode: keeps comments even on change, but is a heavy dependency with its own quirks, and we rarely change human-written front matter. Our own YAML emitter: too much code for the gain |
| **Existing keys keep their order; new keys follow in schema order** | A changed page's diff shows the changed lines, not a reshuffled block | Always canonical order: every first touch of a hand-written page would reorder it |
| **Duplicate YAML keys are an error** | PyYAML silently keeps the last value; a duplicate is nearly always a broken merge | Accepting PyYAML's behaviour |
| **`validate()` returns issues, `parse()` raises** | Syntax errors make a file unusable; schema problems are findings to report all at once | One error mechanism for both |
| **Bytes I/O everywhere, newline style per file** | Windows text mode rewrites newlines; humans may use CRLF editors | Normalising everything to LF: would rewrite every CRLF file on first touch |
| **Vault `.gitattributes`: `* -text`** | Git must store what is on disk, whatever `core.autocrlf` says | Requiring users to configure git |
| **Write = temp file in same folder + `os.replace`, skip if identical** | Atomic on NTFS and POSIX; no timestamp churn | Writing in place; a temp dir elsewhere (cross-volume rename isn't atomic) |
| **Case collisions refused at write time, per path component** | NTFS would silently overwrite `ROCC.md` with `rocc.md` | Lower-casing all names: would rename human files |
| **Hostile names refused only for writes** | We must still read whatever a human put in the vault | Refusing to read them |
| **Slugs: transliterate German, drop other accents, hash for non-Latin** | Readable, portable file names; non-Latin titles still get unique stems | Unicode file names: legal on NTFS, but awkward in shells, URLs and git on other OSes |
| **Link resolution like Obsidian (case-insensitive, suffix paths, ambiguity reported)** | Lint must agree with what Obsidian shows the human | Exact path matching only: would flag links that work in Obsidian |
| **Links in code ignored by masking, not parsing** | Keeps offsets valid for later rewrites; no Markdown AST (TD-9) | A Markdown parser library |
| **Template inside the package** | Ships with any install; `importlib.resources` finds it | Top-level `templates/` (plan's first wording); only works in editable installs |
| **Inbox defaults to `<vault>/../inbox`** (TD-21) | Several vaults each get their own inbox, independent of the working directory | `./inbox` relative to wherever the command runs |

## 5. Known gaps

- **YAML comments are lost when that page's front matter changes.** Documented in
  TD-20; revisit (e.g. `ruamel.yaml` for the rewrite path) only if people
  actually keep comments in front matter.
- **Path confinement on writes covers the vault only.** Writing into the inbox
  (`inbox/rejected/`, M3) needs the same guard; `Vault` will get an inbox-aware
  writer then rather than a second ad-hoc one.
- **Heading links are parsed but not checked** (`[[concepts/overview#No such
  heading]]` resolves to the page). `links.headings()` is ready; the check is lint
  (M2).
- **Obsidian's rules for ambiguous bare names are richer** (it prefers the file
  closest to the linking page). We report the ambiguity instead; M2 decides
  whether that is an error or a warning.
- **No symlink test.** Creating symlinks on Windows needs extra privileges; the
  `is_relative_to` check after `resolve()` covers them, but no test proves it.
- **Unicode normalisation of file names (NFC vs NFD)** isn't handled. macOS can
  store `Größe` decomposed, so a link from another OS might not resolve. Out of
  scope while the vault is used on Windows.
- **`config.MODELS` and the `ollama`/`mcp` dependencies are unused so far.** They
  are installed now so later milestones don't change the packaging.
