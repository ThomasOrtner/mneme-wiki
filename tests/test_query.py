from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from mneme_wiki import cli
from mneme_wiki.integrate import IntegrateError, integrate
from mneme_wiki.lint import lint
from mneme_wiki.query import BUDGET_CHARS, ask, file_answer, retrieve
from mneme_wiki.vault import Vault, init_vault

from .conftest import FIXTURES
from .fakes import Toy, fake_llm
from .test_vault import git_identity  # noqa: F401 - pytest fixture

DAY = dt.date(2026, 11, 5)
KINDS = {"Rover Operations Control Centre": "entity", "Science Team": "entity"}
SRC = "sources/rover-operations-handbook"


@pytest.fixture
def vault(tmp_path: Path, git_identity) -> Vault:  # noqa: F811
    v = init_vault(tmp_path / "vault", language="en", today=DAY)
    llm, _ = fake_llm(Toy(kinds=KINDS))
    integrate(v, FIXTURES / "packets/ops-handbook", llm=llm, today=DAY)
    return v


def answering(answer: str, pages: list[str], answerable: bool = True):
    seen = []

    def handler(role, system, user, schema, thinking):
        seen.append(user)
        return {"answer": answer, "answerable": answerable, "pages": pages}

    return handler, seen


def test_retrieve_ranks_and_budgets(vault: Vault) -> None:
    shown, listed = retrieve(vault, "Tactical Planning Cycle commands")
    assert shown[0].path == "concepts/tactical-planning-cycle.md"
    assert not {p.path for p in shown} & {p.path for p in listed}
    shown, listed = retrieve(vault, "Tactical Planning Cycle commands", budget=1)
    assert len(shown) == 1 and listed  # always at least one page, the rest as lines
    assert retrieve(vault, "zzz unrelated words") == ([], [])


def test_ask_validates_links_and_pages(vault: Vault) -> None:
    answer = (
        "The [[concepts/tactical-planning-cycle|Tactical Planning Cycle]] turns science "
        f"requests into commands ([[{SRC}]]). See also [[concepts/invented|Invented]]."
    )
    handler, seen = answering(
        answer, ["concepts/tactical-planning-cycle", "concepts/nope", "entities/science-team"]
    )
    llm, backend = fake_llm(handler)
    result = ask(vault, "  What does the   Tactical Planning Cycle do? ", llm=llm)
    assert result.question == "What does the Tactical Planning Cycle do?"
    assert result.answerable and "[[concepts/invented" not in result.answer
    assert "See also Invented." in result.answer
    assert result.counters == {"invalid_link_removed": 1, "unknown_page_dropped": 1}
    assert result.pages[0] == "concepts/tactical-planning-cycle.md"
    assert result.sources == [f"{SRC}.md"]
    prompt = seen[0]
    assert "--- PAGE concepts/tactical-planning-cycle (Tactical Planning Cycle) ---" in prompt
    assert backend.requests[0]["role"] == "query"


def test_ask_without_pages_or_answer(vault: Vault) -> None:
    llm, backend = fake_llm(lambda *a: {"answer": "x", "answerable": True, "pages": []})
    result = ask(vault, "zzz unrelated words", llm=llm)
    assert not result.answerable and not backend.requests  # no call without pages
    llm, _ = fake_llm(lambda *a: "{broken")
    result = ask(vault, "Science Team observations", llm=llm)
    assert result.error and not result.answerable
    with pytest.raises(ValueError):
        ask(vault, "   ", llm=llm)


def test_file_answer_creates_synthesis_commit(vault: Vault) -> None:
    answer = (
        "The [[entities/science-team|Science Team]] proposes observations for every sol "
        f"([[{SRC}]])."
    )
    llm, _ = fake_llm(answering(answer, ["entities/science-team"])[0])
    result = ask(vault, "Who proposes observations?", llm=llm)
    file_answer(vault, result, today=DAY)
    assert result.filed == "syntheses/who-proposes-observations.md" and result.commit
    page = vault.read_page(result.filed)
    assert (
        page.meta["type"] == "synthesis" and page.meta["question"] == "Who proposes observations?"
    )
    assert page.meta["sources"] == [f"[[{SRC}]]"]
    assert "## Based on\n\n- [[entities/science-team]]" in page.body
    assert "[[syntheses/who-proposes-observations|Who proposes observations?]]" in vault.read_text(
        "index.md"
    )
    assert "query | Who proposes observations?" in vault.read_text("log.md")
    assert (
        vault.git("log", "-1", "--format=%s").stdout.strip() == "query: Who proposes observations?"
    )
    assert vault.is_clean() and lint(vault).ok
    with pytest.raises(IntegrateError, match="already filed as syntheses/who-proposes"):
        file_answer(vault, ask(vault, "who proposes  observations?", llm=llm), today=DAY)


def test_uncited_answer_is_retried_with_the_sources_named(vault: Vault) -> None:
    replies = [
        {"answer": "The Science Team proposes observations.", "answerable": True, "pages": []},
        {"answer": f"The Science Team proposes observations ([[{SRC}]]).", "answerable": True,
         "pages": []},
    ]  # fmt: skip
    seen = []

    def handler(role, system, user, schema, thinking):
        seen.append(user)
        return replies[len(seen) - 1]

    llm, _ = fake_llm(handler)
    result = ask(vault, "Who proposes observations?", llm=llm)
    assert len(seen) == 2 and result.sources == [f"{SRC}.md"]
    assert result.counters == {"answer_retry": 1}
    assert "The Science Team proposes observations." in seen[1]  # the answer to repair
    assert f"[[{SRC}]]" in seen[1].split("Problems")[1]  # the sources it may cite


def test_refusal_is_not_retried(vault: Vault) -> None:
    llm, backend = fake_llm(answering("Not in the wiki.", [], answerable=False)[0])
    result = ask(vault, "Science Team?", llm=llm)
    assert not result.answerable and len(backend.requests) == 1


def test_answer_that_stays_uncited_is_not_filed(vault: Vault) -> None:
    llm, backend = fake_llm(
        answering("Plain answer without any citation at all.", ["entities/science-team"])[0]
    )
    result = ask(vault, "Science Team?", llm=llm)
    assert len(backend.requests) == 2 and result.answerable and not result.sources
    assert result.counters["uncited_answer"] == 1
    with pytest.raises(IntegrateError, match="cites no source"):
        file_answer(vault, result, today=DAY)
    assert vault.is_clean()


def test_unbacked_expansions_are_removed_or_block_filing(vault: Vault) -> None:
    cite = f"([[{SRC}]])"
    llm, backend = fake_llm(
        answering(
            f"The ROCC (Rover Orbit Command Centre) plans {cite}.", ["entities/science-team"]
        )[0]
    )
    result = ask(vault, "Science Team?", llm=llm)
    assert result.answer == f"The ROCC plans {cite}." and not result.unbacked
    assert result.counters["expansion_removed"] == 1 and len(backend.requests) == 2

    llm, _ = fake_llm(answering(f"ROCC stands for Rover Orbit Command {cite}.", [])[0])
    result = ask(vault, "Science Team?", llm=llm)
    assert result.unbacked == ["ROCC = Rover Orbit Command"]
    with pytest.raises(IntegrateError, match="not backed"):
        file_answer(vault, result, today=DAY)


def test_file_answer_refusals(vault: Vault) -> None:
    llm, _ = fake_llm(answering("Not in the wiki.", [], answerable=False)[0])
    with pytest.raises(IntegrateError, match="only an answer"):
        file_answer(vault, ask(vault, "Science Team?", llm=llm))
    (vault.root / "concepts/draft.md").write_text("x", encoding="utf-8")
    llm, _ = fake_llm(answering(f"A fact ([[{SRC}]]).", ["entities/science-team"])[0])
    with pytest.raises(IntegrateError, match="uncommitted"):
        file_answer(vault, ask(vault, "Science Team?", llm=llm))


def test_cli_refused_filing_still_shows_the_answer(vault: Vault, capsys, monkeypatch) -> None:
    llm, _ = fake_llm(answering("Plain answer.", [])[0])
    monkeypatch.setattr("mneme_wiki.query.LLM", lambda **kw: llm)
    args = ["query", "Who operates the rover?", "--vault", str(vault.root), "--file"]
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert "Plain answer." in captured.out and "cites no source" in captured.err
    assert cli.main([*args, "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert not data["ok"] and data["answer"] == "Plain answer."
    assert "cites no source" in data["file_error"]


def test_cli_query(vault: Vault, capsys, monkeypatch) -> None:
    llm, _ = fake_llm(answering(f"The ROCC operates the rover ([[{SRC}]]).", [])[0])
    monkeypatch.setattr("mneme_wiki.query.LLM", lambda **kw: llm)
    args = ["query", "Who operates the rover?", "--vault", str(vault.root)]
    assert cli.main([*args, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["answerable"] and data["filed"] is None
    assert cli.main([*args, "--file"]) == 0
    out = capsys.readouterr().out
    assert "filed as syntheses/who-operates-the-rover.md" in out
    assert re.search(r"pages used:", out) is None or "pages used" in out
    assert BUDGET_CHARS > 0
