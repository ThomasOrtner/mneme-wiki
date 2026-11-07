from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest

from mneme_wiki import bench, cli
from mneme_wiki import frontmatter as fm
from mneme_wiki.llm import Call
from mneme_wiki.vault import Page, init_vault

from .conftest import FIXTURES
from .fakes import Toy, fake_llm
from .test_vault import git_identity  # noqa: F401 - pytest fixture

KINDS = {"Rover Operations Control Centre": "entity", "Science Team": "entity"}


def page(path: str, body: str, **meta) -> Page:
    return Page(path, fm.new_document({"title": path, "type": "concept", **meta}, body))


def test_load_mapping(tmp_path: Path) -> None:
    f = tmp_path / "m.toml"
    f.write_text(
        'label = "think"\n[models]\npatch = "ollama:qwen3:8b"\n[thinking]\npatch = true\n'
        '[judge]\nmodel = "ollama:qwen3:14b"\nsample = 4\n',
        encoding="utf-8",
    )
    m = bench.load_mapping(f)
    assert m.label == "think" and m.models["patch"] == "ollama:qwen3:8b"
    assert m.models["extract"] == "ollama:qwen3:14b"  # default from config
    assert m.thinking["patch"] is True and m.thinking["resolve"] is True
    assert (m.judge, m.judge_sample) == ("ollama:qwen3:14b", 4)
    assert bench.load_mapping(f, "override").label == "override"
    f.write_text("[models]\nnope = 'x:y'\n", encoding="utf-8")
    with pytest.raises(bench.BenchError, match="unknown role"):
        bench.load_mapping(f)
    f.write_text("not = [toml", encoding="utf-8")
    with pytest.raises(bench.BenchError):
        bench.load_mapping(f)


def test_corpus_order(tmp_path: Path) -> None:
    for name in ("b", "a"):
        shutil.copytree(FIXTURES / "packets/ops-handbook", tmp_path / name)
    assert [p.name for p in bench.corpus_packets(tmp_path)] == ["a", "b"]
    (tmp_path / "order.txt").write_text("# order\nb\na\n", encoding="utf-8")
    assert [p.name for p in bench.corpus_packets(tmp_path)] == ["b", "a"]
    assert [p.name for p in bench.corpus_packets(tmp_path, ["a"])] == ["a"]
    with pytest.raises(bench.BenchError, match="not packets"):
        bench.corpus_packets(tmp_path, ["zzz"])


GOLD = {
    "pages": [
        {"title": "ROCC", "names": ["ROCC", "Rover Operations Control Centre"], "core": True},
        {"title": "Target", "names": ["Target"], "core": False},
        {"title": "DAR", "names": ["DAR"], "core": True},
        {"title": "Missing", "names": ["Nothing"], "core": False},
    ],
    "must_not_merge": [["Planning Target", "Local Target"], ["DAR", "Target"]],
}


def test_gold_metrics() -> None:
    pages = [
        page("entities/rocc.md", "", aliases=["ROCC"], sources=["[[sources/a]]", "[[sources/b]]"]),
        page("concepts/target.md", "", aliases=["Planning Target", "Local Target"]),
        page("entities/dar.md", "", sources=["[[sources/a]]"]),
        page("entities/dar-2.md", "", aliases=["DAR"]),
    ]
    pages[0].meta["title"] = "Rover Operations Control Centre"
    pages[2].meta["title"] = "DAR"
    pages[1].meta["title"] = "Target"
    g = bench.gold_metrics(pages, GOLD)
    assert (g["gold_found"], g["gold_total"], g["gold_missing"]) == (3, 4, ["Missing"])
    assert g["gold_duplicates"] == [
        {"gold": "DAR", "pages": ["entities/dar-2.md", "entities/dar.md"]}
    ]
    assert (g["core_merged"], g["core_total"], g["resolve_recall"]) == (1, 2, 0.5)
    assert g["wrong_merges"] == [
        {"pair": ["Planning Target", "Local Target"], "page": "concepts/target.md"}
    ]
    assert g["resolve_precision"] == 0.5  # 1 of 2 present pairs merged wrongly


def test_quality_metrics() -> None:
    body = (
        "\n# P\n\nLead sentence about the rover planning team here ([[sources/a]]).\n\n"
        "## Use Case 3\n\n- The rover team plans every sol of the mission ([[sources/a]]).\n"
        "- The rover team plans every sol of the mission again ([[sources/a]]).\n"
        "- A different fact about the [[concepts/x|X]] archive and its long history.\n\n"
        "## Overview\n\nShort.\n"
    )
    q = bench.quality_metrics([page("concepts/p.md", body, status="stub")], {"Use Case 3"})
    assert q["sections_per_page"] == 2 and q["bullets_per_page"] == 3
    assert q["duplicate_bullet_rate"] == round(1 / 3, 3)
    assert q["source_structure_headings"] == 0.5
    assert q["links_per_page"] == 1 and q["citation_coverage"] == 0.75
    assert q["stub_rate"] == 1.0


def test_call_metrics_and_aggregate() -> None:
    calls = [
        Call("extract", "m:a", "s", 1, False, 1.0, 100, 10, 0, "bad"),
        Call("extract", "m:a", "s", 2, True, 2.0, 300, 20, 0),
        Call("patch", "m:b", "s", 1, True, 4.0, 50, 5, 0),
    ]
    m = bench.call_metrics(calls)
    assert m["extract"]["json_ok_first_try"] == 0.0 and m["extract"]["retries"] == 1
    assert m["extract"]["tokens_in_max"] == 300 and m["patch"]["calls"] == 1
    runs = [
        {"seconds": 60, "completed": True, "pages": p, "rejected": 0, "lint_errors": 0,
         "lint_warnings": 1, "roles": m, "gold": None,
         "quality": {k: 0.5 for k in ("sections_per_page", "bullets_per_page",
                     "duplicate_bullet_rate", "source_structure_headings", "links_per_page",
                     "citation_coverage")}}
        for p in (10, 14)
    ]  # fmt: skip
    a = bench.aggregate(runs)
    assert a["pages"] == {"mean": 12, "sd": round(2**0.5 * 2, 3)}
    assert a["minutes"]["mean"] == 1 and a["roles"]["patch"]["model"] == "m:b"


def test_run_bench_with_fake_model(tmp_path: Path, git_identity, capsys) -> None:  # noqa: F811
    corpus = tmp_path / "corpus"
    for name in ("ops-handbook", "planning-notes"):
        shutil.copytree(FIXTURES / "packets" / name, corpus / name)
    (corpus / "order.txt").write_text("ops-handbook\nplanning-notes\n", encoding="utf-8")
    (corpus / "gold.json").write_text(json.dumps(GOLD), encoding="utf-8")
    mapping_file = tmp_path / "m.toml"
    mapping_file.write_text('[judge]\nmodel = "fake:judge"\nsample = 2\n', encoding="utf-8")

    def make_llm(models, thinking, log):
        toy = Toy(kinds=KINDS, same=[("Tactical Planning", "Tactical Planning Cycle")])

        def handler(role, system, user, schema, think):
            if role == "judge":
                return {"reason": "fine", "structure": 4, "redundancy": 5, "clarity": 3}
            return toy(role, system, user, schema, think)

        llm, _ = fake_llm(handler, log=log)
        llm.models["judge"] = "fake:judge"
        return llm

    mapping = bench.load_mapping(mapping_file, "toy")
    result = bench.run_bench(
        mapping, corpus, out_root=tmp_path / "results", repeats=2, make_llm=make_llm,
        now=dt.datetime(2026, 11, 5, 12, 0),
    )  # fmt: skip
    assert result.out_dir.name == "20261105-120000_toy"
    assert [r["completed"] for r in result.runs] == [True, True]
    run = result.runs[0]
    assert run["pages"] == 5 and run["lint_errors"] == 0 and run["rejected"] == 0
    assert [s["updated"] for s in run["sources"]] == [0, 2]
    assert run["gold"]["gold_found"] == 1  # only ROCC of the toy gold is in these packets
    assert run["judge"] == {"structure": 4, "redundancy": 5, "clarity": 3, "pages": 2}
    agg = result.aggregate
    assert agg["runs"] == 2 and agg["pages"]["sd"] == 0 and agg["judge_clarity"]["mean"] == 3
    assert agg["unbacked_expansions"]["mean"] == 0
    summary = (result.out_dir / "summary.md").read_text(encoding="utf-8")
    assert "# Bench `toy`" in summary and "judge: structure" in summary
    assert (result.out_dir / "run2/vault/index.md").is_file()

    other = tmp_path / "results/other"
    shutil.copytree(result.out_dir, other)
    assert cli.main(["bench", "--compare", str(result.out_dir), str(other)]) == 0
    table = capsys.readouterr().out
    assert "| | toy | toy |" in table and "core merged" in table
    assert cli.main(["bench", "--json"]) == 2

    # M5: the question set against the finished vaults
    qfile = tmp_path / "questions.md"
    qfile.write_text("# Questions\n\n- Who operates the rover?\n- Qwxyz?\n", encoding="utf-8")
    questions = bench.load_questions(qfile)
    assert questions == ["Who operates the rover?", "Qwxyz?"]

    def query_llm(models, thinking, log):
        src = "sources/rover-operations-handbook"
        llm, _ = fake_llm(lambda *a: {"answer": f"The ROCC ([[{src}]]).", "answerable": True,
                                      "pages": []})  # fmt: skip
        return llm

    agg = bench.run_questions(result.out_dir, questions, make_llm=query_llm)
    assert agg["questions"] == 2 and agg["answered"]["mean"] == 1  # "Qwxyz" retrieves nothing
    assert agg["cited_rate"]["mean"] == 1  # of the answers it could give
    assert agg["retried"]["mean"] == 0
    summary = (result.out_dir / "summary.md").read_text(encoding="utf-8")
    assert "questions answered (of 2)" in summary
    assert "questions answered" in bench.compare([result.out_dir])


def test_unbacked_expansions_counts_line_by_line(tmp_path: Path, git_identity) -> None:  # noqa: F811
    vault = init_vault(tmp_path / "v", language="en")
    meta = {"title": "ROCC", "type": "entity", "aliases": ["Rover Ops Centre"], "status": "active"}
    body = "\n# ROCC\n\nThe Rover Ops Centre (ROCC) plans.\n\nThe DAR (Data Archive Room) stores.\n"
    vault.write_page(Page("entities/rocc.md", fm.new_document(meta, body)))
    assert bench.unbacked_expansions(vault, "The DAR stores.") == 1  # the DAR, not the heading
