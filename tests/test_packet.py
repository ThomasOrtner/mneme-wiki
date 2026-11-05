from __future__ import annotations

import json
from pathlib import Path

import pytest

from mneme_wiki import packet

from .conftest import FIXTURES

PACKETS = FIXTURES / "packets"


def test_load_fixture_packets() -> None:
    p = packet.load(PACKETS / "ops-handbook")
    assert p.name == "ops-handbook" and p.title == "Rover Operations Handbook"
    assert p.summary is None and p.meta["author"] == "Test Team"
    q = packet.load(PACKETS / "planning-notes")
    assert q.summary.startswith("# Planning Workshop Notes")


def _packet(tmp_path: Path, meta: object, text: str = "# T\n\nbody\n") -> Path:
    d = tmp_path / "p"
    d.mkdir(exist_ok=True)
    (d / "source.md").write_bytes(text.encode("utf-8"))
    (d / "source.meta.json").write_bytes(
        (meta if isinstance(meta, str) else json.dumps(meta)).encode("utf-8")
    )
    return d


GOOD = {"title": "T", "source_type": "note", "origin": "manual", "date": "2026-11-05"}


@pytest.mark.parametrize(
    ("meta", "text", "message"),
    [
        ({**GOOD, "origin": ""}, "x", "lacks origin"),
        ({"title": "T"}, "x", "lacks source_type, origin, date"),
        ("{not json", "x", "not valid JSON"),
        ("[1, 2]", "x", "must be an object"),
        (GOOD, "  \n", "is empty"),
    ],
)
def test_bad_packets(tmp_path: Path, meta, text, message) -> None:
    with pytest.raises(packet.PacketError, match=message):
        packet.load(_packet(tmp_path, meta, text))


def test_missing_files(tmp_path: Path) -> None:
    with pytest.raises(packet.PacketError, match="not a packet folder"):
        packet.load(tmp_path / "nope")
    (tmp_path / "p").mkdir()
    with pytest.raises(packet.PacketError, match="missing source.md"):
        packet.load(tmp_path / "p")


def test_crlf_bom_and_broken_toc(tmp_path: Path) -> None:
    d = _packet(tmp_path, GOOD, "﻿# T\r\n\r\nbody\r\n")
    (d / "toc.json").write_bytes(b"{broken")
    p = packet.load(d)
    assert p.text == "# T\n\nbody\n" and p.toc is None


def test_sections_ignore_headings_in_code() -> None:
    text = (PACKETS / "ops-handbook/source.md").read_text(encoding="utf-8")
    assert [loc for loc, _ in packet.sections(text)] == [
        "Rover Operations Handbook",
        "Organisation",
        "Planning",
    ]
    assert packet.sections("intro\n\n# A\nx")[0] == ("start", "intro")


def test_chunk_packs_and_splits() -> None:
    small = "\n\n".join(f"## S{i}\n\n" + "word " * 100 for i in range(6))
    chunks = packet.chunk(small, max_words=250)
    assert [c.locator for c in chunks] == ["S0", "S2", "S4"]
    assert all(c.words <= 250 for c in chunks)
    big = "## Big\n\n" + "\n\n".join("word " * 90 for _ in range(5))
    chunks = packet.chunk(big, max_words=200)
    assert len(chunks) == 3 and {c.locator for c in chunks} == {"Big"}
    assert [c.index for c in chunks] == [0, 1, 2]
