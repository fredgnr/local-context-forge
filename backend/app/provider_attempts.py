"""Durable desktop CLI provider attempt state.

The Python sidecar owns the database state; Electron Main owns executable
discovery and process execution. A committed execution is never reclaimed or
replayed. Renderer-facing callers receive only ``public_view``.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Callable

from .db import Database
from .utils import utcnow


_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_CODE_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_TERMINAL = {"succeeded", "failed", "cancelled", "uncertain"}
_PROVIDERS = {"codex_cli", "cursor_cli"}
_POLICIES = {"codex_only", "codex_then_cursor"}
_FALLBACK_REASONS = {
    "codex_not_installed",
    "codex_not_authenticated",
}
_DIAGNOSTICS = {
    "codex-not-installed",
    "codex-not-authenticated",
    "codex-installation-unsupported",
    "codex-unavailable",
    "cursor-consent-required",
    "cursor-not-installed",
    "cursor-not-authenticated",
    "cursor-installation-unsupported",
    "cursor-unavailable",
    "result-uncertain",
}


class ProviderAttemptError(RuntimeError):
    pass


class ProviderAttemptNotFound(ProviderAttemptError):
    pass


class ProviderAttemptConflict(ProviderAttemptError):
    pass


class ProviderAttemptValidation(ProviderAttemptError):
    pass


def _identifier() -> str:
    return uuid.uuid4().hex


def _parse_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ProviderAttemptValidation("Invalid provider attempt timestamp") from error
    if parsed.tzinfo is None:
        raise ProviderAttemptValidation("Invalid provider attempt timestamp")
    return parsed.astimezone(UTC)


def _validated_evidence_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 512
        or "\0" in value
    ):
        raise ProviderAttemptValidation("Invalid provider attempt evidence path")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ProviderAttemptValidation("Invalid provider attempt evidence path")
    return candidate.as_posix()


def _validated_candidates(policy: str, candidates: list[str]) -> list[str]:
    if policy not in _POLICIES:
        raise ProviderAttemptValidation("Invalid provider policy")
    expected = (
        ["codex_cli"]
        if policy == "codex_only"
        else ["codex_cli", "cursor_cli"]
    )
    if candidates != expected:
        raise ProviderAttemptValidation("Provider candidates do not match policy")
    return candidates


def _validated_identity(
    value: dict[str, Any],
    provider: str,
) -> str:
    if not isinstance(value, dict) or set(value) != {
        "provider",
        "canonical_path",
        "sha256",
        "size",
        "mtime_ms",
        "device",
        "inode",
        "mode",
        "version",
    }:
        raise ProviderAttemptValidation("Invalid executable identity")
    canonical_path = value.get("canonical_path")
    if (
        value.get("provider") != provider
        or not isinstance(canonical_path, str)
        or not canonical_path.startswith("/")
        or "\0" in canonical_path
        or len(canonical_path.encode("utf-8")) > 4096
        or not _SHA256_PATTERN.fullmatch(str(value.get("sha256") or ""))
        or not isinstance(value.get("version"), str)
        or not 1 <= len(str(value["version"])) <= 128
    ):
        raise ProviderAttemptValidation("Invalid executable identity")
    for field in ("size", "device", "inode", "mode"):
        if not isinstance(value.get(field), int) or int(value[field]) < 0:
            raise ProviderAttemptValidation("Invalid executable identity")
    mtime = value.get("mtime_ms")
    if not isinstance(mtime, (int, float)) or float(mtime) < 0:
        raise ProviderAttemptValidation("Invalid executable identity")
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(encoded.encode("utf-8")) > 16 * 1024:
        raise ProviderAttemptValidation("Executable identity is too large")
    return encoded


def input_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ProviderAttemptStore:
    def __init__(
        self,
        database: Database,
        *,
        now: Callable[[], str] = utcnow,
        identifiers: Callable[[], str] = _identifier,
    ) -> None:
        self._database = database
        self._now = now
        self._identifiers = identifiers

    def _row(self, connection: Any, attempt_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM provider_attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise ProviderAttemptNotFound("Provider attempt was not found")
        return dict(row)

    def create(
        self,
        *,
        job_id: str,
        version_id: str | None,
        corpus_revision: int,
        policy: str,
        candidates: list[str],
        cursor_consent_version: int | None,
        cursor_consent_granted_at: str | None,
        input_sha256: str,
        evidence_path: str,
    ) -> dict[str, Any]:
        if not _ID_PATTERN.fullmatch(job_id):
            raise ProviderAttemptValidation("Invalid provider attempt job")
        if version_id is not None and not _ID_PATTERN.fullmatch(version_id):
            raise ProviderAttemptValidation("Invalid provider attempt version")
        if not isinstance(corpus_revision, int) or corpus_revision < 0:
            raise ProviderAttemptValidation("Invalid corpus revision")
        candidates = _validated_candidates(policy, candidates)
        if not _SHA256_PATTERN.fullmatch(input_sha256):
            raise ProviderAttemptValidation("Invalid provider input digest")
        evidence_path = _validated_evidence_path(evidence_path)
        if policy == "codex_then_cursor":
            if cursor_consent_version != 1 or cursor_consent_granted_at is None:
                raise ProviderAttemptValidation(
                    "Current Cursor fallback consent is required"
                )
            _parse_instant(cursor_consent_granted_at)
        elif (
            cursor_consent_version is not None
            or cursor_consent_granted_at is not None
        ):
            raise ProviderAttemptValidation(
                "Cursor consent is not valid for codex_only"
            )
        attempt_id = self._identifiers()
        if not _ID_PATTERN.fullmatch(attempt_id):
            raise ProviderAttemptValidation("Invalid provider attempt identifier")
        now = self._now()
        _parse_instant(now)
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO provider_attempts (
                        id, job_id, version_id, corpus_revision, policy,
                        candidates_json, cursor_consent_version,
                        cursor_consent_granted_at, status, input_sha256,
                        evidence_path, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        job_id,
                        version_id,
                        corpus_revision,
                        policy,
                        json.dumps(candidates, separators=(",", ":")),
                        cursor_consent_version,
                        cursor_consent_granted_at,
                        input_sha256,
                        evidence_path,
                        now,
                        now,
                    ),
                )
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise ProviderAttemptConflict(
                    "Job already has a provider attempt"
                ) from error
            raise
        return self.get(attempt_id)

    def get(self, attempt_id: str) -> dict[str, Any]:
        if not _ID_PATTERN.fullmatch(attempt_id):
            raise ProviderAttemptNotFound("Provider attempt was not found")
        row = self._database.fetchone(
            "SELECT * FROM provider_attempts WHERE id = ?",
            (attempt_id,),
        )
        if row is None:
            raise ProviderAttemptNotFound("Provider attempt was not found")
        row["candidates"] = json.loads(str(row.pop("candidates_json")))
        if row.get("executable_identity_json"):
            row["executable_identity"] = json.loads(
                str(row["executable_identity_json"])
            )
        else:
            row["executable_identity"] = None
        return row

    def public_view(self, attempt_id: str) -> dict[str, Any]:
        row = self.get(attempt_id)
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "policy": row["policy"],
            "status": row["status"],
            "selected_provider": row["selected_provider"],
            "fallback_reason": row["fallback_reason"],
            "diagnostic": row["diagnostic"],
            "requires_explicit_retry": row["status"] == "uncertain",
        }

    def claim(
        self,
        attempt_id: str,
        *,
        lease_seconds: int = 120,
    ) -> dict[str, Any]:
        if not 30 <= lease_seconds <= 900:
            raise ProviderAttemptValidation("Invalid provider claim lease")
        now = self._now()
        now_value = _parse_instant(now)
        expires_at = (now_value + timedelta(seconds=lease_seconds)).isoformat(
            timespec="microseconds"
        )
        claim_id = self._identifiers()
        if not _ID_PATTERN.fullmatch(claim_id):
            raise ProviderAttemptValidation("Invalid provider claim identifier")
        with self._database.transaction() as connection:
            row = self._row(connection, attempt_id)
            if row["execution_committed_at"] is not None:
                raise ProviderAttemptConflict(
                    "Committed provider attempt cannot be reclaimed"
                )
            claimable = row["status"] == "pending"
            if row["status"] in {"claimed", "selected"} and row["claim_expires_at"]:
                claimable = (
                    _parse_instant(str(row["claim_expires_at"])) <= now_value
                )
            if not claimable:
                raise ProviderAttemptConflict(
                    "Provider attempt is not claimable"
                )
            updated = connection.execute(
                """
                UPDATE provider_attempts
                SET status = 'claimed', claim_id = ?, claimed_at = ?,
                    claim_expires_at = ?, selected_provider = NULL,
                    executable_identity_json = NULL, fallback_reason = NULL,
                    diagnostic = NULL, selected_at = NULL, updated_at = ?
                WHERE id = ? AND execution_committed_at IS NULL
                """,
                (claim_id, now, expires_at, now, attempt_id),
            )
            if updated.rowcount != 1:
                raise ProviderAttemptConflict(
                    "Provider attempt claim lost a compare-and-swap race"
                )
        result = self.get(attempt_id)
        result["claim_id"] = claim_id
        return result

    def claim_next(self, *, lease_seconds: int = 120) -> dict[str, Any] | None:
        rows = self._database.fetchall(
            """
            SELECT id FROM provider_attempts
            WHERE execution_committed_at IS NULL
              AND status IN ('pending', 'claimed', 'selected')
            ORDER BY created_at, id
            LIMIT 32
            """
        )
        for row in rows:
            try:
                return self.claim(
                    str(row["id"]),
                    lease_seconds=lease_seconds,
                )
            except ProviderAttemptConflict:
                continue
        return None

    def select(
        self,
        attempt_id: str,
        *,
        claim_id: str,
        provider: str,
        executable_identity: dict[str, Any],
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        if provider not in _PROVIDERS:
            raise ProviderAttemptValidation("Invalid selected provider")
        if fallback_reason is not None and fallback_reason not in _FALLBACK_REASONS:
            raise ProviderAttemptValidation("Invalid provider fallback reason")
        if provider == "codex_cli" and fallback_reason is not None:
            raise ProviderAttemptValidation(
                "Primary provider cannot have a fallback reason"
            )
        identity_json = _validated_identity(executable_identity, provider)
        now = self._now()
        now_value = _parse_instant(now)
        with self._database.transaction() as connection:
            row = self._row(connection, attempt_id)
            candidates = json.loads(str(row["candidates_json"]))
            if provider not in candidates:
                raise ProviderAttemptValidation(
                    "Selected provider is not an attempt candidate"
                )
            if (
                row["status"] != "claimed"
                or row["claim_id"] != claim_id
                or row["execution_committed_at"] is not None
                or row["claim_expires_at"] is None
                or _parse_instant(str(row["claim_expires_at"])) <= now_value
            ):
                raise ProviderAttemptConflict(
                    "Provider attempt selection lost its claim"
                )
            updated = connection.execute(
                """
                UPDATE provider_attempts
                SET status = 'selected', selected_provider = ?,
                    executable_identity_json = ?, fallback_reason = ?,
                    selected_at = ?, updated_at = ?
                WHERE id = ? AND status = 'claimed' AND claim_id = ?
                  AND execution_committed_at IS NULL
                """,
                (
                    provider,
                    identity_json,
                    fallback_reason,
                    now,
                    now,
                    attempt_id,
                    claim_id,
                ),
            )
            if updated.rowcount != 1:
                raise ProviderAttemptConflict(
                    "Provider attempt selection lost a compare-and-swap race"
                )
        return self.get(attempt_id)

    def fail_preflight(
        self,
        attempt_id: str,
        *,
        claim_id: str,
        diagnostic: str,
    ) -> dict[str, Any]:
        if diagnostic not in _DIAGNOSTICS:
            raise ProviderAttemptValidation("Invalid provider diagnostic")
        now = self._now()
        _parse_instant(now)
        with self._database.transaction() as connection:
            updated = connection.execute(
                """
                UPDATE provider_attempts
                SET status = 'failed', diagnostic = ?, error_code = 'preflight',
                    finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'claimed' AND claim_id = ?
                  AND execution_committed_at IS NULL
                """,
                (diagnostic, now, now, attempt_id, claim_id),
            )
            if updated.rowcount != 1:
                raise ProviderAttemptConflict(
                    "Provider preflight completion lost its claim"
                )
        return self.get(attempt_id)

    def commit_execution(
        self,
        attempt_id: str,
        *,
        claim_id: str,
    ) -> dict[str, Any]:
        now = self._now()
        now_value = _parse_instant(now)
        with self._database.transaction() as connection:
            row = self._row(connection, attempt_id)
            if (
                row["status"] != "selected"
                or row["claim_id"] != claim_id
                or row["execution_committed_at"] is not None
                or row["claim_expires_at"] is None
                or _parse_instant(str(row["claim_expires_at"])) <= now_value
            ):
                raise ProviderAttemptConflict(
                    "Provider execution commit lost its claim"
                )
            updated = connection.execute(
                """
                UPDATE provider_attempts
                SET status = 'executing', execution_committed_at = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'selected' AND claim_id = ?
                  AND execution_committed_at IS NULL
                """,
                (now, now, attempt_id, claim_id),
            )
            if updated.rowcount != 1:
                raise ProviderAttemptConflict(
                    "Provider execution commit lost a compare-and-swap race"
                )
            identity = json.loads(str(row["executable_identity_json"]))
            receipt = {
                "attempt_id": attempt_id,
                "claim_id": claim_id,
                "selected_provider": row["selected_provider"],
                "executable_sha256": identity["sha256"],
                "execution_committed_at": now,
            }
        return receipt

    def complete(
        self,
        attempt_id: str,
        *,
        claim_id: str,
        status: str,
        output_sha256: str | None = None,
        output_size: int | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ProviderAttemptValidation("Invalid provider terminal status")
        if status == "succeeded":
            if (
                output_sha256 is None
                or not _SHA256_PATTERN.fullmatch(output_sha256)
                or not isinstance(output_size, int)
                or not 0 <= output_size <= 16 * 1024 * 1024
                or error_code is not None
            ):
                raise ProviderAttemptValidation("Invalid provider output evidence")
        elif (
            output_sha256 is not None
            or output_size is not None
            or error_code is None
            or not _ERROR_CODE_PATTERN.fullmatch(error_code)
        ):
            raise ProviderAttemptValidation("Invalid provider failure evidence")
        now = self._now()
        _parse_instant(now)
        with self._database.transaction() as connection:
            updated = connection.execute(
                """
                UPDATE provider_attempts
                SET status = ?, output_sha256 = ?, output_size = ?,
                    error_code = ?, finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'executing' AND claim_id = ?
                  AND execution_committed_at IS NOT NULL
                """,
                (
                    status,
                    output_sha256,
                    output_size,
                    error_code,
                    now,
                    now,
                    attempt_id,
                    claim_id,
                ),
            )
            if updated.rowcount != 1:
                raise ProviderAttemptConflict(
                    "Provider completion lost a compare-and-swap race"
                )
        return self.get(attempt_id)

    def recover_interrupted(self) -> dict[str, int]:
        now = self._now()
        now_value = _parse_instant(now)
        with self._database.transaction() as connection:
            uncertain = connection.execute(
                """
                UPDATE provider_attempts
                SET status = 'uncertain', diagnostic = 'result-uncertain',
                    error_code = 'result-uncertain', finished_at = ?,
                    updated_at = ?
                WHERE execution_committed_at IS NOT NULL
                  AND status NOT IN (
                      'succeeded', 'failed', 'cancelled', 'uncertain'
                  )
                """,
                (now, now),
            ).rowcount
            rows = connection.execute(
                """
                SELECT id, claim_expires_at FROM provider_attempts
                WHERE execution_committed_at IS NULL
                  AND status IN ('claimed', 'selected')
                """
            ).fetchall()
            expired_ids = [
                str(row["id"])
                for row in rows
                if row["claim_expires_at"]
                and _parse_instant(str(row["claim_expires_at"])) <= now_value
            ]
            reset = 0
            for attempt_id in expired_ids:
                reset += connection.execute(
                    """
                    UPDATE provider_attempts
                    SET status = 'pending', claim_id = NULL, claimed_at = NULL,
                        claim_expires_at = NULL, selected_provider = NULL,
                        executable_identity_json = NULL,
                        fallback_reason = NULL, diagnostic = NULL,
                        selected_at = NULL, updated_at = ?
                    WHERE id = ? AND execution_committed_at IS NULL
                    """,
                    (now, attempt_id),
                ).rowcount
        return {"uncertain": uncertain, "reset": reset}
