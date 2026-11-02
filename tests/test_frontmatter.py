from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mneme_wiki import frontmatter as fm

from .conftest import FIXTURES

BROKEN = {"unterminated.md", "not-a-mapping.md", "bad-syntax.md", "duplicate-key.md"}
ALL_MD = sorted(FIXTURES.rglob("*.md"))
PARSABLE = [p for p in ALL_MD if p.name not in BROKEN]


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def rel_id(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


# --- the M1 exit condition: unchanged documents round-trip byte for byte --------
@pytest.mark.parametrize("path", PARSABLE, ids=rel_id)
def test_round_trip_is_byte_exact(path: Path) -> None:
    text = read(path)
    assert fm.dump(fm.parse(text)) == text


@pytest.mark.parametrize("path", PARSABLE, ids=rel_id)
def test_round_trip_after_noop_edit(path: Path) -> None:
    """Re-assigning meta/body with equal values must not rewrite anything."""
    text = read(path)
    doc = fm.parse(text)
    doc.meta = dict(doc.meta)
    doc.body = str(doc.body)
    assert fm.dump(doc) == text


def test_body_edit_keeps_front_matter_verbatim() -> None:
    text = read(FIXTURES / "clean/entities/rover-operations-control-centre.md")
    doc = fm.parse(text)
    doc.body += "\nOne more line.\n"
    out = fm.dump(doc)
    assert out.startswith(doc.raw_front)
    assert "# Hand-written comment" in out
    assert out.endswith("One more line.\n")


def test_meta_edit_keeps_order_unknown_keys_and_body() -> None:
    text = read(FIXTURES / "clean/entities/rover-operations-control-centre.md")
    doc = fm.parse(text)
    doc.meta["aliases"].append("Ops Centre")
    doc.meta["custom_new"] = 1
    doc.meta["contradicts"] = ["[[entities/other]]"]
    out = fm.dump(doc)
    again = fm.parse(out)
    # existing keys in their original order, then new keys: schema ones first
    assert list(again.meta) == [*fm.parse(text).meta, "contradicts", "custom_new"]
    assert again.meta["reviewed_by"] == "thomas"
    assert again.meta["aliases"] == ["ROCC", "Rover Ops Centre", "Ops Centre"]
    assert again.meta["created"] == dt.date(2026, 11, 2)
    assert again.body == doc.body
    assert "aliases: [ROCC, Rover Ops Centre, Ops Centre]\n" in out
    assert "&id" not in out


def test_meta_edit_keeps_crlf_and_bom() -> None:
    text = read(FIXTURES / "clean/concepts/tactical-planning-cycle.md")
    doc = fm.parse(text)
    assert doc.bom and doc.newline == "\r\n"
    doc.meta["status"] = "stub"
    doc.body += "\nNew line\n"
    out = fm.dump(doc)
    assert out.startswith(fm.BOM + "---\r\n")
    assert "\n" not in out.replace("\r\n", "")  # no bare LF anywhere
    assert fm.parse(out).meta["status"] == "stub"


def test_no_front_matter() -> None:
    text = "# Title\n\nBody.\n"
    doc = fm.parse(text)
    assert doc.meta == {} and doc.raw_front is None and fm.dump(doc) == text
    doc.meta["title"] = "Title"
    assert fm.dump(doc) == "---\ntitle: Title\n---\n" + text


def test_removing_all_meta_drops_block() -> None:
    doc = fm.parse("---\ntitle: X\n---\nbody\n")
    doc.meta.clear()
    assert fm.dump(doc) == "body\n"


@pytest.mark.parametrize(
    "text",
    ["---\n---\n", "---\n---", "---\ntitle: X\n---", "---\ntitle: X\n...\nbody\n"],
)
def test_edge_delimiters_round_trip(text: str) -> None:
    assert fm.dump(fm.parse(text)) == text


def test_horizontal_rule_is_not_front_matter() -> None:
    assert fm.parse("# T\n\n---\n\ntext\n").meta == {}


@pytest.mark.parametrize("name", sorted(BROKEN))
def test_broken_yaml_raises(name: str) -> None:
    with pytest.raises(fm.FrontMatterError):
        fm.parse(read(FIXTURES / "broken-yaml/concepts" / name))


def test_duplicate_key_message() -> None:
    with pytest.raises(fm.FrontMatterError, match="duplicate key 'title'"):
        fm.parse(read(FIXTURES / "broken-yaml/concepts/duplicate-key.md"))


def test_new_document_serialises_in_full() -> None:
    doc = fm.new_document({"title": "A", "type": "concept"}, "\n# A\n")
    assert fm.dump(doc) == "---\ntitle: A\ntype: concept\n---\n\n# A\n"


def test_multiline_string_uses_block_scalar() -> None:
    doc = fm.new_document({"title": "A", "note": "line 1\nline 2"}, "")
    assert "note: |-\n  line 1\n  line 2\n" in fm.dump(doc)


# --- validation -----------------------------------------------------------------
@pytest.mark.parametrize("path", sorted((FIXTURES / "clean").rglob("*.md")), ids=rel_id)
def test_clean_pages_validate(path: Path) -> None:
    if path.name == "WIKI.md":
        pytest.skip("schema file, not a page")
    assert fm.validate(fm.parse(read(path)).meta) == []


def fields(meta: dict) -> set[str]:
    return {i.field for i in fm.validate(meta)}


def test_invalid_schema_is_reported() -> None:
    meta = fm.parse(read(FIXTURES / "broken-yaml/concepts/invalid-schema.md")).meta
    issues = fm.validate(meta)
    assert all(i.level == "error" for i in issues)
    assert {i.field for i in issues} == {"type", "status", "aliases", "sources", "created"}


def test_missing_title_and_type() -> None:
    assert fields({}) == {"title", "type"}


def test_no_front_matter_page_is_invalid() -> None:
    meta = fm.parse(read(FIXTURES / "broken-yaml/concepts/no-front-matter.md")).meta
    assert fields(meta) == {"title", "type"}


def test_content_page_needs_dates_and_type_fields() -> None:
    assert fields({"title": "X", "type": "entity"}) == {"created", "updated", "entity_kind"}
    assert "question" in fields({"title": "X", "type": "synthesis"})
    assert {"source_type", "origin"} <= fields({"title": "X", "type": "source"})
    meta = fm.parse(read(FIXTURES / "broken-yaml/concepts/missing-type-fields.md")).meta
    assert fields(meta) == {"entity_kind"}


def test_index_and_log_need_no_dates() -> None:
    assert fields({"title": "Index", "type": "index"}) == set()


@pytest.mark.parametrize("value", ["2026-11-02", dt.date(2026, 11, 2)])
def test_dates_ok(value) -> None:
    assert "updated" not in fields({"title": "X", "type": "index", "updated": value})


@pytest.mark.parametrize("value", ["2026-11", "02.11.2026", 2026, dt.datetime(2026, 11, 2)])
def test_dates_bad(value) -> None:
    assert "updated" in fields({"title": "X", "type": "index", "updated": value})
