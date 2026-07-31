#!/usr/bin/env python3
"""Bootstrap independent desktop release keys on an administrator host.

This tool intentionally has no CI mode. It writes only public pins into the
repository. Private material stays in a mode-0700 directory outside the
repository and every private file is mode 0600. With ``--upload`` it sends one
versioned credential bundle to the protected ``macos-release`` GitHub
Environment through ``gh secret set`` stdin and removes the private directory
only after the matching public pins have been committed locally.

The command never prints private key, certificate bundle, password, or secret
values.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UPDATE_PUBLIC_KEY = (
    REPOSITORY_ROOT
    / "desktop"
    / "resources"
    / "update"
    / "update-metadata-ed25519-public.pem"
)
UPDATE_LOCK = (
    REPOSITORY_ROOT / "runtime" / "update-metadata-key.lock.json"
)
CODESIGN_LOCK = (
    REPOSITORY_ROOT / "runtime" / "macos-codesign-certificate.lock.json"
)
ENVIRONMENT_NAME = "macos-release"
SIGNING_IDENTITY = "Local Context Forge Self Signed"
CANONICAL_REPOSITORY = "fredgnr/local-context-forge"
RELEASE_TAG_POLICY = "v*.*.*"
CREDENTIAL_BUNDLE_SECRET = "DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64"


class BootstrapError(RuntimeError):
    """Raised when key provisioning cannot remain fail closed."""


def _run(
    arguments: list[str],
    *,
    input_bytes: bytes | None = None,
    label: str,
) -> bytes:
    try:
        completed = subprocess.run(
            arguments,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BootstrapError(f"{label} failed") from exc
    return completed.stdout


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_write(path: Path, value: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )


def _private_file(directory: Path, name: str, value: bytes) -> Path:
    destination = directory / name
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def _ensure_private_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise BootstrapError("Private output directory must be absolute")
    repository = REPOSITORY_ROOT.resolve()
    resolved_parent = path.parent.resolve(strict=True)
    candidate = resolved_parent / path.name
    try:
        candidate.relative_to(repository)
    except ValueError:
        pass
    else:
        raise BootstrapError("Private material must stay outside the repository")
    if candidate.exists() or candidate.is_symlink():
        raise BootstrapError("Private output directory already exists")
    candidate.mkdir(mode=0o700)
    info = candidate.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise BootstrapError("Private output directory is not mode 0700")
    return candidate


def _generate_update_key(private_directory: Path) -> dict[str, bytes | str]:
    private_key = private_directory / "update-metadata-ed25519-private.pem"
    public_temporary = private_directory / "update-metadata-ed25519-public.pem"
    _run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "ED25519",
            "-out",
            str(private_key),
        ],
        label="Ed25519 private-key generation",
    )
    private_key.chmod(0o600)
    _run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_temporary),
        ],
        label="Ed25519 public-key derivation",
    )
    public_bytes = public_temporary.read_bytes()
    _run(
        [
            "openssl",
            "pkey",
            "-pubin",
            "-in",
            str(public_temporary),
            "-text",
            "-noout",
        ],
        label="Ed25519 public-key validation",
    )
    digest = _sha256_bytes(public_bytes)
    return {
        "privateKey": private_key.read_bytes(),
        "publicKey": public_bytes,
        "publicKeySha256": digest,
    }


def _generate_codesign_certificate(
    private_directory: Path,
) -> dict[str, bytes | str]:
    private_key = private_directory / "macos-codesign-private-key.pem"
    certificate = private_directory / "macos-codesign-certificate.pem"
    bundle = private_directory / "macos-codesign-certificate.p12"
    password = secrets.token_urlsafe(36)
    password_file = _private_file(
        private_directory,
        "macos-codesign-password.txt",
        password.encode("ascii"),
    )
    _run(
        [
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:3072",
            "-x509",
            "-sha256",
            "-days",
            "3650",
            "-nodes",
            "-subj",
            (
                "/CN=Local Context Forge Self Signed"
                "/O=Local Context Forge"
            ),
            "-addext",
            "basicConstraints=critical,CA:FALSE",
            "-addext",
            "keyUsage=critical,digitalSignature",
            "-addext",
            "extendedKeyUsage=codeSigning",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ],
        label="Self-signed code-signing certificate generation",
    )
    private_key.chmod(0o600)
    certificate.chmod(0o600)
    _run(
        [
            "openssl",
            "pkcs12",
            "-export",
            "-out",
            str(bundle),
            "-inkey",
            str(private_key),
            "-in",
            str(certificate),
            "-name",
            SIGNING_IDENTITY,
            "-passout",
            f"file:{password_file}",
        ],
        label="PKCS#12 code-signing bundle generation",
    )
    bundle.chmod(0o600)
    certificate_der = _run(
        [
            "openssl",
            "x509",
            "-in",
            str(certificate),
            "-outform",
            "DER",
        ],
        label="Code-signing certificate fingerprint",
    )
    digest = _sha256_bytes(certificate_der)
    return {
        "bundle": bundle.read_bytes(),
        "password": password.encode("ascii"),
        "certificateSha256": digest,
    }


def _gh_api_json(repository: str, endpoint: str, label: str) -> dict[str, Any]:
    raw = _run(
        [
            "gh",
            "api",
            "--method",
            "GET",
            "--header",
            "Accept: application/vnd.github+json",
            "--header",
            "X-GitHub-Api-Version: 2022-11-28",
            endpoint,
        ],
        label=label,
    )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise BootstrapError(f"{label} returned an invalid shape")
    return value


def _verify_protected_environment(repository: str) -> None:
    repository_state = _gh_api_json(
        repository,
        f"repos/{repository}",
        "Canonical repository verification",
    )
    if (
        repository_state.get("full_name") != CANONICAL_REPOSITORY
        or repository_state.get("private") is not False
        or repository_state.get("visibility") != "public"
        or repository_state.get("archived") is True
    ):
        raise BootstrapError(
            "Secret upload requires the canonical active public repository"
        )

    environment = _gh_api_json(
        repository,
        f"repos/{repository}/environments/{ENVIRONMENT_NAME}",
        "Protected Environment verification",
    )
    rules = environment.get("protection_rules")
    reviewer_rules = (
        [
            rule
            for rule in rules
            if isinstance(rule, dict)
            and rule.get("type") == "required_reviewers"
        ]
        if isinstance(rules, list)
        else []
    )
    branch_policy = environment.get("deployment_branch_policy")
    if (
        environment.get("name") != ENVIRONMENT_NAME
        or len(reviewer_rules) != 1
        or not reviewer_rules[0].get("reviewers")
        or not isinstance(branch_policy, dict)
        or branch_policy.get("protected_branches") is not False
        or branch_policy.get("custom_branch_policies") is not True
    ):
        raise BootstrapError(
            "macos-release must require reviewers and use a custom "
            "deployment policy"
        )

    policies = _gh_api_json(
        repository,
        (
            f"repos/{repository}/environments/{ENVIRONMENT_NAME}"
            "/deployment-branch-policies?per_page=100"
        ),
        "Environment deployment policy verification",
    )
    policy_values = policies.get("branch_policies")
    if (
        not isinstance(policy_values, list)
        or len(policy_values) != 1
        or not isinstance(policy_values[0], dict)
        or policy_values[0].get("name") != RELEASE_TAG_POLICY
        or policy_values[0].get("type") not in (None, "tag")
    ):
        raise BootstrapError(
            "macos-release must allow only the v*.*.* deployment tag policy"
        )


def _set_environment_secret(
    repository: str, name: str, value: bytes
) -> None:
    _run(
        [
            "gh",
            "secret",
            "set",
            name,
            "--env",
            ENVIRONMENT_NAME,
            "--repo",
            repository,
        ],
        input_bytes=value,
        label=f"Protected Environment secret {name}",
    )


def _verify_environment_secret_exists(repository: str, name: str) -> None:
    response = _gh_api_json(
        repository,
        (
            f"repos/{repository}/environments/{ENVIRONMENT_NAME}"
            "/secrets?per_page=100"
        ),
        "Protected Environment secret verification",
    )
    values = response.get("secrets")
    if (
        not isinstance(values, list)
        or sum(
            1
            for value in values
            if isinstance(value, dict) and value.get("name") == name
        )
        != 1
    ):
        raise BootstrapError(
            "Versioned desktop release credential bundle is not present"
        )


def _credential_bundle(
    generation_id: str,
    update: dict[str, bytes | str],
    codesign: dict[str, bytes | str],
) -> bytes:
    private_key = update.get("privateKey")
    public_key_sha256 = update.get("publicKeySha256")
    certificate_bundle = codesign.get("bundle")
    certificate_password = codesign.get("password")
    certificate_sha256 = codesign.get("certificateSha256")
    if (
        not isinstance(private_key, bytes)
        or not isinstance(public_key_sha256, str)
        or not isinstance(certificate_bundle, bytes)
        or not isinstance(certificate_password, bytes)
        or not isinstance(certificate_sha256, str)
    ):
        raise BootstrapError("Generated credential material has invalid types")
    payload = _json_bytes(
        {
            "schemaVersion": 1,
            "credentialGenerationId": generation_id,
            "repository": CANONICAL_REPOSITORY,
            "environment": ENVIRONMENT_NAME,
            "updateMetadata": {
                "algorithm": "Ed25519",
                "privateKeyPemBase64": base64.b64encode(
                    private_key
                ).decode("ascii"),
                "publicKeySha256": public_key_sha256,
            },
            "macosCodeSigning": {
                "identity": SIGNING_IDENTITY,
                "certificateP12Base64": base64.b64encode(
                    certificate_bundle
                ).decode("ascii"),
                "certificatePasswordBase64": base64.b64encode(
                    certificate_password
                ).decode("ascii"),
                "certificateSha256": certificate_sha256,
            },
        }
    )
    return base64.b64encode(payload)


def _commit_public_artifacts(
    generation_id: str,
    update: dict[str, bytes | str],
    codesign: dict[str, bytes | str],
) -> None:
    artifacts = {
        UPDATE_PUBLIC_KEY: (
            bytes(update["publicKey"]),
            0o644,
        ),
        UPDATE_LOCK: (
            _json_bytes(
                {
                    "schemaVersion": 1,
                    "algorithm": "Ed25519",
                    "credentialGenerationId": generation_id,
                    "publicKeyPath": UPDATE_PUBLIC_KEY.relative_to(
                        REPOSITORY_ROOT
                    ).as_posix(),
                    "publicKeySha256": update["publicKeySha256"],
                    "status": "provisioned",
                }
            ),
            0o644,
        ),
        CODESIGN_LOCK: (
            _json_bytes(
                {
                    "schemaVersion": 1,
                    "identity": SIGNING_IDENTITY,
                    "credentialGenerationId": generation_id,
                    "certificateSha256": codesign["certificateSha256"],
                    "status": "provisioned",
                }
            ),
            0o644,
        ),
    }
    previous: dict[Path, tuple[bytes, int] | None] = {}
    for destination in artifacts:
        if destination.exists():
            info = destination.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise BootstrapError("Existing public release artifact is unsafe")
            previous[destination] = (
                destination.read_bytes(),
                stat.S_IMODE(info.st_mode),
            )
        else:
            previous[destination] = None
    written: list[Path] = []
    try:
        for destination, (contents, mode) in artifacts.items():
            _atomic_write(destination, contents, mode)
            written.append(destination)
    except Exception as exc:
        rollback_failed = False
        for destination in reversed(written):
            try:
                old = previous[destination]
                if old is None:
                    destination.unlink(missing_ok=True)
                else:
                    _atomic_write(destination, old[0], old[1])
            except Exception:
                rollback_failed = True
        if rollback_failed:
            raise BootstrapError(
                "Public artifact transaction and rollback both failed; "
                "inspect the three public files before continuing"
            ) from exc
        raise BootstrapError(
            "Public artifact transaction failed and was rolled back"
        ) from exc


def _already_provisioned(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("Release key lock is unreadable") from exc
    return value.get("status") == "provisioned"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate independent desktop update/code-signing keys without "
            "placing private material in the repository"
        )
    )
    parser.add_argument(
        "--repo",
        required=True,
        help=(
            "must be the explicit canonical repository "
            "fredgnr/local-context-forge"
        ),
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help=(
            "write one versioned private credential bundle to the protected "
            "macos-release Environment using gh stdin, then remove the "
            "private directory after public-pin commit succeeds"
        ),
    )
    parser.add_argument(
        "--private-output-dir",
        type=Path,
        help=(
            "new absolute directory outside the repository; defaults to a "
            "mode-0700 system temporary directory"
        ),
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="replace existing provisioned public pins intentionally",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.repo != CANONICAL_REPOSITORY:
        raise BootstrapError(
            f"--repo must be exactly {CANONICAL_REPOSITORY}"
        )
    if not arguments.rotate and (
        _already_provisioned(UPDATE_LOCK)
        or _already_provisioned(CODESIGN_LOCK)
        or UPDATE_PUBLIC_KEY.exists()
    ):
        raise BootstrapError(
            "Release keys are already provisioned; use --rotate intentionally"
        )
    if shutil.which("openssl") is None:
        raise BootstrapError("openssl is required")
    if arguments.upload and shutil.which("gh") is None:
        raise BootstrapError("gh is required for protected Environment upload")
    if arguments.upload:
        _verify_protected_environment(arguments.repo)

    if arguments.private_output_dir is None:
        private_directory = Path(
            tempfile.mkdtemp(prefix="lcf-desktop-release-keys-")
        )
        private_directory.chmod(0o700)
    else:
        private_directory = _ensure_private_directory(
            arguments.private_output_dir
        )

    secret_uploaded = False
    public_committed = False
    try:
        generation_id = secrets.token_hex(16)
        update = _generate_update_key(private_directory)
        codesign = _generate_codesign_certificate(private_directory)
        bundle = _credential_bundle(generation_id, update, codesign)
        _private_file(
            private_directory,
            "desktop-release-credential-bundle.base64",
            bundle,
        )
        if arguments.upload:
            _set_environment_secret(
                arguments.repo,
                CREDENTIAL_BUNDLE_SECRET,
                bundle,
            )
            secret_uploaded = True
            _verify_environment_secret_exists(
                arguments.repo,
                CREDENTIAL_BUNDLE_SECRET,
            )
        _commit_public_artifacts(generation_id, update, codesign)
        public_committed = True
    except Exception:
        print(
            "release-key bootstrap failed; no secret value was printed",
            file=sys.stderr,
        )
        if secret_uploaded and not public_committed:
            print(
                "the new whole credential bundle may already be active while "
                "public pins remain unchanged; formal release is fail-closed. "
                f"Keep the recovery directory and rerun with --repo "
                f"{CANONICAL_REPOSITORY} --upload --rotate after fixing the "
                "public-file failure",
                file=sys.stderr,
            )
        raise
    finally:
        if arguments.upload and public_committed:
            shutil.rmtree(private_directory)

    print(
        "release public pins updated; review and commit only the public key "
        "and runtime lock files"
    )
    if arguments.upload:
        print(
            "one versioned private credential bundle was uploaded to the "
            "protected macos-release Environment and removed locally"
        )
    else:
        print(
            "private material remains in this mode-0700 directory; upload it "
            f"securely, then remove it: {private_directory}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as exc:
        print(f"release-key bootstrap failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
