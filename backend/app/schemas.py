from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class LibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str | None = Field(default=None, max_length=180)
    source: str = Field(min_length=1, max_length=2048)
    description: str = Field(default="", max_length=4000)


class LibraryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    source: str | None = Field(default=None, min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=4000)
    default_version: str | None = Field(default=None, max_length=160)


class LibraryOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    slug: str
    context7_id: str
    source: str
    description: str
    default_version: str | None = None
    created_at: str
    updated_at: str


class IngestRequest(BaseModel):
    version: str | None = Field(default=None, min_length=1, max_length=160)
    ref: str = Field(default="HEAD", min_length=1, max_length=200)
    provider: Literal[
        "auto",
        "mock",
        "ollama",
        "codex",
        "codex_cli",
        "cursor",
        "cursor_cli",
    ] = Field(
        default="auto",
        validation_alias=AliasChoices("provider", "generator"),
    )
    auto_publish: bool = False


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    library_id: str | None = Field(default=None, max_length=200)
    version: str | None = Field(default=None, max_length=160)
    limit: int = Field(default=8, ge=1, le=30)


class PageOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    library_id: str
    version: str
    path: str
    title: str
    kind: str
    summary: str
    markdown: str
    source_sha: str
    metadata: dict[str, Any]
    published_at: str


class QueryHit(BaseModel):
    path: str
    title: str
    summary: str
    snippet: str
    score: float
    library_id: str
    version: str
    source_sha: str
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class QueryResponse(BaseModel):
    query: str
    engine: str
    results: list[QueryHit]


class SettingsPatch(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    provider_order: list[
        Literal["codex_cli", "cursor_cli", "mock", "ollama"]
    ] | None = None
    fallback_enabled: bool | None = None
    concurrency: int | None = Field(default=None, ge=1, le=1)
    embedding_model: str | None = Field(default=None, min_length=1, max_length=500)


class EmbeddingModelValidate(BaseModel):
    model: str = Field(min_length=1, max_length=500)


class RebuildRequest(BaseModel):
    model: str | None = Field(default=None, min_length=1, max_length=500)
    library_id: str | None = Field(default=None, min_length=1, max_length=200)
