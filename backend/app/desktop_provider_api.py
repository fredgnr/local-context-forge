"""Main-only provider attempt routes for the authenticated desktop UDS."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from .provider_attempts import (
    ProviderAttemptConflict,
    ProviderAttemptNotFound,
    ProviderAttemptStore,
    ProviderAttemptValidation,
)


class ExecutableIdentityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["codex_cli", "cursor_cli"]
    canonical_path: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    mtime_ms: float = Field(ge=0)
    device: int = Field(ge=0)
    inode: int = Field(ge=0)
    mode: int = Field(ge=0)
    version: str = Field(min_length=1, max_length=128)


class ProviderSelectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    provider: Literal["codex_cli", "cursor_cli"]
    executable_identity: ExecutableIdentityPayload
    fallback_reason: (
        Literal["codex_not_installed", "codex_not_authenticated"] | None
    ) = None


class ProviderClaimPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_seconds: int = Field(default=120, ge=30, le=900)


class ProviderClaimTokenPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class ProviderPreflightFailurePayload(ProviderClaimTokenPayload):
    diagnostic: Literal[
        "codex-not-installed",
        "codex-not-authenticated",
        "codex-installation-unsupported",
        "codex-unavailable",
        "cursor-consent-required",
        "cursor-not-installed",
        "cursor-not-authenticated",
        "cursor-installation-unsupported",
        "cursor-unavailable",
        "attempt-input-invalid",
    ]


class ProviderCompletePayload(ProviderClaimTokenPayload):
    status: Literal["succeeded", "failed", "cancelled"]
    output_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    output_size: int | None = Field(default=None, ge=0, le=16 * 1024 * 1024)
    error_code: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9-]{0,63}$",
    )


def _provider_store(request: Request) -> ProviderAttemptStore:
    store = getattr(request.app.state.service, "provider_attempts", None)
    if not isinstance(store, ProviderAttemptStore):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Desktop provider attempts are unavailable",
        )
    return store


def _translate_provider_error(error: Exception) -> HTTPException:
    if isinstance(error, ProviderAttemptNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        )
    if isinstance(error, ProviderAttemptConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )
    if isinstance(error, ProviderAttemptValidation):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Provider attempt operation failed",
    )


def _private_attempt_directory(
    data_dir: Path,
    evidence_path: str,
) -> Path:
    root = data_dir.resolve()
    candidate = root.joinpath(*Path(evidence_path).parts)
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ProviderAttemptValidation(
            "Provider attempt evidence directory is invalid"
        ) from error
    if not relative.parts:
        raise ProviderAttemptValidation(
            "Provider attempt evidence directory is invalid"
        )
    metadata = resolved.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ProviderAttemptValidation(
            "Provider attempt evidence directory is not private"
        )
    for name in ("request.json", "evidence.json", "schema.json", "prompt.txt"):
        file_path = resolved / name
        file_metadata = file_path.lstat()
        if (
            not stat.S_ISREG(file_metadata.st_mode)
            or stat.S_ISLNK(file_metadata.st_mode)
            or file_metadata.st_uid != os.geteuid()
            or file_metadata.st_size > 16 * 1024 * 1024
        ):
            raise ProviderAttemptValidation(
                "Provider attempt evidence file is invalid"
            )
    output_path = resolved / "result.json"
    if output_path.exists() or output_path.is_symlink():
        raise ProviderAttemptValidation(
            "Provider attempt output already exists before execution"
        )
    return resolved


def _claim_response(request: Request, row: dict[str, Any]) -> dict[str, Any]:
    attempt_directory = _private_attempt_directory(
        Path(request.app.state.service.settings.data_dir),
        str(row["evidence_path"]),
    )
    consent = None
    if row["cursor_consent_version"] is not None:
        consent = {
            "subject": "cursor_cli_fallback",
            "version": row["cursor_consent_version"],
            "granted": True,
            "granted_at": row["cursor_consent_granted_at"],
        }
    return {
        "attempt_id": row["id"],
        "job_id": row["job_id"],
        "claim_id": row["claim_id"],
        "policy": row["policy"],
        "candidates": row["candidates"],
        "cursor_consent": consent,
        "input_sha256": row["input_sha256"],
        "attempt_directory": str(attempt_directory),
        "request_path": str(attempt_directory / "request.json"),
        "evidence_path": str(attempt_directory / "evidence.json"),
        "schema_path": str(attempt_directory / "schema.json"),
        "prompt_path": str(attempt_directory / "prompt.txt"),
        "output_path": str(attempt_directory / "result.json"),
    }


def install_desktop_provider_routes(application: FastAPI) -> None:
    """Install routes that are never present on the browser/TCP application."""

    @application.post(
        "/api/desktop/provider-attempts/claim-next",
        tags=["desktop-internal"],
        response_model=None,
    )
    def claim_next(
        request: Request,
        payload: ProviderClaimPayload,
    ) -> dict[str, Any] | Response:
        try:
            row = _provider_store(request).claim_next(
                lease_seconds=payload.lease_seconds
            )
            if row is None:
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            return _claim_response(request, row)
        except Exception as error:
            raise _translate_provider_error(error) from error

    @application.post(
        "/api/desktop/provider-attempts/{attempt_id}/select",
        tags=["desktop-internal"],
    )
    def select(
        request: Request,
        attempt_id: str,
        payload: ProviderSelectPayload,
    ) -> dict[str, Any]:
        try:
            row = _provider_store(request).select(
                attempt_id,
                claim_id=payload.claim_id,
                provider=payload.provider,
                executable_identity=payload.executable_identity.model_dump(),
                fallback_reason=payload.fallback_reason,
            )
            return _provider_store(request).public_view(str(row["id"]))
        except Exception as error:
            raise _translate_provider_error(error) from error

    @application.post(
        "/api/desktop/provider-attempts/{attempt_id}/fail-preflight",
        tags=["desktop-internal"],
    )
    def fail_preflight(
        request: Request,
        attempt_id: str,
        payload: ProviderPreflightFailurePayload,
    ) -> dict[str, Any]:
        try:
            row = _provider_store(request).fail_preflight(
                attempt_id,
                claim_id=payload.claim_id,
                diagnostic=payload.diagnostic,
            )
            return _provider_store(request).public_view(str(row["id"]))
        except Exception as error:
            raise _translate_provider_error(error) from error

    @application.post(
        "/api/desktop/provider-attempts/{attempt_id}/commit",
        tags=["desktop-internal"],
    )
    def commit(
        request: Request,
        attempt_id: str,
        payload: ProviderClaimTokenPayload,
    ) -> dict[str, Any]:
        try:
            return _provider_store(request).commit_execution(
                attempt_id,
                claim_id=payload.claim_id,
            )
        except Exception as error:
            raise _translate_provider_error(error) from error

    @application.post(
        "/api/desktop/provider-attempts/{attempt_id}/complete",
        tags=["desktop-internal"],
    )
    def complete(
        request: Request,
        attempt_id: str,
        payload: ProviderCompletePayload,
    ) -> dict[str, Any]:
        try:
            row = _provider_store(request).complete(
                attempt_id,
                claim_id=payload.claim_id,
                status=payload.status,
                output_sha256=payload.output_sha256,
                output_size=payload.output_size,
                error_code=payload.error_code,
            )
            return _provider_store(request).public_view(str(row["id"]))
        except Exception as error:
            raise _translate_provider_error(error) from error

    @application.post(
        "/api/desktop/provider-attempts/{attempt_id}/cancellation-state",
        tags=["desktop-internal"],
    )
    def cancellation_state(
        request: Request,
        attempt_id: str,
        payload: ProviderClaimTokenPayload,
    ) -> dict[str, Any]:
        try:
            return _provider_store(request).cancellation_state(
                attempt_id,
                claim_id=payload.claim_id,
            )
        except Exception as error:
            raise _translate_provider_error(error) from error
