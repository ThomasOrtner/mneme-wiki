# mneme-wiki: plan

The order in which open issues are worked on, and why. The issues hold the specs and
their state; this file holds only the **sequence**. The MVP plan (M0–M7, done) with its
designs is archived in [archive/mvp-plan.md](archive/mvp-plan.md).

How agents use this file: [AGENTS.md § 7](../AGENTS.md#7-workflow).

## Rules

- **The plan comes first.** Work goes phase by phase, top to bottom. The next issue is
  the first one in the current phase that is `ready` and not `blocked` or
  `decision-needed`. If no issue in the current phase can be started, stop and ask; don't
  jump to a later phase on your own.
- **Priorities follow the plan:** current phase `p1`, next phase `p2`, the one after `p3`,
  everything later `p4`. When the plan changes, the labels are updated in the same
  change. If labels and plan disagree, the plan wins.
- `ready` and `decision-needed` still apply as in AGENTS.md: the human sets `ready`.
- A new issue gets a place in this file when it is created. A closed issue is ticked
  here in the PR that closes it; a finished phase stays here until the next plan review.
- Changes to the order are made with the human, in a `docs:` commit with a reason.

## Overview

| Phase | Goal | Issues | Priority |
|---|---|---|---|
| 0 | Docs that explain what the pipeline does | PR #18 | – |
| 1 | Stop wrong merges and invented content at the source | #15, #13, #22, #25 | done |
| 2 | Vault-specific knowledge | #24, #27, #14, #16, #33 | p1 |
| 3 | Keep pages up to date, see the vault; document the pipeline | #20, #23, #19, #17, #32 | p2 |
| 4 | Repair what is already in a vault | #6, #3 | p3 |
| Later | Independent infrastructure, follow-ups | #5, #10, #7, #9, #4, #2, #34 | p4 |

## Phase 0: docs

- [x] PR #18: how pages get linked, what `status` and `entity_kind` mean.

## Phase 1: stop wrong merges and invented content at the source

Every integration with a wrong merge or an invented name creates work for a later split
or rename (phase 4), so this goes first. #15 and #13 share one root cause: resolve's exact name/alias match
(`stages/resolve.py`) skips the "same thing?" question. They share code and a bench run.

- [x] **#15** (bug): an exact match only on the subject's *name*; a match through an
      alias goes to the yes/no check. Extract prompt: aliases are other names for the
      same thing only. Drop aliases that are another page's name. The kind guard (its
      fix 2) moves to #16.
- [x] **#13**, cut down to option 1 (prompt rules; local ids like "WP2" never skip the
      check) plus option 3 (producer advice in `docs/wiki/Source-Packets.md`). Option 2
      (`part_of`) moves to #16. Stacked on #15.
- [x] **#22** (bug, from #13's notes): a `replace` can keep a claim's
      citation but change its fact to another source's. Validation (L-4) checks that
      links and citations survive, not that a cited fact still says the same thing.
- [x] **#25** (bug): extract can invent a page title (glued acronym + made-up
      expansion), and new titles and aliases are never checked against the source. Closes
      TD-29's "page titles aren't checked" gap. Independent of #15/#13 in code, but its
      bench check can share their run.

Bench after #15 + #13 together: resolve wrong merges stay 0, coverage not lower than
the current baseline.

## Phase 2: vault-specific knowledge

Phase 1 stops wrong merges; this phase lets a vault tell the pipeline what it already
knows, so that names which mean one thing end up on one page.

- [x] **#24** glossary: a curated list of abbreviations and full names that code reads
      (resolve exact match, aliases, the abbreviation check, the preferred form in
      links). It is the structured part of #14, taken out because it is deterministic,
      needs no prompt rules and helps most in acronym-heavy vaults. It goes first: #14
      and #16 can build on its file and parser. It builds on #15 (curated aliases are
      trusted, model aliases are checked).
- [x] **#27** a source declares its project (`source.meta.json` `project`, or
      `integrate --project`); code expands its bare local ids (`WP2`) to that project, so
      a later report finds the proposal's pages by exact match. Small, builds on #13; the
      packet-level form of #16's scoped kinds, so #16 can later use it as the owner.
- [ ] **#14** domain rules: a `## Domain rules` section in `WIKI.md` that extract and
      resolve read. Simplest home for the vault-specific local-id patterns of #13.
- [ ] **#16** ontology, first version = kinds + scoped kinds. Takes over #13 option 2
      (`part_of`), #15 fix 2 (the kind guard) and #20's D2 (lint on unknown kinds).
- [ ] **#33** a source packet declares the local ids the document defines (work packages,
      tasks, deliverables, milestones); code uses that list instead of guessing from the
      shape. After #16, whose scoped kinds it shares. Producer side: mneme#22.

## Phase 3: keep pages up to date, see the vault

These are small, code only and independent of each other.

- [ ] **#20** list pages by type, kind, status, tag (CLI + MCP), plus counts in
      `status`. Absorbs #8. A cheap diagnostic aid: it may be pulled before phase 1 if
      wrong merges need to be found by hand.
- [ ] **#23** catch-up command: one code-only command
      (`mneme-wiki refresh [--dry-run]`, one commit) that brings an existing vault up to
      today's rules. #17 and #19 each add a rule to it, instead of each building their
      own catch-up. Its D1 suggests shipping it together with #19.
- [ ] **#19** recompute `stub`/`active` when integrate writes a page.
- [ ] **#17** autolink older pages to pages a run creates.
- [ ] **#32** in-depth pipeline reference: every stage, code vs model, prompts. Last in the
      phase, so it describes the pipeline after #14, #16, #19 and #17.

## Phase 4: repair

- [ ] **#6** gated merge, rename **and split**: split is needed to clean up pages
      merged before phase 1 (#13, #15).
- [ ] **#3** re-integrate a source that changed upstream.

## Later

No dependencies on the phases above; ordered by expected value.

- [ ] #5 LLM lint (contradictions, stale claims, missing concepts)
- [ ] #10 parallel patch calls
- [ ] #7 watch the inbox
- [ ] #9 image handling
- [ ] #4 embedding search beyond the MVP scale
- [ ] #2 opt-in remote backend (OpenRouter)
- [ ] #34 deadlines and leads of work packages, deliverables and milestones (split out of #33)

## Issue changes made with this plan

Done on GitHub on 2026-11-11:

- [x] Close #8 with a pointer to #20 (Dataview covers generated views in Obsidian).
- [x] Widen #6 to "merge, rename and split".
- [x] Cut #13 down to options 1 + 3; move option 2 to #16.
- [x] #16: `entity_kind` is already a fixed list (`stages/common.py`), not free text;
      take over #15 fix 2 and #20 D2.
- [x] File the replace-fact bug (#22) and the catch-up command issue (#23).
- [x] Cross-reference comments: #15 ↔ #13, #13/#15/#20 → #16, #17/#19 → #23.
- [x] #15: its only open decision is answered by the plan, `decision-needed` removed.
