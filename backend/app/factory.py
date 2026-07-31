from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import Settings
from .db import SCHEMA_VERSION
from .desktop_session import DesktopSession
from .schemas import (
    EmbeddingModelValidate,
    IngestRequest,
    LibraryCreate,
    LibraryUpdate,
    QueryRequest,
    RebuildRequest,
    SettingsPatch,
)
from .service import AppService, ServiceError, ValidationError
from .version import (
    APP_VERSION,
    DESKTOP_PROTOCOL_MAJOR,
    DESKTOP_PROTOCOL_MINOR,
)


class RejectRequest(BaseModel):
    reason: str = Field(default="", max_length=4000)


def create_app(
    settings: Settings | None = None,
    desktop_session: DesktopSession | None = None,
    retriever: Any | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(current_app: FastAPI) -> AsyncIterator[None]:
        current_app.state.service.reconcile_desktop_retrieval()
        current_app.state.service.start_worker()
        try:
            yield
        finally:
            current_app.state.service.close()

    application = FastAPI(
        title="Local Context Forge API",
        version=APP_VERSION,
        description=(
            "Evidence-first repository ingestion, typed API Wiki generation, "
            "review, publication, and Context7-compatible retrieval."
        ),
        lifespan=lifespan,
    )
    application.state.service = AppService(settings, retriever=retriever)
    if desktop_session is None:
        origins = [
            item.strip()
            for item in os.getenv(
                "LCF_CORS_ORIGINS", "http://localhost:3000"
            ).split(",")
            if item.strip()
        ]
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        application.add_middleware(
            DesktopSession,
            **desktop_session.middleware_options(),
        )

    @application.exception_handler(ServiceError)
    async def service_error_handler(
        _request: Request, error: ServiceError
    ) -> JSONResponse:
        content: dict[str, Any] = {"detail": str(error)}
        if isinstance(error, ValidationError) and error.issues:
            content["issues"] = error.issues
        return JSONResponse(status_code=error.status_code, content=content)

    def service(request: Request) -> AppService:
        return request.app.state.service

    @application.get("/api/desktop/handshake", tags=["system"])
    def desktop_handshake() -> dict[str, Any]:
        if desktop_session is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"detail": "Not Found"},
            )
        return {
            "service": "local-context-forge",
            "role": "python-sidecar",
            "app_version": APP_VERSION,
            "sidecar_version": APP_VERSION,
            "protocol": {
                "major": int(DESKTOP_PROTOCOL_MAJOR),
                "minor": int(DESKTOP_PROTOCOL_MINOR),
            },
            "launch_id": desktop_session.launch_id,
            "transport": "uds",
            "schema_version": SCHEMA_VERSION,
            "capabilities": [
                "desktop-handshake",
                "health",
                "library-api",
                "desktop-retrieval-v1",
            ],
        }

    @application.get("/health", tags=["system"])
    @application.get("/api/health", tags=["system"])
    def health(request: Request) -> dict[str, Any]:
        backend = service(request)
        return {
            "status": "ok",
            "service": "local-context-forge",
            "version": application.version,
            "qmd": {
                "enabled": backend.settings.qmd_enabled,
                "available": backend.retriever.available,
                "hybrid_enabled": backend.settings.qmd_hybrid_enabled,
            },
            "embedding": backend.embedding_status(),
        }

    @application.get("/api/libraries", tags=["libraries"])
    def list_libraries(
        request: Request, search: str | None = None
    ) -> list[dict[str, Any]]:
        return service(request).list_libraries(search)

    @application.post(
        "/api/libraries",
        tags=["libraries"],
        status_code=status.HTTP_201_CREATED,
    )
    def create_library(request: Request, payload: LibraryCreate) -> dict[str, Any]:
        return service(request).create_library(payload.model_dump())

    @application.get("/api/libraries/{library_id}", tags=["libraries"])
    def get_library(request: Request, library_id: str) -> dict[str, Any]:
        return service(request).get_library(library_id)

    @application.patch("/api/libraries/{library_id}", tags=["libraries"])
    def update_library(
        request: Request, library_id: str, payload: LibraryUpdate
    ) -> dict[str, Any]:
        return service(request).update_library(
            library_id, payload.model_dump(exclude_unset=True)
        )

    @application.delete("/api/libraries/{library_id}", tags=["libraries"])
    def delete_library(
        request: Request,
        library_id: str,
        purge: bool = Query(
            False,
            description="Also remove immutable snapshots, facts, and wiki Git files.",
        ),
    ) -> dict[str, Any]:
        return service(request).delete_library(library_id, purge=purge)

    @application.post(
        "/api/libraries/{library_id}/ingest",
        tags=["ingest"],
        status_code=status.HTTP_202_ACCEPTED,
    )
    def ingest(
        request: Request,
        library_id: str,
        payload: IngestRequest,
    ) -> dict[str, Any]:
        backend = service(request)
        job = backend.create_ingest_job(
            library_id,
            version=payload.version,
            ref=payload.ref,
            provider=payload.provider,
            auto_publish=payload.auto_publish,
        )
        return job

    @application.get("/api/jobs", tags=["ingest"])
    def list_jobs(
        request: Request,
        library_id: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return service(request).list_jobs(library_id, limit)

    @application.get("/api/jobs/active", tags=["operations"])
    def active_jobs(request: Request) -> dict[str, Any]:
        return service(request).queue_activity()

    @application.get("/api/jobs/{job_id}", tags=["ingest"])
    def get_job(request: Request, job_id: str) -> dict[str, Any]:
        return service(request).get_job(job_id)

    @application.post("/api/jobs/{job_id}/cancel", tags=["ingest"])
    def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
        return service(request).cancel_job(job_id)

    @application.post(
        "/api/jobs/{job_id}/retry",
        tags=["ingest"],
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry_job(request: Request, job_id: str) -> dict[str, Any]:
        return service(request).retry_job(job_id)

    @application.get("/api/system/status", tags=["system"])
    def system_status(request: Request) -> dict[str, Any]:
        return service(request).system_status()

    @application.get("/api/settings", tags=["system"])
    def get_settings(request: Request) -> dict[str, Any]:
        return service(request).get_settings()

    @application.patch("/api/settings", tags=["system"])
    def patch_settings(
        request: Request, payload: SettingsPatch
    ) -> dict[str, Any]:
        return service(request).patch_settings(payload.model_dump(exclude_unset=True))

    @application.get("/api/embedding/models", tags=["operations"])
    def embedding_models(request: Request) -> list[dict[str, Any]]:
        return service(request).embedding_models()

    @application.post("/api/embedding/models/validate", tags=["operations"])
    def validate_embedding_model(
        request: Request, payload: EmbeddingModelValidate
    ) -> dict[str, Any]:
        return service(request).validate_embedding_model(payload.model)

    @application.post(
        "/api/rebuilds",
        tags=["operations"],
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_rebuild(
        request: Request, payload: RebuildRequest
    ) -> dict[str, Any]:
        return service(request).create_rebuild_job(
            model=payload.model,
            scope_library_id=payload.library_id,
        )

    @application.post("/api/admin/ingest/drain", tags=["operations"])
    def drain_ingest(request: Request) -> dict[str, Any]:
        return service(request).begin_ingest_drain()

    @application.post("/api/admin/ingest/resume", tags=["operations"])
    def resume_ingest(request: Request) -> dict[str, Any]:
        return service(request).resume_ingest()

    @application.post("/api/admin/jobs/recover-orphans", tags=["operations"])
    def recover_orphans(request: Request) -> dict[str, Any]:
        return service(request).recover_orphaned_jobs()

    @application.post("/api/admin/reindex", tags=["operations"])
    def reindex(
        request: Request,
        library_id: str | None = None,
        version: str | None = None,
        embed: bool = False,
    ) -> dict[str, Any]:
        return service(request).reindex(
            library_id=library_id,
            version=version,
            embed=embed,
        )

    @application.get("/api/libraries/{library_id}/pages", tags=["wiki"])
    def list_pages(
        request: Request,
        library_id: str,
        version: str | None = None,
        path: str | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        if path:
            return service(request).get_page(library_id, path, version)
        return service(request).list_pages(library_id, version)

    @application.get(
        "/api/libraries/{library_id}/pages/{page_path:path}", tags=["wiki"]
    )
    def get_page(
        request: Request,
        library_id: str,
        page_path: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        return service(request).get_page(library_id, page_path, version)

    @application.get("/api/libraries/{library_id}/page", tags=["wiki"])
    def get_page_by_query(
        request: Request,
        library_id: str,
        path: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Query-parameter variant convenient for browser clients."""

        return service(request).get_page(library_id, path, version)

    @application.get("/api/libraries/{library_id}/graph", tags=["wiki"])
    def graph(
        request: Request, library_id: str, version: str | None = None
    ) -> dict[str, Any]:
        return service(request).graph(library_id, version)

    @application.get("/api/libraries/{library_id}/proposals", tags=["review"])
    def list_proposals(
        request: Request,
        library_id: str,
        proposal_status: str | None = Query(None, alias="status"),
        version: str | None = None,
    ) -> list[dict[str, Any]]:
        return service(request).list_proposals(
            library_id, status=proposal_status, version=version
        )

    @application.get("/api/proposals/{proposal_id}", tags=["review"])
    def get_proposal(request: Request, proposal_id: str) -> dict[str, Any]:
        return service(request).get_proposal(proposal_id)

    @application.post("/api/proposals/{proposal_id}/publish", tags=["review"])
    def publish_proposal(request: Request, proposal_id: str) -> dict[str, Any]:
        return service(request).publish_proposal(proposal_id)

    @application.post("/api/proposals/{proposal_id}/reject", tags=["review"])
    def reject_proposal(
        request: Request, proposal_id: str, payload: RejectRequest | None = None
    ) -> dict[str, Any]:
        return service(request).reject_proposal(
            proposal_id, payload.reason if payload else ""
        )

    @application.post("/api/query", tags=["retrieval"])
    def query(request: Request, payload: QueryRequest) -> dict[str, Any]:
        return service(request).query(
            payload.query,
            library_id=payload.library_id,
            version=payload.version,
            limit=payload.limit,
        )

    @application.post("/api/libraries/{library_id}/lint", tags=["validation"])
    def lint(
        request: Request, library_id: str, version: str | None = None
    ) -> dict[str, Any]:
        return service(request).lint(library_id, version)

    return application
