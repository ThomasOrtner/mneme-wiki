"""BM25 search over pages (TD-7), built in memory on every call.

At MVP scale (L-5: ~500 pages) building the index takes milliseconds, so there
is no cache to keep in sync. Each field (title + aliases, lead
paragraph, whole body) gets its own BM25 index and the scores are summed with
weights 3 / 2 / 1, so a title match carries the title field's IDF instead of
being drowned by term-frequency saturation in the body. IDF is the always-
positive Lucene variant: rank_bm25's Okapi IDF floors every term that occurs in
more than half the pages, which in a small vault is most of them.
Tokens are casefolded Unicode words without stemming, because the vault mixes
languages (TD-17).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from rank_bm25 import BM25Okapi

from . import text
from .vault import Page, Vault

FIELD_WEIGHTS = {"names": 3.0, "lead": 2.0, "body": 1.0}
SEARCH_TYPES = ("source", "entity", "concept", "synthesis")


@dataclass(frozen=True)
class Hit:
    path: str
    title: str
    type: str
    score: float
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Doc:
    path: str
    title: str
    type: str
    aliases: tuple[str, ...]
    lead: str
    body: str

    @classmethod
    def from_page(cls, page: Page) -> Doc:
        aliases = page.meta.get("aliases")
        lead_block = text.lead(page.body)
        return cls(
            path=page.path,
            title=page.title,
            type=str(page.meta.get("type") or ""),
            aliases=tuple(a for a in aliases if isinstance(a, str))
            if isinstance(aliases, list)
            else (),
            lead=text.plain(lead_block.text) if lead_block else "",
            body=text.plain(page.body),
        )

    def fields(self) -> dict[str, list[str]]:
        return {
            "names": text.tokens(" ".join((self.title, *self.aliases))),
            "lead": text.tokens(self.lead),
            "body": text.tokens(self.body),
        }


class _BM25(BM25Okapi):
    def _calc_idf(self, nd: dict[str, int]) -> None:  # Lucene IDF, never negative
        for word, freq in nd.items():
            self.idf[word] = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1)


class SearchIndex:
    def __init__(self, docs: Iterable[Doc]) -> None:
        self.docs = list(docs)
        fields = [d.fields() for d in self.docs]
        # One index per field; a field that is empty everywhere (or an empty vault)
        # gets none, because BM25 divides by the average document length.
        self._bm25 = {}
        for name in FIELD_WEIGHTS:
            corpus = [f[name] for f in fields]
            if any(corpus):
                self._bm25[name] = _BM25(corpus)

    @classmethod
    def from_vault(cls, vault: Vault, types: Iterable[str] = SEARCH_TYPES) -> SearchIndex:
        wanted = set(types)
        return cls(
            Doc.from_page(p)
            for _, p in vault.iter_pages()
            if isinstance(p, Page) and p.meta.get("type") in wanted
        )

    def search(
        self, query: str, *, limit: int = 10, types: Iterable[str] | None = None,
        exclude: Iterable[str] = (),
    ) -> list[Hit]:  # fmt: skip
        terms = text.tokens(query)
        if not terms or not self._bm25:
            return []
        wanted = set(types) if types is not None else None
        skip = set(exclude)
        scores = [0.0] * len(self.docs)
        for name, bm25 in self._bm25.items():
            for i, score in enumerate(bm25.get_scores(terms)):
                scores[i] += FIELD_WEIGHTS[name] * float(score)
        hits = [
            Hit(d.path, d.title, d.type, round(float(s), 4), text.first_sentence(d.lead, 120))
            for d, s in zip(self.docs, scores, strict=True)
            if s > 0 and d.path not in skip and (wanted is None or d.type in wanted)
        ]
        hits.sort(key=lambda h: (-h.score, h.path))
        return hits[:limit]


def search(
    vault: Vault, query: str, *, limit: int = 10, types: Iterable[str] | None = None
) -> list[Hit]:
    return SearchIndex.from_vault(vault).search(query, limit=limit, types=types)
