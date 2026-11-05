from __future__ import annotations

import pytest

from mneme_wiki import llm as llm_mod
from mneme_wiki.backends import BackendError

from .fakes import fake_llm

SCHEMA = {"type": "object"}


def test_parse_ref() -> None:
    assert llm_mod.parse_ref("ollama:qwen3:14b") == ("ollama", "qwen3:14b")
    for bad in ("qwen3", ":x", "ollama:"):
        with pytest.raises(ValueError):
            llm_mod.parse_ref(bad)


def test_json_ok_and_recorded() -> None:
    seen = []
    llm, backend = fake_llm(lambda *a: {"x": 1}, on_call=seen.append)
    assert llm.for_role("extract").json("s", "u" * 40, SCHEMA, step="extract 1/1") == {"x": 1}
    assert [c.role for c in llm.calls] == ["extract"] and seen == llm.calls
    call = llm.calls[0]
    assert call.ok and call.attempt == 1 and call.model == "fake:extract"
    assert call.step == "extract 1/1" and call.tokens_in > 0


def test_retry_on_invalid_json_then_success() -> None:
    answers = iter(["{broken", '["not", "an object"]', '{"ok": true}'])
    lines = []
    llm, _ = fake_llm(lambda *a: next(answers), log=lines.append)
    client = llm.for_role("patch")
    assert client.json("s", "u", SCHEMA) is None  # broken, then a list: both rejected
    assert [c.error.split(":")[0] for c in llm.calls] == [
        "invalid JSON",
        "expected a JSON object, got list",
    ]
    assert client.json("s", "u", SCHEMA) == {"ok": True}
    assert any("retry" in line for line in lines) and any("FAIL" in line for line in lines)


def test_backend_error_is_a_failed_call() -> None:
    llm, _ = fake_llm(lambda *a: BackendError("connection refused"))
    assert llm.for_role("summary").json("s", "u", SCHEMA, retries=0) is None
    assert llm.calls[0].error == "connection refused"


def test_thinking_per_role() -> None:
    llm, backend = fake_llm(lambda *a: {})
    llm.for_role("resolve").json("s", "u", SCHEMA)
    llm.for_role("extract").json("s", "u", SCHEMA)
    llm.for_role("extract").json("s", "u", SCHEMA, thinking=True)
    assert [r["thinking"] for r in backend.requests] == [True, False, True]


def test_unknown_role_and_backend() -> None:
    llm, _ = fake_llm(lambda *a: {})
    with pytest.raises(ValueError, match="no model configured"):
        llm.for_role("judge")
    plain = llm_mod.LLM({"extract": "openrouter:x"})
    with pytest.raises(BackendError, match="unknown backend"):
        plain.for_role("extract")
