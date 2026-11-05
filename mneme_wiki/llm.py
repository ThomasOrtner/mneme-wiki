"""Thin LLM layer: model per stage role (TD-14), schema-constrained JSON, call records.

Stage code asks `llm.for_role("extract")` for a client and calls `.json(...)`. It
never names a model. Every call is recorded (`Call`) for progress lines, the run
report and the bench; the `on_call` hook lets the orchestrator stream them to a
`calls.jsonl` file as they happen.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

from . import backends, config

TEMPERATURE = 0.2
Log = Callable[[str], None]


@dataclass
class Call:
    role: str
    model: str
    step: str
    attempt: int
    ok: bool
    latency_s: float
    tokens_in: int
    tokens_out: int
    thinking_chars: int
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_ref(ref: str) -> tuple[str, str]:
    """`ollama:qwen3:14b` → (`ollama`, `qwen3:14b`)."""
    backend, sep, model = ref.partition(":")
    if not sep or not backend or not model:
        raise ValueError(f"model ref must be backend:model, got {ref!r}")
    return backend, model


class LLM:
    """Holds the role → model mapping, the backends, and the record of every call."""

    def __init__(
        self,
        models: Mapping[str, str | None] | None = None,
        *,
        backends_by_name: Mapping[str, backends.Backend] | None = None,
        thinking: Mapping[str, bool] | None = None,
        log: Log = lambda _msg: None,
        on_call: Callable[[Call], None] | None = None,
    ) -> None:
        self.models = dict(config.MODELS if models is None else models)
        self.thinking = dict(config.THINKING if thinking is None else thinking)
        self._backends = dict(backends_by_name or {})
        self.log = log
        self.on_call = on_call
        self.calls: list[Call] = []

    def for_role(self, role: str) -> RoleClient:
        ref = self.models.get(role)
        if not ref:
            raise ValueError(f"no model configured for role {role!r}")
        backend_name, model = parse_ref(ref)
        if backend_name not in self._backends:
            self._backends[backend_name] = backends.create(backend_name)
        return RoleClient(self, role, ref, self._backends[backend_name], model)

    def record(self, call: Call) -> None:
        self.calls.append(call)
        if self.on_call:
            self.on_call(call)


class RoleClient:
    def __init__(
        self, llm: LLM, role: str, ref: str, backend: backends.Backend, model: str
    ) -> None:
        self.llm, self.role, self.ref, self.backend, self.model = llm, role, ref, backend, model

    @property
    def thinking(self) -> bool:
        return bool(self.llm.thinking.get(self.role, False))

    def json(
        self,
        system: str,
        user: str,
        schema: dict,
        *,
        step: str = "",
        thinking: bool | None = None,
        retries: int = 1,
    ) -> dict | None:
        """One schema-constrained call, retried on invalid JSON or a backend error.
        Returns the parsed object, or None if every attempt failed."""
        think = self.thinking if thinking is None else thinking
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in range(1, retries + 2):
            data, error, result = None, None, backends.Result(text="")
            try:
                result = self.backend.complete(
                    self.model, messages, schema=schema, thinking=think, temperature=TEMPERATURE
                )
                data = json.loads(result.text)
                if not isinstance(data, dict):
                    data, error = None, f"expected a JSON object, got {type(data).__name__}"
            except backends.BackendError as exc:
                error = str(exc)
            except json.JSONDecodeError as exc:
                error = f"invalid JSON: {exc}"
            call = Call(
                role=self.role,
                model=self.ref,
                step=step,
                attempt=attempt,
                ok=data is not None,
                latency_s=round(result.latency_s, 2),
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                thinking_chars=len(result.thinking),
                error=error,
            )
            self.llm.record(call)
            status = "ok   " if call.ok else ("retry" if attempt <= retries else "FAIL ")
            self.llm.log(
                f"  {step[:60]:<60} {status} {call.latency_s:5.1f}s "
                f"{call.tokens_in:>5}→{call.tokens_out:<5} tok"
                + (f"  ({error[:80]})" if error else "")
            )
            if data is not None:
                return data
        return None
