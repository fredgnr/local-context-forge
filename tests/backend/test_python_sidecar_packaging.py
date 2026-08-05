from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import time
from collections import deque
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import audit_python_sidecar as audit  # noqa: E402
import build_python_sidecar as build  # noqa: E402


INSTALLER_NAME = "python-3.13.14-macos11.pkg"
ARCHIVE_NAME = "python-3.13.14-darwin-arm64.tar.gz"
BASE_ARCHIVE_PAYLOADS = {
    "setup.sh": b"#!/bin/sh\nexit 0\n",
    "build_output.txt": b"",
    INSTALLER_NAME: b"synthetic-python-installer-package",
}
ArchiveEntry = tuple[str, bytes, str]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_test_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic executable")
    path.chmod(0o755)


def _write_missing_import_allowlist(
    path: Path,
    modules: set[str],
) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "target": {
                    "os": "darwin",
                    "architecture": "arm64",
                    "pythonVersion": "3.13.14",
                },
                "pyinstallerVersion": "6.21.0",
                "pyinstallerHooksContribVersion": "2026.6",
                "modules": {
                    name: "synthetic reviewed reason"
                    for name in sorted(modules)
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_source_archive(
    path: Path,
    entries: list[ArchiveEntry],
) -> None:
    with tarfile.open(path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for name, payload, kind in entries:
            member = tarfile.TarInfo(name)
            member.mtime = 0
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            if kind == "file":
                member.mode = 0o644
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.mode = 0o777
                member.linkname = payload.decode("utf-8")
                member.size = 0
                archive.addfile(member)
            else:  # pragma: no cover - test helper misuse
                raise AssertionError(f"unsupported synthetic archive kind: {kind}")


def _source_fixture(
    tmp_path: Path,
    *,
    archive_entries: list[ArchiveEntry] | None = None,
    expected_payloads: dict[str, bytes] | None = None,
    manifest_text: str | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    expected = expected_payloads or BASE_ARCHIVE_PAYLOADS
    entries = archive_entries or [
        (name, payload, "file") for name, payload in expected.items()
    ]
    archive_path = tmp_path / ARCHIVE_NAME
    _write_source_archive(archive_path, entries)
    archive_bytes = archive_path.read_bytes()
    archive_sha256 = _sha256_bytes(archive_bytes)

    rendered_manifest = (
        manifest_text.format(
            archive_name=ARCHIVE_NAME,
            archive_sha=archive_sha256,
        )
        if manifest_text is not None
        else f"{archive_sha256}  {ARCHIVE_NAME}\n"
    )
    hash_manifest_path = tmp_path / "hashes.sha256"
    hash_manifest_path.write_text(rendered_manifest, encoding="ascii")
    hash_manifest_bytes = hash_manifest_path.read_bytes()

    distribution = {
        "provider": "actions/python-versions",
        "releaseTag": "synthetic-test-release",
        "archiveName": ARCHIVE_NAME,
        "archiveSource": f"https://example.invalid/{ARCHIVE_NAME}",
        "archiveSha256": archive_sha256,
        "archiveSize": len(archive_bytes),
        "archiveMembers": [
            {
                "path": name,
                "size": len(payload),
                "sha256": _sha256_bytes(payload),
            }
            for name, payload in expected.items()
        ],
        "installerPackageName": INSTALLER_NAME,
        "installerPackageSha256": _sha256_bytes(expected[INSTALLER_NAME]),
        "installMethod": "macos-installer-pkg-direct",
        "hashManifestName": "hashes.sha256",
        "hashManifestSource": "https://example.invalid/hashes.sha256",
        "hashManifestSha256": _sha256_bytes(hash_manifest_bytes),
        "hashManifestSize": len(hash_manifest_bytes),
    }
    toolchain = {
        "python": {
            "implementation": "CPython",
            "version": "3.13.14",
            "installRoot": "/synthetic/python/3.13",
            "interpreterRelativePath": "bin/python3.13",
            "distribution": distribution,
        }
    }
    return archive_path, hash_manifest_path, toolchain


def test_distribution_source_verifier_accepts_complete_synthetic_chain(
    tmp_path: Path,
) -> None:
    archive, hashes, toolchain = _source_fixture(tmp_path)

    provenance = build.verify_distribution_files(
        archive,
        hashes,
        toolchain=toolchain,
    )

    distribution = toolchain["python"]["distribution"]
    assert provenance == {
        "implementation": "CPython",
        "version": "3.13.14",
        "installRoot": "/synthetic/python/3.13",
        "provider": "actions/python-versions",
        "releaseTag": "synthetic-test-release",
        "archiveName": ARCHIVE_NAME,
        "archiveSource": f"https://example.invalid/{ARCHIVE_NAME}",
        "archiveSha256": distribution["archiveSha256"],
        "installerPackageName": INSTALLER_NAME,
        "installerPackageSha256": distribution["installerPackageSha256"],
        "hashManifestName": "hashes.sha256",
        "hashManifestSource": "https://example.invalid/hashes.sha256",
        "hashManifestSha256": distribution["hashManifestSha256"],
    }


def test_distribution_source_verifier_rejects_archive_tamper(
    tmp_path: Path,
) -> None:
    archive, hashes, toolchain = _source_fixture(tmp_path)
    tampered = bytearray(archive.read_bytes())
    tampered[-1] ^= 0x01
    archive.write_bytes(tampered)

    with pytest.raises(build.BuildError, match="archive differs"):
        build.verify_distribution_files(archive, hashes, toolchain=toolchain)


@pytest.mark.parametrize(
    "manifest_text",
    [
        "not-a-checksum  {archive_name}\n",
        "{archive_sha}  path/to/{archive_name}\n",
        (
            "{archive_sha}  {archive_name}\n"
            "{archive_sha}  {archive_name}\n"
        ),
    ],
    ids=["malformed-line", "unsafe-name", "duplicate-target"],
)
def test_distribution_source_verifier_rejects_malformed_hash_manifest(
    tmp_path: Path,
    manifest_text: str,
) -> None:
    archive, hashes, toolchain = _source_fixture(
        tmp_path,
        manifest_text=manifest_text,
    )

    with pytest.raises(build.BuildError, match="hash manifest"):
        build.verify_distribution_files(archive, hashes, toolchain=toolchain)


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../escape",
        "/absolute/path",
        "nested\\windows-path",
    ],
    ids=["parent", "absolute", "backslash"],
)
def test_distribution_source_verifier_rejects_unsafe_archive_member_path(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    entries = [
        (name, payload, "file") for name, payload in BASE_ARCHIVE_PAYLOADS.items()
    ]
    entries.append((unsafe_name, b"untrusted", "file"))
    archive, hashes, toolchain = _source_fixture(
        tmp_path,
        archive_entries=entries,
    )

    with pytest.raises(build.BuildError, match="unsafe path"):
        build.verify_distribution_files(archive, hashes, toolchain=toolchain)


def test_distribution_source_verifier_rejects_archive_symlink_member(
    tmp_path: Path,
) -> None:
    entries = [
        ("setup.sh", INSTALLER_NAME.encode("utf-8"), "symlink"),
        ("build_output.txt", b"", "file"),
        (INSTALLER_NAME, BASE_ARCHIVE_PAYLOADS[INSTALLER_NAME], "file"),
    ]
    archive, hashes, toolchain = _source_fixture(
        tmp_path,
        archive_entries=entries,
    )

    with pytest.raises(build.BuildError, match="non-regular member"):
        build.verify_distribution_files(archive, hashes, toolchain=toolchain)


def test_distribution_source_verifier_rejects_duplicate_archive_member(
    tmp_path: Path,
) -> None:
    entries = [
        (name, payload, "file") for name, payload in BASE_ARCHIVE_PAYLOADS.items()
    ]
    entries.append(("setup.sh", BASE_ARCHIVE_PAYLOADS["setup.sh"], "file"))
    archive, hashes, toolchain = _source_fixture(
        tmp_path,
        archive_entries=entries,
    )

    with pytest.raises(build.BuildError, match="duplicate members"):
        build.verify_distribution_files(archive, hashes, toolchain=toolchain)


def test_distribution_source_verifier_rejects_inconsistent_inner_package_pin(
    tmp_path: Path,
) -> None:
    archive, hashes, toolchain = _source_fixture(tmp_path)
    toolchain["python"]["distribution"]["installerPackageSha256"] = "0" * 64

    with pytest.raises(build.BuildError, match="package evidence"):
        build.verify_distribution_files(archive, hashes, toolchain=toolchain)


@pytest.mark.parametrize("unsafe_input", ["relative", "symlink"])
def test_distribution_source_verifier_requires_real_absolute_input_files(
    tmp_path: Path,
    unsafe_input: str,
) -> None:
    archive, hashes, toolchain = _source_fixture(tmp_path)
    if unsafe_input == "relative":
        rejected_archive = Path(archive.name)
    else:
        rejected_archive = tmp_path / "linked-archive.tar.gz"
        rejected_archive.symlink_to(archive.name)

    with pytest.raises(build.BuildError, match="archive"):
        build.verify_distribution_files(
            rejected_archive,
            hashes,
            toolchain=toolchain,
        )


def test_installer_extraction_writes_only_reviewed_package_with_private_mode(
    tmp_path: Path,
) -> None:
    archive, hashes, toolchain = _source_fixture(tmp_path)
    output = tmp_path / "extracted" / INSTALLER_NAME

    result = build.extract_reviewed_installer_package(
        archive,
        hashes,
        output,
        toolchain=toolchain,
    )

    assert result == output
    assert output.read_bytes() == BASE_ARCHIVE_PAYLOADS[INSTALLER_NAME]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(output.parent.iterdir()) == [output]


def test_installer_extraction_rejects_relative_output(tmp_path: Path) -> None:
    archive, hashes, toolchain = _source_fixture(tmp_path)

    with pytest.raises(build.BuildError, match="path must be absolute"):
        build.extract_reviewed_installer_package(
            archive,
            hashes,
            Path(INSTALLER_NAME),
            toolchain=toolchain,
        )


def test_installer_extraction_rejects_existing_output_symlink(
    tmp_path: Path,
) -> None:
    archive, hashes, toolchain = _source_fixture(tmp_path)
    output_directory = tmp_path / "extracted"
    output_directory.mkdir()
    sentinel = tmp_path / "sentinel.pkg"
    sentinel.write_bytes(b"must not be overwritten")
    output = output_directory / INSTALLER_NAME
    output.symlink_to("../sentinel.pkg")

    with pytest.raises(build.BuildError, match="not a regular file"):
        build.extract_reviewed_installer_package(
            archive,
            hashes,
            output,
            toolchain=toolchain,
        )

    assert output.is_symlink()
    assert sentinel.read_bytes() == b"must not be overwritten"
    assert list(output_directory.iterdir()) == [output]


def _valid_build_requirement_lines() -> list[str]:
    versions = {
        "altgraph": "0.17.4",
        "macholib": "1.16.3",
        "packaging": "26.2",
        "pyinstaller": "6.21.0",
        "pyinstaller-hooks-contrib": "2026.6",
        "setuptools": "83.0.0",
        "uv": "0.11.29",
    }
    return [
        f"{name}=={version} --hash=sha256:{index:064x}"
        for index, (name, version) in enumerate(versions.items(), start=1)
    ]


def test_build_requirements_parser_accepts_reviewed_lock() -> None:
    assert build.parse_build_requirements() == {
        "altgraph": "0.17.4",
        "macholib": "1.16.3",
        "packaging": "26.2",
        "pyinstaller": "6.21.0",
        "pyinstaller-hooks-contrib": "2026.6",
        "setuptools": "83.0.0",
        "uv": "0.11.29",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "hashless",
        "range",
        "uppercase-hash",
        "duplicate",
        "missing-package",
        "dangling-continuation",
    ],
)
def test_build_requirements_parser_rejects_non_exact_lock(
    tmp_path: Path,
    mutation: str,
) -> None:
    lines = _valid_build_requirement_lines()
    if mutation == "hashless":
        lines[0] = "altgraph==0.17.4"
    elif mutation == "range":
        lines[0] = lines[0].replace("==0.17.4", ">=0.17.4")
    elif mutation == "uppercase-hash":
        lines[0] = lines[0][:-64] + ("A" * 64)
    elif mutation == "duplicate":
        lines.append(lines[0])
    elif mutation == "missing-package":
        lines.pop()
    elif mutation == "dangling-continuation":
        lines.append("\\")
    lock = tmp_path / "build-requirements.lock"
    lock.write_text("\n".join(lines) + "\n", encoding="ascii")

    with pytest.raises(build.BuildError, match="Build requirements"):
        build.parse_build_requirements(lock)


def test_production_uv_lock_resolves_only_the_reviewed_runtime_closure() -> None:
    versions = build.runtime_dependency_versions()

    assert {
        "certifi": "2026.7.22",
        "dulwich": "1.2.11",
        "h11": "0.16.0",
        "urllib3": "2.7.0",
        "uvicorn": "0.51.0",
    }.items() <= versions.items()
    assert not {"httptools", "uvloop", "watchfiles", "websockets"} & versions.keys()
    assert not {"httpx", "packaging", "pytest"} & versions.keys()


def test_uv_lock_resolver_rejects_forbidden_uvicorn_extra(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        """\
version = 1

[[package]]
name = "local-context-forge-backend"
version = "0"
dependencies = [{ name = "websockets" }]

[[package]]
name = "websockets"
version = "99"
""",
        encoding="utf-8",
    )

    with pytest.raises(build.BuildError, match="forbidden Uvicorn"):
        build.runtime_dependency_versions(lock)


def test_uv_lock_check_binds_the_build_venv_to_the_reviewed_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_bin = tmp_path / "build-venv" / "bin"
    uv_executable = build_bin / "uv"
    framework_python = tmp_path / "framework" / "bin" / "python3.13"
    active_python = build_bin / "python"
    _write_test_executable(uv_executable)
    _write_test_executable(framework_python)
    active_python.symlink_to(framework_python)
    monkeypatch.setattr(build.sys, "executable", str(active_python))
    observed: dict[str, Any] = {}

    def checked_run(
        arguments: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        observed["arguments"] = arguments
        observed.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(build.subprocess, "run", checked_run)

    build.verify_uv_lock(uv_executable)

    assert observed["arguments"] == [
        str(uv_executable),
        "lock",
        "--check",
        "--python",
        str(framework_python),
    ]
    assert observed["cwd"] == build.BACKEND_ROOT
    assert observed["check"] is False
    assert observed["timeout"] == 180
    environment = observed["env"]
    assert environment["PATH"] == "/usr/bin:/bin"
    assert environment["UV_NO_CONFIG"] == "1"
    assert environment["UV_OFFLINE"] == "1"
    assert environment["UV_PYTHON_DOWNLOADS"] == "never"
    assert Path(environment["UV_CACHE_DIR"]).name.startswith("lcf-uv-lock-cache-")
    assert "HOME" not in environment


def test_uv_lock_check_rejects_a_python_from_another_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uv_executable = tmp_path / "build-venv" / "bin" / "uv"
    active_python = tmp_path / "other-venv" / "bin" / "python"
    _write_test_executable(uv_executable)
    _write_test_executable(active_python)
    monkeypatch.setattr(build.sys, "executable", str(active_python))

    with pytest.raises(build.BuildError, match="same build venv"):
        build.verify_uv_lock(uv_executable)


@pytest.mark.parametrize(
    ("stderr", "category"),
    [
        ("The lockfile needs to be updated; token=must-not-leak", "lock-drift"),
        ("No interpreter found for Python >=3.11", "interpreter-unavailable"),
        ("Packages were unavailable because the network was disabled", "offline-resolution"),
        ("error: unexpected argument '--future'\nUsage: uv lock", "cli-contract"),
        ("opaque failure with token=must-not-leak", "unclassified"),
    ],
)
def test_uv_lock_check_reports_only_a_controlled_failure_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stderr: str,
    category: str,
) -> None:
    build_bin = tmp_path / "build-venv" / "bin"
    uv_executable = build_bin / "uv"
    active_python = build_bin / "python"
    _write_test_executable(uv_executable)
    _write_test_executable(active_python)
    monkeypatch.setattr(build.sys, "executable", str(active_python))

    def failed_run(
        arguments: list[str],
        **_: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 2, stdout="", stderr=stderr)

    monkeypatch.setattr(build.subprocess, "run", failed_run)

    with pytest.raises(
        build.BuildError,
        match=rf"^uv lock check failed \(exit=2; category={category}\)$",
    ) as failure:
        build.verify_uv_lock(uv_executable)

    assert "must-not-leak" not in str(failure.value)


def test_missing_import_validator_reports_only_safe_module_names(
    tmp_path: Path,
) -> None:
    warning = tmp_path / "warn-lcf-service.txt"
    allowlist = tmp_path / "allowlist.json"
    _write_missing_import_allowlist(allowlist, {"winreg"})
    warning.write_text(
        "missing module named 'winreg' - imported by platform (optional)\n"
        "missing module named 'safe_new.module' - imported by package (optional)\n",
        encoding="utf-8",
    )

    with pytest.raises(
        build.BuildError,
        match=(
            r"^PyInstaller missing-import inventory differs from the reviewed target "
            r"\(observed=2; reviewed=1; unexpected=safe_new\.module\)$"
        ),
    ):
        build.validate_missing_imports(warning, allowlist_path=allowlist)


def test_missing_import_validator_rejects_a_stale_reviewed_entry(
    tmp_path: Path,
) -> None:
    warning = tmp_path / "warn-lcf-service.txt"
    allowlist = tmp_path / "allowlist.json"
    _write_missing_import_allowlist(allowlist, {"expected.module", "winreg"})
    warning.write_text(
        "missing module named 'winreg' - imported by platform (optional)\n",
        encoding="utf-8",
    )

    with pytest.raises(
        build.BuildError,
        match=r"observed=1; reviewed=2; missing=expected\.module",
    ):
        build.validate_missing_imports(warning, allowlist_path=allowlist)


def test_missing_import_validator_rejects_a_path_like_module_without_leaking_it(
    tmp_path: Path,
) -> None:
    warning = tmp_path / "warn-lcf-service.txt"
    warning.write_text(
        "missing module named '/Users/runner/must-not-leak' - imported by package\n",
        encoding="utf-8",
    )

    with pytest.raises(
        build.BuildError,
        match="malformed module name",
    ) as failure:
        build.validate_missing_imports(warning)

    assert "must-not-leak" not in str(failure.value)


@pytest.mark.parametrize(
    ("log", "category"),
    [
        (
            "Traceback (most recent call last):\n"
            "ModuleNotFoundError: No module named 'safe_runtime.module'\n",
            "module-not-found",
        ),
        (
            "Traceback (most recent call last):\n"
            "ImportError: cannot import name 'SafeSymbol' from 'safe.module' "
            "(/private/path-that-must-not-leak.py)\n",
            "import-error",
        ),
        (
            "Traceback (most recent call last):\n"
            "AttributeError: module 'safe.module' has no attribute 'SafeSymbol'\n",
            "attribute-error",
        ),
        (
            "lcf-service: desktop transport setup failed\n",
            "desktop-transport",
        ),
        (
            "ModuleNotFoundError: No module named '"
            + ("A" * 43)
            + "'\n",
            "module-not-found",
        ),
        ("Traceback (most recent call last):\nopaque secret\n", "python-traceback"),
        ("opaque secret\n", "unclassified"),
        ("", "no-output"),
    ],
)
def test_frozen_start_failure_category_is_controlled(
    tmp_path: Path,
    log: str,
    category: str,
) -> None:
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    log_handle.write(log.encode("utf-8"))
    try:
        observed = build._frozen_start_failure_category(
            log_handle,
            log_path,
            identity,
        )
    finally:
        log_handle.close()

    assert observed == category


def test_frozen_start_failure_category_does_not_expose_malformed_name(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    log_handle.write(
        (
            "Traceback (most recent call last):\n"
            "ModuleNotFoundError: No module named "
            "'/Users/runner/token-must-not-leak'\n"
        ).encode("utf-8"),
    )
    try:
        category = build._frozen_start_failure_category(
            log_handle,
            log_path,
            identity,
        )
    finally:
        log_handle.close()

    assert category == "module-not-found"
    assert "runner" not in category
    assert "token" not in category


def test_frozen_start_failure_category_rejects_non_utf8_output(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    log_handle.write(b"\xfftoken-must-not-leak")
    try:
        category = build._frozen_start_failure_category(
            log_handle,
            log_path,
            identity,
        )
    finally:
        log_handle.close()

    assert category == "log-non-utf8"
    assert "token" not in category


@pytest.mark.parametrize("return_code", [2, -9])
def test_wait_for_socket_reports_only_exit_and_controlled_category(
    tmp_path: Path,
    return_code: int,
) -> None:
    class ExitedProcess:
        def poll(self) -> int:
            return return_code

    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    log_handle.write(
        (
            "lcf-service: desktop transport setup failed; "
            "token=must-not-leak; /private/path-must-not-leak\n"
        ).encode("utf-8"),
    )

    try:
        with pytest.raises(
            build.BuildError,
            match=(
                r"^Frozen sidecar exited before its UDS became ready "
                rf"\(exit={return_code}; category=desktop-transport\)$"
            ),
        ) as failure:
            build._wait_for_socket(
                tmp_path / "missing.sock",
                ExitedProcess(),  # type: ignore[arg-type]
                log_handle,
                log_path,
                identity,
            )
    finally:
        log_handle.close()

    assert "must-not-leak" not in str(failure.value)
    assert "/private" not in str(failure.value)


@pytest.mark.parametrize("mutation", ["hardlink", "mode", "oversize", "owner"])
def test_frozen_start_failure_category_rejects_metadata_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    log_handle.write(b"original-log\n")
    if mutation == "hardlink":
        (tmp_path / "second-link.log").hardlink_to(log_path)
    elif mutation == "mode":
        log_path.chmod(0o640)
    elif mutation == "oversize":
        log_handle.write(b"x" * build.MAX_FROZEN_START_LOG_BYTES)
    else:
        owner = log_path.stat().st_uid
        monkeypatch.setattr(build.os, "geteuid", lambda: owner + 1)
    try:
        category = build._frozen_start_failure_category(
            log_handle,
            log_path,
            identity,
        )
    finally:
        log_handle.close()

    assert category == "log-unsafe"


def test_frozen_start_failure_category_rechecks_metadata_after_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    log_handle.write(b"original-log\n")
    original_read = build.os.read
    mutated = False

    def read_then_mutate(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        result = original_read(descriptor, size)
        if result and not mutated:
            mutated = True
            log_path.chmod(0o640)
        return result

    monkeypatch.setattr(build.os, "read", read_then_mutate)
    try:
        category = build._frozen_start_failure_category(
            log_handle,
            log_path,
            identity,
        )
    finally:
        log_handle.close()

    assert category == "log-changed"


def test_frozen_start_failure_category_rejects_path_replacement(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    log_handle.write(b"original-log\n")
    log_path.unlink()
    replacement = tmp_path / "replacement.log"
    replacement.write_text("secret-that-must-not-leak\n", encoding="utf-8")
    log_path.symlink_to(replacement)
    try:
        category = build._frozen_start_failure_category(
            log_handle,
            log_path,
            identity,
        )
    finally:
        log_handle.close()

    assert category == "log-changed"


def test_wait_for_socket_rechecks_process_after_socket_is_ready(
    tmp_path: Path,
) -> None:
    class ExitAtReadyProcess:
        def __init__(self) -> None:
            self.polls = 0

        def poll(self) -> int | None:
            self.polls += 1
            return None if self.polls == 1 else 2

    class ReadySocketPath:
        @staticmethod
        def lstat() -> os.stat_result:
            values = list((tmp_path / "sidecar.log").stat())
            values[0] = stat.S_IFSOCK | 0o600
            values[3] = 1
            values[4] = os.geteuid()
            return os.stat_result(values)

    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    log_handle.write(b"lcf-service: desktop transport setup failed\n")
    try:
        with pytest.raises(
            build.BuildError,
            match=r"exit=2; category=desktop-transport",
        ):
            build._wait_for_socket(
                ReadySocketPath(),  # type: ignore[arg-type]
                ExitAtReadyProcess(),  # type: ignore[arg-type]
                log_handle,
                log_path,
                identity,
            )
    finally:
        log_handle.close()


def test_wait_for_socket_rejects_a_socket_owned_by_another_identity(
    tmp_path: Path,
) -> None:
    class RunningProcess:
        @staticmethod
        def poll() -> None:
            return None

    class ForeignSocketPath:
        @staticmethod
        def lstat() -> os.stat_result:
            values = list((tmp_path / "sidecar.log").stat())
            values[0] = stat.S_IFSOCK | 0o600
            values[3] = 1
            values[4] = os.geteuid() + 1
            return os.stat_result(values)

    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    try:
        with pytest.raises(
            build.BuildError,
            match=r"^Frozen sidecar created an unsafe socket$",
        ):
            build._wait_for_socket(
                ForeignSocketPath(),  # type: ignore[arg-type]
                RunningProcess(),  # type: ignore[arg-type]
                log_handle,
                log_path,
                identity,
            )
    finally:
        log_handle.close()


def test_canonical_private_smoke_root_resolves_a_parent_alias(
    tmp_path: Path,
) -> None:
    physical_parent = tmp_path / "physical"
    physical_parent.mkdir(mode=0o700)
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(physical_parent, target_is_directory=True)
    lexical_root = alias_parent / "smoke"
    lexical_root.mkdir(mode=0o700)

    canonical = build._canonical_private_smoke_root(str(lexical_root))

    assert canonical == physical_parent / "smoke"
    assert canonical.resolve(strict=True) == canonical


def test_canonical_private_smoke_root_rejects_a_nonprivate_directory(
    tmp_path: Path,
) -> None:
    smoke_root = tmp_path / "smoke"
    smoke_root.mkdir(mode=0o700)
    smoke_root.chmod(0o755)

    with pytest.raises(
        build.BuildError,
        match=r"^Frozen smoke root is not a private canonical directory$",
    ):
        build._canonical_private_smoke_root(str(smoke_root))


def test_frozen_socket_paths_fit_the_canonical_macos_runtime_bound() -> None:
    from app.desktop_session import MAX_UDS_PATH_BYTES

    typical_root = Path(
        "/private/var/folders/zz/zyxvpxvq6csfxvn_n0000000000000/"
        "T/lcf-abcdefgh"
    )

    runtime, sidecar, broker = build._frozen_socket_paths(typical_root)

    assert runtime == typical_root / "r"
    assert sidecar == runtime / "s"
    assert broker == runtime / "b"
    assert build.MAX_FROZEN_UDS_PATH_BYTES == MAX_UDS_PATH_BYTES
    assert len(str(sidecar).encode("utf-8")) <= build.MAX_FROZEN_UDS_PATH_BYTES
    assert len(str(broker).encode("utf-8")) <= build.MAX_FROZEN_UDS_PATH_BYTES


def test_frozen_socket_paths_accept_exactly_the_runtime_bound() -> None:
    root = Path("/" + ("a" * (build.MAX_FROZEN_UDS_PATH_BYTES - 5)))

    _runtime, sidecar, broker = build._frozen_socket_paths(root)

    assert len(str(sidecar).encode("utf-8")) == build.MAX_FROZEN_UDS_PATH_BYTES
    assert len(str(broker).encode("utf-8")) == build.MAX_FROZEN_UDS_PATH_BYTES


def test_frozen_socket_paths_reject_more_than_the_runtime_bound() -> None:
    root = Path("/" + ("a" * (build.MAX_FROZEN_UDS_PATH_BYTES - 4)))

    with pytest.raises(
        build.BuildError,
        match=r"^Frozen smoke socket path exceeds the runtime bound$",
    ):
        build._frozen_socket_paths(root)


def _install_fake_uds_socket(
    monkeypatch: pytest.MonkeyPatch,
    response: bytes,
) -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = deque((response, b""))

        def settimeout(self, _timeout: float) -> None:
            pass

        def connect(self, _path: str) -> None:
            pass

        def sendall(self, _request: bytes) -> None:
            pass

        def recv(self, _size: int) -> bytes:
            return self.responses.popleft()

        def close(self) -> None:
            pass

    monkeypatch.setattr(build.socket, "socket", lambda *_args: FakeSocket())


@pytest.mark.parametrize(
    ("status", "payload", "expected_category"),
    [
        (503, {"detail": "token-must-not-leak"}, "payload=object"),
        (200, "token-must-not-leak", "payload=scalar"),
    ],
)
def test_frozen_uds_failure_reports_only_a_fixed_check_and_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    payload: Any,
    expected_category: str,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    response = (
        f"HTTP/1.1 {status} Synthetic\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode("ascii") + body
    _install_fake_uds_socket(monkeypatch, response)

    with pytest.raises(build.BuildError) as failure:
        build._http_json_over_uds(
            tmp_path / "sidecar.sock",
            "/api/desktop/handshake",
            check="handshake",
            token="A" * 43,
            launch_id="00000000-0000-4000-8000-000000000000",
        )

    message = str(failure.value)
    assert message == (
        "Frozen UDS response did not pass "
        f"(check=handshake; expected=200; observed={status}; "
        f"{expected_category})"
    )
    assert "must-not-leak" not in message


@pytest.mark.parametrize(
    "status_line",
    [
        b"HTTP/1.1 +200 OK",
        b"HTTP/1.1 0200 OK",
        b"HTTP/1.1 2_00 OK",
        b"BOGUS 200 OK",
        b"HTTP/1.0 200 OK",
    ],
)
def test_frozen_uds_rejects_a_noncanonical_status_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_line: bytes,
) -> None:
    response = status_line + b'\r\nContent-Length: 2\r\n\r\n{}'
    _install_fake_uds_socket(monkeypatch, response)

    with pytest.raises(
        build.BuildError,
        match=r"^Frozen UDS response is malformed \(check=handshake\)$",
    ):
        build._http_json_over_uds(
            tmp_path / "sidecar.sock",
            "/api/desktop/handshake",
            check="handshake",
            token="A" * 43,
            launch_id="00000000-0000-4000-8000-000000000000",
        )


def test_frozen_uds_contains_json_recursion_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"{}"
    response = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        + body
    )
    _install_fake_uds_socket(monkeypatch, response)

    def fail_json_loads(_value: str) -> Any:
        raise RecursionError("token/path-must-not-leak")

    monkeypatch.setattr(build.json, "loads", fail_json_loads)

    with pytest.raises(
        build.BuildError,
        match=r"^Frozen UDS response is malformed \(check=handshake\)$",
    ):
        build._http_json_over_uds(
            tmp_path / "sidecar.sock",
            "/api/desktop/handshake",
            check="handshake",
            token="A" * 43,
            launch_id="00000000-0000-4000-8000-000000000000",
        )


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("construct", "Frozen UDS request failed (check=handshake)"),
        ("settimeout", "Frozen UDS request failed (check=handshake)"),
        ("close", "Frozen UDS request cleanup failed (check=handshake)"),
    ],
)
def test_frozen_uds_contains_socket_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    expected: str,
) -> None:
    response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"

    class FailingSocket:
        def __init__(self) -> None:
            self.responses = deque((response, b""))

        def settimeout(self, _timeout: float) -> None:
            if stage == "settimeout":
                raise OSError("token/path-must-not-leak")

        def connect(self, _path: str) -> None:
            pass

        def sendall(self, _request: bytes) -> None:
            pass

        def recv(self, _size: int) -> bytes:
            return self.responses.popleft()

        def close(self) -> None:
            if stage == "close":
                raise OSError("token/path-must-not-leak")

    def create_socket(*_args: Any) -> FailingSocket:
        if stage == "construct":
            raise OSError("token/path-must-not-leak")
        return FailingSocket()

    monkeypatch.setattr(build.socket, "socket", create_socket)

    with pytest.raises(build.BuildError) as failure:
        build._http_json_over_uds(
            tmp_path / "sidecar.sock",
            "/api/desktop/handshake",
            check="handshake",
            token="A" * 43,
            launch_id="00000000-0000-4000-8000-000000000000",
        )

    assert str(failure.value) == expected
    assert "must-not-leak" not in str(failure.value)


def test_frozen_uds_rejects_a_non_ascii_request_path(tmp_path: Path) -> None:
    with pytest.raises(
        build.BuildError,
        match=r"^Frozen UDS request is invalid \(check=handshake\)$",
    ):
        build._http_json_over_uds(
            tmp_path / "sidecar.sock",
            "/api/秘密",
            check="handshake",
            token="A" * 43,
            launch_id="00000000-0000-4000-8000-000000000000",
        )


def test_frozen_uds_rejects_an_unknown_diagnostic_check(tmp_path: Path) -> None:
    with pytest.raises(
        build.BuildError,
        match=r"^Frozen UDS smoke requested an unknown check$",
    ):
        build._http_json_over_uds(
            tmp_path / "sidecar.sock",
            "/api/desktop/handshake",
            check="token-must-not-leak",
            token="A" * 43,
            launch_id="00000000-0000-4000-8000-000000000000",
        )


def _install_binding_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    install_root = (
        tmp_path / "Library" / "Frameworks" / "Python.framework" / "Versions" / "3.13"
    )
    interpreter = install_root / "bin" / "python3.13"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"synthetic interpreter")
    interpreter.chmod(0o755)
    toolchain = {
        "python": {
            "implementation": "CPython",
            "version": "3.13.14",
            "installRoot": str(install_root),
            "interpreterRelativePath": "bin/python3.13",
        }
    }
    observed = {
        "toolchain": toolchain,
        "implementation": "CPython",
        "version": "3.13.14",
        "system": "Darwin",
        "machine": "arm64",
        "base_prefix": install_root,
        "base_executable": interpreter,
        "executable": interpreter,
        "cache_tag": "cpython-313",
        "gil_disabled": False,
    }
    return install_root, interpreter, toolchain, observed


def test_install_root_fingerprint_requires_the_exact_reviewed_broken_links(
    tmp_path: Path,
) -> None:
    root = tmp_path / "python-root"
    framework = root / "Frameworks" / "Tcl.framework"
    framework.mkdir(parents=True)
    private_headers = framework / "PrivateHeaders"
    target = "Versions/Current/PrivateHeaders"
    private_headers.symlink_to(target)
    reviewed = {"Frameworks/Tcl.framework/PrivateHeaders": target}

    with pytest.raises(build.BuildError, match="unreviewed broken symlink"):
        build.fingerprint_install_root(root)

    digest = build.fingerprint_install_root(
        root,
        reviewed_broken_symlinks=reviewed,
    )
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")

    with pytest.raises(build.BuildError, match="set changed"):
        build.fingerprint_install_root(
            root,
            reviewed_broken_symlinks={
                **reviewed,
                "Frameworks/Tk.framework/PrivateHeaders": target,
            },
        )

    private_headers.unlink()
    (framework / target).mkdir(parents=True)
    private_headers.symlink_to(target)
    with pytest.raises(build.BuildError, match="set changed"):
        build.fingerprint_install_root(
            root,
            reviewed_broken_symlinks=reviewed,
        )


def test_install_root_fingerprint_rejects_reviewed_broken_link_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "python-root"
    root.mkdir()
    link = root / "escape"
    link.symlink_to("../outside")

    with pytest.raises(build.BuildError, match="unreviewed broken symlink"):
        build.fingerprint_install_root(
            root,
            reviewed_broken_symlinks={"escape": "../outside"},
        )


def test_install_root_binding_accepts_fully_injected_reviewed_interpreter(
    tmp_path: Path,
) -> None:
    install_root, _, _, observed = _install_binding_fixture(tmp_path)
    fingerprinted: list[Path] = []

    def fingerprint(path: Path) -> str:
        fingerprinted.append(path)
        return "a" * 64

    result = build.verify_python_install_binding(
        install_root,
        **observed,
        fingerprint=fingerprint,
    )

    assert result == "a" * 64
    assert fingerprinted == [install_root.resolve()]


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("implementation", "PyPy"),
        ("version", "3.13.13"),
        ("system", "Linux"),
        ("machine", "x86_64"),
        ("cache_tag", "cpython-312"),
        ("gil_disabled", True),
        ("base_prefix", "outside"),
        ("base_executable", "outside"),
        ("executable", "outside"),
    ],
)
def test_install_root_binding_rejects_mismatched_interpreter_evidence(
    tmp_path: Path,
    field: str,
    bad_value: object,
) -> None:
    install_root, _, _, observed = _install_binding_fixture(tmp_path)
    observed[field] = (
        tmp_path / "outside" / field if bad_value == "outside" else bad_value
    )

    with pytest.raises(build.BuildError, match="reviewed CPython"):
        build.verify_python_install_binding(
            install_root,
            **observed,
            fingerprint=lambda _: "a" * 64,
        )


def test_install_root_binding_rejects_alias_of_reviewed_root(
    tmp_path: Path,
) -> None:
    install_root, _, _, observed = _install_binding_fixture(tmp_path)
    alias = tmp_path / "python-root-alias"
    alias.symlink_to(install_root, target_is_directory=True)

    with pytest.raises(build.BuildError, match="framework path"):
        build.verify_python_install_binding(
            alias,
            **observed,
            fingerprint=lambda _: "a" * 64,
        )


def _native_fixture(
    tmp_path: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    root = tmp_path / "sidecar"
    internal = root / "_internal"
    internal.mkdir(parents=True)
    executable = root / audit.EXPECTED_EXECUTABLE
    executable.write_bytes(b"synthetic Mach-O policy fixture")
    executable.chmod(0o755)
    library = internal / "libfixture.dylib"
    library.write_bytes(b"synthetic dylib policy fixture")
    records = [
        {
            "path": audit.EXPECTED_EXECUTABLE,
            "architectures": ["arm64"],
            "dylibs": [
                "/usr/lib/libSystem.B.dylib",
                "@rpath/libfixture.dylib",
            ],
            "rpaths": ["@executable_path/_internal"],
            "platform": "macos",
            "minimumMacosVersion": "14.0",
            "codeSignature": "valid",
        },
        {
            "path": "_internal/libfixture.dylib",
            "architectures": ["arm64"],
            "dylibs": ["/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"],
            "rpaths": ["@loader_path"],
            "platform": "macos",
            "minimumMacosVersion": "11.0",
            "codeSignature": "valid",
            "installName": "@rpath/libfixture.dylib",
        },
    ]
    return root, records


def test_native_inventory_policy_accepts_arm64_closed_bundle(
    tmp_path: Path,
) -> None:
    root, records = _native_fixture(tmp_path)

    audit.validate_native_inventory(root, records)


def test_native_inventory_policy_accepts_three_part_target_equivalent_minimum(
    tmp_path: Path,
) -> None:
    root, records = _native_fixture(tmp_path)
    records[0]["minimumMacosVersion"] = "14.0.0"

    audit.validate_native_inventory(root, records)


@pytest.mark.parametrize(
    "field,bad_value,error",
    [
        ("architectures", ["arm64", "x86_64"], "arm64-only"),
        ("minimumMacosVersion", "14.1", "minimum macOS"),
        ("minimumMacosVersion", "14.0.1", "minimum macOS"),
        ("platform", "ios", "target macOS"),
        ("codeSignature", "invalid", "valid code signature"),
    ],
)
def test_native_inventory_policy_rejects_invalid_binary_contract(
    tmp_path: Path,
    field: str,
    bad_value: object,
    error: str,
) -> None:
    root, records = _native_fixture(tmp_path)
    records[0][field] = bad_value

    with pytest.raises(audit.AuditError, match=error):
        audit.validate_native_inventory(root, records)


@pytest.mark.parametrize(
    "dependency,error",
    [
        ("/opt/homebrew/lib/libcrypto.dylib", "Homebrew"),
        (
            "/Library/Frameworks/Python.framework/Versions/3.13/Python",
            "external Python framework",
        ),
    ],
)
def test_native_inventory_policy_rejects_host_runtime_dependency(
    tmp_path: Path,
    dependency: str,
    error: str,
) -> None:
    root, records = _native_fixture(tmp_path)
    records[0]["dylibs"] = [dependency]

    with pytest.raises(audit.AuditError, match=error):
        audit.validate_native_inventory(root, records)


def test_native_inventory_policy_rejects_unsafe_record_path(
    tmp_path: Path,
) -> None:
    root, records = _native_fixture(tmp_path)
    records[0]["path"] = "../outside"

    with pytest.raises(audit.AuditError, match="unsafe"):
        audit.validate_native_inventory(root, records)


def test_native_inventory_policy_rejects_escaping_rpath(
    tmp_path: Path,
) -> None:
    root, records = _native_fixture(tmp_path)
    records[0]["rpaths"] = ["@loader_path/../../outside"]
    records[0]["dylibs"] = ["/usr/lib/libSystem.B.dylib"]

    with pytest.raises(audit.AuditError, match="RPATH escapes"):
        audit.validate_native_inventory(root, records)


def test_native_inventory_policy_rejects_dependency_missing_from_native_set(
    tmp_path: Path,
) -> None:
    root, records = _native_fixture(tmp_path)

    with pytest.raises(audit.AuditError, match="absent from native inventory"):
        audit.validate_native_inventory(root, records[:1])


def test_native_inventory_policy_rejects_symlinked_native_file(
    tmp_path: Path,
) -> None:
    root, records = _native_fixture(tmp_path)
    library = root / "_internal" / "libfixture.dylib"
    real_library = root / "_internal" / "real-libfixture.dylib"
    library.rename(real_library)
    library.symlink_to(real_library.name)

    with pytest.raises(audit.AuditError, match="non-regular file"):
        audit.validate_native_inventory(root, records)


def _minimal_audited_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, list[dict[str, Any]]]:
    root = tmp_path / "audited-sidecar"
    root.mkdir()
    executable = root / audit.EXPECTED_EXECUTABLE
    executable.write_bytes(b"synthetic executable")
    executable.chmod(0o755)
    payload = root / "payload.dat"
    payload.write_bytes(b"reviewed payload")
    payload.chmod(0o644)
    native = [
        {
            "path": audit.EXPECTED_EXECUTABLE,
            "architectures": ["arm64"],
            "dylibs": ["/usr/lib/libSystem.B.dylib"],
            "rpaths": [],
            "platform": "macos",
            "minimumMacosVersion": "14.0",
            "codeSignature": "valid",
        }
    ]
    files = audit.build_file_inventory(root)
    manifest = {
        "files": files,
        "native": native,
        "components": [],
        "audit": {
            "status": "pass",
            "policyVersion": 1,
            "normalizedInventorySha256": audit.normalized_inventory_sha256(
                files,
                native,
            ),
            "frozenSmoke": copy.deepcopy(audit.EXPECTED_FROZEN_SMOKE),
        },
    }
    (root / audit.MANIFEST_NAME).write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "_validate_manifest_shape", lambda _: None)
    monkeypatch.setattr(audit, "_validate_components", lambda _root, _manifest: None)
    monkeypatch.setattr(audit, "_validate_sbom", lambda _root, _manifest: None)
    return root, native


def test_exact_inventory_audit_accepts_unchanged_linux_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, native = _minimal_audited_bundle(tmp_path, monkeypatch)

    summary = audit.audit_bundle(
        root,
        native_scanner=lambda _: copy.deepcopy(native),
    )

    assert summary == {"files": 2, "nativeFiles": 1, "components": 0}


@pytest.mark.parametrize("tamper", ["content", "mode", "unexpected-file"])
def test_exact_inventory_audit_rejects_payload_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    root, native = _minimal_audited_bundle(tmp_path, monkeypatch)
    payload = root / "payload.dat"
    if tamper == "content":
        payload.write_bytes(b"tampered payload")
    elif tamper == "mode":
        payload.chmod(0o600)
    else:
        (root / "injected.dat").write_bytes(b"unexpected")

    with pytest.raises(audit.AuditError, match="exact file inventory"):
        audit.audit_bundle(
            root,
            native_scanner=lambda _: copy.deepcopy(native),
        )


def test_exact_inventory_audit_rejects_normalized_digest_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, native = _minimal_audited_bundle(tmp_path, monkeypatch)
    manifest_path = root / audit.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["audit"]["normalizedInventorySha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(audit.AuditError, match="normalized inventory digest"):
        audit.audit_bundle(
            root,
            native_scanner=lambda _: copy.deepcopy(native),
        )


def test_file_inventory_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside.dat"
    outside.write_bytes(b"outside")
    root = tmp_path / "sidecar"
    root.mkdir()
    (root / "escape").symlink_to("../outside.dat")

    with pytest.raises(audit.AuditError, match="escapes the bundle"):
        audit.build_file_inventory(root)


def test_atomic_publish_swaps_verified_staging_without_a_gap(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    destination = tmp_path / "published"
    candidate.mkdir()
    destination.mkdir()
    (candidate / "state").write_text("new", encoding="utf-8")
    (destination / "state").write_text("old", encoding="utf-8")
    verified: list[Path] = []

    def verifier(path: Path) -> None:
        verified.append(path)
        assert (path / "state").read_text(encoding="utf-8") == "new"

    build.publish_staging(candidate, destination, verifier=verifier)

    assert verified == [candidate, destination]
    assert not candidate.exists()
    assert (destination / "state").read_text(encoding="utf-8") == "new"


def test_atomic_publish_rolls_back_when_post_swap_verification_fails(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    destination = tmp_path / "published"
    candidate.mkdir()
    destination.mkdir()
    (candidate / "state").write_text("new", encoding="utf-8")
    (destination / "state").write_text("old", encoding="utf-8")

    def verifier(path: Path) -> None:
        if path == destination:
            raise RuntimeError("simulated post-swap audit failure")
        assert (path / "state").read_text(encoding="utf-8") == "new"

    with pytest.raises(build.BuildError, match="post-swap audit"):
        build.publish_staging(candidate, destination, verifier=verifier)

    assert (candidate / "state").read_text(encoding="utf-8") == "new"
    assert (destination / "state").read_text(encoding="utf-8") == "old"


def test_manifest_schema_loads_with_reviewed_fail_closed_constants() -> None:
    schema = json.loads(audit.MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    toolchain = json.loads(build.TOOLCHAIN_LOCK.read_text(encoding="utf-8"))
    properties = schema["properties"]
    definitions = schema["$defs"]
    python_lock = toolchain["python"]
    distribution = python_lock["distribution"]

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert properties["schemaVersion"]["const"] == 1
    assert properties["kind"]["const"] == "local-context-forge-python-sidecar"
    assert properties["entrypoint"]["const"] == audit.EXPECTED_EXECUTABLE
    assert properties["target"]["properties"]["os"]["const"] == "darwin"
    assert properties["target"]["properties"]["architecture"]["const"] == "arm64"
    assert properties["build"]["properties"]["runnerImage"]["const"] == "macos-15"
    assert properties["build"]["properties"]["macosDeploymentTarget"]["const"] == "14.0"
    assert properties["build"]["properties"]["pyinstallerVersion"]["const"] == "6.21.0"

    provenance = definitions["pythonProvenance"]["properties"]
    assert provenance["implementation"]["const"] == python_lock["implementation"]
    assert provenance["version"]["const"] == python_lock["version"] == "3.13.14"
    assert provenance["installRoot"]["const"] == python_lock["installRoot"]
    assert python_lock["reviewedBrokenSymlinks"] == [
        {
            "path": "Frameworks/Tcl.framework/PrivateHeaders",
            "target": "Versions/Current/PrivateHeaders",
        },
        {
            "path": "Frameworks/Tk.framework/PrivateHeaders",
            "target": "Versions/Current/PrivateHeaders",
        },
    ]
    for key in (
        "provider",
        "releaseTag",
        "archiveName",
        "archiveSource",
        "archiveSha256",
        "installerPackageName",
        "installerPackageSha256",
        "hashManifestName",
        "hashManifestSource",
        "hashManifestSha256",
    ):
        assert provenance[key]["const"] == distribution[key]

    native = definitions["nativeInventoryEntry"]["properties"]
    assert native["architectures"]["const"] == ["arm64"]
    assert native["platform"]["const"] == "macos"
    assert native["codeSignature"]["const"] == "valid"
    frozen = properties["audit"]["properties"]["frozenSmoke"]["properties"]
    assert frozen["status"]["const"] == "pass"
    assert frozen["pathTrap"]["const"] is True
    assert frozen["checks"]["const"] == audit.EXPECTED_FROZEN_SMOKE["checks"]


def test_frozen_smoke_source_fixture_is_a_real_dulwich_repository(
    tmp_path: Path,
) -> None:
    from dulwich.repo import Repo

    repository = tmp_path / "source-root" / "fixture"
    build._create_smoke_source_repository(
        repository,
        source_date_epoch=1_700_000_000,
    )

    opened = Repo(repository)
    try:
        assert len(opened.head()) == 40
        assert set(opened.open_index()) == {
            b"README.md",
            b"src/widget.py",
        }
    finally:
        opened.close()
    assert b"build_widget" in (repository / "src" / "widget.py").read_bytes()


class _BrokerConnectionFixture:
    def __init__(self, request: bytes) -> None:
        self.request = request
        self.offset = 0
        self.responses: list[bytes] = []

    def __enter__(self) -> _BrokerConnectionFixture:
        return self

    def __exit__(self, *_arguments: object) -> None:
        return None

    def settimeout(self, _timeout: float) -> None:
        return None

    def recv(self, maximum: int) -> bytes:
        result = self.request[self.offset : self.offset + maximum]
        self.offset += len(result)
        return result

    def sendall(self, payload: bytes) -> None:
        self.responses.append(payload)


class _BrokerListenerFixture:
    def __init__(
        self,
        connection: _BrokerConnectionFixture,
        stop: Any,
    ) -> None:
        self.connection = connection
        self.stop = stop
        self.accepted = False

    def settimeout(self, _timeout: float) -> None:
        return None

    def accept(self) -> tuple[_BrokerConnectionFixture, None]:
        if not self.accepted:
            self.accepted = True
            return self.connection, None
        self.stop.set()
        raise OSError("fixture complete")


def _broker_request(*, capability: str, protocol: str = "1.1") -> bytes:
    payload = b'{"revision":4,"collections":[]}'
    deadline = int(time.time() * 1000) + 60_000
    return (
        b"POST /reconcile HTTP/1.1\r\n"
        b"Accept: application/json\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(payload)}\r\n".encode("ascii")
        + f"Authorization: Bearer {capability}\r\n".encode("ascii")
        + f"X-LCF-Protocol-Version: {protocol}\r\n".encode("ascii")
        + b"X-LCF-Launch-Id: 663e210a-f7e0-4e15-826a-25c3ae657eeb\r\n"
        + b"X-LCF-Request-Id: 13d47b32-9ef7-4ab9-8097-5a4568d43e30\r\n"
        + f"X-LCF-Deadline-Ms: {deadline}\r\n".encode("ascii")
        + b"\r\n"
        + payload
    )


def test_frozen_smoke_broker_accepts_only_capability_scoped_reconcile() -> None:
    import threading

    capability = "a" * 43
    stop = threading.Event()
    connection = _BrokerConnectionFixture(
        _broker_request(capability=capability)
    )
    listener = _BrokerListenerFixture(connection, stop)
    requests: deque[dict[str, Any]] = deque()
    failures: deque[str] = deque()

    build._serve_smoke_broker(
        listener,  # type: ignore[arg-type]
        capability=capability,
        launch_id="663e210a-f7e0-4e15-826a-25c3ae657eeb",
        protocol="1.1",
        stop=stop,
        requests=requests,
        failures=failures,
    )

    assert not failures
    assert list(requests) == [
        {
            "endpoint": "/reconcile",
            "revision": 4,
            "collections": 0,
        }
    ]
    assert connection.responses
    assert connection.responses[0].startswith(b"HTTP/1.1 200 OK\r\n")


def test_frozen_smoke_broker_rejects_wrong_capability() -> None:
    import threading

    stop = threading.Event()
    connection = _BrokerConnectionFixture(
        _broker_request(capability="b" * 43)
    )
    listener = _BrokerListenerFixture(connection, stop)
    requests: deque[dict[str, Any]] = deque()
    failures: deque[str] = deque()

    build._serve_smoke_broker(
        listener,  # type: ignore[arg-type]
        capability="a" * 43,
        launch_id="663e210a-f7e0-4e15-826a-25c3ae657eeb",
        protocol="1.1",
        stop=stop,
        requests=requests,
        failures=failures,
    )

    assert list(failures) == ["request"]
    assert not requests
    assert connection.responses
    assert connection.responses[0].startswith(
        b"HTTP/1.1 400 Bad Request\r\n"
    )


def test_frozen_smoke_broker_rejects_general_desktop_protocol() -> None:
    import threading

    capability = "a" * 43
    stop = threading.Event()
    connection = _BrokerConnectionFixture(
        _broker_request(capability=capability, protocol="1.0")
    )
    listener = _BrokerListenerFixture(connection, stop)
    requests: deque[dict[str, Any]] = deque()
    failures: deque[str] = deque()

    build._serve_smoke_broker(
        listener,  # type: ignore[arg-type]
        capability=capability,
        launch_id="663e210a-f7e0-4e15-826a-25c3ae657eeb",
        protocol="1.1",
        stop=stop,
        requests=requests,
        failures=failures,
    )

    assert list(failures) == ["request"]
    assert not requests
    assert connection.responses
    assert connection.responses[0].startswith(
        b"HTTP/1.1 400 Bad Request\r\n"
    )


def test_frozen_smoke_selects_distinct_retrieval_protocol() -> None:
    versions = json.loads(build.VERSION_FILE.read_text(encoding="utf-8"))

    assert versions["desktopProtocol"] == {"major": 1, "minor": 0}
    assert versions["desktopRetrievalProtocol"] == {"major": 1, "minor": 1}
    assert build._desktop_retrieval_protocol(versions) == "1.1"

    without_retrieval = copy.deepcopy(versions)
    del without_retrieval["desktopRetrievalProtocol"]
    with pytest.raises(build.BuildError, match="desktop retrieval protocol"):
        build._desktop_retrieval_protocol(without_retrieval)


def test_selected_source_commit_prefers_exact_checkout_input() -> None:
    exact_source = "a" * 40
    synthetic_merge = "b" * 40

    assert build._selected_source_commit(
        {
            "LCF_SOURCE_SHA": exact_source,
            "GITHUB_SHA": synthetic_merge,
        }
    ) == exact_source
    assert build._selected_source_commit(
        {
            "LCF_SOURCE_SHA": "",
            "GITHUB_SHA": synthetic_merge,
        }
    ) == synthetic_merge


def test_selected_source_commit_rejects_invalid_explicit_input() -> None:
    with pytest.raises(build.BuildError, match="LCF_SOURCE_SHA"):
        build._selected_source_commit(
            {
                "LCF_SOURCE_SHA": "not-a-commit",
                "GITHUB_SHA": "b" * 40,
            }
        )


def test_release_environment_reads_the_locked_python_install_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    epoch = 1_800_000_000
    install_root = "/Library/Frameworks/Python.framework/Versions/3.13"
    environment = {
        "GITHUB_SHA": commit,
        "LCF_SOURCE_DATE_EPOCH": str(epoch),
        "ImageVersion": "20260729.1.0",
        "LCF_PYTHON_DISTRIBUTION_ARCHIVE": "/tmp/python.tar.gz",
        "LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST": "/tmp/hashes.sha256",
        "LCF_PYTHON_INSTALL_ROOT": install_root,
        "GITHUB_ACTIONS": "true",
        "RUNNER_OS": "macOS",
        "RUNNER_ARCH": "ARM64",
        "ImageOS": "macos15",
    }
    toolchain = {
        "requiredCiInputs": [
            "GITHUB_SHA",
            "LCF_SOURCE_DATE_EPOCH",
            "ImageVersion",
            "LCF_PYTHON_DISTRIBUTION_ARCHIVE",
            "LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST",
            "LCF_PYTHON_INSTALL_ROOT",
        ],
        "target": {
            "runnerLabel": "macos-15",
            "deploymentTarget": "14.0",
        },
        "python": {"installRoot": install_root},
    }

    monkeypatch.setattr(build.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(build.platform, "machine", lambda: "arm64")

    def native_output(command: tuple[str, ...], **_: Any) -> str:
        if command[:2] == ("/usr/sbin/sysctl", "-in"):
            return "0"
        if command == ("/usr/bin/xcodebuild", "-version"):
            return "Xcode 16.4\nBuild version 16F6"
        if command[:3] == ("/usr/bin/xcrun", "--sdk", "macosx"):
            return "15.5"
        raise AssertionError(command)

    def git_output(*arguments: str) -> str:
        if arguments == ("rev-parse", "HEAD"):
            return commit
        if arguments == ("status", "--porcelain", "--untracked-files=all"):
            return ""
        if arguments == ("show", "-s", "--format=%ct", "HEAD"):
            return str(epoch)
        raise AssertionError(arguments)

    monkeypatch.setattr(build, "_run_checked", native_output)
    monkeypatch.setattr(build, "_git_output", git_output)

    release = build.validate_release_environment(environment, toolchain)

    assert release["repositoryCommit"] == commit
    assert release["runnerImage"] == "macos-15"
    assert release["xcodeVersion"] == "16.4"
    assert release["sdkVersion"] == "15.5"
