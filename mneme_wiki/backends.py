"""Model backends behind one small protocol (TD-2).

A backend turns chat messages (+ an optional JSON schema) into text. Ollama is the
only real backend in the MVP (L-1); OpenRouter can be added later behind the same
`complete()` without touching stage code. Tests register a scripted backend.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import config


@dataclass
class Result:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0
    thinking: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class BackendError(RuntimeError):
    """The backend could not produce an answer (connection, model missing, ...)."""


class Backend(Protocol):
    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        schema: dict | None = None,
        thinking: bool = False,
        temperature: float = 0.2,
    ) -> Result: ...


class OllamaBackend:
    """Local inference through the `ollama` package; `format=<schema>` constrains output."""

    def __init__(
        self,
        host: str = config.OLLAMA_BASE_URL,
        num_ctx: int = config.NUM_CTX,
        max_output_tokens: int = config.MAX_OUTPUT_TOKENS,
        timeout_s: float = config.CALL_TIMEOUT_S,
    ) -> None:
        import ollama  # imported lazily so tests never need a server

        self._client = ollama.Client(host=host, timeout=timeout_s)
        self.num_ctx = num_ctx
        self.max_output_tokens = max_output_tokens

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        schema: dict | None = None,
        thinking: bool = False,
        temperature: float = 0.2,
    ) -> Result:
        t0 = time.monotonic()
        try:
            response = self._client.chat(
                model=model,
                messages=messages,
                format=schema,
                think=thinking,
                options={
                    "num_ctx": self.num_ctx,
                    "num_predict": self.max_output_tokens,
                    "temperature": temperature,
                },
            )
        except Exception as exc:  # connection refused, model not pulled, timeout, server error
            raise BackendError(f"ollama {model}: {exc}") from exc
        if getattr(response, "done_reason", None) == "length":
            raise BackendError(
                f"ollama {model}: answer cut off at {self.max_output_tokens} tokens "
                "(MAX_OUTPUT_TOKENS); the model probably looped"
            )
        message = response.message
        return Result(
            text=message.content or "",
            tokens_in=response.prompt_eval_count or 0,
            tokens_out=response.eval_count or 0,
            latency_s=time.monotonic() - t0,
            thinking=getattr(message, "thinking", None) or "",
        )


def create(name: str) -> Backend:
    if name == "ollama":
        return OllamaBackend()
    raise BackendError(f"unknown backend {name!r} (only 'ollama' is available)")
