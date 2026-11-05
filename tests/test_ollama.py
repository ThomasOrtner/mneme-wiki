"""Real-model tests (opt-in): `pytest -m ollama`. Need Ollama with the configured models.

- the resolve regression set (M0's pairs, extended) must keep its precision/recall;
- the small fixture packet integrates end to end with a clean lint.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from mneme_wiki.integrate import integrate
from mneme_wiki.lint import lint
from mneme_wiki.llm import LLM
from mneme_wiki.stages import resolve
from mneme_wiki.stages.common import Claim, Subject
from mneme_wiki.vault import init_vault

from .conftest import FIXTURES
from .test_vault import git_identity  # noqa: F401 - pytest fixture

pytestmark = pytest.mark.ollama

PAIRS = json.loads((Path(__file__).parent / "data/resolve_pairs.json").read_text("utf-8"))["pairs"]
MIN_PRECISION = 0.95  # a false merge is the expensive error (M0: P = 1.0 with thinking)
MIN_RECALL = 0.75  # M0: R = 0.9 on the first 22 pairs


def test_resolve_regression() -> None:
    client = LLM().for_role("resolve")
    tp = fp = fn = 0
    wrong = []
    for a, a_desc, b, b_aliases, b_desc, same in PAIRS:
        subject = Subject(a, "concept", "other", [], a_desc, [Claim("x", "y")])
        cand = resolve.Candidate("x", b, b_aliases, b_desc, "concept")
        data = client.json(resolve.SYSTEM, resolve.pair_prompt(subject, cand), resolve.SCHEMA)
        said = bool((data or {}).get("same"))
        tp += said and same
        fp += said and not same
        fn += (not said) and same
        if said != same:
            wrong.append(f"{a} vs {b}: said {'same' if said else 'different'}")
    precision, recall = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    print(f"\nresolve: P={precision:.2f} R={recall:.2f} wrong={wrong}")
    assert precision >= MIN_PRECISION, wrong
    assert recall >= MIN_RECALL, wrong


def test_integrate_fixture_packet(tmp_path: Path, git_identity) -> None:  # noqa: F811
    vault = init_vault(tmp_path / "vault", language="en")
    report = integrate(vault, FIXTURES / "packets/ops-handbook", today=dt.date.today())
    assert report.ok and report.commit and report.created
    assert lint(vault).ok
