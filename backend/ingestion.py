from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_DATASET_BYTES = 10 * 1024 * 1024
MAX_DOCUMENTS = 10_000


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2048)
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("id", "title", "url", "content")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError("URL must not contain whitespace or control characters")
        if "\\" in value:
            raise ValueError("URL must not contain backslashes")
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Invalid URL") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("URL must be an absolute HTTP(S) URL without credentials")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Invalid URL port")
        return value


def load_documents(path: Path) -> tuple[Document, ...]:
    try:
        with path.open("rb") as source:
            payload = source.read(MAX_DATASET_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"Cannot read dataset: {path}") from exc
    if len(payload) > MAX_DATASET_BYTES:
        raise ValueError("Dataset exceeds the 10 MiB limit")
    try:
        records = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Dataset must be valid UTF-8 JSON") from exc
    if not isinstance(records, list) or not records:
        raise ValueError("Dataset must be a nonempty JSON array")
    if len(records) > MAX_DOCUMENTS:
        raise ValueError(f"Dataset exceeds the {MAX_DOCUMENTS} document limit")

    documents: list[Document] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        try:
            document = Document.model_validate(record)
        except ValidationError as exc:
            raise ValueError(f"Invalid document at array index {index}: {exc}") from exc
        if document.id in seen_ids:
            raise ValueError(f"Duplicate document ID: {document.id}")
        seen_ids.add(document.id)
        documents.append(document)
    return tuple(documents)
