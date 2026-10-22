# DIYSearch

A local document search engine built with Python, FastAPI, rank_bm25,
HTML5, Tailwind CSS, and vanilla JavaScript.

**BM25 is lexical relevance ranking, not semantic embedding search.** It
matches tokens; synonyms do not match unless present in the documents.

## Setup

Requires Python 3.11 or newer. Run from this directory.

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. API documentation: http://127.0.0.1:8000/docs.

Python packages need internet access during installation. The browser loads
a pinned, precompiled Tailwind CSS stylesheet from jsDelivr. Searches and
documents stay on the local backend; they are not transmitted to the CDN.
For offline use, download the linked stylesheet to frontend/tailwind.min.css
and change its HTML href to /static/tailwind.min.css.

## Project structure

```text
DIYSearch/
├── README.md
├── requirements.txt
├── .gitignore
├── main.py
├── backend/
│   ├── __init__.py
│   ├── ingestion.py
│   └── search.py
├── data/
│   └── documents.json
├── frontend/
│   ├── index.html
│   └── app.js
└── tests/
    └── test_api.py
```

## Dataset ingestion

The ten mock documents in data/documents.json are validated and indexed at
startup. Example.com document URLs are illustrative, not hosted articles.
Replace this file with a nonempty JSON array of records containing exactly:

| Field | Type | Constraint |
| --- | --- | --- |
| id | string | Unique, nonblank, at most 128 characters |
| title | string | Nonblank, at most 300 characters |
| url | string | Absolute HTTP(S), no credentials, at most 2048 characters |
| content | string | Nonblank, at most 100000 characters |

Invalid records, duplicate IDs, unknown fields, malformed JSON, and invalid
URLs fail startup rather than silently producing an incomplete index.
Limits: 10 MiB per dataset, 10000 documents. Restart after editing the data.
There is no public ingestion endpoint.

Set SEARCH_DATA_PATH before startup to ingest another file. Relative paths
resolve from the project directory, not the terminal's working directory.

PowerShell: `$env:SEARCH_DATA_PATH = "data/documents.json"`

macOS/Linux: `export SEARCH_DATA_PATH=data/documents.json`

## Tokenization and ranking

Queries, documents, and highlights use the same Unicode-aware tokenizer:
letter/number sequences, with internal straight or curly apostrophes.
Unicode case folding is applied, and curly apostrophes normalize to straight
apostrophes. Hyphens, underscores, and other punctuation separate tokens.

- `Local SEARCH` → `local`, `search`
- `home-repair` → `home`, `repair`
- `don’t` → `don't`
- `Café 2026` → `café`, `2026`

Query tokens are deduplicated. There is no stemming, stop-word removal,
phrase matching, fuzzy matching, or semantic search. Titles and content are
indexed once each. Documents containing at least one query token are eligible
and ranked by rank_bm25.BM25Okapi. Ties resolve by ID. Scores can be zero or
negative and are not probabilities; matching documents are not filtered by score.

## API contract

### GET /api/health

HTTP 200: `{"status":"ok","documents":10}`

### GET /api/search?q=garden&limit=10

| Parameter | Constraint |
| --- | --- |
| q | Required string, 1–200 characters before whitespace normalization |
| limit | Integer, 1–50, default 10 |

Whitespace is collapsed in the returned query. A successful response has:

```json
{
  "query": "garden",
  "tokens": ["garden"],
  "total": 1,
  "returned": 1,
  "took_ms": 0.42,
  "results": [
    {
      "id": "doc-009",
      "title": "Plan a home vegetable garden",
      "url": "https://example.com/vegetable-garden",
      "snippet": "Choose a sunny location for a home vegetable garden.",
      "score": 2.5,
      "title_highlights": [{"start": 22, "end": 28}],
      "snippet_highlights": [{"start": 45, "end": 51}]
    }
  ]
}
```

This illustrates the schema; snippets, scores, timings, and offsets depend on
the dataset. `total` counts all eligible documents, and `returned` counts
those included after applying the limit. Results sort by descending BM25
score, then ID. No match is HTTP 200 with total 0 and results [].

Highlights are half-open `[start, end)` offsets into the exact returned title
or snippet, measured in Unicode code points, not UTF-16 code units.

### Errors

```json
{"error":{"code":"invalid_query","message":"Enter at least one letter or number."}}
```

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | invalid_query | Whitespace-only or punctuation-only query |
| 422 | validation_error | Missing/oversized q or invalid limit |
| 503 | unavailable | Index not ready |
| 500 | internal_error | Unexpected failure; details logged locally |

## Interface and safety

The UI supports Enter, example searches, bookmarkable q URLs, explicit
initial/loading/no-match/error states, request cancellation, stale-response
protection, and a 15-second request timeout. A new search cancels the old one.

Untrusted content uses text nodes, never innerHTML. Highlight marks are DOM
elements built from validated ranges; Array.from handles Unicode code points.
Document URLs are validated at ingestion and checked in the browser.
External links use noopener/noreferrer. API requests are same-origin; CORS
is unnecessary. Responses include browser security headers.

## Tests

Windows: `.\.venv\Scripts\python.exe -m pytest -q`

macOS/Linux: `.venv/bin/python -m pytest -q`

## Operation

The index is immutable for the process lifetime. Each worker holds its own
copy. Use one worker for small local collections. BM25 scoring scans the
in-memory corpus and is intended for small datasets.

Bind to 127.0.0.1 for local operation. Public deployments require a reverse
proxy with HTTPS, appropriate authentication, request throttling, and
monitoring. Those infrastructure services are outside the local scope.
