from __future__ import annotations

from mneme_wiki import expansions as x

SOURCE = "The DAR stores targets. The Rover Operations Control Centre (ROCC) plans each sol."


def test_finds_all_explicit_forms() -> None:
    found = x.find(
        "MMGIS (Mission Management Geospatial Interface) reads the Data Archive and "
        "Retrieval (DAR). RVP stands for Rover Visualization Platform.",
        SOURCE,
    )
    assert [(e.abbr, e.long) for e in found] == [
        ("MMGIS", "Mission Management Geospatial Interface"),
        ("DAR", "Data Archive and Retrieval"),
        ("RVP", "Rover Visualization Platform"),
    ]
    assert found[-1].replacement is None  # a sentence can't lose its predicate


def test_backed_expansions_and_other_brackets_stay() -> None:
    text = (
        "ROCC (Rover Operations Control Centre) and the rover operations control centre "
        "(ROCC) use the DAR (see below), MMGIS (2 tools) and PRo3D (Tool)."
    )
    assert x.find(text, SOURCE) == []
    assert x.strip(text, SOURCE) == text


def test_strip_keeps_the_sentence() -> None:
    counters: dict[str, int] = {}
    text = (
        "The Data Archive and Retrieval (DAR) feeds MMGIS (Mission Management Interface) "
        "([[sources/a]])."
    )
    assert x.strip(text, SOURCE, counters) == "The DAR feeds MMGIS ([[sources/a]])."
    assert counters == {"expansion_removed": 2}


def test_strip_after_a_link_keeps_the_link() -> None:
    text = "Stored in [[entities/dar|DAR]] (Data Archive and Retrieval) every sol."
    assert x.strip(text, SOURCE) == "Stored in [[entities/dar|DAR]] every sol."


def test_stands_for_is_reported_not_removed() -> None:
    text = "DAR stands for Data Archive and Retrieval."
    assert x.strip(text, SOURCE) == text
    assert len(x.find(text, SOURCE)) == 1


def test_words_before_the_expansion_are_not_part_of_it() -> None:
    text = "Uses Data Archive and Retrieval (DAR) daily."
    assert [e.long for e in x.find(text, SOURCE)] == ["Data Archive and Retrieval"]
    assert x.strip(text, SOURCE) == "Uses DAR daily."
    assert x.strip("The Data Archive Room (DAR) stores.", SOURCE) == "The DAR stores."
