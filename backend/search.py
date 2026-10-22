from __future__ import annotations

import re
from time import perf_counter

from pydantic import BaseModel
from rank_bm25 import BM25Okapi

from backend.ingestion import Document

TOKEN_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
SNIPPET_LENGTH = 240


def normalize_token(token: str) -> str:
    return token.replace("’", "'").casefold()


def tokenize(text: str) -> list[str]:
    return [normalize_token(match.group()) for match in TOKEN_PATTERN.finditer(text)]


class Highlight(BaseModel):
    start: int
    end: int


class SearchResult(BaseModel):
    id: str
    title: str
    url: str
    snippet: str
    score: float
    title_highlights: list[Highlight]
    snippet_highlights: list[Highlight]


class SearchResponse(BaseModel):
    query: str
    tokens: list[str]
    total: int
    returned: int
    took_ms: float
    results: list[SearchResult]


def highlight_ranges(text: str, tokens: set[str]) -> list[Highlight]:
    return [
        Highlight(start=match.start(), end=match.end())
        for match in TOKEN_PATTERN.finditer(text)
        if normalize_token(match.group()) in tokens
    ]


def make_snippet(content: str, tokens: set[str]) -> str:
    text = " ".join(content.split())
    if len(text) <= SNIPPET_LENGTH:
        return text
    first_match = next(
        (match for match in TOKEN_PATTERN.finditer(text)
         if normalize_token(match.group()) in tokens), None
    )
    start = max(0, first_match.start() - 65) if first_match else 0
    start = min(start, len(text) - SNIPPET_LENGTH)
    if start > 0 and not text[start - 1].isspace():
        boundary = text.find(" ", start, min(len(text), start + 40))
        if boundary != -1:
            start = boundary + 1
    end = min(len(text), start + SNIPPET_LENGTH)
    if end < len(text) and not text[end].isspace():
        boundary = text.rfind(" ", start, end)
        if boundary > start + SNIPPET_LENGTH // 2:
            end = boundary
    excerpt = text[start:end].strip()
    return ("…" if start else "") + excerpt + ("…" if end < len(text) else "")


class SearchEngine:
    def __init__(self, documents: tuple[Document, ...]):
        if not documents:
            raise ValueError("Cannot index an empty collection")
        self._documents = documents
        corpus = [tokenize(f"{doc.title} {doc.content}") for doc in documents]
        if not any(corpus):
            raise ValueError("Dataset contains no searchable tokens")
        self._token_sets = tuple(frozenset(tokens) for tokens in corpus)
        self._bm25 = BM25Okapi(corpus)

    @property
    def document_count(self) -> int:
        return len(self._documents)

    def search(self, query: str, limit: int = 10) -> SearchResponse:
        started = perf_counter()
        normalized_query = " ".join(query.split())
        query_tokens = list(dict.fromkeys(tokenize(normalized_query)))
        if not query_tokens:
            raise ValueError("Query contains no searchable tokens")
        token_set = set(query_tokens)
        candidates = [
            index for index, document_tokens in enumerate(self._token_sets)
            if document_tokens.intersection(token_set)
        ]
        results: list[SearchResult] = []
        if candidates:
            scores = self._bm25.get_scores(query_tokens)
            candidates.sort(key=lambda index: (
                -float(scores[index]), self._documents[index].id
            ))
            for index in candidates[:limit]:
                document = self._documents[index]
                snippet = make_snippet(document.content, token_set)
                results.append(SearchResult(
                    id=document.id,
                    title=document.title,
                    url=document.url,
                    snippet=snippet,
                    score=round(float(scores[index]), 6),
                    title_highlights=highlight_ranges(document.title, token_set),
                    snippet_highlights=highlight_ranges(snippet, token_set),
                ))
        return SearchResponse(
            query=normalized_query,
            tokens=query_tokens,
            total=len(candidates),
            returned=len(results),
            took_ms=round((perf_counter() - started) * 1000, 2),
            results=results,
        )
