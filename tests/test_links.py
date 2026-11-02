from __future__ import annotations

import pytest

from mneme_wiki import links
from mneme_wiki.vault import Vault

from .conftest import FIXTURES


def one(text: str) -> links.Link:
    found = links.extract(text)
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize(
    ("text", "target", "heading", "alias"),
    [
        ("[[page]]", "page", None, None),
        ("[[folder/page]]", "folder/page", None, None),
        ("[[page|Alias]]", "page", None, "Alias"),
        ("[[page#Heading]]", "page", "Heading", None),
        ("[[page#Heading|Alias]]", "page", "Heading", "Alias"),
        ("[[#Heading]]", "", "Heading", None),
        ("[[page\\|Alias]]", "page", None, "Alias"),  # escaped pipe inside a table
        ("[[ page | Alias ]]", "page", None, "Alias"),
        ("[[page.md]]", "page.md", None, None),
        ("[[Größe des Rovers]]", "Größe des Rovers", None, None),
    ],
)
def test_extract_forms(text, target, heading, alias) -> None:
    link = one(f"before {text} after")
    assert (link.target, link.heading, link.alias, link.embed) == (target, heading, alias, False)
    assert link.raw == text


def test_embed_and_offsets() -> None:
    text = "x ![[attachments/a.png]] y [[b]]"
    embed, plain = links.extract(text)
    assert embed.embed and embed.target == "attachments/a.png"
    assert not plain.embed
    for link in (embed, plain):
        assert text[link.start : link.end] == link.raw


def test_links_in_code_are_ignored() -> None:
    text = (
        "[[a]] `[[inline]]` ``[[double `tick`]]``\n"
        "```\n[[fenced]]\n```\n"
        "~~~~python\n[[tilde]]\n~~~\n[[still-fenced]]\n~~~~\n"
        "[[b]]\n"
    )
    assert [lk.target for lk in links.extract(text)] == ["a", "b"]


def test_unclosed_fence_masks_to_end() -> None:
    assert [lk.target for lk in links.extract("[[a]]\n```\n[[b]]\n")] == ["a"]


def test_mask_keeps_length_and_newlines() -> None:
    text = "a `code` b\r\n```\r\nx\r\n```\r\n"
    masked = links.mask_code(text)
    assert len(masked) == len(text) and masked.count("\n") == text.count("\n")


def test_not_links() -> None:
    assert links.extract("[single] [[]] [[a\nb]]") == []


def test_headings() -> None:
    body = "# Title\n\n## Größe und Dauer ##\n```\n# not a heading\n```\n#nospace\n"
    assert links.headings(body) == ["Title", "Größe und Dauer"]


def test_format_link() -> None:
    assert links.format_link("concepts/rag.md") == "[[concepts/rag]]"
    assert links.format_link("concepts/rag.md", alias="RAG") == "[[concepts/rag|RAG]]"
    assert links.format_link("concepts/rag", heading="Use") == "[[concepts/rag#Use]]"


# --- resolution -------------------------------------------------------------------
@pytest.fixture
def index() -> links.LinkIndex:
    return links.LinkIndex(
        [
            "concepts/overview.md",
            "sources/overview.md",
            "entities/rocc.md",
            "concepts/Größe des Rovers.md",
            "attachments/diagram.png",
            "a/b/deep.md",
        ]
    )


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("rocc", "entities/rocc.md"),
        ("ROCC", "entities/rocc.md"),
        ("entities/rocc", "entities/rocc.md"),
        ("entities/rocc.md", "entities/rocc.md"),
        ("Entities/ROCC", "entities/rocc.md"),
        ("/entities/rocc", "entities/rocc.md"),
        ("concepts/overview", "concepts/overview.md"),
        ("größe des rovers", "concepts/Größe des Rovers.md"),
        ("diagram.png", "attachments/diagram.png"),
        ("attachments/diagram.png", "attachments/diagram.png"),
        ("b/deep", "a/b/deep.md"),  # path suffix, as in Obsidian
    ],
)
def test_resolve(index, target, expected) -> None:
    assert index.resolve(target) == expected


def test_ambiguous_and_broken(index) -> None:
    assert index.candidates("overview") == ["concepts/overview.md", "sources/overview.md"]
    assert index.resolve("overview") is None
    assert index.candidates("missing") == []
    assert index.candidates("") == []
    assert index.candidates("diagram") == []  # non-Markdown files need their extension


def _vault_links(name: str):
    vault = Vault(FIXTURES / name)
    metas, by_page = {}, {}
    for rel, page in vault.iter_pages():
        metas[rel] = page.meta
        by_page[rel] = links.extract(page.body)
    return vault, metas, by_page


def test_clean_fixture_has_no_broken_links() -> None:
    vault, _, by_page = _vault_links("clean")
    index = links.LinkIndex(vault.files())
    broken = [
        (rel, lk.raw)
        for rel, lks in by_page.items()
        for lk in lks
        if lk.target and index.resolve(lk.target) is None
    ]
    assert broken == []


def test_broken_links_fixture() -> None:
    vault, _, by_page = _vault_links("broken-links")
    index = links.LinkIndex(vault.files())
    found = {lk.target: len(index.candidates(lk.target)) for lks in by_page.values() for lk in lks}
    assert found["concepts/missing-page"] == 0
    assert found["nowhere"] == 0
    assert found["overview"] == 2  # ambiguous
    assert found["concepts/overview"] == 1  # resolves; the missing heading is a lint check (M2)
    assert found["rocc"] == 1


def test_backlinks_on_clean_fixture() -> None:
    vault, _, by_page = _vault_links("clean")
    back = links.backlinks(by_page, links.LinkIndex(vault.files()))
    assert back["sources/rocc-glossary.md"] >= {
        "entities/rover-operations-control-centre.md",
        "concepts/tactical-planning-cycle.md",
    }
    assert back["attachments/diagram.png"] == {"concepts/activity-plan.md"}
    assert back["concepts/tactical-planning-cycle.md"] >= {"concepts/activity-plan.md"}


def test_backlinks_skip_self_links() -> None:
    index = links.LinkIndex(["a.md"])
    assert links.backlinks({"a.md": links.extract("[[a]] [[#Heading]]")}, index) == {}


def test_alias_map_finds_duplicates() -> None:
    metas = {
        "entities/rocc.md": {"title": "ROCC", "aliases": ["Rover Ops Centre"]},
        "entities/rover-operations-control-centre.md": {
            "title": "Rover Operations Control Centre",
            "aliases": ["rocc", "Rover  Ops   Centre"],
        },
        "bad.md": {"title": None, "aliases": "not-a-list"},
    }
    amap = links.alias_map(metas)
    assert amap["rocc"] == {"entities/rocc.md", "entities/rover-operations-control-centre.md"}
    assert amap["rover ops centre"] == amap["rocc"]
    assert "not-a-list" not in amap


def test_alias_map_on_fixture() -> None:
    _, metas, _ = _vault_links("clean")
    amap = links.alias_map(metas)
    assert amap["tpc"] == {"concepts/tactical-planning-cycle.md"}
    assert all(len(paths) == 1 for paths in amap.values())
