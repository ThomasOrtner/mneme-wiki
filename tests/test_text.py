from __future__ import annotations

from mneme_wiki import text

BODY = """
# Title

Lead paragraph that
spans two lines ([[sources/a]]).

- item one
  continued
- item two
1. numbered

> [!warning] Contradiction
> quoted

| a | b |
|---|---|

```text
## not a heading
```

![[attachments/x.png]]

---

## Section

<!-- html -->
Plain paragraph.
"""


def test_blocks_kinds_and_lines() -> None:
    got = [(b.kind, b.line) for b in text.blocks(BODY)]
    assert got == [
        ("heading", 2),
        ("paragraph", 4),
        ("list_item", 7),
        ("list_item", 9),
        ("list_item", 10),
        ("quote", 12),
        ("table", 15),
        ("code", 18),
        ("embed", 22),
        ("rule", 24),
        ("heading", 26),
        ("html", 28),
    ]
    blocks = text.blocks(BODY)
    assert blocks[2].text == "- item one\n  continued"
    assert blocks[10].level == 2 and blocks[10].text == "Section"


def test_unclosed_fence_runs_to_end() -> None:
    assert [b.kind for b in text.blocks("a\n\n```\n# x\n\nb\n")] == ["paragraph", "code"]


def test_lead() -> None:
    lead = text.lead(BODY)
    assert lead is not None and lead.line == 4
    assert text.lead("# T\n\n## H2\n\nlate paragraph\n") is None
    assert text.lead("no heading at all\n").text == "no heading at all"


def test_plain() -> None:
    md = (
        "The **ROCC** runs [[concepts/tactical-planning-cycle]] and [[a|the alias]] "
        "`code` ([[sources/x]])."
    )
    assert text.plain(md) == "The ROCC runs tactical planning cycle and the alias code."
    assert text.plain(md, drop_citations=False).endswith("code (x).")
    assert text.plain("- item with ![[img.png]] [md](http://x)") == "item with md"
    assert text.plain("cite ([[sources/a]], [[sources/b]]) here") == "cite here"


def test_first_sentence() -> None:
    assert text.first_sentence("One. Two.") == "One."
    assert (
        text.first_sentence("e.g. lower case keeps going. Next.") == "e.g. lower case keeps going."
    )
    long = "word " * 40
    cut = text.first_sentence(long, 30)
    assert len(cut) <= 30 and cut.endswith("…")


def test_tokens() -> None:  # casefold() maps ß to ss, so Größe == GRÖSSE
    assert text.tokens("Größe, ROCC-team a 7 Zyklus") == ["grösse", "rocc", "team", "7", "zyklus"]
