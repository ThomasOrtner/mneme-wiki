"""OllamaBackend without a server: a stub client records what is sent."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mneme_wiki.backends import BackendError, OllamaBackend


class StubClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response, self.error, self.kwargs = response, error, None

    def chat(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def response(done_reason: str = "stop", content: str = '{"x": 1}'):
    return SimpleNamespace(
        message=SimpleNamespace(content=content, thinking="hmm"),
        prompt_eval_count=12,
        eval_count=34,
        done_reason=done_reason,
    )


def backend(stub: StubClient) -> OllamaBackend:
    b = OllamaBackend(max_output_tokens=777, timeout_s=5)
    b._client = stub
    return b


def test_every_call_is_bounded() -> None:
    """Regression (M4): an uncapped qwen3:8b call looped for 9 h / 327k tokens."""
    stub = StubClient(response())
    result = backend(stub).complete(
        "m", [{"role": "user", "content": "u"}], schema={}, thinking=True
    )
    assert stub.kwargs["options"]["num_predict"] == 777
    assert stub.kwargs["think"] is True and stub.kwargs["format"] == {}
    assert (result.text, result.tokens_in, result.tokens_out, result.thinking) == (
        '{"x": 1}',
        12,
        34,
        "hmm",
    )


def test_cut_off_answer_is_an_error() -> None:
    stub = StubClient(response(done_reason="length", content='{"x": "aaaa'))
    with pytest.raises(BackendError, match="cut off at 777 tokens"):
        backend(stub).complete("m", [{"role": "user", "content": "u"}])


def test_client_errors_become_backend_errors() -> None:
    stub = StubClient(error=TimeoutError("read timed out"))
    with pytest.raises(BackendError, match="read timed out"):
        backend(stub).complete("m", [{"role": "user", "content": "u"}])


def test_client_gets_the_timeout(monkeypatch) -> None:
    seen = {}

    class FakeOllamaClient:
        def __init__(self, host=None, **kwargs):
            seen.update(host=host, **kwargs)

    import ollama

    monkeypatch.setattr(ollama, "Client", FakeOllamaClient)
    OllamaBackend(host="http://h:1", timeout_s=42)
    assert seen == {"host": "http://h:1", "timeout": 42}
