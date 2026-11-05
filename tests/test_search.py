from __future__ import annotations

import json

from mneme_wiki import cli
from mneme_wiki.search import Doc, SearchIndex, search
from mneme_wiki.vault import Vault

from .conftest import FIXTURES

CLEAN = Vault(FIXTURES / "clean")


def paths(hits) -> list[str]:
    return [h.path for h in hits]


def test_title_match_ranks_first() -> None:
    assert paths(search(CLEAN, "planning cycle"))[0] == "concepts/tactical-planning-cycle.md"
    assert paths(search(CLEAN, "rover operations"))[0] == (
        "entities/rover-operations-control-centre.md"
    )


def test_alias_and_case_insensitive() -> None:
    assert paths(search(CLEAN, "tpc"))[0] == "concepts/tactical-planning-cycle.md"


def test_german_words_in_body() -> None:
    assert paths(search(CLEAN, "Zyklus Stunden")) == ["concepts/tactical-planning-cycle.md"]


def test_no_match_and_empty_query() -> None:
    assert search(CLEAN, "spacecraft telemetry") == []
    assert search(CLEAN, "  !! ") == []


def test_type_filter_exclude_and_limit() -> None:
    hits = search(CLEAN, "ROCC", types=["entity"])
    assert paths(hits) == ["entities/rover-operations-control-centre.md"]
    index = SearchIndex.from_vault(CLEAN)
    all_hits = index.search("ROCC")
    assert len(index.search("ROCC", limit=2)) == 2
    excluded = index.search("ROCC", exclude=[all_hits[0].path])
    assert all_hits[0].path not in paths(excluded)
    assert all(h.snippet for h in all_hits)


def test_index_and_log_are_not_searched() -> None:
    assert not any(h.type in ("index", "log") for h in search(CLEAN, "integrate index log"))


def test_empty_index() -> None:
    assert SearchIndex([]).search("x") == []
    empty = Doc("a.md", "", "concept", (), "", "")
    assert SearchIndex([empty]).search("x") == []


def test_cli_search_json(capsys) -> None:
    assert cli.main(["search", "TPC", "--vault", str(FIXTURES / "clean"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hits"][0]["path"] == "concepts/tactical-planning-cycle.md"
    assert cli.main(["search", "telemetry spacecraft", "--vault", str(FIXTURES / "clean")]) == 0
    assert "no matches" in capsys.readouterr().out
