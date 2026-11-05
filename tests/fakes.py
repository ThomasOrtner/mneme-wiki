"""A scripted model backend for tests: no server, deterministic answers.

`ScriptedBackend(handler)` calls `handler(role, system, user, schema, thinking)` and
sends back whatever it returns (a dict is JSON-encoded, a str is sent as is, so
tests can also feed broken JSON). `fake_llm()` wires it into a real `LLM`, so the
retry, logging and call records are the production code paths.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from mneme_wiki.backends import BackendError, Result
from mneme_wiki.llm import LLM

ROLES = ("extract", "resolve", "patch", "summary", "query")


class ScriptedBackend:
    def __init__(self, handler: Callable[..., object]) -> None:
        self.handler = handler
        self.requests: list[dict] = []

    def complete(self, model, messages, *, schema=None, thinking=False, temperature=0.2):
        role = model  # fake_llm() uses the role name as the model name
        system, user = messages[0]["content"], messages[1]["content"]
        self.requests.append({"role": role, "user": user, "thinking": thinking})
        answer = self.handler(role, system, user, schema, thinking)
        if isinstance(answer, BackendError):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return Result(
            text=text, tokens_in=len(user) // 4, tokens_out=len(text) // 4, latency_s=0.01
        )


def fake_llm(handler: Callable[..., object], **kwargs) -> tuple[LLM, ScriptedBackend]:
    backend = ScriptedBackend(handler)
    llm = LLM(
        {role: f"fake:{role}" for role in ROLES},
        backends_by_name={"fake": backend},
        thinking={"resolve": True},
        **kwargs,
    )
    return llm, backend


# ---------------------------------------------------------------------------
# A small "model" that is good enough to drive the whole pipeline
# ---------------------------------------------------------------------------
CLAIM_LINE = re.compile(r"^- (.+?)  \(section: (.+)\)$", re.MULTILINE)
SOURCE_ID = re.compile(r"^Source id: (\S+)", re.MULTILINE)


class Toy:
    """Answers every role by simple rules over the prompt.

    - extract: every `**Name** (Alias)` in the chunk is a subject; the sentence it is
      in is its claim; `kinds` decides entity vs concept.
    - resolve: "same" iff the pair is listed in `same`.
    - patch: appends each new claim as a bullet to section "Overview" (citing the
      source), unless `patch_answer` overrides the answer.
    - summary: a fixed summary.
    """

    SUBJECT = re.compile(r"\*\*([^*]+)\*\*(?: \(([^)]+)\))?")

    def __init__(self, *, kinds=None, same=(), patch_answer=None) -> None:
        self.kinds = kinds or {}
        self.same = {frozenset(p) for p in same}
        self.patch_answer = patch_answer
        self.patch_calls = 0

    def __call__(self, role, system, user, schema, thinking):
        return getattr(self, role)(user)

    def extract(self, user: str) -> dict:
        chunk = user.split("--- CHUNK ---", 1)[1].split("--- END ---", 1)[0]
        chunk = re.sub(r"```.*?```", "", chunk, flags=re.DOTALL)  # the toy ignores code
        subjects = {}
        for sentence in re.split(r"(?<=[.!?])\s+", chunk):
            for m in self.SUBJECT.finditer(sentence):
                name, alias = m.group(1).strip(), m.group(2)
                plain = self.SUBJECT.sub(lambda x: x.group(1), sentence).strip()
                kind = self.kinds.get(name, "concept")
                s = subjects.setdefault(name, {
                    "name": name, "kind": kind,
                    "entity_kind": "organisation" if kind == "entity" else "other",
                    "aliases": [alias] if alias else [],
                    "description": f"{name} as described in the source.",
                    "claims": [],
                })  # fmt: skip
                if plain not in s["claims"]:
                    s["claims"].append(plain)
        return {"subjects": list(subjects.values())}

    def resolve(self, user: str) -> dict:
        a = re.search(r"^A: (.+?) \(aliases", user, re.MULTILINE).group(1)
        b = re.search(r"^B: (.+?) \(aliases", user, re.MULTILINE).group(1)
        same = frozenset((a, b)) in self.same
        return {"reason": "listed as same" if same else "not listed", "same": same}

    def patch(self, user: str) -> dict:
        self.patch_calls += 1
        if self.patch_answer is not None:
            answer = self.patch_answer(user, self.patch_calls)
            if answer is not None:
                return answer
        source = SOURCE_ID.search(user).group(1)
        claims = [m.group(1) for m in CLAIM_LINE.finditer(user)]
        text = "\n".join(f"- {c} ([[{source}]])" for c in claims)
        return {"lead": "", "ops": [{"section": "Overview", "op": "append", "text": text}]}

    def summary(self, user: str) -> dict:
        return {"summary": "A short test document about rover operations.", "key_points": ["One."]}
