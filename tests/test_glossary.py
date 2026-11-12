from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mneme_wiki import expansions, glossary, links
from mneme_wiki import frontmatter as fm
from mneme_wiki.integrate import integrate
from mneme_wiki.lint import lint
from mneme_wiki.stages import autolink
from mneme_wiki.vault import Page, Vault, init_vault

from .conftest import FIXTURES
from .fakes import Toy, fake_llm
from .test_vault import git_identity  # noqa: F401 - pytest fixture

PACKETS = FIXTURES / "packets"
DAY = dt.date(2026, 11, 5)
ROCC_FULL = "Rover Operations Control Centre"
TABLE = """# Glossary

Curated names for this vault.

| Term | Full name | Kind | Prefer | Definition |
|---|---|---|---|---|
| ROCC | Rover Operations Control Centre | organisation | {prefer} | Operates the rover. |
| TPC | Tactical Planning Cycle | concept | full | The daily planning loop. |
"""


@pytest.fixture
def vault(tmp_path: Path, git_identity) -> Vault:  # noqa: F811
    return init_vault(tmp_path / "vault", language="en", today=DAY)


def with_glossary(vault: Vault, text: str) -> None:
    vault.write_text("glossary.md", text)
    vault.git("add", "-A")
    vault.git("commit", "-q", "-m", "schema: glossary")


def run(vault: Vault, name: str, toy: Toy | None = None):
    llm, backend = fake_llm(toy or Toy(kinds={"ROCC": "entity", ROCC_FULL: "entity"}))
    report = integrate(vault, PACKETS / name, llm=llm, inbox=vault.root.parent / "inbox",
                       today=DAY)  # fmt: skip
    return report, backend


# -- parsing -------------------------------------------------------------------------
def test_parse_reads_the_fixed_columns() -> None:
    g = glossary.parse(TABLE.format(prefer="short"))
    rocc, tpc = g.terms
    assert (rocc.term, rocc.full, rocc.kind, rocc.entity_kind, rocc.prefer) == (
        "ROCC", ROCC_FULL, "entity", "organisation", "short")  # fmt: skip
    assert rocc.definition == "Operates the rover." and rocc.line == 7
    assert (tpc.kind, tpc.prefer, tpc.title) == ("concept", "full", "Tactical Planning Cycle")
    assert g.lookup("rocc") is rocc and g.lookup(ROCC_FULL.upper()) is rocc
    assert not g.problems


def test_parse_reports_bad_rows_instead_of_failing() -> None:
    g = glossary.parse(
        "| Term | Full name | Kind | Prefer | Definition |\n|---|---|---|---|---|\n"
        "| [[entities/rocc|ROCC]] | **Rover Operations Control Centre** | team | | |\n"
        "| X | Y | weird | sometimes | |\n"
        "| only two | cells |\n"
        "| | | | | nothing named |\n"
        "| ROCC | Something Else | | | |\n"
    )
    assert [t.title for t in g.terms] == [ROCC_FULL, "Y"]
    assert g.terms[0].term == "ROCC"  # link syntax and emphasis are stripped
    assert [(p.line, p.check) for p in g.problems] == [
        (4, "glossary-format"), (4, "glossary-format"), (5, "glossary-format"),
        (6, "glossary-format"), (7, "glossary-conflict"),
    ]  # fmt: skip
    assert glossary.parse("no table here").terms == []


def test_glossary_file_is_not_a_page(vault: Vault) -> None:
    with_glossary(vault, TABLE.format(prefer=""))
    assert "glossary.md" not in vault.page_paths()
    assert lint(vault).ok


# -- integrate (fake model) --------------------------------------------------------------
def test_without_glossary_the_two_names_stay_two_pages(vault: Vault) -> None:
    report, backend = run(vault, "rocc-two-ways")
    assert {"entities/rocc.md", "entities/rover-operations-control-centre.md"} <= set(
        report.created
    )
    assert any(r["role"] == "resolve" for r in backend.requests)  # the yes/no question


def test_glossary_makes_one_page_by_exact_match(vault: Vault) -> None:
    with_glossary(vault, TABLE.format(prefer="short"))
    report, backend = run(vault, "rocc-two-ways")
    assert report.ok
    assert "entities/rover-operations-control-centre.md" in report.created
    assert "entities/rocc.md" not in report.created
    page = vault.read_page("entities/rover-operations-control-centre.md")
    assert page.title == ROCC_FULL and page.meta["aliases"] == ["ROCC"]
    assert page.meta["entity_kind"] == "organisation"
    assert "twelve operators" in page.body and "every sol" in page.body
    assert not any(r["role"] == "resolve" for r in backend.requests)
    assert report.counters["glossary_matched"] == 2


def test_extract_sees_the_terms_mentioned_in_the_chunk(vault: Vault) -> None:
    with_glossary(vault, TABLE.format(prefer=""))
    _, backend = run(vault, "rocc-two-ways")
    first = next(r["user"] for r in backend.requests if r["role"] == "extract")
    assert f"{ROCC_FULL} (aka ROCC)" in first and "Tactical Planning Cycle" not in first


def test_an_unrelated_glossary_changes_no_prompt(vault: Vault, tmp_path: Path) -> None:
    _, plain = run(vault, "rocc-two-ways")
    other = init_vault(tmp_path / "other", language="en", today=DAY)
    header = "| Term | Full name | Kind | Prefer | Definition |\n|---|---|---|---|---|\n"
    with_glossary(other, header + "| ZZZ | Zebra Zone Zero | | | |\n")
    _, with_unrelated = run(other, "rocc-two-ways")
    assert [r["user"] for r in plain.requests] == [r["user"] for r in with_unrelated.requests]


def test_existing_page_gets_glossary_names_when_touched(vault: Vault) -> None:
    """D6: a page made before the glossary existed (`ROCC`, no aliases) is found by the
    full name and gets it as alias."""
    page = Page("entities/rocc.md", fm.new_document(
        {"title": "ROCC", "type": "entity", "entity_kind": "organisation", "aliases": [],
         "created": DAY, "updated": DAY, "sources": [], "status": "stub"},
        "\n# ROCC\n\nA human note about the ROCC.\n"))  # fmt: skip
    vault.write_page(page)
    with_glossary(vault, TABLE.format(prefer=""))
    report, backend = run(vault, "rocc-two-ways")
    assert report.updated == ["entities/rocc.md"] and not report.created[1:]
    assert vault.read_page("entities/rocc.md").meta["aliases"] == [ROCC_FULL]
    assert not any(r["role"] == "resolve" for r in backend.requests)


# -- autolink, abbreviations ---------------------------------------------------------------
def _page(path: str, title: str, aliases: list[str], body: str = "") -> Page:
    meta = {"title": title, "type": "entity", "aliases": aliases}
    return Page(path, fm.new_document(meta, body or f"\n# {title}\n"))


@pytest.mark.parametrize(("prefer", "shown"), [("short", "ROCC"), ("full", ROCC_FULL)])
def test_autolink_shows_the_preferred_form(prefer: str, shown: str) -> None:
    g = glossary.parse(TABLE.format(prefer=prefer))
    target = _page("entities/rocc.md", ROCC_FULL, [])  # alias not on the page yet
    names = autolink.names_for([target], g)
    index = links.LinkIndex(["entities/rocc.md", "concepts/a.md", "concepts/b.md"])
    for text in ("The ROCC plans the sol.", f"The {ROCC_FULL} plans the sol."):
        body, n = autolink.link_body(text, "concepts/a.md", names, index)
        assert n == 1 and f"[[entities/rocc|{shown}]]" in body


def test_autolink_without_prefer_keeps_the_text() -> None:
    g = glossary.parse(TABLE.format(prefer=""))
    names = autolink.names_for([_page("entities/rocc.md", ROCC_FULL, ["ROCC"])], g)
    index = links.LinkIndex(["entities/rocc.md", "concepts/a.md"])
    body, _ = autolink.link_body("The ROCC plans.", "concepts/a.md", names, index)
    assert "[[entities/rocc|ROCC]]" in body


def test_glossary_backs_a_correct_expansion_only() -> None:
    g = glossary.parse(TABLE.format(prefer=""))
    evidence = "A note that only says ROCC.\n" + g.evidence()
    good = expansions.strip("The ROCC (Rover Operations Control Centre) plans.", evidence)
    bad = expansions.strip("The ROCC (Rover Orbit Command Centre) plans.", evidence)
    assert good == "The ROCC (Rover Operations Control Centre) plans."
    assert bad == "The ROCC plans."
