from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.ingestion import load_documents
from backend.search import SearchEngine, SearchResponse

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
logger = logging.getLogger("diysearch")


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "error": {"code": code, "message": message}
    })


@asynccontextmanager
async def lifespan(application: FastAPI):
    configured_path = Path(os.environ.get("SEARCH_DATA_PATH", "data/documents.json"))
    dataset_path = configured_path if configured_path.is_absolute() else BASE_DIR / configured_path
    try:
        documents = load_documents(dataset_path)
        application.state.engine = SearchEngine(documents)
    except Exception:
        logger.exception("Dataset ingestion failed: %s", dataset_path)
        raise
    logger.info("Indexed %d documents", len(documents))
    try:
        yield
    finally:
        application.state.engine = None


app = FastAPI(
    title="DIYSearch",
    description="Local lexical search powered by BM25.",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' https://cdn.jsdelivr.net; connect-src 'self'; "
        "img-src 'self' data:; font-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    # FastAPI's generated Swagger page includes a trusted inline initializer
    # and loads its versioned UI bundle from jsDelivr. Keep this exception
    # scoped to the generated documentation, never the search interface.
    if request.url.path in {"/docs", "/docs/oauth2-redirect"}:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return error_response(422, "validation_error",
        "Provide q with 1–200 characters and limit as an integer from 1 to 50.")


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.error("Unhandled error processing %s", request.url.path,
                 exc_info=(type(exc), exc, exc.__traceback__))
    return error_response(500, "internal_error",
                          "Search could not be completed. Please try again.")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        return error_response(503, "unavailable", "Search is not ready.")
    return {"status": "ok", "documents": engine.document_count}


@app.get("/api/search", response_model=SearchResponse, responses={
    400: {"description": "Query has no searchable tokens"},
    422: {"description": "Invalid query parameters"},
    500: {"description": "Unexpected search failure"},
    503: {"description": "Search index unavailable"},
})
def search(request: Request,
           q: str = Query(..., min_length=1, max_length=200),
           limit: int = Query(10, ge=1, le=50)):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        return error_response(503, "unavailable", "Search is not ready.")
    try:
        return engine.search(q, limit)
    except ValueError:
        return error_response(400, "invalid_query", "Enter at least one letter or number.")
