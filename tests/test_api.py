from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.ingestion import Document, load_documents
from backend.search import SearchEngine, highlight_ranges, tokenize
from main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("SEARCH_DATA_PATH", raising=False)
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "documents": 10}


def test_search_ranks_and_limits_matches(client):
    response = client.get("/api/search", params={"q": "garden", "limit": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "garden"
    assert data["tokens"] == ["garden"]
    assert data["total"] == 1
    assert data["returned"] == 1
    assert data["results"][0]["id"] == "doc-009"
    assert data["took_ms"] >= 0


def test_no_match_returns_empty_success(client):
    response = client.get("/api/search", params={"q": "zzzznomatch"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["returned"] == 0
    assert data["results"] == []


@pytest.mark.parametrize("query", ["   ", "!!!", "___"])
def test_nonsearchable_query(client, query):
    response = client.get("/api/search", params={"q": query})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_query"


@pytest.mark.parametrize("parameters", [
    {}, {"q": ""}, {"q": "x" * 201}, {"q": "search", "limit": 0},
    {"q": "search", "limit": 51}, {"q": "search", "limit": "invalid"},
])
def test_parameter_validation(client, parameters):
    response = client.get("/api/search", params=parameters)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unicode_tokenization_and_offsets():
    assert tokenize("Café HOME-repair don’t 2026") == [
        "café", "home", "repair", "don't", "2026"
    ]
    text = "🔎 Café"
    ranges = highlight_ranges(text, {"café"})
    assert [(item.start, item.end) for item in ranges] == [(2, 6)]
    assert text[ranges[0].start:ranges[0].end] == "Café"


def test_returned_highlights_match_query_tokens(client):
    data = client.get("/api/search", params={"q": "local search"}).json()
    tokens = set(data["tokens"])
    for result in data["results"]:
        for field, highlights in [("title", "title_highlights"),
                                  ("snippet", "snippet_highlights")]:
            text = result[field]
            previous_end = 0
            for highlight in result[highlights]:
                start, end = highlight["start"], highlight["end"]
                assert previous_end <= start < end <= len(text)
                assert tokenize(text[start:end])[0] in tokens
                previous_end = end


def test_zero_score_matches_are_not_discarded():
    documents = (
        Document(id="a", title="Alpha", url="https://example.com/a", content="Common"),
        Document(id="b", title="Beta", url="https://example.com/b", content="Other"),
    )
    response = SearchEngine(documents).search("alpha")
    assert response.total == 1
    assert response.results[0].id == "a"


def test_duplicate_ids_are_rejected(tmp_path):
    record = {"id": "same", "title": "Title", "url": "https://example.com", "content": "Content"}
    dataset = tmp_path / "documents.json"
    dataset.write_text(json.dumps([record, record]), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate document ID"):
        load_documents(dataset)


def test_unsafe_document_url_is_rejected(tmp_path):
    dataset = tmp_path / "documents.json"
    dataset.write_text(json.dumps([{
        "id": "unsafe", "title": "Unsafe", "url": "javascript:alert(1)", "content": "Example"
    }]), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid document"):
        load_documents(dataset)
