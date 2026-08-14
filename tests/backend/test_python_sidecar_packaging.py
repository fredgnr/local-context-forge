from __future__ import annotations

import copy
import errno
import hashlib
import inspect
import io
import json
import os
import plistlib
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time
import types
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import audit_python_sidecar as audit  # noqa: E402
import bootstrap_python_sidecar as bootstrap  # noqa: E402
import build_python_sidecar as build  # noqa: E402


INSTALLER_NAME = "python-3.13.14-macos11.pkg"
ARCHIVE_NAME = "python-3.13.14-darwin-arm64.tar.gz"
BASE_ARCHIVE_PAYLOADS = {
    "setup.sh": b"#!/bin/sh\nexit 0\n",
    "build_output.txt": b"",
    INSTALLER_NAME: b"synthetic-python-installer-package",
}
FRAMEWORK_COMPONENT_FIXTURE = copy.deepcopy(
    json.loads(
        (
            PROJECT_ROOT
            / "backend"
            / "packaging"
            / "python-sidecar-toolchain.lock.json"
        ).read_text(encoding="utf-8")
    )["python"]["distribution"]["frameworkComponent"]
)
ArchiveEntry = tuple[str, bytes, str]


def _run_signal_probe(script: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Traceback" not in completed.stderr
    assert completed.stderr == ""
    return json.loads(completed.stdout)


def _cleanup_signal_numbers() -> tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            (
                signal.SIGINT,
                signal.SIGTERM,
                getattr(signal, "SIGHUP", signal.SIGTERM),
            )
        )
    )


def test_held_cwd_exec_runner_uses_renamed_inode_and_exact_fd_allowlist(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    backend = source / "backend"
    backend.mkdir(parents=True)
    (backend / "marker").write_text("held", encoding="ascii")
    cwd_descriptor = os.open(
        backend,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    held_identity = os.fstat(cwd_descriptor)
    held = tmp_path / "held-source"
    source.rename(held)
    replacement = source / "backend"
    replacement.mkdir(parents=True)
    (replacement / "marker").write_text("replacement", encoding="ascii")
    keep_path = tmp_path / "keep"
    keep_path.write_text("keep", encoding="ascii")
    denied_path = tmp_path / "denied"
    denied_path.write_text("denied", encoding="ascii")
    keep_descriptor = os.open(keep_path, os.O_RDONLY | os.O_CLOEXEC)
    denied_descriptor = os.open(denied_path, os.O_RDONLY | os.O_CLOEXEC)
    target = r"""
import json
import os
import signal
import sys

def opened(raw):
    try:
        os.fstat(int(raw))
    except OSError:
        return False
    return True

cleanup = tuple(map(int, sys.argv[6:]))
mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
cwd = os.stat(".", follow_symlinks=False)
print(json.dumps({
    "cwd": open("marker", encoding="ascii").read(),
    "cwdIdentity": (cwd.st_dev, cwd.st_ino) == tuple(map(int, sys.argv[4:6])),
    "cwdFdOpen": opened(sys.argv[1]),
    "keepFdOpen": opened(sys.argv[2]),
    "deniedFdOpen": opened(sys.argv[3]),
    "cleanupBlocked": any(item in mask for item in cleanup),
    # CPython installs its own SIGINT handler during target startup; TERM/HUP
    # remain a direct observation of the launcher's disposition reset.
    "cleanupDefault": all(
        signal.getsignal(item) == signal.SIG_DFL
        for item in cleanup
        if item != signal.SIGINT
    ),
}, sort_keys=True))
""".strip()
    cleanup_signals = _cleanup_signal_numbers()
    command, inherited, _identity = bootstrap._held_cwd_exec_command(
        Path(sys.executable),
        (
            sys.executable,
            "-I",
            "-c",
            target,
            str(cwd_descriptor),
            str(keep_descriptor),
            str(denied_descriptor),
            str(held_identity.st_dev),
            str(held_identity.st_ino),
            *(str(item) for item in cleanup_signals),
        ),
        cwd_descriptor=cwd_descriptor,
        keep_fds=(keep_descriptor,),
    )
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set(cleanup_signals))
    previous_handlers = {item: signal.getsignal(item) for item in cleanup_signals}
    try:
        for item in cleanup_signals:
            signal.signal(item, signal.SIG_IGN)
        completed = subprocess.run(
            command,
            cwd="/",
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=(*inherited, denied_descriptor),
            close_fds=True,
            start_new_session=True,
            timeout=20,
            check=False,
        )
    finally:
        for item, handler in previous_handlers.items():
            signal.signal(item, handler)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        os.close(denied_descriptor)
        os.close(keep_descriptor)
        os.close(cwd_descriptor)

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "cleanupBlocked": False,
        "cleanupDefault": True,
        "cwd": "held",
        "cwdFdOpen": False,
        "cwdIdentity": True,
        "deniedFdOpen": False,
        "keepFdOpen": True,
    }


@pytest.mark.parametrize("stop_signal", _cleanup_signal_numbers())
def test_held_cwd_exec_runner_restores_real_signal_termination(
    tmp_path: Path,
    stop_signal: int,
) -> None:
    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    command, inherited, _identity = bootstrap._held_cwd_exec_command(
        Path(sys.executable),
        ("/bin/sleep", "30"),
        cwd_descriptor=cwd_descriptor,
        keep_fds=(),
    )
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {stop_signal})
    previous_handler = signal.getsignal(stop_signal)
    process: subprocess.Popen[str] | None = None
    try:
        signal.signal(stop_signal, signal.SIG_IGN)
        process = subprocess.Popen(
            command,
            cwd="/",
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=inherited,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        signal.signal(stop_signal, previous_handler)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    try:
        time.sleep(0.2)
        assert process is not None
        assert process.poll() is None
        os.kill(process.pid, stop_signal)
        assert process.wait(timeout=5) == -stop_signal
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(cwd_descriptor)


def test_held_cwd_exec_runner_rejects_bad_cwd_and_target_drift(
    tmp_path: Path,
) -> None:
    regular = tmp_path / "regular"
    regular.write_text("not-a-directory", encoding="ascii")
    regular_descriptor = os.open(regular, os.O_RDONLY | os.O_CLOEXEC)
    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="cwd capability is unsafe",
    ):
        bootstrap._held_cwd_exec_command(
            Path(sys.executable),
            (sys.executable, "-c", "pass"),
            cwd_descriptor=regular_descriptor,
            keep_fds=(),
        )
    os.close(regular_descriptor)
    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="cwd capability is unavailable",
    ):
        bootstrap._held_cwd_exec_command(
            Path(sys.executable),
            (sys.executable, "-c", "pass"),
            cwd_descriptor=regular_descriptor,
            keep_fds=(),
        )

    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    target = tmp_path / "target"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
    target.chmod(0o700)
    command, inherited, _identity = bootstrap._held_cwd_exec_command(
        Path(sys.executable),
        (str(target),),
        cwd_descriptor=cwd_descriptor,
        keep_fds=(),
    )
    mismatched = list(command)
    mismatched[7] = str(int(mismatched[7]) + 1)
    mismatch_completed = subprocess.run(
        mismatched,
        cwd="/",
        env=dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        pass_fds=inherited,
        close_fds=True,
        timeout=20,
        check=False,
    )
    assert mismatch_completed.returncode == 126
    assert mismatch_completed.stdout == ""
    assert mismatch_completed.stderr == (
        "lcf-held-cwd-exec: stage=cwd-fd "
        f"errno={errno.ENOTDIR}\n"
    )
    target.write_text("#!/bin/sh\nexit 9\n# changed\n", encoding="ascii")
    target.chmod(0o700)
    try:
        completed = subprocess.run(
            command,
            cwd="/",
            env=dict(os.environ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=inherited,
            close_fds=True,
            timeout=20,
            check=False,
        )
    finally:
        os.close(cwd_descriptor)
    assert completed.returncode == 126
    assert completed.stdout == ""
    assert completed.stderr == "lcf-held-cwd-exec: stage=target errno=0\n"


def test_run_owned_process_uses_fixed_held_cwd_spawn_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    observed: dict[str, Any] = {}

    class CheckedPopen:
        pid = 424242
        returncode = 0

        def __init__(self, arguments: list[str], **kwargs: Any) -> None:
            observed["arguments"] = arguments
            observed.update(kwargs)

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            observed["timeout"] = timeout
            return "ok", ""

    monkeypatch.setattr(bootstrap.subprocess, "Popen", CheckedPopen)
    monkeypatch.setattr(
        bootstrap,
        "_communicate_bounded",
        lambda _process, **_kwargs: ("ok", ""),
    )
    monkeypatch.setattr(build, "_process_group_exists", lambda _pid: False)
    try:
        assert bootstrap._run_owned_process(
            (sys.executable, "-I", "-c", "print('ok')"),
            cwd=tmp_path,
            environment={"PATH": "/usr/bin:/bin"},
            pass_fds=(),
            timeout=30,
            label="held cwd probe",
            build=build,
            cwd_descriptor=cwd_descriptor,
            launcher_python=Path(sys.executable),
        ) == "ok"
    finally:
        os.close(cwd_descriptor)

    assert observed["arguments"][:5] == [
        sys.executable,
        "-I",
        "-S",
        "-c",
        bootstrap.HELD_CWD_EXEC_RUNNER,
    ]
    assert observed["cwd"] == Path("/")
    assert observed["close_fds"] is True
    assert observed["start_new_session"] is True
    assert "preexec_fn" not in observed
    assert observed["pass_fds"] == (cwd_descriptor,)


def test_run_owned_process_check_false_returns_bounded_completed_process(
    tmp_path: Path,
) -> None:
    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    arguments = (
        sys.executable,
        "-I",
        "-c",
        "import os,sys; os.write(1,b'out'); os.write(2,b'err'); sys.exit(7)",
    )
    try:
        completed = bootstrap._run_owned_process(
            arguments,
            cwd=tmp_path,
            environment={"PATH": "/usr/bin:/bin"},
            pass_fds=(),
            timeout=30,
            label="completed-process probe",
            build=build,
            cwd_descriptor=cwd_descriptor,
            launcher_python=Path(sys.executable),
            check=False,
        )
    finally:
        os.close(cwd_descriptor)

    assert isinstance(completed, subprocess.CompletedProcess)
    assert completed.args == arguments
    assert completed.returncode == 7
    assert completed.stdout == "out"
    assert completed.stderr == "err"


def test_owned_process_allows_owned_content_in_a_stable_keep_directory(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    producer = tmp_path / "producer"
    cwd.mkdir()
    producer.mkdir(mode=0o700)
    cwd_descriptor = os.open(
        cwd,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    producer_descriptor = os.open(
        producer,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    child = (
        "import os,sys;"
        "fd=int(sys.argv[1]);"
        "created=os.open('created',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=fd);"
        "os.write(created,b'owned');os.close(created)"
    )
    try:
        assert bootstrap._run_owned_process(
            (sys.executable, "-I", "-c", child, str(producer_descriptor)),
            cwd=cwd,
            environment={"PATH": "/usr/bin:/bin"},
            pass_fds=(producer_descriptor,),
            timeout=30,
            label="mutable keep-fd probe",
            build=build,
            cwd_descriptor=cwd_descriptor,
            launcher_python=Path(sys.executable),
        ) == ""
    finally:
        os.close(producer_descriptor)
        os.close(cwd_descriptor)

    assert (producer / "created").read_bytes() == b"owned"


def test_path_capability_exec_runner_rejects_replaced_child_input(
    tmp_path: Path,
) -> None:
    held = tmp_path / "input"
    held.write_text("reviewed", encoding="utf-8")
    descriptor = os.open(held, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    identity = bootstrap._identity(os.fstat(descriptor))
    actual = (
        sys.executable,
        "-I",
        "-c",
        "from pathlib import Path;print(Path('input').read_text())",
    )
    effective = (
        sys.executable,
        "-I",
        "-c",
        bootstrap.PATH_CAPABILITY_EXEC_RUNNER,
        "1",
        str(descriptor),
        "relative",
        *(str(value) for value in identity),
        "input",
        *(str(value) for value in bootstrap._exec_target_identity(Path(actual[0]))),
        *actual,
    )
    held.rename(tmp_path / "reviewed-input")
    held.write_text("replacement", encoding="utf-8")
    command, inherited, _exec_identity = bootstrap._held_cwd_exec_command(
        Path(sys.executable),
        effective,
        cwd_descriptor=cwd_descriptor,
        keep_fds=(descriptor,),
    )
    try:
        completed = subprocess.run(
            command,
            cwd="/",
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=inherited,
            close_fds=True,
            timeout=20,
            check=False,
        )
    finally:
        os.close(descriptor)
        os.close(cwd_descriptor)

    assert completed.returncode == 126
    assert completed.stdout == ""
    assert completed.stderr == "lcf-path-capability-exec: stage=path-name errno=0\n"


def test_owned_process_rejects_path_capability_without_held_cwd(
    tmp_path: Path,
) -> None:
    target = tmp_path / "input"
    target.write_text("reviewed", encoding="utf-8")
    descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match=r"requires a held cwd",
        ):
            bootstrap._run_owned_process(
                (sys.executable, "-I", "-c", "pass"),
                cwd=tmp_path,
                environment={"PATH": "/usr/bin:/bin"},
                pass_fds=(),
                timeout=30,
                label="path capability probe",
                build=build,
                path_capabilities=((descriptor, "input", False),),
            )
    finally:
        os.close(descriptor)


def test_owned_process_rejects_regular_keep_fd_metadata_drift(
    tmp_path: Path,
) -> None:
    target = tmp_path / "immutable"
    target.write_bytes(b"reviewed")
    descriptor = os.open(target, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    child = "import os,sys;os.write(int(sys.argv[1]),b'!')"
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match=r"owned process state could not be verified",
        ):
            bootstrap._run_owned_process(
                (sys.executable, "-I", "-c", child, str(descriptor)),
                cwd=tmp_path,
                environment={"PATH": "/usr/bin:/bin"},
                pass_fds=(descriptor,),
                timeout=30,
                label="immutable keep-fd probe",
                build=build,
                cwd_descriptor=cwd_descriptor,
                launcher_python=Path(sys.executable),
            )
    finally:
        os.close(descriptor)
        os.close(cwd_descriptor)


def test_held_executable_rejects_launcher_name_replacement(
    tmp_path: Path,
) -> None:
    executable_payload = Path(sys.executable).read_bytes()
    launcher = tmp_path / "launcher"
    replacement = tmp_path / "replacement"
    launcher.write_bytes(executable_payload)
    replacement.write_bytes(executable_payload)
    launcher.chmod(0o700)
    replacement.chmod(0o700)

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="fixture launcher changed",
    ):
        with bootstrap._held_executable(
            launcher,
            error_message="fixture launcher changed",
        ):
            os.replace(replacement, launcher)


def test_held_executable_still_rejects_group_writable_framework_launcher(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "python3.13"
    launcher.write_bytes(Path(sys.executable).read_bytes())
    launcher.chmod(0o775)

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="fixture launcher is unsafe",
    ):
        with bootstrap._held_executable(
            launcher,
            error_message="fixture launcher is unsafe",
        ):
            raise AssertionError("group-writable launcher was entered")


def test_held_executable_rejects_hardlink_count_drift(
    tmp_path: Path,
) -> None:
    executable_payload = Path(sys.executable).read_bytes()
    launcher = tmp_path / "launcher"
    hidden = tmp_path / "hidden-launcher"
    launcher.write_bytes(executable_payload)
    launcher.chmod(0o700)

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="fixture launcher changed",
    ):
        with bootstrap._held_executable(
            launcher,
            error_message="fixture launcher changed",
        ):
            os.link(launcher, hidden)


def test_held_executable_terminal_revalidation_rejects_bytes_drift(
    tmp_path: Path,
) -> None:
    executable_payload = Path(sys.executable).read_bytes()
    launcher = tmp_path / "launcher"
    launcher.write_bytes(executable_payload)
    launcher.chmod(0o700)
    writable = os.open(launcher, os.O_WRONLY | os.O_CLOEXEC)
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="fixture launcher changed",
        ):
            with bootstrap._held_executable(
                launcher,
                error_message="fixture launcher changed",
            ):
                os.pwrite(writable, b"X", 0)
    finally:
        os.close(writable)


def test_held_executable_rejects_privileged_mode_drift(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "launcher"
    launcher.write_bytes(Path(sys.executable).read_bytes())
    launcher.chmod(0o700)

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="fixture launcher changed",
    ):
        with bootstrap._held_executable(
            launcher,
            error_message="fixture launcher changed",
        ):
            launcher.chmod(0o4700)


def test_held_executable_combines_primary_and_terminal_failure(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "launcher"
    launcher.write_bytes(Path(sys.executable).read_bytes())
    launcher.chmod(0o700)

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="terminal capability could not be verified",
    ) as observed:
        with bootstrap._held_executable(
            launcher,
            error_message="fixture launcher changed",
        ) as binding:
            os.fchmod(binding.descriptor, 0o500)
            raise RuntimeError("primary fixture failure")
    assert isinstance(observed.value.__cause__, RuntimeError)


def test_inner_build_fixed_diagnostic_is_bounded_and_does_not_leak_stderr(
    tmp_path: Path,
) -> None:
    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    secret = "token=/private/unreviewed/secret"
    child = (
        "import os,sys;"
        f"fd=int(os.environ[{bootstrap.INNER_BUILD_DIAGNOSTIC_FD_ENV!r}]);"
        "os.write(fd,b'lcf-inner-build: primary=source-materialize "
        "cleanup=build-root-quarantine\\n');"
        f"os.write(2,{secret.encode()!r});"
        "sys.exit(2)"
    )
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match=(
                r"category=inner-build; primary=source-materialize; "
                r"cleanup=build-root-quarantine"
            ),
        ) as failure:
            bootstrap._run_owned_process(
                (sys.executable, "-I", "-c", child),
                cwd=tmp_path,
                environment={"PATH": "/usr/bin:/bin"},
                pass_fds=(),
                timeout=30,
                label="Exact Python sidecar inner build",
                build=build,
                cwd_descriptor=cwd_descriptor,
                launcher_python=Path(sys.executable),
                inner_build_diagnostic=True,
            )
    finally:
        os.close(cwd_descriptor)

    assert secret not in str(failure.value)
    assert "/private" not in str(failure.value)


def test_inner_build_rejects_unreviewed_diagnostic_enum_without_leaking(
    tmp_path: Path,
) -> None:
    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    child = (
        "import os,sys;"
        f"fd=int(os.environ[{bootstrap.INNER_BUILD_DIAGNOSTIC_FD_ENV!r}]);"
        "os.write(fd,b'lcf-inner-build: primary=secret-path "
        "cleanup=none\\n');"
        "os.write(2,b'/private/token');"
        "sys.exit(2)"
    )
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match=r"category=unclassified",
        ) as failure:
            bootstrap._run_owned_process(
                (sys.executable, "-I", "-c", child),
                cwd=tmp_path,
                environment={"PATH": "/usr/bin:/bin"},
                pass_fds=(),
                timeout=30,
                label="Exact Python sidecar inner build",
                build=build,
                cwd_descriptor=cwd_descriptor,
                launcher_python=Path(sys.executable),
                inner_build_diagnostic=True,
            )
    finally:
        os.close(cwd_descriptor)

    assert "/private" not in str(failure.value)
    assert "token" not in str(failure.value)


def test_inner_build_diagnostic_writer_emits_only_fixed_enums(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, writer = os.pipe()
    monkeypatch.setenv(build.INNER_BUILD_DIAGNOSTIC_FD_ENV, str(writer))
    failure = build.BuildError(
        "token=/private/unreviewed/secret",
        primary_category="source-materialize",
        cleanup_category="build-root-quarantine",
    )
    try:
        build._write_inner_build_diagnostic(failure)
        payload = os.read(reader, 256)
    finally:
        os.close(reader)

    assert payload == (
        b"lcf-inner-build: primary=source-materialize "
        b"cleanup=build-root-quarantine\n"
    )
    assert b"token" not in payload
    assert b"private" not in payload
    with pytest.raises(OSError):
        os.fstat(writer)


def test_inner_build_diagnostic_reader_rejects_a_retained_writer_without_blocking(
) -> None:
    reader, writer = os.pipe()
    os.write(
        writer,
        b"lcf-inner-build: primary=source-materialize cleanup=none\n",
    )
    started = time.monotonic()
    try:
        assert bootstrap._read_inner_build_diagnostic(reader) is None
    finally:
        os.close(writer)

    assert time.monotonic() - started < 1


def test_owned_process_output_bound_terminates_without_echoing_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    monkeypatch.setattr(bootstrap, "MAX_SUBPROCESS_OUTPUT_BYTES", 128)
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match=r"output exceeds its bound",
        ) as failure:
            bootstrap._run_owned_process(
                (
                    sys.executable,
                    "-I",
                    "-c",
                    "import os; os.write(1, b'private-token/' * 64)",
                ),
                cwd=tmp_path,
                environment={"PATH": "/usr/bin:/bin"},
                pass_fds=(),
                timeout=30,
                label="bounded output probe",
                build=build,
                cwd_descriptor=cwd_descriptor,
                launcher_python=Path(sys.executable),
            )
    finally:
        os.close(cwd_descriptor)

    assert "private-token" not in str(failure.value)


def test_owned_process_timeout_stops_and_reaps_the_exact_group(
    tmp_path: Path,
) -> None:
    cwd_descriptor = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    started = time.monotonic()
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match=r"^timeout probe failed$",
        ):
            bootstrap._run_owned_process(
                ("/bin/sleep", "30"),
                cwd=tmp_path,
                environment={"PATH": "/usr/bin:/bin"},
                pass_fds=(),
                timeout=1,
                label="timeout probe",
                build=build,
                cwd_descriptor=cwd_descriptor,
                launcher_python=Path(sys.executable),
            )
    finally:
        os.close(cwd_descriptor)

    assert time.monotonic() - started < 8


def test_process_group_cleanup_reaps_an_already_exited_leader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float | None] = []

    class ExitedProcess:
        pid = 424242

        def wait(self, timeout: float | None = None) -> int:
            waits.append(timeout)
            return 0

    monkeypatch.setattr(
        build.os,
        "killpg",
        lambda _process_group, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )
    monkeypatch.setattr(build, "_process_group_exists", lambda _group: False)

    build._terminate_owned_process_group(
        ExitedProcess(),
        error_message="process group did not stop",
    )

    assert waits


def test_exact_git_archive_pipe_reader_has_a_total_deadline() -> None:
    reader_descriptor, writer_descriptor = os.pipe()
    stream = os.fdopen(reader_descriptor, "rb", buffering=0)
    reader = build._DeadlinePipeReader(
        stream,
        arguments=("/usr/bin/git", "archive"),
        timeout=0.05,
    )
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            reader.read(512)
    finally:
        reader.close()
        stream.close()
        os.close(writer_descriptor)

    assert time.monotonic() - started < 1


def test_darwin_external_process_contract_has_no_fd_child_lookup_or_unsafe_spawn(
) -> None:
    runner = bootstrap.HELD_CWD_EXEC_RUNNER
    assert "os.fchdir(cwd_fd)" in runner
    assert "os.set_inheritable(cwd_fd, False)" in runner
    assert "os.execve(target, target_arguments, dict(os.environ))" in runner
    assert 'os.listdir("/dev/fd")' in runner
    assert "/dev/fd/" not in runner
    for unsafe in (
        "preexec_fn",
        "shell=",
        "os.system",
        "subprocess",
        "os.execvp(",
        "os.execvpe(",
    ):
        assert unsafe not in runner

    outer_source = inspect.getsource(bootstrap.build_with_exact_toolchain)
    outer_uv_start = outer_source.index("runtime_text = _run_owned_process(")
    outer_uv_end = outer_source.index("runtime_payload =", outer_uv_start)
    outer_uv = outer_source[outer_uv_start:outer_uv_end]
    assert "/dev/fd" not in outer_uv
    assert "cwd_descriptor=backend_fd" in outer_uv
    assert "launcher_python=bootstrap_python" in outer_uv

    external_boundaries = "\n".join(
        inspect.getsource(function)
        for function in (
            build.verify_uv_lock,
            build._run_pyinstaller_command,
            build.run_pyinstaller,
            build.run_frozen_smoke,
            build._build_manifest,
            build._build_python_sidecar_impl,
        )
    )
    assert "/dev/fd" not in external_boundaries
    assert "preexec_fn" not in external_boundaries
    assert "shell=" not in external_boundaries
    assert "/dev/fd" not in build.PYINSTALLER_CAPABILITY_RUNNER
    assert "/dev/fd" not in (
        PROJECT_ROOT / "backend" / "packaging" / "lcf_sidecar.spec"
    ).read_text(encoding="utf-8")


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
        "installMethod": "macos-installer-no-op-framework-component",
        "frameworkComponent": copy.deepcopy(FRAMEWORK_COMPONENT_FIXTURE),
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
        arguments: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        observed["arguments"] = arguments
        observed["cwd_descriptor_identity"] = os.fstat(kwargs["cwd_descriptor"])
        observed.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(build, "_run_owned_command", checked_run)

    cache = tmp_path / "uv-cache"
    cache.mkdir(mode=0o700)
    source = tmp_path / "source"
    (source / "backend").mkdir(parents=True)
    source_descriptor = os.open(
        source,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        build.verify_uv_lock(
            uv_executable,
            backend_root=source / "backend",
            cache_directory=cache,
            source_descriptor=source_descriptor,
        )
    finally:
        os.close(source_descriptor)

    assert observed["arguments"] == (
        str(uv_executable),
        "lock",
        "--check",
        "--no-cache",
        "--python",
        str(framework_python),
    )
    assert observed["cwd"] == source / "backend"
    assert stat.S_ISDIR(observed["cwd_descriptor_identity"].st_mode)
    assert observed["timeout"] == 180
    environment = observed["environment"]
    assert environment["PATH"] == "/usr/bin:/bin"
    assert environment["UV_NO_CONFIG"] == "1"
    assert environment["UV_OFFLINE"] == "1"
    assert environment["UV_PYTHON_DOWNLOADS"] == "never"
    assert "UV_CACHE_DIR" not in environment
    assert "HOME" not in environment


def test_uv_lock_subprocess_uses_revalidated_canonical_source_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_bin = tmp_path / "build-venv" / "bin"
    uv_executable = build_bin / "uv"
    active_python = build_bin / "python"
    _write_test_executable(uv_executable)
    _write_test_executable(active_python)
    monkeypatch.setattr(build.sys, "executable", str(active_python))
    source = tmp_path / "source"
    (source / "backend").mkdir(parents=True)
    source_descriptor = os.open(
        source,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    cache = tmp_path / "uv-cache"
    cache.mkdir(mode=0o700)
    cache_descriptor = os.open(
        cache,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    cache_snapshot = build._snapshot_from_stat(os.fstat(cache_descriptor), ())
    observed: dict[str, Any] = {}

    def checked_run(
        arguments: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        observed["arguments"] = arguments
        observed["cwd_descriptor_identity"] = os.fstat(kwargs["cwd_descriptor"])
        observed.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(build, "_run_owned_command", checked_run)
    try:
        source_root = source
        build.verify_uv_lock(
            uv_executable,
            backend_root=source_root / "backend",
            cache_directory=cache,
            cache_descriptor=cache_descriptor,
            cache_snapshot=cache_snapshot,
            source_descriptor=source_descriptor,
        )
    finally:
        os.close(cache_descriptor)
        os.close(source_descriptor)

    assert observed["cwd"] == source_root / "backend"
    assert "--no-cache" in observed["arguments"]
    assert "UV_CACHE_DIR" not in observed["environment"]
    assert stat.S_ISDIR(observed["cwd_descriptor_identity"].st_mode)
    assert observed["launcher_python"] == active_python.resolve()


def test_pyinstaller_command_inherits_source_and_all_private_output_fds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptors: dict[str, int] = {}
    paths: dict[str, Path] = {}
    for name in ("source", "dist", "work", "config", "temp"):
        path = tmp_path / name
        path.mkdir()
        paths[name] = path
        descriptors[name] = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    paths["bundle"] = paths["dist"] / "lcf-service"
    paths["bundle"].mkdir()
    descriptors["bundle"] = os.open(
        paths["bundle"],
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    observed: dict[str, Any] = {}

    def checked_owner(
        arguments: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        observed["arguments"] = arguments
        observed["cwd_identity"] = (
            os.fstat(kwargs["cwd_descriptor"]).st_dev,
            os.fstat(kwargs["cwd_descriptor"]).st_ino,
        )
        observed.update(kwargs)
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(build, "_run_owned_command", checked_owner)
    try:
        source_root = paths["source"]
        dist_root = paths["dist"]
        work_root = paths["work"]
        config_root = paths["config"]
        temp_root = paths["temp"]
        build._run_pyinstaller_command(
            active_python=Path(sys.executable),
            source_root=source_root,
            source_descriptor=descriptors["source"],
            bundle_descriptor=descriptors["bundle"],
            dist_descriptor=descriptors["dist"],
            work_descriptor=descriptors["work"],
            config_descriptor=descriptors["config"],
            temp_descriptor=descriptors["temp"],
            dist_root=dist_root,
            work_root=work_root,
            config_root=config_root,
            temp_root=temp_root,
            environment={
                "LC_ALL": "C",
                "PYINSTALLER_CONFIG_DIR": str(config_root),
                "TMPDIR": str(temp_root),
            },
        )
    finally:
        for descriptor in descriptors.values():
            os.close(descriptor)

    arguments = observed["arguments"]
    assert arguments[:4] == (
        sys.executable,
        "-I",
        "-c",
        build.PYINSTALLER_CAPABILITY_RUNNER,
    )
    assert arguments[4:10] == (
        str(descriptors["source"]),
        str(descriptors["bundle"]),
        str(descriptors["dist"]),
        str(descriptors["work"]),
        str(descriptors["config"]),
        str(descriptors["temp"]),
    )
    assert arguments[10:16] == (
        str(source_root),
        str(paths["bundle"]),
        str(dist_root),
        str(work_root),
        str(config_root),
        str(temp_root),
    )
    assert arguments[arguments.index("--workpath") + 1] == str(work_root)
    assert arguments[-1] == str(
        source_root / "backend" / "packaging" / "lcf_sidecar.spec"
    )
    assert observed["cwd"] == source_root
    assert observed["cwd_identity"] == (
        source_root.stat().st_dev,
        source_root.stat().st_ino,
    )
    assert observed["environment"]["PYINSTALLER_CONFIG_DIR"] == str(config_root)
    assert observed["environment"]["TMPDIR"] == str(temp_root)
    assert observed["launcher_python"] == Path(sys.executable)
    assert observed["pass_fds"] == (
        descriptors["source"],
        descriptors["bundle"],
        descriptors["dist"],
        descriptors["work"],
        descriptors["config"],
        descriptors["temp"],
    )


def test_pyinstaller_command_rejects_exec_target_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths: dict[str, Path] = {}
    descriptors: dict[str, int] = {}
    for name in ("source", "dist", "work", "config", "temp"):
        path = tmp_path / name
        path.mkdir()
        paths[name] = path
        descriptors[name] = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    paths["bundle"] = paths["dist"] / "lcf-service"
    paths["bundle"].mkdir()
    descriptors["bundle"] = os.open(
        paths["bundle"],
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    def failed_owner(
        _arguments: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        assert kwargs["launcher_python"] == Path(sys.executable)
        raise build.BuildError("PyInstaller failed (category=target)")

    monkeypatch.setattr(build, "_run_owned_command", failed_owner)
    try:
        with pytest.raises(
            build.BuildError,
            match=r"^PyInstaller failed \(category=target\)$",
        ):
            build._run_pyinstaller_command(
                active_python=Path(sys.executable),
                source_root=paths["source"],
                source_descriptor=descriptors["source"],
                bundle_descriptor=descriptors["bundle"],
                dist_descriptor=descriptors["dist"],
                work_descriptor=descriptors["work"],
                config_descriptor=descriptors["config"],
                temp_descriptor=descriptors["temp"],
                dist_root=paths["dist"],
                work_root=paths["work"],
                config_root=paths["config"],
                temp_root=paths["temp"],
                environment={
                    "LC_ALL": "C",
                    "PYINSTALLER_CONFIG_DIR": str(paths["config"]),
                    "TMPDIR": str(paths["temp"]),
                },
            )
    finally:
        for descriptor in descriptors.values():
            os.close(descriptor)

def test_pyinstaller_runner_validates_canonical_roots_and_closes_child_fds(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    dist = tmp_path / "dist"
    bundle = dist / "lcf-service"
    work = tmp_path / "work"
    config = tmp_path / "config"
    temp = tmp_path / "temp"
    for directory in (source, dist, bundle, work, config, temp):
        directory.mkdir()
    descriptors = tuple(
        os.open(
            directory,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        for directory in (source, bundle, dist, work, config, temp)
    )
    roots = (source, bundle, dist, work, config, temp)
    child = r"""
import os
import sys
for raw in sys.argv[1:]:
    try:
        os.fstat(int(raw))
    except OSError:
        continue
    raise SystemExit("capability fd leaked")
print("closed")
""".strip()
    harness = f"""
import os
import subprocess
import sys
import types

expected = tuple(map(int, sys.argv[1:7]))
roots = tuple(sys.argv[7:13])

pyinstaller = types.ModuleType("PyInstaller")
pyinstaller.__path__ = []
lib = types.ModuleType("PyInstaller.lib")
lib.__path__ = []
modulegraph_package = types.ModuleType("PyInstaller.lib.modulegraph")
modulegraph_package.__path__ = []
modulegraph = types.ModuleType("PyInstaller.lib.modulegraph.modulegraph")
modulegraph.os = os
modulegraph_package.modulegraph = modulegraph
building = types.ModuleType("PyInstaller.building")
building.__path__ = []
api = types.ModuleType("PyInstaller.building.api")

class COLLECT:
    def __init__(self, *args, **kwargs):
        self.name = kwargs.get("name")

api.COLLECT = COLLECT
api._make_clean_directory = lambda _path: None
building.api = api
main = types.ModuleType("PyInstaller.__main__")

def run():
    assert all(
        modulegraph.os.path.realpath(root + "/held") == root + "/held"
        for root in roots
    )
    completed = subprocess.run(
        [sys.executable, "-c", {child!r}, *map(str, expected)],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    print(completed.stdout, end="")
    isolated = subprocess.run(
        [sys.executable, "-c", {child!r}, *map(str, expected)],
        close_fds=False,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    print(isolated.stdout, end="")

main.run = run
pyinstaller.lib = lib
pyinstaller.building = building
pyinstaller.__main__ = main
sys.modules.update({{
    "PyInstaller": pyinstaller,
    "PyInstaller.lib": lib,
    "PyInstaller.lib.modulegraph": modulegraph_package,
    "PyInstaller.lib.modulegraph.modulegraph": modulegraph,
    "PyInstaller.building": building,
    "PyInstaller.building.api": api,
    "PyInstaller.__main__": main,
}})
exec({build.PYINSTALLER_CAPABILITY_RUNNER!r}, globals(), globals())
"""
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                harness,
                *(str(descriptor) for descriptor in descriptors),
                *(str(root) for root in roots),
                "--distpath",
                str(dist),
                "--workpath",
                str(work),
                "synthetic.spec",
            ],
            env={
                **os.environ,
                "PYINSTALLER_CONFIG_DIR": str(config),
                "TMPDIR": str(temp),
            },
            pass_fds=descriptors,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout.splitlines() == [
        "closed",
        "closed",
    ]


def test_pyinstaller_double_signal_stops_nested_fd_holding_process_group(
    tmp_path: Path,
) -> None:
    root = tmp_path / "process-group"
    root.mkdir()
    runner = r"""
import os
import subprocess
import sys
import time

descriptors = tuple(map(int, sys.argv[1:7]))
child_code = r'''import os,signal,sys,time
descriptors=tuple(map(int,sys.argv[1:]))
for item in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)):
    signal.signal(item, signal.SIG_IGN)
assert all(os.fstat(descriptor).st_ino for descriptor in descriptors)
with open(os.environ["LCF_TEST_CHILD"], "w", encoding="ascii") as handle:
    handle.write(str(os.getpid()))
while True:
    time.sleep(1)
'''
subprocess.Popen(
    [sys.executable, "-c", child_code, *map(str, descriptors)],
    pass_fds=descriptors,
)
while not os.path.exists(os.environ["LCF_TEST_CHILD"]):
    time.sleep(0.01)
while True:
    time.sleep(1)
""".strip()
    script = f"""
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
root = Path({json.dumps(str(root))})
paths = {{}}
for name in ("source", "dist", "work", "config", "tmp"):
    paths[name] = root / name
    paths[name].mkdir()
paths["bundle"] = paths["dist"] / "lcf-service"
paths["bundle"].mkdir()
descriptors = {{
    name: os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    for name, path in paths.items()
}}
marker = root / "child.pid"
build.PYINSTALLER_CAPABILITY_RUNNER = {runner!r}
environment = {{
    "LCF_TEST_CHILD": str(marker),
    "PYINSTALLER_CONFIG_DIR": str(paths["config"]),
    "TMPDIR": str(paths["tmp"]),
}}
sender_code = r'''import os,signal,sys,time
target = int(sys.argv[1])
marker = sys.argv[2]
while not os.path.exists(marker):
    time.sleep(0.01)
os.kill(target, signal.SIGTERM)
time.sleep(0.1)
os.kill(target, signal.SIGINT)
'''
sender = subprocess.Popen(
    [sys.executable, "-c", sender_code, str(os.getpid()), str(marker)],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
error = None
try:
    with build._translate_cleanup_signals():
        build._run_pyinstaller_command(
            active_python=Path(sys.executable),
            source_root=paths["source"],
            source_descriptor=descriptors["source"],
            bundle_descriptor=descriptors["bundle"],
            dist_descriptor=descriptors["dist"],
            work_descriptor=descriptors["work"],
            config_descriptor=descriptors["config"],
            temp_descriptor=descriptors["tmp"],
            dist_root=paths["dist"],
            work_root=paths["work"],
            config_root=paths["config"],
            temp_root=paths["tmp"],
            environment=environment,
        )
except build.BuildError as exc:
    error = str(exc)
sender.wait(timeout=2)
child_pid = int(marker.read_text(encoding="ascii"))
try:
    os.kill(child_pid, 0)
except ProcessLookupError:
    child_alive = False
else:
    child_alive = True
fds_open = all(stat.S_ISDIR(os.fstat(descriptor).st_mode) for descriptor in descriptors.values())
for descriptor in descriptors.values():
    os.close(descriptor)
print(json.dumps({{
    "childAlive": child_alive,
    "error": error,
    "fdsOpen": fds_open,
    "senderExit": sender.returncode,
}}))
"""

    assert _run_signal_probe(script) == {
        "childAlive": False,
        "error": "Python sidecar operation was interrupted after reaching a safe state",
        "fdsOpen": True,
        "senderExit": 0,
    }


@pytest.mark.parametrize("phase", ["popen-return", "communicate-return"])
@pytest.mark.parametrize(
    "signal_name",
    ["SIGINT", "SIGTERM", *(["SIGHUP"] if hasattr(signal, "SIGHUP") else [])],
)
def test_pyinstaller_process_owner_handoff_cleans_real_process_group(
    tmp_path: Path,
    phase: str,
    signal_name: str,
) -> None:
    root = tmp_path / phase / signal_name
    root.mkdir(parents=True)
    runner = r"""
import os
import subprocess
import sys
import time
descriptors = tuple(map(int, sys.argv[1:7]))
child = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import os,sys,time; "
        "assert all(os.fstat(int(fd)).st_ino for fd in sys.argv[1:]); "
        "open(os.environ['LCF_TEST_CHILD'],'w').write(str(os.getpid())); "
        "time.sleep(60)",
        *map(str, descriptors),
    ],
    pass_fds=descriptors,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
while not os.path.exists(os.environ["LCF_TEST_CHILD"]):
    time.sleep(0.01)
if os.environ["LCF_TEST_PHASE"] == "communicate-return":
    raise SystemExit(0)
while True:
    time.sleep(1)
""".strip()
    script = f"""
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
import bootstrap_python_sidecar as bootstrap
root = Path({json.dumps(str(root))})
phase = {json.dumps(phase)}
paths = {{}}
for name in ("source", "dist", "work", "config", "tmp"):
    paths[name] = root / name
    paths[name].mkdir()
paths["bundle"] = paths["dist"] / "lcf-service"
paths["bundle"].mkdir()
descriptors = {{
    name: os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    for name, path in paths.items()
}}
marker = root / "child.pid"
original_popen = bootstrap.subprocess.Popen
original_communicate = bootstrap._communicate_bounded

class SignallingPopen:
    def __init__(self, *args, **kwargs):
        self.inner = original_popen(*args, **kwargs)
        if phase == "popen-return":
            os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    def __getattr__(self, name):
        return getattr(self.inner, name)

def signalling_communicate(process, **kwargs):
    result = original_communicate(process, **kwargs)
    if phase == "communicate-return":
        os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    return result

bootstrap._communicate_bounded = signalling_communicate

bootstrap.subprocess.Popen = SignallingPopen
build.PYINSTALLER_CAPABILITY_RUNNER = {runner!r}
environment = {{
    "LCF_TEST_CHILD": str(marker),
    "LCF_TEST_PHASE": phase,
    "PYINSTALLER_CONFIG_DIR": str(paths["config"]),
    "TMPDIR": str(paths["tmp"]),
}}
error = None
try:
    with build._translate_cleanup_signals():
        build._run_pyinstaller_command(
            active_python=Path(sys.executable),
            source_root=paths["source"],
            source_descriptor=descriptors["source"],
            bundle_descriptor=descriptors["bundle"],
            dist_descriptor=descriptors["dist"],
            work_descriptor=descriptors["work"],
            config_descriptor=descriptors["config"],
            temp_descriptor=descriptors["tmp"],
            dist_root=paths["dist"],
            work_root=paths["work"],
            config_root=paths["config"],
            temp_root=paths["tmp"],
            environment=environment,
        )
except build.BuildError as exc:
    error = str(exc)
finally:
    bootstrap.subprocess.Popen = original_popen
    bootstrap._communicate_bounded = original_communicate
if marker.exists():
    child_pid = int(marker.read_text(encoding="ascii"))
    for _attempt in range(100):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            child_alive = False
            break
        child_alive = True
        time.sleep(0.01)
else:
    # The signal may arrive after the owned leader exists but before its
    # capability wrapper has started the grandchild.  Absence is the strongest
    # no-orphan result for that handoff cut point.
    child_alive = False
fds_open = all(stat.S_ISDIR(os.fstat(fd).st_mode) for fd in descriptors.values())
for fd in descriptors.values():
    os.close(fd)
print(json.dumps({{
    "childAlive": child_alive,
    "error": error,
    "fdsOpen": fds_open,
}}))
"""

    assert _run_signal_probe(script) == {
        "childAlive": False,
        "error": build._INTERRUPTED_ERROR,
        "fdsOpen": True,
    }


def test_pyinstaller_spec_keeps_entrypoint_under_revalidated_canonical_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    (source / "backend" / "packaging").mkdir(parents=True)
    descriptor = os.open(
        source,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    held = tmp_path / "held-source"
    source.rename(held)
    (source / "backend" / "packaging").mkdir(parents=True)
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda _name: []  # type: ignore[attr-defined]
    hooks.copy_metadata = lambda _name: []  # type: ignore[attr-defined]
    pyinstaller = types.ModuleType("PyInstaller")
    pyinstaller.__path__ = []  # type: ignore[attr-defined]
    utils = types.ModuleType("PyInstaller.utils")
    utils.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PyInstaller", pyinstaller)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", utils)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    observed: dict[str, Any] = {}

    class AnalysisResult:
        pure: list[Any] = []
        scripts: list[Any] = []
        binaries: list[Any] = []
        datas: list[Any] = []

    def analysis(arguments: list[str], **kwargs: Any) -> AnalysisResult:
        observed["arguments"] = arguments
        observed.update(kwargs)
        return AnalysisResult()

    namespace = {
        "SPECPATH": str(held / "backend" / "packaging"),
        "Analysis": analysis,
        "PYZ": lambda *_args, **_kwargs: object(),
        "EXE": lambda *_args, **_kwargs: object(),
        "COLLECT": lambda *_args, **_kwargs: object(),
    }
    monkeypatch.setenv("LCF_PYINSTALLER_SOURCE_FD", str(descriptor))
    monkeypatch.setenv("LCF_PYINSTALLER_SOURCE_ROOT", str(held))
    try:
        spec_text = (PROJECT_ROOT / "backend" / "packaging" / "lcf_sidecar.spec").read_text(
            encoding="utf-8"
        )
        exec(compile(spec_text, "lcf_sidecar.spec", "exec"), namespace)
    finally:
        os.close(descriptor)

    assert observed["arguments"] == [
        str(held / "backend" / "packaging" / "frozen_entrypoint.py")
    ]
    assert observed["pathex"] == [str(held / "backend")]
    assert str(source) not in observed["arguments"][0]


def test_uv_lock_check_rejects_a_python_from_another_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uv_executable = tmp_path / "build-venv" / "bin" / "uv"
    active_python = tmp_path / "other-venv" / "bin" / "python"
    _write_test_executable(uv_executable)
    _write_test_executable(active_python)
    monkeypatch.setattr(build.sys, "executable", str(active_python))
    cache = tmp_path / "uv-cache"
    cache.mkdir(mode=0o700)

    with pytest.raises(build.BuildError, match="same build venv"):
        build.verify_uv_lock(
            uv_executable,
            backend_root=build.BACKEND_ROOT,
            cache_directory=cache,
        )


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
        arguments: tuple[str, ...],
        **_: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 2, stdout="", stderr=stderr)

    monkeypatch.setattr(build, "_run_owned_command", failed_run)
    cache = tmp_path / "uv-cache"
    cache.mkdir(mode=0o700)
    source = tmp_path / "source"
    (source / "backend").mkdir(parents=True)
    source_descriptor = os.open(
        source,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )

    try:
        with pytest.raises(
            build.BuildError,
            match=rf"^uv lock check failed \(exit=2; category={category}\)$",
        ) as failure:
            build.verify_uv_lock(
                uv_executable,
                backend_root=source / "backend",
                cache_directory=cache,
                source_descriptor=source_descriptor,
            )
    finally:
        os.close(source_descriptor)

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


def test_frozen_live_log_collector_bounds_output_before_owner_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "sidecar.log"
    log_handle, _identity = build._open_frozen_log(log_path)
    monkeypatch.setattr(build, "MAX_FROZEN_START_LOG_BYTES", 128)
    process = subprocess.Popen(
        (
            sys.executable,
            "-I",
            "-c",
            "import os,time;os.write(1,b'x'*512);time.sleep(30)",
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        close_fds=True,
        start_new_session=True,
    )
    assert process.stdout is not None
    collector = build._BoundedFrozenLogCollector(process.stdout, log_handle)
    collector.start()
    deadline = time.monotonic() + 5
    observed = False
    try:
        while time.monotonic() < deadline:
            try:
                collector.assert_healthy()
            except build.BuildError as exc:
                assert str(exc) == "Frozen sidecar log exceeded its size bound"
                observed = True
                break
            time.sleep(0.01)
        assert observed
        assert process.poll() is None
        assert os.fstat(log_handle.fileno()).st_size == 128
    finally:
        build._terminate_owned_process_group(
            process,
            error_message="Frozen log test process group did not stop",
        )
        log_handle.close()

    assert process.poll() is not None
    assert not build._process_group_exists(process.pid)


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


def test_wait_for_socket_probes_until_the_bound_socket_listens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RunningProcess:
        @staticmethod
        def poll() -> None:
            return None

    class ReadySocketPath:
        @staticmethod
        def lstat() -> os.stat_result:
            values = list((tmp_path / "sidecar.log").stat())
            values[0] = stat.S_IFSOCK | 0o600
            values[3] = 1
            values[4] = os.geteuid()
            return os.stat_result(values)

        @staticmethod
        def __str__() -> str:
            return "/private/path-that-must-not-leak.sock"

    outcomes = deque(["refused", "success"])
    probes: list[Any] = []
    sleeps: list[float] = []

    class Probe:
        def __init__(self, outcome: str) -> None:
            self.outcome = outcome
            self.closed = False
            self.timeout: float | None = None

        def settimeout(self, timeout: float) -> None:
            self.timeout = timeout

        def connect(self, _path: str) -> None:
            if self.outcome == "refused":
                raise ConnectionRefusedError(
                    errno.ECONNREFUSED,
                    "token-must-not-leak /private/path-must-not-leak",
                )

        def sendall(self, _payload: bytes) -> None:
            pytest.fail("a readiness probe must not send request bytes")

        def recv(self, _size: int) -> bytes:
            pytest.fail("a readiness probe must not read response bytes")

        def close(self) -> None:
            self.closed = True

    def open_probe(family: int, kind: int) -> Probe:
        assert (family, kind) == (socket.AF_UNIX, socket.SOCK_STREAM)
        probe = Probe(outcomes.popleft())
        probes.append(probe)
        return probe

    monkeypatch.setattr(build.socket, "socket", open_probe)
    monkeypatch.setattr(build.time, "sleep", sleeps.append)
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    try:
        build._wait_for_socket(
            ReadySocketPath(),  # type: ignore[arg-type]
            RunningProcess(),  # type: ignore[arg-type]
            log_handle,
            log_path,
            identity,
        )
    finally:
        log_handle.close()

    assert not outcomes
    assert len(probes) == 2
    assert all(probe.closed for probe in probes)
    assert all(probe.timeout is not None for probe in probes)
    assert sleeps == [pytest.approx(0.05)]


def test_wait_for_socket_reports_exit_during_listen_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExitAfterRefusalProcess:
        def __init__(self) -> None:
            self.polls = deque([None, None, 7])

        def poll(self) -> int | None:
            return self.polls.popleft() if self.polls else 7

    class ReadySocketPath:
        @staticmethod
        def lstat() -> os.stat_result:
            values = list((tmp_path / "sidecar.log").stat())
            values[0] = stat.S_IFSOCK | 0o600
            values[3] = 1
            values[4] = os.geteuid()
            return os.stat_result(values)

    class RefusedProbe:
        @staticmethod
        def settimeout(_timeout: float) -> None:
            return None

        @staticmethod
        def connect(_path: str) -> None:
            raise ConnectionRefusedError(
                errno.ECONNREFUSED,
                "token-must-not-leak /private/path-must-not-leak",
            )

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(
        build.socket,
        "socket",
        lambda _family, _kind: RefusedProbe(),
    )
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    log_handle.write(
        b"lcf-service: desktop transport setup failed; token-must-not-leak\n"
    )
    try:
        with pytest.raises(
            build.BuildError,
            match=(
                r"^Frozen sidecar exited before its UDS became ready "
                r"\(exit=7; category=desktop-transport\)$"
            ),
        ) as failure:
            build._wait_for_socket(
                ReadySocketPath(),  # type: ignore[arg-type]
                ExitAfterRefusalProcess(),  # type: ignore[arg-type]
                log_handle,
                log_path,
                identity,
            )
    finally:
        log_handle.close()

    assert "token-must-not-leak" not in str(failure.value)
    assert "/private" not in str(failure.value)


@pytest.mark.parametrize("phase", ["construct", "settimeout", "connect"])
def test_wait_for_socket_rejects_nontransient_probe_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    class RunningProcess:
        @staticmethod
        def poll() -> None:
            return None

    class ReadySocketPath:
        @staticmethod
        def lstat() -> os.stat_result:
            values = list((tmp_path / "sidecar.log").stat())
            values[0] = stat.S_IFSOCK | 0o600
            values[3] = 1
            values[4] = os.geteuid()
            return os.stat_result(values)

    probes = 0

    class FailedProbe:
        def settimeout(self, _timeout: float) -> None:
            if phase == "settimeout":
                raise OSError(
                    errno.EACCES,
                    "token-must-not-leak /private/path-must-not-leak",
                )

        def connect(self, _path: str) -> None:
            if phase == "connect":
                raise OSError(
                    errno.EACCES,
                    "token-must-not-leak /private/path-must-not-leak",
                )

        @staticmethod
        def close() -> None:
            return None

    def open_probe(_family: int, _kind: int) -> FailedProbe:
        nonlocal probes
        probes += 1
        if phase == "construct":
            raise OSError(
                errno.EACCES,
                "token-must-not-leak /private/path-must-not-leak",
            )
        return FailedProbe()

    monkeypatch.setattr(build.socket, "socket", open_probe)
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    try:
        with pytest.raises(
            build.BuildError,
            match=r"^Frozen sidecar UDS readiness probe failed$",
        ) as failure:
            build._wait_for_socket(
                ReadySocketPath(),  # type: ignore[arg-type]
                RunningProcess(),  # type: ignore[arg-type]
                log_handle,
                log_path,
                identity,
            )
    finally:
        log_handle.close()

    assert probes == 1
    assert "token-must-not-leak" not in str(failure.value)
    assert "/private" not in str(failure.value)


def test_wait_for_socket_rejects_probe_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RunningProcess:
        @staticmethod
        def poll() -> None:
            return None

    class ReadySocketPath:
        @staticmethod
        def lstat() -> os.stat_result:
            values = list((tmp_path / "sidecar.log").stat())
            values[0] = stat.S_IFSOCK | 0o600
            values[3] = 1
            values[4] = os.geteuid()
            return os.stat_result(values)

    class FailedCleanupProbe:
        @staticmethod
        def settimeout(_timeout: float) -> None:
            return None

        @staticmethod
        def connect(_path: str) -> None:
            return None

        @staticmethod
        def close() -> None:
            raise OSError(
                errno.EIO,
                "token-must-not-leak /private/path-must-not-leak",
            )

    monkeypatch.setattr(
        build.socket,
        "socket",
        lambda _family, _kind: FailedCleanupProbe(),
    )
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    try:
        with pytest.raises(
            build.BuildError,
            match=(
                r"^Frozen sidecar UDS readiness probe cleanup failed$"
            ),
        ) as failure:
            build._wait_for_socket(
                ReadySocketPath(),  # type: ignore[arg-type]
                RunningProcess(),  # type: ignore[arg-type]
                log_handle,
                log_path,
                identity,
            )
    finally:
        log_handle.close()

    assert "token-must-not-leak" not in str(failure.value)
    assert "/private" not in str(failure.value)


@pytest.mark.parametrize(
    "mutation",
    ["inode", "mode", "owner", "hardlink", "type", "missing"],
)
def test_wait_for_socket_rejects_socket_mutation_after_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    class RunningProcess:
        @staticmethod
        def poll() -> None:
            return None

    metadata_source = tmp_path / "metadata-source"
    metadata_source.write_bytes(b"")
    base = list(metadata_source.stat())
    base[0] = stat.S_IFSOCK | 0o600
    base[3] = 1
    base[4] = os.geteuid()
    changed = list(base)
    if mutation == "inode":
        changed[1] += 1
    elif mutation == "mode":
        changed[0] = stat.S_IFSOCK | 0o640
    elif mutation == "owner":
        changed[4] += 1
    elif mutation == "hardlink":
        changed[3] = 2
    elif mutation == "type":
        changed[0] = stat.S_IFREG | 0o600

    class MutatedSocketPath:
        def __init__(self) -> None:
            self.inspections = 0

        def lstat(self) -> os.stat_result:
            self.inspections += 1
            if self.inspections == 1:
                return os.stat_result(base)
            if mutation == "missing":
                raise FileNotFoundError("/private/path-must-not-leak")
            return os.stat_result(changed)

    class SuccessfulProbe:
        @staticmethod
        def settimeout(_timeout: float) -> None:
            return None

        @staticmethod
        def connect(_path: str) -> None:
            return None

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(
        build.socket,
        "socket",
        lambda _family, _kind: SuccessfulProbe(),
    )
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    try:
        with pytest.raises(
            build.BuildError,
            match=r"^Frozen sidecar socket changed during readiness$",
        ) as failure:
            build._wait_for_socket(
                MutatedSocketPath(),  # type: ignore[arg-type]
                RunningProcess(),  # type: ignore[arg-type]
                log_handle,
                log_path,
                identity,
            )
    finally:
        log_handle.close()

    assert "/private" not in str(failure.value)


def test_wait_for_socket_times_out_while_bound_socket_refuses_connections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RunningProcess:
        @staticmethod
        def poll() -> None:
            return None

    class ReadySocketPath:
        @staticmethod
        def lstat() -> os.stat_result:
            values = list((tmp_path / "sidecar.log").stat())
            values[0] = stat.S_IFSOCK | 0o600
            values[3] = 1
            values[4] = os.geteuid()
            return os.stat_result(values)

    class RefusedProbe:
        @staticmethod
        def settimeout(_timeout: float) -> None:
            return None

        @staticmethod
        def connect(_path: str) -> None:
            raise ConnectionRefusedError(
                errno.ECONNREFUSED,
                "token-must-not-leak /private/path-must-not-leak",
            )

        @staticmethod
        def close() -> None:
            return None

    clock = iter((0.0, 10.0, 20.0, 30.0, 40.0))
    monkeypatch.setattr(build.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(build.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        build.socket,
        "socket",
        lambda _family, _kind: RefusedProbe(),
    )
    log_path = tmp_path / "sidecar.log"
    log_handle, identity = build._open_frozen_log(log_path)
    try:
        with pytest.raises(
            build.BuildError,
            match=r"^Frozen sidecar UDS readiness timed out$",
        ) as failure:
            build._wait_for_socket(
                ReadySocketPath(),  # type: ignore[arg-type]
                RunningProcess(),  # type: ignore[arg-type]
                log_handle,
                log_path,
                identity,
            )
    finally:
        log_handle.close()

    assert "token-must-not-leak" not in str(failure.value)
    assert "/private" not in str(failure.value)


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


def test_held_private_smoke_root_cleans_exact_nested_tree(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "private-temp"
    parent.mkdir(mode=0o700)
    child: Path | None = None

    with build._held_private_smoke_root(parent) as root:
        child = root
        nested = root / "nested"
        nested.mkdir(mode=0o700)
        (nested / "state").write_text("smoke", encoding="utf-8")

    assert child is not None
    assert not child.exists()
    assert list(parent.iterdir()) == []


def test_held_private_smoke_root_refuses_replacement_cleanup(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "private-temp"
    parent.mkdir(mode=0o700)
    replacement: Path | None = None
    detached: Path | None = None

    with pytest.raises(build.BuildError, match="root cleanup failed"):
        with build._held_private_smoke_root(parent) as root:
            detached = parent / "detached"
            root.rename(detached)
            root.mkdir(mode=0o700)
            replacement = root
            (root / "do-not-delete").write_text("replacement", encoding="utf-8")

    assert replacement is not None
    assert detached is not None
    assert (replacement / "do-not-delete").read_text(encoding="utf-8") == (
        "replacement"
    )
    assert detached.is_dir()


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


def test_python_sidecar_build_root_uses_private_ignored_parent(
    tmp_path: Path,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)

    capability = build._create_private_build_root(destination_parent)
    assert capability.build_root.parent == capability.scratch_parent
    scratch_suffix = capability.scratch_parent.name.removeprefix(
        f"{build.SCRATCH_PARENT_NAME}-"
    )
    assert len(scratch_suffix) == 32
    assert set(scratch_suffix) <= set("0123456789abcdef")
    assert stat.S_IMODE(capability.scratch_parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(capability.build_root.stat().st_mode) == 0o700
    assert capability.destination_parent_descriptor >= 0
    assert capability.scratch_parent_descriptor >= 0
    assert capability.build_root_descriptor >= 0
    assert capability.build_root_snapshot.entries == ()
    build._cleanup_scratch_capability(capability)

    ignore_lines = {
        line.strip()
        for line in (PROJECT_ROOT / ".gitignore").read_text(
            encoding="utf-8"
        ).splitlines()
    }
    assert "desktop/generated/python-sidecar-build-*/" in ignore_lines
    ignored_probe = subprocess.run(
        (
            "git",
            "check-ignore",
            "--quiet",
            "desktop/generated/python-sidecar-build-"
            + "0" * 32
            + "/candidate-probe/file",
        ),
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert ignored_probe.returncode == 0


@pytest.mark.parametrize("stale_kind", ["symlink", "mode"])
def test_python_sidecar_build_root_ignores_unowned_stale_prefix_entries(
    tmp_path: Path,
    stale_kind: str,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    stale = destination_parent / "python-sidecar-build-stale"
    if stale_kind == "symlink":
        outside = tmp_path / "outside"
        outside.mkdir(mode=0o700)
        stale.symlink_to(outside, target_is_directory=True)
    else:
        stale.mkdir(mode=0o700)
        stale.chmod(0o755)

    capability = build._create_private_build_root(destination_parent)
    assert capability.scratch_parent.name.startswith(
        f"{build.SCRATCH_PARENT_NAME}-"
    )
    assert capability.scratch_parent != stale
    build._cleanup_scratch_capability(capability)
    assert stale.exists() or stale.is_symlink()


def test_scratch_creation_cleanup_refuses_an_unbound_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    original = build._capture_bound_directory

    def replace_before_build_binding(
        descriptor: int,
        path: Path,
        *,
        parent_descriptor: int | None,
        relative_name: str | None,
        expected: build._DirectorySnapshot | None,
        expected_mode: int | None,
        exact_entries: tuple[str, ...] | None,
        error_message: str,
    ) -> build._DirectorySnapshot:
        if (
                parent_descriptor is not None
                and relative_name is not None
                and relative_name.startswith("candidate-")
                and expected is not None
        ):
            os.rename(
                relative_name,
                "captured-candidate",
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.mkdir(relative_name, mode=0o700, dir_fd=parent_descriptor)
            replacement_descriptor = os.open(
                relative_name,
                os.O_RDONLY | os.O_DIRECTORY,
                dir_fd=parent_descriptor,
            )
            try:
                marker = os.open(
                    "do-not-delete",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=replacement_descriptor,
                )
                os.close(marker)
            finally:
                os.close(replacement_descriptor)
            raise build._CapabilityDriftError(error_message)
        return original(
            descriptor,
            path,
            parent_descriptor=parent_descriptor,
            relative_name=relative_name,
            expected=expected,
            expected_mode=expected_mode,
            exact_entries=exact_entries,
            error_message=error_message,
        )

    monkeypatch.setattr(build, "_capture_bound_directory", replace_before_build_binding)

    with pytest.raises(
        build.BuildError,
        match=r"^Python sidecar scratch creation cleanup failed$",
    ):
        build._create_private_build_root(destination_parent)

    scratch = next(
        destination_parent.glob(f"{build.SCRATCH_PARENT_NAME}-*")
    )
    replacements = list(scratch.glob("candidate-*"))
    assert len(replacements) == 1
    assert (replacements[0] / "do-not-delete").read_text(encoding="utf-8") == ""
    assert (scratch / "captured-candidate").is_dir()


@pytest.mark.parametrize("phase", ["scratch-parent", "build-root"])
@pytest.mark.parametrize(
    "signal_name",
    ["SIGINT", "SIGTERM", *( ["SIGHUP"] if hasattr(signal, "SIGHUP") else [] )],
)
def test_private_build_root_defers_real_signals_until_binding_and_cleanup(
    tmp_path: Path,
    phase: str,
    signal_name: str,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    script = f"""
import json
import os
import signal
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
destination = Path({json.dumps(str(destination_parent))})
original_open = build.os.open
fired = False
def injected_open(path, flags, mode=0o777, *, dir_fd=None):
    global fired
    is_target = (
        ({json.dumps(phase)} == "scratch-parent" and isinstance(path, str) and path.startswith(build.SCRATCH_PARENT_NAME + "-"))
        or ({json.dumps(phase)} == "build-root" and isinstance(path, str) and path.startswith("candidate-"))
    )
    if not fired and is_target and dir_fd is not None:
        fired = True
        os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    keyword = {{}} if dir_fd is None else {{"dir_fd": dir_fd}}
    return original_open(path, flags, mode, **keyword)
build.os.open = injected_open
error = None
try:
    capability = build._create_private_build_root(destination)
except build.BuildError as exc:
    error = str(exc)
else:
    build._cleanup_scratch_capability(capability)
finally:
    build.os.open = original_open
scratch_exists = any(destination.glob(build.SCRATCH_PARENT_NAME + "-*"))
print(json.dumps({{
    "error": error,
    "fired": fired,
    "scratchExists": scratch_exists,
    "entries": sorted(item.name for item in destination.iterdir()),
}}))
"""

    result = _run_signal_probe(script)

    assert result == {
        "error": (
            "Python sidecar operation was interrupted after reaching a safe state"
        ),
        "fired": True,
        "scratchExists": False,
        "entries": [],
    }


@pytest.mark.parametrize("phase", ["scratch-parent", "build-root"])
@pytest.mark.parametrize("first_stage", ["open", "bind", "cleanup"])
@pytest.mark.parametrize(
    "signal_name",
    ["SIGINT", "SIGTERM", *(["SIGHUP"] if hasattr(signal, "SIGHUP") else [])],
)
def test_private_build_root_double_signal_latch_covers_bind_and_cleanup(
    tmp_path: Path,
    phase: str,
    first_stage: str,
    signal_name: str,
) -> None:
    destination_parent = tmp_path / phase / first_stage / signal_name / "generated"
    destination_parent.mkdir(mode=0o755, parents=True)
    second_signal = "SIGTERM" if signal_name == "SIGINT" else "SIGINT"
    script = f"""
import json
import os
import signal
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
destination = Path({json.dumps(str(destination_parent))})
phase = {json.dumps(phase)}
first_stage = {json.dumps(first_stage)}
first_signal = getattr(signal, {json.dumps(signal_name)})
second_signal = getattr(signal, {json.dumps(second_signal)})
original_open = build.os.open
original_mkdir = build.os.mkdir
original_capture = build._capture_bound_directory
original_remove_leaf = build._remove_verified_quarantine_leaf
first_fired = False
second_fired = False
target_bound = False

def is_target(name):
    return isinstance(name, str) and (
        (phase == "scratch-parent" and name.startswith(build.SCRATCH_PARENT_NAME + "-"))
        or (phase == "build-root" and name.startswith("candidate-"))
    )

def fire_first():
    global first_fired
    if not first_fired:
        first_fired = True
        os.kill(os.getpid(), first_signal)

def fire_second():
    global second_fired
    if not second_fired:
        second_fired = True
        os.kill(os.getpid(), second_signal)

def injected_open(path, flags, mode=0o777, *, dir_fd=None):
    if first_stage == "open" and is_target(path) and dir_fd is not None:
        fire_first()
    keyword = {{}} if dir_fd is None else {{"dir_fd": dir_fd}}
    return original_open(path, flags, mode, **keyword)

def injected_mkdir(path, mode=0o777, *, dir_fd=None):
    if (
        first_stage == "cleanup"
        and phase == "scratch-parent"
        and target_bound
        and isinstance(path, str)
        and path.startswith("candidate-")
    ):
        raise OSError("synthetic post-bind creation failure")
    keyword = {{}} if dir_fd is None else {{"dir_fd": dir_fd}}
    return original_mkdir(path, mode, **keyword)

def injected_capture(descriptor, path, **kwargs):
    global target_bound
    relative_name = kwargs.get("relative_name")
    exact_entries = kwargs.get("exact_entries")
    if (
        first_stage == "cleanup"
        and phase == "build-root"
        and target_bound
        and isinstance(relative_name, str)
        and relative_name.startswith(build.SCRATCH_PARENT_NAME + "-")
        and exact_entries is not None
        and any(str(item).startswith("candidate-") for item in exact_entries)
    ):
        raise build.BuildError("synthetic post-bind validation failure")
    result = original_capture(descriptor, path, **kwargs)
    if is_target(relative_name) and kwargs.get("expected") is not None:
        target_bound = True
        if first_stage == "bind":
            fire_first()
    return result

def injected_remove_leaf(parent_descriptor, **kwargs):
    if is_target(kwargs.get("original_name")):
        if first_stage == "cleanup":
            fire_first()
        fire_second()
    return original_remove_leaf(parent_descriptor, **kwargs)

build.os.open = injected_open
build.os.mkdir = injected_mkdir
build._capture_bound_directory = injected_capture
build._remove_verified_quarantine_leaf = injected_remove_leaf
error = None
try:
    capability = build._create_private_build_root(destination)
except build.BuildError as exc:
    error = str(exc)
else:
    build._cleanup_scratch_capability(capability)
finally:
    build.os.open = original_open
    build.os.mkdir = original_mkdir
    build._capture_bound_directory = original_capture
    build._remove_verified_quarantine_leaf = original_remove_leaf
print(json.dumps({{
    "entries": sorted(item.name for item in destination.iterdir()),
    "error": error,
    "firstFired": first_fired,
    "secondFired": second_fired,
}}))
"""

    assert _run_signal_probe(script) == {
        "entries": [],
        "error": build._INTERRUPTED_ERROR,
        "firstFired": True,
        "secondFired": True,
    }


@pytest.mark.parametrize(
    "target",
    ["dist", "work", "pyinstaller-config", "tmp", "lcf-service", "evidence"],
)
@pytest.mark.parametrize(
    "signal_name",
    ["SIGINT", "SIGTERM", *(["SIGHUP"] if hasattr(signal, "SIGHUP") else [])],
)
def test_capability_acquisition_double_signal_rolls_back_every_bound_root(
    tmp_path: Path,
    target: str,
    signal_name: str,
) -> None:
    destination_parent = tmp_path / signal_name / target / "generated"
    destination_parent.mkdir(mode=0o755, parents=True)
    second_signal = "SIGTERM" if signal_name == "SIGINT" else "SIGINT"
    script = f"""
import json
import os
import signal
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
destination = Path({json.dumps(str(destination_parent))})
target = {json.dumps(target)}
first_signal = getattr(signal, {json.dumps(signal_name)})
second_signal = getattr(signal, {json.dumps(second_signal)})
original_capture = build._capture_bound_directory
original_rollback = build._rollback_bound_directory
first_fired = False
second_fired = False

def injected_capture(descriptor, path, **kwargs):
    global first_fired
    result = original_capture(descriptor, path, **kwargs)
    if (
        not first_fired
        and kwargs.get("relative_name") == target
        and kwargs.get("expected") is not None
    ):
        first_fired = True
        os.kill(os.getpid(), first_signal)
    return result

def injected_rollback(**kwargs):
    global second_fired
    if not second_fired:
        second_fired = True
        os.kill(os.getpid(), second_signal)
    return original_rollback(**kwargs)

build._capture_bound_directory = injected_capture
build._rollback_bound_directory = injected_rollback
build._validate_source_snapshot = lambda capability: capability.build_root
error = None
scratch = None
try:
    with build._translate_cleanup_signals():
        scratch = build._create_private_build_root(destination)
        try:
            if target == "evidence":
                build._create_failure_evidence_capability(scratch)
            else:
                build._prepare_pyinstaller_capabilities(scratch)
        finally:
            build._cleanup_scratch_capability(scratch)
except build.BuildError as exc:
    error = str(exc)
finally:
    build._capture_bound_directory = original_capture
    build._rollback_bound_directory = original_rollback
print(json.dumps({{
    "entries": sorted(item.name for item in destination.iterdir()),
    "error": error,
    "firstFired": first_fired,
    "secondFired": second_fired,
}}))
"""

    assert _run_signal_probe(script) == {
        "entries": [],
        "error": build._INTERRUPTED_ERROR,
        "firstFired": True,
        "secondFired": True,
    }


@pytest.mark.parametrize(
    "signal_name",
    ["SIGINT", "SIGTERM", *(["SIGHUP"] if hasattr(signal, "SIGHUP") else [])],
)
def test_background_thread_signal_delivery_cannot_pierce_masked_transaction(
    tmp_path: Path,
    signal_name: str,
) -> None:
    destination_parent = tmp_path / signal_name / "generated"
    destination_parent.mkdir(mode=0o755, parents=True)
    second_signal = "SIGTERM" if signal_name == "SIGINT" else "SIGINT"
    script = f"""
import json
import signal
import threading
import time
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
destination = Path({json.dumps(str(destination_parent))})
first_signal = getattr(signal, {json.dumps(signal_name)})
second_signal = getattr(signal, {json.dumps(second_signal)})
allow_second = threading.Event()
sender_done = threading.Event()
transaction_completed = False

def sender():
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {{first_signal, second_signal}})
    signal.pthread_kill(threading.get_ident(), first_signal)
    allow_second.wait(timeout=2)
    signal.pthread_kill(threading.get_ident(), second_signal)
    sender_done.set()

error = None
scratch = None
try:
    with build._translate_cleanup_signals():
        scratch = build._create_private_build_root(destination)
        try:
            with build._defer_publish_signals():
                worker = threading.Thread(target=sender)
                worker.start()
                deadline = time.monotonic() + 2
                while (
                    not getattr(build._SIGNAL_TRANSLATION_STATE, "cancelled", False)
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.001)
                allow_second.set()
                worker.join(timeout=2)
                if not sender_done.is_set():
                    raise RuntimeError("background sender did not finish")
                marker = scratch.build_root / "transaction-complete"
                marker.write_text("stable", encoding="ascii")
                marker.unlink()
                transaction_completed = True
        finally:
            build._cleanup_scratch_capability(scratch)
except build.BuildError as exc:
    error = str(exc)
print(json.dumps({{
    "entries": sorted(item.name for item in destination.iterdir()),
    "error": error,
    "senderDone": sender_done.is_set(),
    "transactionCompleted": transaction_completed,
}}))
"""

    assert _run_signal_probe(script) == {
        "entries": [],
        "error": build._INTERRUPTED_ERROR,
        "senderDone": True,
        "transactionCompleted": True,
    }


@pytest.mark.parametrize("phase", ["scratch-parent", "build-root"])
def test_private_build_root_refuses_name_cleanup_when_open_never_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    original_open = os.open

    def fail_target_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        is_target = (
            phase == "scratch-parent"
            and isinstance(path, str)
            and path.startswith(f"{build.SCRATCH_PARENT_NAME}-")
        ) or (
            phase == "build-root"
            and isinstance(path, str)
            and path.startswith("candidate-")
        )
        if is_target and dir_fd is not None:
            raise OSError(errno.EIO, "synthetic open failure /private/token")
        keyword = {} if dir_fd is None else {"dir_fd": dir_fd}
        return original_open(path, flags, mode, **keyword)

    monkeypatch.setattr(build.os, "open", fail_target_open)

    with pytest.raises(
        build.BuildError,
        match=r"^Python sidecar scratch creation cleanup failed$",
    ) as failure:
        build._create_private_build_root(destination_parent)

    assert "/private" not in str(failure.value)
    scratch = next(
        destination_parent.glob(f"{build.SCRATCH_PARENT_NAME}-*")
    )
    assert scratch.is_dir()
    if phase == "scratch-parent":
        assert list(scratch.iterdir()) == []
    else:
        candidates = list(scratch.glob("candidate-*"))
        assert len(candidates) == 1
        assert candidates[0].is_dir()


def test_unbound_random_scratch_residue_does_not_block_the_next_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    original_open = os.open
    failed_once = False

    def fail_first_scratch_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal failed_once
        if (
            not failed_once
            and isinstance(path, str)
            and path.startswith(f"{build.SCRATCH_PARENT_NAME}-")
            and dir_fd is not None
        ):
            failed_once = True
            raise OSError(errno.EIO, "synthetic first-open failure")
        keyword = {} if dir_fd is None else {"dir_fd": dir_fd}
        return original_open(path, flags, mode, **keyword)

    monkeypatch.setattr(build.os, "open", fail_first_scratch_open)
    with pytest.raises(
        build.BuildError,
        match=r"^Python sidecar scratch creation cleanup failed$",
    ):
        build._create_private_build_root(destination_parent)
    residue = list(
        destination_parent.glob(f"{build.SCRATCH_PARENT_NAME}-*")
    )
    assert len(residue) == 1

    capability = build._create_private_build_root(destination_parent)
    assert capability.scratch_parent != residue[0]
    build._cleanup_scratch_capability(capability)
    assert residue[0].is_dir()


@pytest.mark.parametrize("phase", ["scratch-parent", "build-root"])
def test_private_build_root_rejects_replacement_between_stat_and_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    original_open = os.open
    attacked = False

    def replace_before_real_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal attacked
        is_target = (
            phase == "scratch-parent"
            and isinstance(path, str)
            and path.startswith(f"{build.SCRATCH_PARENT_NAME}-")
        ) or (
            phase == "build-root"
            and isinstance(path, str)
            and path.startswith("candidate-")
        )
        if not attacked and is_target and dir_fd is not None:
            attacked = True
            os.rename(
                path,
                "held-created-object",
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
            )
            os.mkdir(path, mode=0o700, dir_fd=dir_fd)
            replacement = original_open(
                path,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=dir_fd,
            )
            try:
                marker = original_open(
                    "replacement",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    0o600,
                    dir_fd=replacement,
                )
                os.close(marker)
            finally:
                os.close(replacement)
        keyword = {} if dir_fd is None else {"dir_fd": dir_fd}
        return original_open(path, flags, mode, **keyword)

    monkeypatch.setattr(build.os, "open", replace_before_real_open)

    with pytest.raises(
        build.BuildError,
        match=r"^Python sidecar scratch creation cleanup failed$",
    ):
        build._create_private_build_root(destination_parent)

    assert attacked is True
    if phase == "scratch-parent":
        replacement = next(
            destination_parent.glob(f"{build.SCRATCH_PARENT_NAME}-*")
        )
        held = destination_parent / "held-created-object"
    else:
        scratch = next(
            destination_parent.glob(f"{build.SCRATCH_PARENT_NAME}-*")
        )
        replacement = next(scratch.glob("candidate-*"))
        held = scratch / "held-created-object"
    assert (replacement / "replacement").is_file()
    assert held.is_dir()


@pytest.mark.parametrize(
    "signal_name",
    ["SIGTERM", *(["SIGHUP"] if hasattr(signal, "SIGHUP") else [])],
)
def test_build_lifecycle_translates_real_signal_during_nonpublish_phase(
    tmp_path: Path,
    signal_name: str,
) -> None:
    output = tmp_path / signal_name / "generated"
    output.mkdir(parents=True, mode=0o755)
    script = f"""
import json
import os
import signal
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
output = Path({json.dumps(str(output))})
build.DEFAULT_STAGING = output / "sidecar"
build.DEFAULT_EVIDENCE = output / "evidence"
build._ensure_fixed_output_parent = lambda: output
build._verify_exact_toolchain_environment = lambda _environment: ({{}}, b"")
def interrupted(_environment):
    os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
build._validate_repository_state = interrupted
error = None
try:
    build.build_python_sidecar(
        destination=build.DEFAULT_STAGING,
        evidence_destination=build.DEFAULT_EVIDENCE,
        environment={{}},
    )
except build.BuildError as exc:
    error = str(exc)
print(json.dumps({{
    "error": error,
    "scratch": any(output.glob(build.SCRATCH_PARENT_NAME + "-*")),
    "entries": sorted(item.name for item in output.iterdir()),
}}))
"""

    assert _run_signal_probe(script) == {
        "error": "Python sidecar operation was interrupted after reaching a safe state",
        "scratch": False,
        "entries": [],
    }


def test_build_lifecycle_classifies_source_materialization_and_clean_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "generated"
    output.mkdir(mode=0o755)
    monkeypatch.setattr(build, "DEFAULT_STAGING", output / "sidecar")
    monkeypatch.setattr(build, "DEFAULT_EVIDENCE", output / "evidence")
    monkeypatch.setattr(build, "_ensure_fixed_output_parent", lambda: output)
    monkeypatch.setattr(
        build,
        "_verify_exact_toolchain_environment",
        lambda _environment: ({}, b""),
    )
    monkeypatch.setattr(build, "_validate_repository_state", lambda _environment: {})

    def fail_materialization(*_args: Any, **_kwargs: Any) -> None:
        raise build.BuildError("private source /token/path")

    monkeypatch.setattr(build, "_materialize_source_snapshot", fail_materialization)

    with pytest.raises(build.BuildError) as failure:
        build.build_python_sidecar(
            destination=build.DEFAULT_STAGING,
            evidence_destination=build.DEFAULT_EVIDENCE,
            environment={},
        )

    assert failure.value.primary_category == "source-materialize"
    assert failure.value.cleanup_category is None
    assert not list(output.glob(f"{build.SCRATCH_PARENT_NAME}-*"))


@pytest.mark.parametrize(
    "signal_name",
    ["SIGTERM", *(["SIGHUP"] if hasattr(signal, "SIGHUP") else [])],
)
def test_build_lifecycle_defers_real_signal_through_final_cleanup(
    tmp_path: Path,
    signal_name: str,
) -> None:
    output = tmp_path / signal_name / "generated"
    output.mkdir(parents=True, mode=0o755)
    script = f"""
import json
import os
import signal
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
output = Path({json.dumps(str(output))})
build.DEFAULT_STAGING = output / "sidecar"
build.DEFAULT_EVIDENCE = output / "evidence"
build._ensure_fixed_output_parent = lambda: output
build._verify_exact_toolchain_environment = lambda _environment: ({{}}, b"")
def primary_failure(_environment):
    raise build.BuildError("fixed primary failure")
build._validate_repository_state = primary_failure
original_cleanup = build._cleanup_scratch_capability
def interrupted_cleanup(capability):
    os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    return original_cleanup(capability)
build._cleanup_scratch_capability = interrupted_cleanup
error = None
try:
    build.build_python_sidecar(
        destination=build.DEFAULT_STAGING,
        evidence_destination=build.DEFAULT_EVIDENCE,
        environment={{}},
    )
except build.BuildError as exc:
    error = str(exc)
print(json.dumps({{
    "error": error,
    "scratch": any(output.glob(build.SCRATCH_PARENT_NAME + "-*")),
    "entries": sorted(item.name for item in output.iterdir()),
}}))
"""

    assert _run_signal_probe(script) == {
        "error": build._INTERRUPTED_ERROR,
        "scratch": False,
        "entries": [],
    }


@pytest.mark.parametrize(
    "signal_name",
    [
        "SIGINT",
        "SIGTERM",
        *(["SIGHUP"] if hasattr(signal, "SIGHUP") else []),
    ],
)
def test_signal_translation_exit_transition_never_restores_default_while_pending(
    signal_name: str,
) -> None:
    script = f"""
import json
import os
import signal
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
original = signal.pthread_sigmask
setmask_calls = 0
fired = False
def injected(how, mask):
    global setmask_calls, fired
    result = original(how, mask)
    if how == signal.SIG_SETMASK:
        setmask_calls += 1
        if setmask_calls == 2:
            fired = True
            os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    return result
signal.pthread_sigmask = injected
error = None
try:
    with build._translate_cleanup_signals():
        pass
except build.BuildError as exc:
    error = str(exc)
print(json.dumps({{"error": error, "fired": fired}}))
"""

    assert _run_signal_probe(script) == {
        "error": "Python sidecar operation was interrupted after reaching a safe state",
        "fired": True,
    }


def test_fixed_output_parent_is_created_without_following_an_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repository"
    desktop_root = repository_root / "desktop"
    desktop_root.mkdir(parents=True, mode=0o755)
    monkeypatch.setattr(build, "REPOSITORY_ROOT", repository_root)

    generated = build._ensure_fixed_output_parent()

    assert generated == desktop_root / "generated"
    assert generated.is_dir()
    assert not generated.is_symlink()

    generated.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    generated.symlink_to(outside, target_is_directory=True)
    with pytest.raises(build.BuildError, match="output parent is unsafe"):
        build._ensure_fixed_output_parent()
    assert generated.is_symlink()
    assert list(outside.iterdir()) == []


def test_build_rejects_nonfixed_output_paths_before_creating_alias_children(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)

    with pytest.raises(build.BuildError, match="fixed contract"):
        build.build_python_sidecar(
            destination=alias / "created" / "sidecar",
            evidence_destination=alias / "created" / "evidence",
            environment={},
        )

    assert not (outside / "created").exists()


def _stub_native_exec_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bootstrap,
        "_exec_target_identity",
        lambda _path: (1, 2, stat.S_IFREG | 0o755, os.geteuid(), os.getegid(), 1, 1, 1, 1),
    )


@pytest.mark.parametrize("replace_target", [False, True])
def test_native_input_exec_runner_binds_the_child_opened_target(
    tmp_path: Path,
    replace_target: bool,
) -> None:
    target = tmp_path / "target"
    target.write_text("held", encoding="ascii")
    target_descriptor = os.open(
        target,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    tool = tmp_path / "native-tool"
    tool.write_text("#!/bin/sh\ncat \"$2\"\n", encoding="ascii")
    tool.chmod(0o700)
    target_identity = audit._bound_file_identity(os.fstat(target_descriptor))
    tool_identity = bootstrap._exec_target_identity(tool)
    command = (
        sys.executable,
        "-I",
        "-c",
        audit.NATIVE_INPUT_EXEC_RUNNER,
        str(target_descriptor),
        *(str(item) for item in target_identity),
        *(str(item) for item in tool_identity),
        str(tool),
        "inspect",
        target.name,
    )
    held = tmp_path / "held-target"
    if replace_target:
        target.rename(held)
        target.write_text("replacement", encoding="ascii")
    try:
        completed = subprocess.run(
            command,
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=(target_descriptor,),
            close_fds=True,
            start_new_session=True,
            timeout=20,
            check=False,
        )
    finally:
        os.close(target_descriptor)

    if replace_target:
        assert completed.returncode == 126
        assert completed.stdout == ""
        assert completed.stderr == (
            "lcf-native-input-exec: stage=input-path errno=0\n"
        )
        assert target.read_text(encoding="ascii") == "replacement"
        assert held.read_text(encoding="ascii") == "held"
    else:
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == "held"
        assert completed.stderr == ""


def test_held_native_inventory_never_enumerates_a_replacement_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "lcf-service").write_bytes(
        b"\xcf\xfa\xed\xfe" + b"held macho"
    )
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    held = tmp_path / "held-bundle"
    root.rename(held)
    root.mkdir()
    (root / "replacement").write_bytes(b"not macho")
    try:
        inventory = audit._held_native_tree_inventory(descriptor)
    finally:
        os.close(descriptor)

    assert [(relative, kind, macho) for relative, _identity, kind, macho in inventory] == [
        ("lcf-service", "file", True),
    ]
    assert (root / "replacement").read_bytes() == b"not macho"


@pytest.mark.parametrize(
    ("command", "label"),
    [
        (("/usr/bin/otool", "-l"), "otool-load-commands"),
        (("/usr/bin/otool", "-L"), "otool-dependencies"),
        (("/usr/bin/otool", "-D"), "otool-install-name"),
        (("/usr/bin/lipo", "-archs"), "lipo-architectures"),
        (
            ("/usr/bin/codesign", "--verify", "--strict"),
            "codesign-verify",
        ),
    ],
)
def test_native_tool_failure_reports_only_a_fixed_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: tuple[str, ...],
    label: str,
) -> None:
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    _stub_native_exec_identity(monkeypatch)
    root = tmp_path / "native-root"
    root.mkdir()
    native_target = root / "other"
    native_target.write_bytes(b"synthetic macho")
    root_descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    arguments = (*command, str(native_target))

    def failed_run(
        observed_arguments: tuple[str, ...],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            observed_arguments,
            1,
            stdout="",
            stderr="token/path-must-not-leak",
        )

    monkeypatch.setattr(build, "_run_owned_command", failed_run)

    try:
        with pytest.raises(
            audit.AuditError,
            match=(
                rf"^Native inspection tool failed \(tool={label}; "
                r"target=other-macho; category=exit; code=1\)$"
            ),
        ) as failure:
            audit._run_native_tool(
                arguments,
                execution_root=root,
                execution_root_descriptor=root_descriptor,
            )
    finally:
        os.close(root_descriptor)

    assert "must-not-leak" not in str(failure.value)
    assert "/secret" not in str(failure.value)


def test_codesign_unsigned_failure_uses_only_fixed_categories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    _stub_native_exec_identity(monkeypatch)
    root = tmp_path / "native-root"
    root.mkdir()
    native_target = root / "lcf-service"
    native_target.write_bytes(b"synthetic macho")
    root_descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )

    def failed_run(
        arguments: tuple[str, ...],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            arguments,
            1,
            stdout="",
            stderr=(
                "/secret/lcf-service: code object is not signed at all; "
                "token-must-not-leak"
            ),
        )

    monkeypatch.setattr(build, "_run_owned_command", failed_run)

    try:
        with pytest.raises(
            audit.AuditError,
            match=(
                r"^Native inspection tool failed \(tool=codesign-verify; "
                r"target=entrypoint; category=unsigned; code=1\)$"
            ),
        ) as failure:
            audit._run_native_tool(
                (
                    "/usr/bin/codesign",
                    "--verify",
                    "--strict",
                    str(native_target),
                ),
                execution_root=root,
                execution_root_descriptor=root_descriptor,
            )
    finally:
        os.close(root_descriptor)

    assert "must-not-leak" not in str(failure.value)
    assert "/secret" not in str(failure.value)


def test_codesign_framework_leaf_failure_uses_only_fixed_categories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_isolation_parent(tmp_path, monkeypatch)
    source = _write_reviewed_python_framework(tmp_path / "sidecar")
    isolation = audit._prepare_isolated_framework_leaf(source)
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    _stub_native_exec_identity(monkeypatch)
    target = isolation.copy

    def failed_run(
        arguments: tuple[str, ...],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            arguments,
            1,
            stdout="",
            stderr=f"{target}: code object is not signed at all; token-must-not-leak",
        )

    monkeypatch.setattr(build, "_run_owned_command", failed_run)

    with pytest.raises(
        audit.AuditError,
        match=(
            r"^Native inspection tool failed "
            r"\(tool=codesign-verify-isolated-leaf; "
            r"target=python-framework; category=unsigned; code=1\)$"
        ),
    ) as failure:
        try:
            audit._run_native_tool(
                ("/usr/bin/codesign", "--verify", "--strict", str(target)),
                isolated_framework_leaf=isolation,
            )
        finally:
            _cleanup_test_isolation(isolation)

    assert "must-not-leak" not in str(failure.value)
    assert str(tmp_path) not in str(failure.value)


@pytest.mark.parametrize("with_capability", [False, True])
def test_three_argument_codesign_contract_is_always_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_capability: bool,
) -> None:
    _configure_test_isolation_parent(tmp_path, monkeypatch)
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    target = "/secret/_internal/Python.framework/Versions/3.13/Python"
    keyword_arguments: dict[str, Any] = {}
    isolation: audit._IsolatedFrameworkLeaf | None = None
    if with_capability:
        source = _write_reviewed_python_framework(tmp_path / "sidecar")
        isolation = audit._prepare_isolated_framework_leaf(source)
        target = str(isolation.copy)
        keyword_arguments["isolated_framework_leaf"] = isolation

    try:
        with pytest.raises(
            audit.AuditError,
            match=r"^Native inspection tool contract is invalid$",
        ):
            audit._run_native_tool(
                ("/usr/bin/codesign", "--verify", target),
                **keyword_arguments,
            )
    finally:
        if isolation is not None:
            _cleanup_test_isolation(isolation)


@pytest.mark.parametrize(
    "mutation",
    [
        "source-layout",
        "target-mismatch",
        "framework-copy",
        "public-parent",
    ],
)
def test_isolated_framework_leaf_contract_rejects_mismatched_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _configure_test_isolation_parent(tmp_path, monkeypatch)
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    source = _write_reviewed_python_framework(tmp_path / "sidecar")
    isolation = audit._prepare_isolated_framework_leaf(source)
    capability = isolation
    target = isolation.copy
    if mutation == "source-layout":
        capability = replace(
            isolation,
            source=(
                source.parent.parent / "3.12" / "Python"
            ),
        )
    elif mutation == "target-mismatch":
        target = isolation.child / "Other"
    elif mutation == "framework-copy":
        capability = replace(
            isolation,
            copy=(
                isolation.child / "Copy.framework" / "Python"
            ),
        )
        target = capability.copy
    elif mutation == "public-parent":
        capability = replace(isolation, parent=tmp_path.resolve())

    try:
        with pytest.raises(
            audit.AuditError,
            match=r"^Native inspection tool contract is invalid$",
        ):
            audit._run_native_tool(
                ("/usr/bin/codesign", "--verify", "--strict", str(target)),
                isolated_framework_leaf=capability,
            )
    finally:
        _cleanup_test_isolation(isolation)


@pytest.mark.parametrize(
    ("framework", "expected_target"),
    [
        ("Python.framework", "python-framework"),
        ("Tcl.framework", "tcl-framework"),
        ("Tk.framework", "tk-framework"),
        ("Widget.framework", "other-framework"),
    ],
)
def test_codesign_framework_failure_reports_only_a_fixed_framework_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    framework: str,
    expected_target: str,
) -> None:
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    _stub_native_exec_identity(monkeypatch)
    root = tmp_path / "native-root"
    target_path = (
        root / framework / "Versions" / "A" / framework.removesuffix(".framework")
    )
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"synthetic macho")
    target = str(target_path)
    root_descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )

    def failed_run(
        arguments: tuple[str, ...],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            arguments,
            1,
            stdout="",
            stderr=(
                f"{target}: main executable failed strict validation; "
                "token-must-not-leak"
            ),
        )

    monkeypatch.setattr(build, "_run_owned_command", failed_run)

    try:
        with pytest.raises(
            audit.AuditError,
            match=(
                r"^Native inspection tool failed \(tool=codesign-verify; "
                rf"target={expected_target}; category=strict-layout; code=1\)$"
            ),
        ) as failure:
            audit._run_native_tool(
                ("/usr/bin/codesign", "--verify", "--strict", target),
                execution_root=root,
                execution_root_descriptor=root_descriptor,
            )
    finally:
        os.close(root_descriptor)

    assert "must-not-leak" not in str(failure.value)
    assert "/secret" not in str(failure.value)


def test_native_tool_rejects_an_unreviewed_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")

    with pytest.raises(
        audit.AuditError,
        match=r"^Native inspection tool contract is invalid$",
    ):
        audit._run_native_tool(("/usr/bin/file", "--brief", "/secret/path"))


def test_native_tool_rejects_an_fd_child_path_for_external_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "lcf-service").write_bytes(b"macho")
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    try:
        target = Path("/dev/fd") / str(descriptor) / "lcf-service"
        with pytest.raises(
            audit.AuditError,
            match=r"^Native inspection tool contract is invalid$",
        ):
            audit._run_native_tool(
                ("/usr/bin/otool", "-l", str(target)),
                execution_root=root,
                execution_root_descriptor=descriptor,
            )
    finally:
        os.close(descriptor)


def test_native_tool_uses_a_held_canonical_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    target = root / "lcf-service"
    target.write_bytes(b"macho")
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    observed: dict[str, Any] = {}
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    _stub_native_exec_identity(monkeypatch)

    def checked_owner(
        arguments: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        observed["arguments"] = arguments
        observed["cwd_identity"] = (
            os.fstat(kwargs["cwd_descriptor"]).st_dev,
            os.fstat(kwargs["cwd_descriptor"]).st_ino,
        )
        observed.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, stdout="ok", stderr="")

    monkeypatch.setattr(build, "_run_owned_command", checked_owner)
    try:
        assert audit._run_native_tool(
            ("/usr/bin/otool", "-l", str(target)),
            execution_root=root,
            execution_root_descriptor=descriptor,
        ) == "ok"
    finally:
        os.close(descriptor)

    assert observed["arguments"][:4] == (
        sys.executable,
        "-I",
        "-c",
        audit.NATIVE_INPUT_EXEC_RUNNER,
    )
    assert observed["arguments"][-3:] == (
        "/usr/bin/otool",
        "-l",
        "lcf-service",
    )
    assert observed["cwd"] == root
    assert observed["cwd_identity"] == (root.stat().st_dev, root.stat().st_ino)
    assert observed["pass_fds"]
    assert observed["launcher_python"] == Path(sys.executable)
    assert "/dev/fd" not in str(observed["arguments"])


def _write_reviewed_python_framework(root: Path) -> Path:
    framework = root / "_internal" / "Python.framework"
    version = framework / "Versions" / "3.13"
    resources = version / "Resources"
    resources.mkdir(parents=True)
    leaf = version / "Python"
    leaf.write_bytes(b"synthetic signed Mach-O")
    leaf.chmod(0o755)
    (resources / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": "Python",
                "CFBundleName": "Python",
                "CFBundleIdentifier": "org.python.python",
                "CFBundlePackageType": "FMWK",
            }
        )
    )
    (framework / "Python").symlink_to("Versions/Current/Python")
    (framework / "Resources").symlink_to("Versions/Current/Resources")
    (framework / "Versions" / "Current").symlink_to("3.13")
    return leaf


def _configure_test_isolation_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    parent = tmp_path / "private-tmp"
    parent.mkdir(mode=0o700)
    parent.chmod(0o1777)
    canonical = parent.resolve()
    monkeypatch.setattr(
        audit,
        "ISOLATED_FRAMEWORK_LEAF_PARENT",
        canonical,
    )
    return canonical


def _cleanup_test_isolation(
    isolation: audit._IsolatedFrameworkLeaf,
) -> None:
    audit._cleanup_isolated_framework_leaf(
        parent=isolation.parent,
        child=isolation.child,
        parent_descriptor=isolation.parent_descriptor,
        child_descriptor=isolation.child_descriptor,
        source_descriptor=isolation.source_descriptor,
        copy_descriptor=isolation.copy_descriptor,
        child_name=isolation.child_name,
        copy_created=True,
    )


def test_python_framework_isolation_parent_is_fixed_private_tmp() -> None:
    assert audit.PRODUCTION_ISOLATION_PARENT == Path("/private/tmp")
    assert (
        audit.ISOLATED_FRAMEWORK_LEAF_PARENT
        == audit.PRODUCTION_ISOLATION_PARENT
    )


@pytest.mark.parametrize("mutation", ["mode", "symlink", "framework-parent"])
def test_python_framework_isolation_parent_rejects_unsafe_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    if mutation == "symlink":
        target = tmp_path / "real-private-tmp"
        target.mkdir(mode=0o700)
        target.chmod(0o1777)
        parent = tmp_path / "private-tmp"
        parent.symlink_to(target, target_is_directory=True)
    elif mutation == "framework-parent":
        parent = tmp_path / "Copy.FRAMEWORK" / "private-tmp"
        parent.mkdir(parents=True, mode=0o700)
        parent.chmod(0o1777)
    else:
        parent = tmp_path / "private-tmp"
        parent.mkdir(mode=0o700)
    monkeypatch.setattr(
        audit,
        "ISOLATED_FRAMEWORK_LEAF_PARENT",
        parent,
    )

    with pytest.raises(
        audit.AuditError,
        match=r"^Python framework isolation parent is unsafe$",
    ):
        audit._open_isolation_parent()


def test_python_framework_leaf_uses_strict_isolated_copy_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolation_parent = _configure_test_isolation_parent(tmp_path, monkeypatch)
    root = tmp_path / "sidecar"
    leaf = _write_reviewed_python_framework(root)
    calls: list[tuple[str, ...]] = []
    isolated_children: list[Path] = []

    def record_isolated_verification(
        arguments: tuple[str, ...],
        *,
        isolated_framework_leaf: audit._IsolatedFrameworkLeaf | None = None,
    ) -> str:
        assert isolated_framework_leaf is not None
        source = isolated_framework_leaf.source
        isolated_copy = isolated_framework_leaf.copy
        assert source == leaf
        assert isolated_copy == Path(arguments[-1])
        assert isolated_framework_leaf.parent == isolation_parent
        assert isolated_copy.read_bytes() == leaf.read_bytes()
        assert stat.S_IMODE(isolated_copy.stat().st_mode) == 0o500
        assert stat.S_IMODE(isolated_copy.parent.stat().st_mode) == 0o700
        assert os.fstat(isolated_framework_leaf.parent_descriptor)
        assert os.fstat(isolated_framework_leaf.child_descriptor)
        assert os.fstat(isolated_framework_leaf.source_descriptor)
        assert os.fstat(isolated_framework_leaf.copy_descriptor)
        assert (
            os.fstat(isolated_framework_leaf.source_descriptor).st_dev,
            os.fstat(isolated_framework_leaf.source_descriptor).st_ino,
        ) != (
            os.fstat(isolated_framework_leaf.copy_descriptor).st_dev,
            os.fstat(isolated_framework_leaf.copy_descriptor).st_ino,
        )
        assert tuple(sorted(os.listdir(isolated_framework_leaf.child_descriptor))) == (
            "Python",
        )
        assert not any(
            part.casefold().endswith(".framework")
            for part in isolated_copy.parts
        )
        isolated_children.append(isolated_copy.parent)
        calls.append(tuple(arguments[:3]))
        return ""

    monkeypatch.setattr(audit, "_run_native_tool", record_isolated_verification)

    audit._verify_code_signature(root, leaf)

    assert calls == [
        ("/usr/bin/codesign", "--verify", "--strict"),
    ]
    assert all(not child.exists() for child in isolated_children)


def test_nonframework_macho_keeps_strict_signature_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sidecar"
    root.mkdir()
    leaf = root / "lcf-service"
    leaf.write_bytes(b"synthetic signed Mach-O")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        audit,
        "_run_native_tool",
        lambda arguments, **_kwargs: calls.append(tuple(arguments)) or "",
    )

    audit._verify_code_signature(root, leaf)

    assert calls == [
        ("/usr/bin/codesign", "--verify", "--strict", str(leaf)),
    ]


@pytest.mark.parametrize(
    "relative",
    [
        "_internal/Widget.framework/Versions/A/Widget",
        "_internal/Python.framework/Versions/3.12/Python",
        "_internal/Python.framework/Versions/3.13/Other",
    ],
)
def test_unreviewed_framework_macho_cannot_use_leaf_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
) -> None:
    root = tmp_path / "sidecar"
    leaf = root.joinpath(*relative.split("/"))
    leaf.parent.mkdir(parents=True)
    leaf.write_bytes(b"synthetic signed Mach-O")
    monkeypatch.setattr(
        audit,
        "_run_native_tool",
        lambda _arguments, **_kwargs: pytest.fail("codesign must not run"),
    )

    with pytest.raises(
        audit.AuditError,
        match=r"^Mach-O uses an unreviewed framework layout$",
    ):
        audit._verify_code_signature(root, leaf)


def test_case_changed_framework_name_is_an_unreviewed_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sidecar"
    leaf = root / "_internal" / "Python.FRAMEWORK" / "Versions" / "3.13" / "Python"
    leaf.parent.mkdir(parents=True)
    leaf.write_bytes(b"synthetic signed Mach-O")
    monkeypatch.setattr(
        audit,
        "_run_native_tool",
        lambda _arguments, **_kwargs: pytest.fail("codesign must not run"),
    )

    with pytest.raises(
        audit.AuditError,
        match=r"^Mach-O uses an unreviewed framework layout$",
    ):
        audit._verify_code_signature(root, leaf)


@pytest.mark.parametrize(
    "mutation",
    [
        "current-target",
        "binary-link",
        "resources-link",
        "plist",
        "extra-top",
        "extra-version",
        "leaf-symlink",
        "leaf-hardlink",
        "plist-symlink",
        "plist-hardlink",
        "plist-oversize",
        "plist-malformed",
    ],
)
def test_reviewed_python_framework_layout_mutations_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    root = tmp_path / "sidecar"
    leaf = _write_reviewed_python_framework(root)
    framework = root / "_internal" / "Python.framework"
    if mutation == "current-target":
        current = framework / "Versions" / "Current"
        current.unlink()
        current.symlink_to("3.12")
    elif mutation == "binary-link":
        binary_link = framework / "Python"
        binary_link.unlink()
        binary_link.write_bytes(b"not a symlink")
    elif mutation == "resources-link":
        resources_link = framework / "Resources"
        resources_link.unlink()
        resources_link.symlink_to("Versions/3.12/Resources")
    elif mutation == "extra-top":
        (framework / "CodeResources").write_bytes(b"unsealed content")
    elif mutation == "extra-version":
        (framework / "Versions" / "3.12").mkdir()
    elif mutation == "leaf-symlink":
        leaf.unlink()
        outside = tmp_path / "outside-python"
        outside.write_bytes(b"replacement")
        leaf.symlink_to(outside)
    elif mutation == "leaf-hardlink":
        os.link(leaf, tmp_path / "linked-python")
    else:
        info_plist = (
            framework / "Versions" / "3.13" / "Resources" / "Info.plist"
        )
        if mutation == "plist-symlink":
            info_plist.unlink()
            outside = tmp_path / "outside-plist"
            outside.write_bytes(b"replacement")
            info_plist.symlink_to(outside)
        elif mutation == "plist-hardlink":
            os.link(info_plist, tmp_path / "linked-plist")
        elif mutation == "plist-oversize":
            info_plist.write_bytes(b"x" * (1024 * 1024 + 1))
        elif mutation == "plist-malformed":
            info_plist.write_bytes(b"not a plist")
        else:
            info_plist.write_bytes(
                plistlib.dumps(
                    {
                        "CFBundleExecutable": "Other",
                        "CFBundleName": "Python",
                        "CFBundleIdentifier": "org.python.python",
                        "CFBundlePackageType": "FMWK",
                    }
                )
            )
    monkeypatch.setattr(
        audit,
        "_run_native_tool",
        lambda _arguments, **_kwargs: pytest.fail("codesign must not run"),
    )

    with pytest.raises(audit.AuditError, match=r"Reviewed Python framework"):
        audit._verify_code_signature(root, leaf)


def test_python_framework_mutation_during_codesign_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_isolation_parent(tmp_path, monkeypatch)
    root = tmp_path / "sidecar"
    leaf = _write_reviewed_python_framework(root)

    def mutate_after_verification(
        _arguments: tuple[str, ...],
        **_kwargs: Any,
    ) -> str:
        leaf.write_bytes(b"changed after codesign")
        return ""

    monkeypatch.setattr(audit, "_run_native_tool", mutate_after_verification)

    with pytest.raises(
        audit.AuditError,
        match=r"^Reviewed Python framework changed during verification$",
    ):
        audit._verify_code_signature(root, leaf)


def test_python_framework_isolated_copy_mutation_during_codesign_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_isolation_parent(tmp_path, monkeypatch)
    root = tmp_path / "sidecar"
    leaf = _write_reviewed_python_framework(root)

    def mutate_after_verification(
        _arguments: tuple[str, ...],
        *,
        isolated_framework_leaf: audit._IsolatedFrameworkLeaf | None = None,
    ) -> str:
        assert isolated_framework_leaf is not None
        copy_descriptor = isolated_framework_leaf.copy_descriptor
        os.ftruncate(copy_descriptor, 0)
        os.pwrite(copy_descriptor, b"changed after codesign", 0)
        os.fsync(copy_descriptor)
        return ""

    monkeypatch.setattr(audit, "_run_native_tool", mutate_after_verification)

    with pytest.raises(
        audit.AuditError,
        match=(
            r"^Isolated Python framework leaf changed during verification$"
        ),
    ):
        audit._verify_code_signature(root, leaf)


@pytest.mark.parametrize("mutation", ["replacement", "extra-entry"])
def test_python_framework_cleanup_never_removes_unbound_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _configure_test_isolation_parent(tmp_path, monkeypatch)
    root = tmp_path / "sidecar"
    leaf = _write_reviewed_python_framework(root)
    observed_child: list[Path] = []

    def replace_isolation_entry(
        _arguments: tuple[str, ...],
        *,
        isolated_framework_leaf: audit._IsolatedFrameworkLeaf | None = None,
    ) -> str:
        assert isolated_framework_leaf is not None
        observed_child.append(isolated_framework_leaf.child)
        if mutation == "replacement":
            os.unlink(
                "Python",
                dir_fd=isolated_framework_leaf.child_descriptor,
            )
            replacement = os.open(
                "Python",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o500,
                dir_fd=isolated_framework_leaf.child_descriptor,
            )
            try:
                os.write(replacement, b"replacement must remain")
            finally:
                os.close(replacement)
        else:
            unexpected = os.open(
                "Unexpected",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o500,
                dir_fd=isolated_framework_leaf.child_descriptor,
            )
            try:
                os.write(unexpected, b"unexpected must remain")
            finally:
                os.close(unexpected)
        return ""

    monkeypatch.setattr(audit, "_run_native_tool", replace_isolation_entry)

    with pytest.raises(
        audit.AuditError,
        match=r"^Python framework isolation cleanup failed$",
    ):
        audit._verify_code_signature(root, leaf)

    assert len(observed_child) == 1
    child = observed_child[0]
    assert child.is_dir()
    if mutation == "replacement":
        assert (child / "Python").read_bytes() == b"replacement must remain"
    else:
        assert (child / "Unexpected").read_bytes() == b"unexpected must remain"


def test_python_framework_cleanup_without_child_dirfd_never_rmdirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _configure_test_isolation_parent(tmp_path, monkeypatch)
    parent_path, parent_descriptor = audit._open_isolation_parent()
    child_name = f"{audit.ISOLATED_FRAMEWORK_LEAF_TEMP_PREFIX}{'0' * 32}"
    os.mkdir(child_name, mode=0o700, dir_fd=parent_descriptor)
    child = parent / child_name

    with pytest.raises(
        audit.AuditError,
        match=r"^Python framework isolation cleanup failed$",
    ):
        audit._cleanup_isolated_framework_leaf(
            parent=parent_path,
            child=child,
            parent_descriptor=parent_descriptor,
            child_descriptor=None,
            source_descriptor=None,
            copy_descriptor=None,
            child_name=child_name,
            copy_created=False,
        )

    assert child.is_dir()


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


def test_install_root_fingerprint_excludes_only_exact_dynamic_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "python-root"
    (root / "bin").mkdir(parents=True)
    stdlib = root / "lib" / "python3.13"
    stdlib.mkdir(parents=True)
    (stdlib / "json.py").write_text("reviewed = True\n", encoding="ascii")
    baseline = build.fingerprint_install_root(root)

    site_packages = stdlib / "site-packages"
    site_packages.mkdir()
    (site_packages / "unlocked.py").write_text("dynamic = True\n", encoding="ascii")
    (root / "bin" / "pip").write_text("dynamic script\n", encoding="ascii")
    exclusions = ("bin/pip", "lib/python3.13/site-packages")
    assert build.fingerprint_install_root(
        root,
        excluded_paths=exclusions,
    ) == baseline

    (stdlib / "unexpected.py").write_text("drift = True\n", encoding="ascii")
    assert build.fingerprint_install_root(
        root,
        excluded_paths=exclusions,
    ) != baseline


def test_install_root_fingerprint_ignores_casefolded_bytecode_caches(
    tmp_path: Path,
) -> None:
    root = tmp_path / "python-root"
    stdlib = root / "lib" / "python3.13"
    stdlib.mkdir(parents=True)
    (stdlib / "json.py").write_text("reviewed = True\n", encoding="ascii")
    baseline = build.fingerprint_install_root(root)

    cache = stdlib / "__PYCACHE__"
    cache.mkdir()
    (cache / "JSON.CPYTHON-313.PYC").write_bytes(b"cached bytecode\n")
    assert build.fingerprint_install_root(root) == baseline


@pytest.mark.parametrize(
    "excluded_paths",
    (
        ("../escape",),
        ("z", "a"),
        ("lib", "lib/python3.13"),
    ),
)
def test_install_root_fingerprint_rejects_unsafe_dynamic_exclusions(
    tmp_path: Path,
    excluded_paths: tuple[str, ...],
) -> None:
    root = tmp_path / "python-root"
    root.mkdir()
    (root / "reviewed").write_text("payload\n", encoding="ascii")

    with pytest.raises(build.BuildError, match="fingerprint exclusion"):
        build.fingerprint_install_root(root, excluded_paths=excluded_paths)


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


def test_otool_dependencies_remove_one_matching_install_name() -> None:
    output = """/private/build/libfixture.dylib:
\t@rpath/libfixture.dylib (compatibility version 1.0.0, current version 1.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1345.120.2)
"""

    raw_dependencies = audit._parse_otool_dependencies(output)

    assert raw_dependencies == [
        "@rpath/libfixture.dylib",
        "/usr/lib/libSystem.B.dylib",
    ]
    assert audit._reconcile_otool_dependencies(
        raw_dependencies,
        "@rpath/libfixture.dylib",
    ) == ["/usr/lib/libSystem.B.dylib"]


def test_otool_dependencies_reject_install_name_missing_from_listing() -> None:
    install_name = "/secret/token-must-not-leak.dylib"

    with pytest.raises(
        audit.AuditError,
        match=(
            r"^Mach-O install name does not match dependency evidence exactly once$"
        ),
    ) as failure:
        audit._reconcile_otool_dependencies(
            [
                "/usr/lib/libSystem.B.dylib",
                "/secret/token-must-not-leak.dylib.backup",
            ],
            install_name,
        )

    assert install_name not in str(failure.value)
    assert "/secret" not in str(failure.value)


def test_otool_dependencies_reject_duplicate_self_reference() -> None:
    output = """/private/build/libfixture.dylib:
\t@rpath/libfixture.dylib (compatibility version 1.0.0, current version 1.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1345.120.2)
\t@rpath/libfixture.dylib (compatibility version 1.0.0, current version 1.0.0)
"""

    raw_dependencies = audit._parse_otool_dependencies(output)

    assert raw_dependencies.count("@rpath/libfixture.dylib") == 2
    with pytest.raises(
        audit.AuditError,
        match=(
            r"^Mach-O install name does not match dependency evidence exactly once$"
        ),
    ):
        audit._reconcile_otool_dependencies(
            raw_dependencies,
            "@rpath/libfixture.dylib",
        )


def test_otool_dependencies_canonicalize_executable_without_install_name() -> None:
    dependencies = [
        "@rpath/libfixture.dylib",
        "/usr/lib/libSystem.B.dylib",
        "@rpath/libfixture.dylib",
    ]

    assert audit._parse_otool_install_name("/private/build/lcf-service:\n") is None
    assert audit._reconcile_otool_dependencies(dependencies, None) == [
        "/usr/lib/libSystem.B.dylib",
        "@rpath/libfixture.dylib",
    ]


@pytest.mark.parametrize(
    "output",
    [
        "",
        "/secret/path-without-header-terminator\n",
        "/secret/libfixture.dylib:\n@rpath/one.dylib\n@rpath/two.dylib\n",
    ],
)
def test_otool_install_name_rejects_malformed_evidence(output: str) -> None:
    with pytest.raises(
        audit.AuditError,
        match=r"^Malformed Mach-O install name evidence$",
    ) as failure:
        audit._parse_otool_install_name(output)

    assert "/secret" not in str(failure.value)


def _mock_macho_scan_tools(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dependencies: str,
    install_name: str,
) -> None:
    outputs = {
        "-l": """/secret/lcf-service:
Load command 0
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 14.0
""",
        "-L": dependencies,
        "-D": install_name,
        "-archs": "arm64\n",
    }

    def inspect(arguments: tuple[str, ...], **_kwargs: Any) -> str:
        return outputs[arguments[1]]

    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(audit, "is_macho", lambda _path: True)
    monkeypatch.setattr(
        audit,
        "_verify_code_signature",
        lambda _root, _path, **_kwargs: None,
    )
    monkeypatch.setattr(audit, "_run_native_tool", inspect)


def test_scan_macho_inventory_pairs_install_name_with_raw_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sidecar"
    root.mkdir()
    (root / audit.EXPECTED_EXECUTABLE).write_bytes(
        b"\xcf\xfa\xed\xfe" + b"synthetic Mach-O"
    )
    _mock_macho_scan_tools(
        monkeypatch,
        dependencies="""/secret/lcf-service:
\t@rpath/libfixture.dylib (compatibility version 1.0.0, current version 1.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1345.120.2)
""",
        install_name="/secret/lcf-service:\n@rpath/libfixture.dylib\n",
    )

    records = audit.scan_macho_inventory(root)

    assert records[0]["dylibs"] == ["/usr/lib/libSystem.B.dylib"]
    assert records[0]["installName"] == "@rpath/libfixture.dylib"


def test_scan_macho_inventory_pairing_failure_does_not_leak_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "secret-sidecar"
    root.mkdir()
    (root / audit.EXPECTED_EXECUTABLE).write_bytes(
        b"\xcf\xfa\xed\xfe" + b"synthetic Mach-O"
    )
    install_name = "@rpath/token-must-not-leak.dylib"
    _mock_macho_scan_tools(
        monkeypatch,
        dependencies="""/secret/lcf-service:
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1345.120.2)
""",
        install_name=f"/secret/lcf-service:\n{install_name}\n",
    )

    with pytest.raises(
        audit.AuditError,
        match=(
            r"^Mach-O install name does not match dependency evidence exactly once$"
        ),
    ) as failure:
        audit.scan_macho_inventory(root)

    assert str(root) not in str(failure.value)
    assert install_name not in str(failure.value)


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


def test_native_inventory_policy_rejects_dependency_equal_to_install_name(
    tmp_path: Path,
) -> None:
    root, records = _native_fixture(tmp_path)
    records[1]["dylibs"].append("@rpath/libfixture.dylib")

    with pytest.raises(
        audit.AuditError,
        match=(
            r"^Mach-O dependency evidence includes its install name$"
        ),
    ):
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
    monkeypatch.setattr(
        audit,
        "_validate_manifest_shape",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(audit, "_validate_components", lambda _root, _manifest: None)
    monkeypatch.setattr(
        audit,
        "_validate_toolchain_evidence_artifact",
        lambda *_args, **_kwargs: None,
    )
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


def test_atomic_publish_noreplace_succeeds_when_destination_is_absent(
    tmp_path: Path,
) -> None:
    candidate_parent = tmp_path / "scratch"
    destination_parent = tmp_path / "generated"
    candidate_parent.mkdir()
    destination_parent.mkdir()
    candidate = candidate_parent / "candidate"
    destination = destination_parent / "published"
    candidate.mkdir()
    (candidate / "state").write_text("new", encoding="utf-8")
    verified: list[Path] = []

    def verifier(path: Path) -> None:
        verified.append(path)
        assert (path / "state").read_text(encoding="utf-8") == "new"

    build.publish_staging(candidate, destination, verifier=verifier)

    assert verified == [candidate, destination]
    assert not candidate.exists()
    assert (destination / "state").read_text(encoding="utf-8") == "new"


def test_atomic_publish_noreplace_rolls_back_to_absence(
    tmp_path: Path,
) -> None:
    candidate_parent = tmp_path / "scratch"
    destination_parent = tmp_path / "generated"
    candidate_parent.mkdir()
    destination_parent.mkdir()
    candidate = candidate_parent / "candidate"
    destination = destination_parent / "published"
    candidate.mkdir()
    (candidate / "state").write_text("new", encoding="utf-8")

    def verifier(path: Path) -> None:
        if path == destination:
            raise RuntimeError("simulated post-swap audit failure")

    with pytest.raises(build.BuildError, match="post-swap audit"):
        build.publish_staging(candidate, destination, verifier=verifier)

    assert (candidate / "state").read_text(encoding="utf-8") == "new"
    assert not destination.exists()


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


def _publish_topology_paths(
    tmp_path: Path,
    topology: str,
) -> tuple[Path, Path, bool]:
    existing = topology.startswith("existing-")
    same_parent = topology.endswith("-same")
    if same_parent:
        candidate_parent = destination_parent = tmp_path / "shared"
        candidate_parent.mkdir()
    else:
        candidate_parent = tmp_path / "scratch"
        destination_parent = tmp_path / "generated"
        candidate_parent.mkdir()
        destination_parent.mkdir()
    candidate = candidate_parent / "candidate"
    destination = destination_parent / "published"
    candidate.mkdir()
    (candidate / "state").write_text("new", encoding="utf-8")
    if existing:
        destination.mkdir()
        (destination / "state").write_text("old", encoding="utf-8")
    return candidate, destination, existing


@pytest.mark.parametrize(
    "topology",
    [
        "existing-same",
        "existing-different",
        "absent-same",
        "absent-different",
    ],
)
def test_atomic_publish_failure_rolls_back_all_parent_topologies(
    tmp_path: Path,
    topology: str,
) -> None:
    candidate, destination, existing = _publish_topology_paths(tmp_path, topology)

    def verifier(path: Path) -> None:
        if path == destination:
            raise RuntimeError("synthetic post-audit secret /private/token")

    with pytest.raises(
        build.BuildError,
        match=r"^Published staging failed its post-swap audit$",
    ) as failure:
        build.publish_staging(candidate, destination, verifier=verifier)

    assert "/private" not in str(failure.value)
    assert (candidate / "state").read_text(encoding="utf-8") == "new"
    if existing:
        assert (destination / "state").read_text(encoding="utf-8") == "old"
    else:
        assert not destination.exists()
    assert not list(tmp_path.rglob(".lcf-delete-*"))
    assert not list(tmp_path.rglob(".lcf-old-*"))


@pytest.mark.parametrize(
    "topology",
    [
        "existing-same",
        "existing-different",
        "absent-same",
        "absent-different",
    ],
)
@pytest.mark.parametrize("outcome", ["commit", "rollback"])
@pytest.mark.parametrize(
    "signal_name",
    ["SIGTERM", *(["SIGHUP"] if hasattr(signal, "SIGHUP") else [])],
)
def test_atomic_publish_real_signal_reaches_only_a_stable_topology(
    tmp_path: Path,
    topology: str,
    outcome: str,
    signal_name: str,
) -> None:
    probe_root = tmp_path / f"{topology}-{outcome}-{signal_name}"
    probe_root.mkdir()
    script = f"""
import json
import os
import signal
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
root = Path({json.dumps(str(probe_root))})
topology = {json.dumps(topology)}
existing = topology.startswith("existing-")
same_parent = topology.endswith("-same")
if same_parent:
    candidate_parent = destination_parent = root / "shared"
    candidate_parent.mkdir()
else:
    candidate_parent = root / "scratch"
    destination_parent = root / "generated"
    candidate_parent.mkdir()
    destination_parent.mkdir()
candidate = candidate_parent / "candidate"
destination = destination_parent / "published"
candidate.mkdir()
(candidate / "state").write_text("new", encoding="utf-8")
if existing:
    destination.mkdir()
    (destination / "state").write_text("old", encoding="utf-8")
fired = False
def verifier(path):
    global fired
    if path == destination:
        fired = True
        os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
        if {json.dumps(outcome)} == "rollback":
            raise RuntimeError("synthetic post-audit secret /private/token")
error = None
try:
    build.publish_staging(candidate, destination, verifier=verifier)
except build.BuildError as exc:
    error = str(exc)
candidate_state = (candidate / "state").read_text(encoding="utf-8") if candidate.exists() else None
destination_state = (destination / "state").read_text(encoding="utf-8") if destination.exists() else None
print(json.dumps({{
    "candidate": candidate_state,
    "destination": destination_state,
    "error": error,
    "fired": fired,
    "quarantine": sorted(path.name for path in root.rglob(".lcf-*-*")),
}}))
"""

    result = _run_signal_probe(script)

    assert result["fired"] is True
    assert result["quarantine"] == []
    assert "/private" not in result["error"]
    if outcome == "commit":
        assert result["candidate"] is None
        assert result["destination"] == "new"
        assert result["error"] == (
            "Python sidecar operation was interrupted after reaching a safe state"
        )
    else:
        assert result["candidate"] == "new"
        assert result["destination"] == (
            "old" if topology.startswith("existing-") else None
        )
        assert result["error"] == build._INTERRUPTED_ERROR


@pytest.mark.parametrize(
    "existing,phase",
    [
        (False, "before-ownership-prepare"),
        (False, "after-ownership-prepare"),
        (True, "before-ownership-prepare"),
        (True, "after-ownership-prepare"),
        (True, "during-retained-cleanup"),
    ],
)
@pytest.mark.parametrize(
    "signal_name",
    ["SIGINT", "SIGTERM", *( ["SIGHUP"] if hasattr(signal, "SIGHUP") else [] )],
)
def test_owned_bundle_publish_defers_real_signal_through_transfer_and_scratch_cleanup(
    tmp_path: Path,
    existing: bool,
    phase: str,
    signal_name: str,
) -> None:
    probe_root = tmp_path / f"{existing}-{phase}-{signal_name}"
    probe_root.mkdir()
    script = f"""
import json
import os
import signal
import stat
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
root = Path({json.dumps(str(probe_root))})
lifecycle_parent = root / "lifecycle"
lifecycle_parent.mkdir(mode=0o755)
destination = lifecycle_parent / "published"
if {existing!r}:
    destination.mkdir(mode=0o700)
    (destination / "state").write_text("old", encoding="utf-8")
scratch = build._create_private_build_root(lifecycle_parent)
build._validate_source_snapshot = lambda capability: capability.build_root
parent_descriptor, parent_snapshot = build._create_bound_child_directory(
    parent_descriptor=scratch.build_root_descriptor,
    parent_path=scratch.build_root,
    name="dist",
    mode=0o700,
    error_message="fixture",
)
candidate_descriptor, candidate_snapshot = build._create_bound_child_directory(
    parent_descriptor=parent_descriptor,
    parent_path=scratch.build_root / "dist",
    name="lcf-service",
    mode=0o700,
    error_message="fixture",
)
bundle = build._create_bundle_capability(
    scratch,
    dist_root=scratch.build_root / "dist",
    dist_descriptor=parent_descriptor,
    dist_snapshot=parent_snapshot,
    descriptor=candidate_descriptor,
    created_snapshot=candidate_snapshot,
)
candidate = bundle.path
(build._bundle_capability_path(bundle) / "state").write_text("new", encoding="utf-8")
build._validate_bundle_capability(scratch, accept_tree_changes=True)
fired = False
original_prepare = build._prepare_published_bundle_ownership
original_rollback = build._rollback_bound_directory
def interrupted_prepare(scratch_capability, bundle_capability, publish_capability):
    global fired
    if {json.dumps(phase)} == "before-ownership-prepare":
        fired = True
        os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    result = original_prepare(
        scratch_capability,
        bundle_capability,
        publish_capability,
    )
    if {json.dumps(phase)} == "after-ownership-prepare":
        fired = True
        os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    return result
def interrupted_rollback(**kwargs):
    global fired
    if (
        {json.dumps(phase)} == "during-retained-cleanup"
        and kwargs.get("name") == "lcf-service"
    ):
        fired = True
        os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    return original_rollback(**kwargs)
build._prepare_published_bundle_ownership = interrupted_prepare
build._rollback_bound_directory = interrupted_rollback
primary = None
error = None
bundle_fds_closed = False
accepted_destination_fd_open = False
try:
    with build._translate_cleanup_signals():
        try:
            build._publish_owned_bundle(
                scratch,
                bundle,
                destination,
                verifier=lambda path: (
                    (path / "state").read_text(encoding="utf-8") == "new"
                    or (_ for _ in ()).throw(AssertionError("state"))
                ),
            )
        except BaseException as exc:
            primary = exc
        accepted_destination_fd_open = stat.S_ISDIR(
            os.fstat(scratch.destination_parent_descriptor).st_mode
        )
        with build._defer_publish_signals(preserve_error=primary):
            build._finish_scratch_lifecycle(scratch, primary)
        if primary is not None:
            raise primary
except build.BuildError as exc:
    error = str(exc)
finally:
    build._prepare_published_bundle_ownership = original_prepare
    build._rollback_bound_directory = original_rollback
for descriptor in (candidate_descriptor, parent_descriptor):
    try:
        os.fstat(descriptor)
    except OSError:
        continue
    break
else:
    bundle_fds_closed = True
print(json.dumps({{
    "acceptedDestinationFdOpen": accepted_destination_fd_open,
    "bundleClosed": bundle.closed and scratch.bundle is None,
    "bundleFdsClosed": bundle_fds_closed,
    "candidateExists": candidate.exists(),
    "destination": (destination / "state").read_text(encoding="utf-8") if destination.exists() else None,
    "error": error,
    "fired": fired,
    "quarantine": sorted(path.name for path in root.rglob(".lcf-*-*")),
    "scratch": any(lifecycle_parent.glob(build.SCRATCH_PARENT_NAME + "-*")),
}}))
"""

    assert _run_signal_probe(script) == {
        "acceptedDestinationFdOpen": True,
        "bundleClosed": True,
        "bundleFdsClosed": True,
        "candidateExists": False,
        "destination": "new",
        "error": "Python sidecar operation was interrupted after reaching a safe state",
        "fired": True,
        "quarantine": [],
        "scratch": False,
    }


@pytest.mark.parametrize(
    "existing,phase",
    [
        (False, "before-ownership-prepare"),
        (False, "after-ownership-prepare"),
        (True, "before-ownership-prepare"),
        (True, "after-ownership-prepare"),
        (True, "during-retained-cleanup"),
    ],
)
@pytest.mark.parametrize(
    "signal_name",
    ["SIGINT", "SIGTERM", *( ["SIGHUP"] if hasattr(signal, "SIGHUP") else [] )],
)
def test_owned_evidence_publish_defers_real_signal_through_transfer_and_scratch_cleanup(
    tmp_path: Path,
    existing: bool,
    phase: str,
    signal_name: str,
) -> None:
    output = tmp_path / f"{existing}-{phase}-{signal_name}"
    output.mkdir(mode=0o755)
    script = f"""
import json
import os
import signal
import sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import build_python_sidecar as build
output = Path({json.dumps(str(output))})
destination = output / "published-evidence"
if {existing!r}:
    destination.mkdir(mode=0o700)
    (destination / "pyinstaller.log").write_text("old log\\n", encoding="utf-8")
scratch = build._create_private_build_root(output)
build._validate_source_snapshot = lambda capability: capability.build_root
evidence = build._create_failure_evidence_capability(scratch)
(evidence.path / "pyinstaller.log").write_text("new safe log\\n", encoding="utf-8")
evidence = build._seal_failure_evidence_capability(scratch)
evidence_descriptor = evidence.descriptor
fired = False
original_prepare = build._prepare_published_evidence_ownership
original_rollback = build._rollback_bound_directory
def interrupted_prepare(scratch_capability, evidence_capability, publish_capability):
    global fired
    if {json.dumps(phase)} == "before-ownership-prepare":
        fired = True
        os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    result = original_prepare(
        scratch_capability,
        evidence_capability,
        publish_capability,
    )
    if {json.dumps(phase)} == "after-ownership-prepare":
        fired = True
        os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    return result
def interrupted_rollback(**kwargs):
    global fired
    if (
        {json.dumps(phase)} == "during-retained-cleanup"
        and kwargs.get("name") == "evidence"
    ):
        fired = True
        os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
    return original_rollback(**kwargs)
build._prepare_published_evidence_ownership = interrupted_prepare
build._rollback_bound_directory = interrupted_rollback
primary = None
error = None
try:
    with build._translate_cleanup_signals():
        try:
            build._preserve_evidence(
                evidence,
                destination,
                scratch=scratch,
            )
        except BaseException as exc:
            primary = exc
        with build._defer_publish_signals(preserve_error=primary):
            build._finish_scratch_lifecycle(scratch, primary)
        if primary is not None:
            raise primary
except build.BuildError as exc:
    error = str(exc)
finally:
    build._prepare_published_evidence_ownership = original_prepare
    build._rollback_bound_directory = original_rollback
try:
    os.fstat(evidence_descriptor)
except OSError:
    evidence_fd_closed = True
else:
    evidence_fd_closed = False
print(json.dumps({{
    "destination": (destination / "pyinstaller.log").read_text(encoding="utf-8"),
    "error": error,
    "evidenceClosed": evidence.closed and scratch.evidence is None,
    "evidenceFdClosed": evidence_fd_closed,
    "fired": fired,
    "poisoned": scratch.poisoned,
    "quarantine": sorted(path.name for path in output.rglob(".lcf-*-*")),
    "scratch": any(output.glob(build.SCRATCH_PARENT_NAME + "-*")),
}}))
"""

    assert _run_signal_probe(script) == {
        "destination": "new safe log\n",
        "error": "Python sidecar operation was interrupted after reaching a safe state",
        "evidenceClosed": True,
        "evidenceFdClosed": True,
        "fired": True,
        "poisoned": False,
        "quarantine": [],
        "scratch": False,
    }


def test_scratch_capability_rejects_parent_rename_recreate_and_preserves_replacement(
    tmp_path: Path,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(destination_parent)
    os.rename(
        capability.scratch_parent_name,
        "captured-scratch",
        src_dir_fd=capability.destination_parent_descriptor,
        dst_dir_fd=capability.destination_parent_descriptor,
    )
    os.mkdir(
        capability.scratch_parent_name,
        mode=0o700,
        dir_fd=capability.destination_parent_descriptor,
    )

    with pytest.raises(build.BuildError, match="(?:destination|scratch) parent changed"):
        build._refresh_scratch_capability(capability)
    with pytest.raises(
        build.BuildError,
        match=r"^Python sidecar scratch cleanup failed$",
    ):
        build._cleanup_scratch_capability(capability)

    replacement = destination_parent / capability.scratch_parent_name
    assert replacement.is_dir()
    assert not replacement.is_symlink()
    assert (destination_parent / "captured-scratch").is_dir()


def test_scratch_capability_rejects_child_aba_even_when_inode_returns(
    tmp_path: Path,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(destination_parent)
    os.rename(
        capability.build_root_name,
        "detached-candidate",
        src_dir_fd=capability.scratch_parent_descriptor,
        dst_dir_fd=capability.scratch_parent_descriptor,
    )
    os.rename(
        "detached-candidate",
        capability.build_root_name,
        src_dir_fd=capability.scratch_parent_descriptor,
        dst_dir_fd=capability.scratch_parent_descriptor,
    )

    with pytest.raises(build.BuildError, match="scratch parent changed"):
        build._refresh_scratch_capability(capability)
    with pytest.raises(build.BuildError, match="scratch cleanup failed"):
        build._cleanup_scratch_capability(capability)


def test_scratch_cleanup_refuses_same_name_replacement(
    tmp_path: Path,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(destination_parent)
    os.rename(
        capability.build_root_name,
        "captured-candidate",
        src_dir_fd=capability.scratch_parent_descriptor,
        dst_dir_fd=capability.scratch_parent_descriptor,
    )
    os.mkdir(
        capability.build_root_name,
        mode=0o700,
        dir_fd=capability.scratch_parent_descriptor,
    )
    replacement = capability.scratch_parent / capability.build_root_name
    (replacement / "do-not-delete").write_text("replacement", encoding="utf-8")

    with pytest.raises(build.BuildError, match="scratch cleanup failed"):
        build._cleanup_scratch_capability(capability)

    assert (replacement / "do-not-delete").read_text(encoding="utf-8") == (
        "replacement"
    )
    assert (capability.scratch_parent / "captured-candidate").is_dir()


@pytest.mark.parametrize("leaf_kind", ["file", "directory"])
def test_remove_tree_quarantines_and_restores_a_racing_leaf_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    leaf_kind: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    victim = root / "victim"
    if leaf_kind == "file":
        victim.write_text("held", encoding="utf-8")
    else:
        victim.mkdir(mode=0o700)
        (victim / "held").write_text("held", encoding="utf-8")
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    original_rename = build._rename_noreplace_at
    attacked = False

    def replace_before_quarantine(
        source_parent: int,
        source_name: str,
        destination_parent: int,
        destination_name: str,
    ) -> None:
        nonlocal attacked
        if not attacked and source_name == "victim":
            attacked = True
            os.rename(
                "victim",
                "held-victim",
                src_dir_fd=source_parent,
                dst_dir_fd=source_parent,
            )
            if leaf_kind == "file":
                replacement = os.open(
                    "victim",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    0o600,
                    dir_fd=source_parent,
                )
                try:
                    os.write(replacement, b"replacement")
                finally:
                    os.close(replacement)
            else:
                os.mkdir("victim", mode=0o700, dir_fd=source_parent)
                replacement_directory = os.open(
                    "victim",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
                    dir_fd=source_parent,
                )
                try:
                    marker = os.open(
                        "replacement",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                        0o600,
                        dir_fd=replacement_directory,
                    )
                    os.close(marker)
                finally:
                    os.close(replacement_directory)
        original_rename(
            source_parent,
            source_name,
            destination_parent,
            destination_name,
        )

    monkeypatch.setattr(build, "_rename_noreplace_at", replace_before_quarantine)
    try:
        with pytest.raises(build._CleanupBlockedError, match="cleanup refused"):
            build._remove_tree_contents(
                descriptor,
                error_message="cleanup refused",
            )
    finally:
        os.close(descriptor)

    assert attacked is True
    if leaf_kind == "file":
        assert victim.read_text(encoding="utf-8") == "replacement"
        assert (root / "held-victim").read_text(encoding="utf-8") == "held"
    else:
        assert (victim / "replacement").is_file()
        assert (root / "held-victim" / "held").read_text(
            encoding="utf-8"
        ) == "held"
    assert not list(root.glob(".lcf-delete-*"))


def test_remove_tree_restores_owner_write_before_directory_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    victim = root / "victim"
    victim.mkdir(mode=0o700)
    (victim / "state").write_text("held", encoding="utf-8")
    (victim / "state").chmod(0o400)
    victim.chmod(0o500)
    assert stat.S_IMODE(victim.stat().st_mode) == 0o500
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    victim_descriptor = os.open(
        victim,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    original_rename = build._rename_noreplace_at
    observed_modes: list[int] = []

    def darwin_permission_probe(
        source_parent: int,
        source_name: str,
        destination_parent: int,
        destination_name: str,
    ) -> None:
        info = os.stat(source_name, dir_fd=source_parent, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            observed_modes.append(stat.S_IMODE(info.st_mode))
            if not stat.S_IMODE(info.st_mode) & stat.S_IWUSR:
                raise PermissionError(errno.EACCES, "Darwin directory rename denied")
        original_rename(
            source_parent,
            source_name,
            destination_parent,
            destination_name,
        )

    monkeypatch.setattr(build, "_rename_noreplace_at", darwin_permission_probe)
    try:
        build._remove_tree_contents(descriptor, error_message="cleanup refused")
    finally:
        os.close(victim_descriptor)
        os.close(descriptor)

    assert observed_modes[0] == 0o700
    assert not victim.exists()
    assert not list(root.iterdir())


def test_scratch_root_final_gate_preserves_a_quarantine_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(destination_parent)
    (capability.build_root / "state").write_text("held", encoding="utf-8")
    original = build._remove_verified_quarantine_leaf
    attacked = False

    def replace_at_root_final_gate(
        parent_descriptor: int,
        *,
        original_name: str,
        quarantine_name: str,
        expected: os.stat_result,
        directory: bool,
        error_message: str,
    ) -> None:
        nonlocal attacked
        if not attacked and quarantine_name.startswith(".lcf-acquisition-"):
            attacked = True
            os.rename(
                quarantine_name,
                "held-root",
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.mkdir(quarantine_name, mode=0o700, dir_fd=parent_descriptor)
            replacement = os.open(
                quarantine_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
                dir_fd=parent_descriptor,
            )
            try:
                marker = os.open(
                    "replacement",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    0o600,
                    dir_fd=replacement,
                )
                os.close(marker)
            finally:
                os.close(replacement)
        original(
            parent_descriptor,
            original_name=original_name,
            quarantine_name=quarantine_name,
            expected=expected,
            directory=directory,
            error_message=error_message,
        )

    monkeypatch.setattr(
        build,
        "_remove_verified_quarantine_leaf",
        replace_at_root_final_gate,
    )

    with pytest.raises(build.BuildError, match="scratch cleanup failed"):
        build._cleanup_scratch_capability(capability)

    assert attacked is True
    assert (capability.build_root / "replacement").is_file()
    assert (capability.scratch_parent / "held-root").is_dir()


@pytest.mark.parametrize("leaf_kind", ["file", "directory"])
def test_remove_tree_final_gate_retains_a_quarantine_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    leaf_kind: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    victim = root / "victim"
    if leaf_kind == "file":
        victim.write_text("held", encoding="utf-8")
    else:
        victim.mkdir(mode=0o700)
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    original = build._remove_verified_quarantine_leaf
    attacked = False

    def replace_at_final_gate(
        parent_descriptor: int,
        *,
        original_name: str,
        quarantine_name: str,
        expected: os.stat_result,
        directory: bool,
        error_message: str,
    ) -> None:
        nonlocal attacked
        if not attacked:
            attacked = True
            os.rename(
                quarantine_name,
                "held-final-object",
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            if leaf_kind == "file":
                replacement = os.open(
                    quarantine_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    0o600,
                    dir_fd=parent_descriptor,
                )
                try:
                    os.write(replacement, b"replacement")
                finally:
                    os.close(replacement)
            else:
                os.mkdir(quarantine_name, mode=0o700, dir_fd=parent_descriptor)
                replacement = os.open(
                    quarantine_name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
                    dir_fd=parent_descriptor,
                )
                try:
                    marker = os.open(
                        "replacement",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                        0o600,
                        dir_fd=replacement,
                    )
                    os.close(marker)
                finally:
                    os.close(replacement)
        original(
            parent_descriptor,
            original_name=original_name,
            quarantine_name=quarantine_name,
            expected=expected,
            directory=directory,
            error_message=error_message,
        )

    monkeypatch.setattr(build, "_remove_verified_quarantine_leaf", replace_at_final_gate)
    try:
        with pytest.raises(build._CleanupBlockedError, match="cleanup refused"):
            build._remove_tree_contents(descriptor, error_message="cleanup refused")
    finally:
        os.close(descriptor)

    assert attacked is True
    if leaf_kind == "file":
        assert victim.read_text(encoding="utf-8") == "replacement"
        assert (root / "held-final-object").read_text(encoding="utf-8") == "held"
    else:
        assert (victim / "replacement").is_file()
        assert (root / "held-final-object").is_dir()


def test_atomic_publish_absent_race_is_noreplace_and_preserves_intruder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    destination = tmp_path / "published"
    candidate.mkdir()
    (candidate / "state").write_text("new", encoding="utf-8")
    original = build._rename_noreplace_at

    def race(
        source_parent: int,
        source_name: str,
        destination_parent: int,
        destination_name: str,
    ) -> None:
        os.mkdir(destination_name, mode=0o755, dir_fd=destination_parent)
        descriptor = os.open(
            destination_name,
            os.O_RDONLY | os.O_DIRECTORY,
            dir_fd=destination_parent,
        )
        try:
            marker = os.open(
                "intruder",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=descriptor,
            )
            os.close(marker)
        finally:
            os.close(descriptor)
        original(
            source_parent,
            source_name,
            destination_parent,
            destination_name,
        )

    monkeypatch.setattr(build, "_rename_noreplace_at", race)

    with pytest.raises(build.BuildError, match="candidate failed verification"):
        build.publish_staging(candidate, destination, verifier=lambda _: None)

    assert (candidate / "state").read_text(encoding="utf-8") == "new"
    assert (destination / "intruder").is_file()


def test_atomic_publish_refuses_rollback_after_destination_replacement(
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
            destination.rename(tmp_path / "displaced-new")
            destination.mkdir()
            (destination / "intruder").write_text("keep", encoding="utf-8")
            raise RuntimeError("secret=/private/path")

    with pytest.raises(
        build.BuildError,
        match=r"^Published staging rollback safety check failed$",
    ) as failure:
        build.publish_staging(candidate, destination, verifier=verifier)

    assert "/private/path" not in str(failure.value)
    assert (destination / "intruder").read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "displaced-new" / "state").read_text(
        encoding="utf-8"
    ) == "new"
    assert (candidate / "state").read_text(encoding="utf-8") == "old"


def test_atomic_publish_old_destination_cleanup_refuses_replacement(
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
            candidate.rename(tmp_path / "displaced-old")
            candidate.mkdir()
            (candidate / "intruder").write_text("keep", encoding="utf-8")

    with pytest.raises(
        build.BuildError,
        match=r"^Published staging old destination cleanup failed$",
    ):
        build.publish_staging(candidate, destination, verifier=verifier)

    assert (destination / "state").read_text(encoding="utf-8") == "new"
    assert (candidate / "intruder").read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "displaced-old" / "state").read_text(
        encoding="utf-8"
    ) == "old"


def test_primary_and_cleanup_failure_is_fixed_and_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(destination_parent)
    primary = build.BuildError(
        "primary token /private/primary",
        primary_category="source-materialize",
    )

    def cleanup_failure(_capability: Any) -> None:
        raise build.BuildError(
            "cleanup token /private/cleanup",
            cleanup_category="build-root-quarantine",
        )

    monkeypatch.setattr(build, "_cleanup_scratch_capability", cleanup_failure)

    with pytest.raises(
        build.BuildError,
        match=r"^Python sidecar build failed and scratch cleanup failed$",
    ) as failure:
        build._finish_scratch_lifecycle(capability, primary)

    assert "token" not in str(failure.value)
    assert "/private" not in str(failure.value)
    assert failure.value.primary_category == "source-materialize"
    assert failure.value.cleanup_category == "build-root-quarantine"
    build._close_scratch_descriptors(capability)


def test_non_build_primary_keeps_its_fixed_stage_through_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(destination_parent)
    primary = build._bind_failure_categories(
        RuntimeError("primary token /private/primary"),
        primary="final-audit",
    )

    def cleanup_failure(_capability: Any) -> None:
        raise build.BuildError(
            "cleanup token /private/cleanup",
            cleanup_category="scratch-root-quarantine",
        )

    monkeypatch.setattr(build, "_cleanup_scratch_capability", cleanup_failure)
    with pytest.raises(build.BuildError) as failure:
        build._finish_scratch_lifecycle(capability, primary)

    assert failure.value.primary_category == "final-audit"
    assert failure.value.cleanup_category == "scratch-root-quarantine"
    assert "token" not in str(failure.value)
    assert "/private" not in str(failure.value)
    build._close_scratch_descriptors(capability)


def test_signal_during_post_swap_audit_rolls_back_before_propagation(
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
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        build.publish_staging(candidate, destination, verifier=verifier)

    assert (candidate / "state").read_text(encoding="utf-8") == "new"
    assert (destination / "state").read_text(encoding="utf-8") == "old"


def test_poisoned_scratch_is_closed_but_intentionally_preserved(
    tmp_path: Path,
) -> None:
    destination_parent = tmp_path / "generated"
    destination_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(destination_parent)
    marker = capability.build_root / "untrusted-replacement"
    marker.write_text("preserve", encoding="utf-8")
    capability.poisoned = True

    with pytest.raises(
        build.BuildError,
        match=r"^Python sidecar build failed and scratch cleanup failed$",
    ):
        build._finish_scratch_lifecycle(
            capability,
            build._CleanupBlockedError("publish cleanup blocked"),
        )

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert capability.scratch_parent.is_dir()
    assert capability.closed is True


def test_failure_evidence_rejects_symlink_without_publishing(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "pyinstaller.log").write_text("safe log\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (evidence / "warn-lcf-service.txt").symlink_to(outside)
    destination = tmp_path / "published-evidence"

    with pytest.raises(build.BuildError, match="candidate failed verification"):
        build._preserve_evidence(evidence, destination)

    assert not destination.exists()
    assert (evidence / "warn-lcf-service.txt").is_symlink()


def test_pyinstaller_evidence_is_text_limited_and_sanitized(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "warn-lcf-service.txt").write_text(
        f"warning in {tmp_path}/secret\n",
        encoding="utf-8",
    )
    (work / "xref-lcf-service.html").write_text("private source", encoding="utf-8")
    (work / "Analysis-00.toc").write_text("private tuple", encoding="utf-8")
    (work / "other.txt").write_text("not reviewed", encoding="utf-8")
    destination = tmp_path / "evidence"
    build_root = tmp_path / "build-root"
    source_root = build_root / "source-snapshot"
    install_root = tmp_path / "python"

    build._collect_pyinstaller_evidence(
        work_root=work,
        log_text=f"build={build_root} source={source_root} python={install_root}",
        destination=destination,
        build_root=build_root,
        install_root=install_root,
        source_root=source_root,
    )

    assert sorted(path.name for path in destination.iterdir()) == [
        "pyinstaller.log",
        "warn-lcf-service.txt",
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in destination.iterdir()
    )
    assert str(tmp_path) not in combined
    assert "$BUILD_ROOT" in combined
    assert "$SOURCE_SNAPSHOT" in combined
    assert "$PYTHON_INSTALL_ROOT" in combined


def _create_exact_git_fixture(root: Path) -> tuple[str, str]:
    root.mkdir()
    environment = build._isolated_git_environment()

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["/usr/bin/git", *arguments],
            cwd=root,
            env=environment,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.stdout.strip()

    git("init", "--quiet")
    (root / "README.md").write_text("reviewed source\n", encoding="utf-8")
    package = root / "backend" / "packaging"
    package.mkdir(parents=True)
    executable = package / "fixture.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    git("add", "--all")
    git(
        "-c",
        "user.name=LCF Test",
        "-c",
        "user.email=lcf-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    return git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")


def test_git_provenance_overrides_hostile_local_worktree_and_excludes(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    outside = tmp_path / "outside"
    outside.mkdir()
    excludes = tmp_path / "local-excludes"
    excludes.write_text("ignored.txt\n", encoding="utf-8")
    environment = build._isolated_git_environment()
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repository),
            "config",
            "--local",
            "core.worktree",
            str(outside),
        ],
        env=environment,
        check=True,
    )
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repository),
            "config",
            "--local",
            "core.excludesFile",
            str(excludes),
        ],
        env=environment,
        check=True,
    )

    assert build._git_output(
        "rev-parse",
        "--show-toplevel",
        repository_root=repository,
    ) == str(repository)
    (repository / "ignored.txt").write_text("must remain visible\n", encoding="utf-8")
    with pytest.raises(
        build.BuildError,
        match=r"^Git repository local configuration is unsafe$",
    ):
        build._validate_repository_state(
            {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
            repository_root=repository,
        )


def _fixture_git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", *arguments],
        cwd=repository,
        env=build._isolated_git_environment(),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def test_git_filter_configuration_is_rejected_without_executing_the_filter(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _create_exact_git_fixture(repository)
    (repository / ".gitattributes").write_text(
        "README.md filter=hostile\n",
        encoding="utf-8",
    )
    _fixture_git(repository, "add", ".gitattributes")
    _fixture_git(
        repository,
        "-c",
        "user.name=LCF Test",
        "-c",
        "user.email=lcf-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "attributes",
    )
    commit = _fixture_git(repository, "rev-parse", "HEAD")
    tree = _fixture_git(repository, "rev-parse", "HEAD^{tree}")
    marker = tmp_path / "filter-executed"
    _fixture_git(
        repository,
        "config",
        "filter.hostile.clean",
        f"/bin/sh -c 'touch {marker}; cat'",
    )

    with pytest.raises(
        build.BuildError,
        match=r"^Git repository local configuration is unsafe$",
    ):
        build._validate_repository_state(
            {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
            repository_root=repository,
        )

    assert not marker.exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("include.path", "/tmp/unreviewed-git-config"),
        ("includeIf.onbranch:main.path", "/tmp/unreviewed-git-config"),
        ("diff.hostile.command", "/bin/false"),
        ("merge.hostile.driver", "/bin/false %O %A %B"),
        ("url.file:///tmp/attacker/.insteadOf", "https://example.invalid/"),
        ("core.attributesFile", "/tmp/unreviewed-attributes"),
        ("core.excludesFile", "/tmp/unreviewed-excludes"),
        ("core.fsmonitor", "/bin/false"),
        ("core.hooksPath", "/tmp/unreviewed-hooks"),
    ],
)
def test_git_local_execution_and_visibility_keys_are_rejected(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    repository = tmp_path / "repository"
    _create_exact_git_fixture(repository)
    _fixture_git(repository, "config", "--local", key, value)

    with pytest.raises(
        build.BuildError,
        match=r"^Git repository local configuration is unsafe$",
    ):
        build._validate_local_git_configuration(repository_root=repository)


@pytest.mark.parametrize(
    "flag",
    ["--assume-unchanged", "--skip-worktree"],
)
def test_git_index_hidden_flags_cannot_conceal_tracked_byte_drift(
    tmp_path: Path,
    flag: str,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    _fixture_git(repository, "update-index", flag, "README.md")
    (repository / "README.md").write_text("concealed drift\n", encoding="utf-8")

    with pytest.raises(build.BuildError, match=r"^Git index state is unsafe$"):
        build._validate_repository_state(
            {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
            repository_root=repository,
        )


@pytest.mark.parametrize("name", ["attributes", "exclude"])
def test_git_info_attributes_and_excludes_must_be_comment_only(
    tmp_path: Path,
    name: str,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    (repository / ".git" / "info" / name).write_text(
        "*.secret unsafe-local-rule\n",
        encoding="utf-8",
    )

    with pytest.raises(
        build.BuildError,
        match=r"^Git repository local attributes or excludes are unsafe$",
    ):
        build._validate_repository_state(
            {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
            repository_root=repository,
        )


@pytest.mark.parametrize(
    "relative",
    [
        Path("info") / "grafts",
        Path("objects") / "info" / "alternates",
        Path("objects") / "info" / "http-alternates",
    ],
)
def test_git_info_object_overrides_must_be_empty(
    tmp_path: Path,
    relative: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    override = repository / ".git" / relative
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("unreviewed-object-source\n", encoding="utf-8")

    with pytest.raises(
        build.BuildError,
        match=r"^Git repository local attributes or excludes are unsafe$",
    ):
        build._validate_repository_state(
            {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
            repository_root=repository,
        )


def test_actions_checkout_gc_configuration_has_one_exact_safe_value(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    _fixture_git(repository, "config", "--local", "gc.auto", "0")

    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )

    assert state["repositoryCommit"] == commit
    _fixture_git(repository, "config", "--local", "gc.auto", "1")
    with pytest.raises(
        build.BuildError,
        match=r"^Git repository local configuration is unsafe$",
    ):
        build._validate_repository_state(
            {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
            repository_root=repository,
        )


def test_git_provenance_drops_host_process_git_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    injected = tmp_path / "injected"
    injected.mkdir()
    for name, value in {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.worktree",
        "GIT_CONFIG_VALUE_0": str(injected),
        "GIT_INDEX_FILE": str(tmp_path / "attacker-index"),
        "GIT_OBJECT_DIRECTORY": str(tmp_path / "attacker-objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(tmp_path / "alternate-objects"),
    }.items():
        monkeypatch.setenv(name, value)

    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )

    assert state["repositoryCommit"] == commit
    isolated = build._isolated_git_environment()
    assert not set(isolated).intersection(
        {
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_KEY_0",
            "GIT_CONFIG_VALUE_0",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        }
    )


def test_git_replace_refs_cannot_rebind_the_reviewed_commit_tree(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    (repository / "README.md").write_text("replacement commit\n", encoding="utf-8")
    _fixture_git(repository, "add", "README.md")
    _fixture_git(
        repository,
        "-c",
        "user.name=LCF Test",
        "-c",
        "user.email=lcf-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "replacement",
    )
    replacement = _fixture_git(repository, "rev-parse", "HEAD")
    _fixture_git(repository, "replace", commit, replacement)
    _fixture_git(repository, "reset", "--hard", "--quiet", commit)

    replace_enabled_environment = build._isolated_git_environment()
    replace_enabled_environment.pop("GIT_NO_REPLACE_OBJECTS")
    replaced = subprocess.run(
        ["/usr/bin/git", "show", f"{commit}:README.md"],
        cwd=repository,
        env=replace_enabled_environment,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert replaced.stdout == "replacement commit\n"

    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    assert state["repositoryCommit"] == commit
    assert (repository / "README.md").read_text(encoding="utf-8") == (
        "reviewed source\n"
    )


def test_tracked_worktree_rejects_a_group_writable_parent_directory(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    (repository / "backend").chmod(0o775)

    with pytest.raises(
        build.BuildError,
        match=r"^Tracked worktree differs from the selected commit$",
    ):
        build._validate_repository_state(
            {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
            repository_root=repository,
        )


@pytest.mark.skipif(os.geteuid() != 0, reason="requires a real foreign owner")
def test_tracked_worktree_rejects_a_foreign_owned_parent_directory(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    parent = repository / "backend"
    original = parent.stat()
    try:
        os.chown(parent, 1, original.st_gid)
    except OSError:
        pytest.skip("filesystem rejects a foreign uid")
    try:
        with pytest.raises(
            build.BuildError,
            match=r"^Tracked worktree differs from the selected commit$",
        ):
            build._validate_repository_state(
                {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
                repository_root=repository,
            )
    finally:
        os.chown(parent, original.st_uid, original.st_gid)


def test_exact_source_snapshot_is_tree_bound_read_only_and_live_mutation_independent(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    environment = {
        "LCF_SOURCE_SHA": commit,
        "LCF_SOURCE_TREE": tree,
    }
    state = build._validate_repository_state(
        environment,
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(output_parent)
    snapshot = build._materialize_source_snapshot(
        capability,
        state,
        repository_root=repository,
    )

    assert (snapshot / "README.md").read_text(encoding="utf-8") == (
        "reviewed source\n"
    )
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o500
    assert stat.S_IMODE((snapshot / "README.md").stat().st_mode) == 0o444
    assert stat.S_IMODE(
        (snapshot / "backend" / "packaging" / "fixture.sh").stat().st_mode
    ) == 0o555
    live = repository / "README.md"
    original = live.read_bytes()
    live.write_bytes(b"transient attacker bytes\n")
    live.write_bytes(original)
    assert build._validate_source_snapshot(capability) == snapshot
    assert (snapshot / "README.md").read_bytes() == original
    build._cleanup_scratch_capability(capability)
    assert not list(output_parent.glob(f"{build.SCRATCH_PARENT_NAME}-*"))


@pytest.mark.parametrize("link_model", ["subdirectories", "entries"])
def test_source_inventory_accepts_one_consistent_directory_link_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    link_model: str,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(output_parent)
    snapshot = build._materialize_source_snapshot(
        capability,
        state,
        repository_root=repository,
    )
    descriptor = capability.source_snapshot_descriptor
    assert descriptor is not None

    link_counts: dict[tuple[int, int], int] = {}
    directories = [snapshot, *(path for path in snapshot.rglob("*") if path.is_dir())]
    for directory in directories:
        info = directory.stat()
        children = tuple(directory.iterdir())
        link_counts[(info.st_dev, info.st_ino)] = 2 + (
            sum(child.is_dir() for child in children)
            if link_model == "subdirectories"
            else len(children)
        )

    class LinkCountView:
        def __init__(self, value: os.stat_result, links: int) -> None:
            self._value = value
            self.st_nlink = links

        def __getattr__(self, name: str) -> Any:
            return getattr(self._value, name)

    original_fstat = os.fstat
    original_stat = os.stat

    def with_link_count(value: os.stat_result) -> os.stat_result | LinkCountView:
        links = link_counts.get((value.st_dev, value.st_ino))
        return value if links is None else LinkCountView(value, links)

    with monkeypatch.context() as patch:
        patch.setattr(
            build.os,
            "fstat",
            lambda file_descriptor: with_link_count(original_fstat(file_descriptor)),
        )
        patch.setattr(
            build.os,
            "stat",
            lambda path, *args, **kwargs: with_link_count(
                original_stat(path, *args, **kwargs)
            ),
        )
        records = build._verify_source_inventory(
            descriptor,
            state["sourceInventory"],
            error_message="source inventory rejected",
        )

    assert len(records) == len(state["sourceInventory"]) + 2
    build._cleanup_scratch_capability(capability)
    assert not list(output_parent.glob(f"{build.SCRATCH_PARENT_NAME}-*"))


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin/APFS stat")
def test_darwin_apfs_directory_link_count_includes_immediate_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "apfs-link-model"
    root.mkdir()
    assert root.stat().st_nlink == 2
    (root / "file").write_bytes(b"reviewed")
    assert root.stat().st_nlink == 3
    (root / "directory").mkdir()
    assert root.stat().st_nlink == 4


def test_source_inventory_rejects_mixed_directory_link_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(output_parent)
    snapshot = build._materialize_source_snapshot(
        capability,
        state,
        repository_root=repository,
    )
    descriptor = capability.source_snapshot_descriptor
    assert descriptor is not None

    link_counts: dict[tuple[int, int], int] = {}
    directories = [snapshot, *(path for path in snapshot.rglob("*") if path.is_dir())]
    for directory in directories:
        info = directory.stat()
        children = tuple(directory.iterdir())
        link_counts[(info.st_dev, info.st_ino)] = 2 + (
            len(children)
            if directory == snapshot
            else sum(child.is_dir() for child in children)
        )

    class LinkCountView:
        def __init__(self, value: os.stat_result, links: int) -> None:
            self._value = value
            self.st_nlink = links

        def __getattr__(self, name: str) -> Any:
            return getattr(self._value, name)

    original_fstat = os.fstat
    original_stat = os.stat

    def with_link_count(value: os.stat_result) -> os.stat_result | LinkCountView:
        links = link_counts.get((value.st_dev, value.st_ino))
        return value if links is None else LinkCountView(value, links)

    with monkeypatch.context() as patch:
        patch.setattr(
            build.os,
            "fstat",
            lambda file_descriptor: with_link_count(original_fstat(file_descriptor)),
        )
        patch.setattr(
            build.os,
            "stat",
            lambda path, *args, **kwargs: with_link_count(
                original_stat(path, *args, **kwargs)
            ),
        )
        with pytest.raises(build.BuildError, match="source inventory rejected"):
            build._verify_source_inventory(
                descriptor,
                state["sourceInventory"],
                error_message="source inventory rejected",
            )

    build._cleanup_scratch_capability(capability)


def test_source_consumer_inherits_fd_root_across_path_replacement_window(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(output_parent)
    source_root = build._materialize_source_snapshot(
        capability,
        state,
        repository_root=repository,
    )
    lexical = capability.source_snapshot
    descriptor = capability.source_snapshot_descriptor
    assert lexical is not None
    assert descriptor is not None
    assert source_root == Path("/dev/fd") / str(descriptor)
    assert (os.stat(source_root).st_dev, os.stat(source_root).st_ino) == (
        os.fstat(descriptor).st_dev,
        os.fstat(descriptor).st_ino,
    )

    os.rename(
        build.SOURCE_SNAPSHOT_NAME,
        "held-source",
        src_dir_fd=capability.build_root_descriptor,
        dst_dir_fd=capability.build_root_descriptor,
    )
    os.mkdir(
        build.SOURCE_SNAPSHOT_NAME,
        mode=0o700,
        dir_fd=capability.build_root_descriptor,
    )
    replacement_descriptor = os.open(
        build.SOURCE_SNAPSHOT_NAME,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=capability.build_root_descriptor,
    )
    try:
        replacement_file = os.open(
            "README.md",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
            dir_fd=replacement_descriptor,
        )
        try:
            os.write(replacement_file, b"replacement source\n")
        finally:
            os.close(replacement_file)
    finally:
        os.close(replacement_descriptor)

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json,sys; from pathlib import Path; "
                    "print(json.dumps({'argument': Path(sys.argv[1]).read_text(), "
                    "'cwd': Path('README.md').read_text()}))"
                ),
                str(source_root / "README.md"),
            ],
            cwd=source_root,
            pass_fds=(descriptor,),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        assert json.loads(completed.stdout) == {
            "argument": "reviewed source\n",
            "cwd": "reviewed source\n",
        }
        assert completed.stderr == ""
    finally:
        os.rename(
            build.SOURCE_SNAPSHOT_NAME,
            "discarded-source",
            src_dir_fd=capability.build_root_descriptor,
            dst_dir_fd=capability.build_root_descriptor,
        )
        os.rename(
            "held-source",
            build.SOURCE_SNAPSHOT_NAME,
            src_dir_fd=capability.build_root_descriptor,
            dst_dir_fd=capability.build_root_descriptor,
        )
        discarded_descriptor = os.open(
            "discarded-source",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=capability.build_root_descriptor,
        )
        try:
            os.unlink("README.md", dir_fd=discarded_descriptor)
        finally:
            os.close(discarded_descriptor)
        os.rmdir("discarded-source", dir_fd=capability.build_root_descriptor)
        build._cleanup_scratch_capability(capability)


def test_source_snapshot_first_open_replacement_is_refused_and_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(output_parent)
    original_open = os.open
    attacked = False

    def replace_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal attacked
        if (
            not attacked
            and path == build.SOURCE_SNAPSHOT_NAME
            and dir_fd == capability.build_root_descriptor
            and flags & os.O_DIRECTORY
        ):
            attacked = True
            os.rename(
                build.SOURCE_SNAPSHOT_NAME,
                "detached-created-source",
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
            )
            os.mkdir(build.SOURCE_SNAPSHOT_NAME, mode=0o700, dir_fd=dir_fd)
        keyword_arguments = {} if dir_fd is None else {"dir_fd": dir_fd}
        return original_open(path, flags, mode, **keyword_arguments)

    monkeypatch.setattr(build.os, "open", replace_before_open)
    with pytest.raises(
        build._CleanupBlockedError,
        match=r"^Exact Git source snapshot could not be materialized$",
    ):
        build._materialize_source_snapshot(
            capability,
            state,
            repository_root=repository,
        )

    assert attacked is True
    assert capability.poisoned is True
    for name in (build.SOURCE_SNAPSHOT_NAME, "detached-created-source"):
        assert stat.S_ISDIR(
            os.stat(
                name,
                dir_fd=capability.build_root_descriptor,
                follow_symlinks=False,
            ).st_mode
        )
    build._close_scratch_descriptors(capability)


def test_sealed_evidence_consumers_ignore_root_replacement_and_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    scratch = build._create_private_build_root(output_parent)
    source_root = build._materialize_source_snapshot(
        scratch,
        state,
        repository_root=repository,
    )
    work = tmp_path / "work"
    work.mkdir()
    reviewed_warning = "missing module named 'reviewed.module' - optional\n"
    (work / "warn-lcf-service.txt").write_text(
        reviewed_warning,
        encoding="utf-8",
    )
    evidence = build._collect_pyinstaller_evidence(
        work_root=work,
        log_text="reviewed producer log\n",
        destination=scratch.build_root / "evidence",
        build_root=scratch.build_root,
        install_root=tmp_path / "python",
        source_root=source_root,
        scratch=scratch,
    )
    assert evidence is not None
    held_file_identities = {
        (path.stat().st_dev, path.stat().st_ino)
        for path in evidence.path.rglob("*")
        if path.is_file()
    }
    original_read = os.read
    attacked = False

    def replace_root_during_held_read(descriptor: int, length: int) -> bytes:
        nonlocal attacked
        info = os.fstat(descriptor)
        if not attacked and (info.st_dev, info.st_ino) in held_file_identities:
            attacked = True
            parent = scratch.build_root_descriptor
            os.rename(
                "evidence",
                "held-evidence",
                src_dir_fd=parent,
                dst_dir_fd=parent,
            )
            os.mkdir("evidence", mode=0o700, dir_fd=parent)
            replacement = os.open(
                "evidence",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            try:
                for name, payload in (
                    ("pyinstaller.log", b"replacement log\n"),
                    ("warn-lcf-service.txt", b"replacement warning\n"),
                ):
                    leaf = os.open(
                        name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                        0o600,
                        dir_fd=replacement,
                    )
                    try:
                        os.write(leaf, payload)
                    finally:
                        os.close(leaf)
                payload = original_read(descriptor, length)
                os.unlink("pyinstaller.log", dir_fd=replacement)
                os.unlink("warn-lcf-service.txt", dir_fd=replacement)
            finally:
                os.close(replacement)
            os.rmdir("evidence", dir_fd=parent)
            os.rename(
                "held-evidence",
                "evidence",
                src_dir_fd=parent,
                dst_dir_fd=parent,
            )
            return payload
        return original_read(descriptor, length)

    monkeypatch.setattr(build.os, "read", replace_root_during_held_read)
    with pytest.raises(build._CleanupBlockedError, match="evidence changed"):
        build._consume_failure_evidence(
            scratch,
            evidence,
            error_message="evidence changed",
        )

    assert attacked is True
    assert scratch.poisoned is True
    assert (evidence.path / "warn-lcf-service.txt").read_text(
        encoding="utf-8"
    ) == reviewed_warning
    assert not (tmp_path / "bundle-evidence").exists()
    build._close_scratch_descriptors(scratch)


def _create_test_bundle_capability(
    tmp_path: Path,
    *,
    existing_destination: bool = False,
) -> tuple[build._ScratchCapability, build._BundleCapability, Path]:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    if existing_destination:
        destination = output_parent / "published"
        destination.mkdir(mode=0o700)
        (destination / "state").write_text("old", encoding="utf-8")
    scratch = build._create_private_build_root(output_parent)
    build._materialize_source_snapshot(
        scratch,
        state,
        repository_root=repository,
    )
    dist_descriptor, dist_snapshot = build._create_bound_child_directory(
        parent_descriptor=scratch.build_root_descriptor,
        parent_path=scratch.build_root,
        name="dist",
        mode=0o700,
        error_message="bundle fixture failed",
    )
    bundle_descriptor, bundle_snapshot = build._create_bound_child_directory(
        parent_descriptor=dist_descriptor,
        parent_path=scratch.build_root / "dist",
        name="lcf-service",
        mode=0o700,
        error_message="bundle fixture failed",
    )
    capability = build._create_bundle_capability(
        scratch,
        dist_root=scratch.build_root / "dist",
        dist_descriptor=dist_descriptor,
        dist_snapshot=dist_snapshot,
        descriptor=bundle_descriptor,
        created_snapshot=bundle_snapshot,
    )
    return scratch, capability, output_parent


@pytest.mark.parametrize(
    "target_name",
    ["dist", "work", "pyinstaller-config", "tmp", "lcf-service"],
)
def test_pyinstaller_first_open_replacement_poison_closes_and_preserves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    scratch = build._create_private_build_root(output_parent)
    build._materialize_source_snapshot(
        scratch,
        state,
        repository_root=repository,
    )
    original_open = os.open
    opened_children: list[int] = []
    attacked = False

    def replace_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal attacked
        if (
            not attacked
            and path == target_name
            and dir_fd is not None
            and flags & os.O_DIRECTORY
        ):
            attacked = True
            os.rename(
                target_name,
                f"detached-{target_name}",
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
            )
            os.mkdir(target_name, mode=0o700, dir_fd=dir_fd)
        keyword_arguments = {} if dir_fd is None else {"dir_fd": dir_fd}
        descriptor = original_open(path, flags, mode, **keyword_arguments)
        if (
            isinstance(path, str)
            and path
            in {"dist", "work", "pyinstaller-config", "tmp", "lcf-service"}
            and flags & os.O_DIRECTORY
        ):
            opened_children.append(descriptor)
        return descriptor

    monkeypatch.setattr(build.os, "open", replace_before_open)
    with pytest.raises(build._CleanupBlockedError):
        build._prepare_pyinstaller_capabilities(scratch)

    assert attacked is True
    assert scratch.poisoned is True
    for descriptor in opened_children:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    parent = (
        scratch.build_root / "dist"
        if target_name == "lcf-service"
        else scratch.build_root
    )
    assert (parent / target_name).is_dir()
    assert (parent / f"detached-{target_name}").is_dir()
    build._close_scratch_descriptors(scratch)

    # A fail-closed random invocation never makes the next independent build
    # rediscover or delete its residue.
    second = build._create_private_build_root(output_parent)
    build._cleanup_scratch_capability(second)


def test_bundle_ownership_transfers_only_after_post_acquisition_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    scratch = build._create_private_build_root(output_parent)
    build._materialize_source_snapshot(
        scratch,
        state,
        repository_root=repository,
    )
    original_validate = build._validate_source_snapshot
    validation_calls = 0

    def fail_post_acquisition(
        capability: build._ScratchCapability,
    ) -> Path:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            raise build.BuildError("synthetic post-acquisition failure")
        return original_validate(capability)

    bundle_descriptor: int | None = None
    original_create = build._create_bundle_capability

    def capture_bundle_descriptor(*args: Any, **kwargs: Any) -> Any:
        nonlocal bundle_descriptor
        bundle_descriptor = kwargs["descriptor"]
        return original_create(*args, **kwargs)

    original_close = os.close
    sentinel_descriptor: int | None = None
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()

    def reuse_closed_bundle_descriptor(descriptor: int) -> None:
        nonlocal sentinel_descriptor
        original_close(descriptor)
        if descriptor == bundle_descriptor and sentinel_descriptor is None:
            sentinel_descriptor = os.open(
                sentinel,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            assert sentinel_descriptor == descriptor

    monkeypatch.setattr(build, "_validate_source_snapshot", fail_post_acquisition)
    monkeypatch.setattr(build, "_create_bundle_capability", capture_bundle_descriptor)
    monkeypatch.setattr(build.os, "close", reuse_closed_bundle_descriptor)
    with pytest.raises(
        build._CleanupBlockedError,
        match=r"^PyInstaller bundle capability could not be acquired$",
    ):
        build._prepare_pyinstaller_capabilities(scratch)

    assert validation_calls == 2
    assert scratch.bundle is None
    assert scratch.poisoned is False
    assert tuple(sorted(item.name for item in scratch.build_root.iterdir())) == (
        build.SOURCE_SNAPSHOT_NAME,
    )
    assert sentinel_descriptor == bundle_descriptor
    assert sentinel_descriptor is not None
    build._cleanup_scratch_capability(scratch)
    assert stat.S_ISDIR(os.fstat(sentinel_descriptor).st_mode)
    original_close(sentinel_descriptor)


@pytest.mark.parametrize("name", ["work", "pyinstaller-config", "tmp"])
@pytest.mark.parametrize("phase", ["before-producer", "after-producer"])
def test_pyinstaller_producer_roots_reject_rename_recreate_restore_in_each_phase(
    tmp_path: Path,
    name: str,
    phase: str,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    scratch = build._create_private_build_root(output_parent)
    build._materialize_source_snapshot(
        scratch,
        state,
        repository_root=repository,
    )
    _bundle, producers = build._prepare_pyinstaller_capabilities(scratch)
    capability = producers.directories[name]
    if phase == "after-producer":
        marker = os.open(
            "producer-output",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
            dir_fd=capability.descriptor,
        )
        os.close(marker)

    detached = f"detached-{name}"
    os.rename(
        name,
        detached,
        src_dir_fd=scratch.build_root_descriptor,
        dst_dir_fd=scratch.build_root_descriptor,
    )
    os.mkdir(name, mode=0o700, dir_fd=scratch.build_root_descriptor)
    os.rmdir(name, dir_fd=scratch.build_root_descriptor)
    os.rename(
        detached,
        name,
        src_dir_fd=scratch.build_root_descriptor,
        dst_dir_fd=scratch.build_root_descriptor,
    )

    with pytest.raises(
        build._CleanupBlockedError,
        match=r"^producer root changed$",
    ):
        build._revalidate_pyinstaller_producer_capabilities(
            scratch,
            producers,
            accept_tree_changes=phase == "after-producer",
            error_message="producer root changed",
        )

    assert scratch.poisoned is True
    assert os.fstat(capability.descriptor).st_ino == capability.snapshot.inode
    build._close_pyinstaller_producer_capabilities(scratch, producers)
    build._close_scratch_descriptors(scratch)


def test_bundle_capability_precedes_producer_and_fd_consumers_ignore_root_aba(
    tmp_path: Path,
) -> None:
    scratch, capability, _output_parent = _create_test_bundle_capability(tmp_path)
    assert capability.tree_snapshot == ()
    held_root = build._bundle_capability_path(capability)
    (held_root / "state").write_text("reviewed", encoding="utf-8")
    build._validate_bundle_capability(scratch, accept_tree_changes=True)

    os.rename(
        capability.name,
        "held-bundle",
        src_dir_fd=capability.parent_descriptor,
        dst_dir_fd=capability.parent_descriptor,
    )
    os.mkdir(capability.name, mode=0o700, dir_fd=capability.parent_descriptor)
    replacement = os.open(
        capability.name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=capability.parent_descriptor,
    )
    try:
        leaf = os.open(
            "state",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
            dir_fd=replacement,
        )
        try:
            os.write(leaf, b"replacement")
        finally:
            os.close(leaf)
    finally:
        os.close(replacement)
    try:
        verified_root = build._verify_held_bundle_tree(
            capability,
            error_message="bundle changed",
        )
        assert (verified_root / "state").read_text(encoding="utf-8") == "reviewed"
        inventory = audit.build_file_inventory(verified_root)
        assert [item["path"] for item in inventory] == ["state"]
        assert inventory[0]["sha256"] == hashlib.sha256(b"reviewed").hexdigest()
    finally:
        replacement = os.open(
            capability.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=capability.parent_descriptor,
        )
        try:
            os.unlink("state", dir_fd=replacement)
        finally:
            os.close(replacement)
        os.rmdir(capability.name, dir_fd=capability.parent_descriptor)
        os.rename(
            "held-bundle",
            capability.name,
            src_dir_fd=capability.parent_descriptor,
            dst_dir_fd=capability.parent_descriptor,
        )

    with pytest.raises(build._CleanupBlockedError, match="bundle capability changed"):
        build._validate_bundle_capability(scratch)
    assert scratch.poisoned is True
    build._close_scratch_descriptors(scratch)


def test_publish_reuses_the_held_bundle_candidate(
    tmp_path: Path,
) -> None:
    scratch, capability, output_parent = _create_test_bundle_capability(tmp_path)
    held_root = build._bundle_capability_path(capability)
    (held_root / "state").write_text("reviewed", encoding="utf-8")
    build._validate_bundle_capability(scratch, accept_tree_changes=True)
    destination = output_parent / "published"
    observed: list[str] = []

    def verifier(_candidate: Path) -> None:
        root = build._verify_held_bundle_tree(
            capability,
            error_message="bundle changed",
        )
        observed.append((root / "state").read_text(encoding="utf-8"))

    build.publish_staging(
        capability.path,
        destination,
        verifier=verifier,
        held_candidate=capability,
    )
    build._close_published_bundle_capability(scratch)
    build._accept_destination_parent_metadata(scratch)

    assert observed == ["reviewed", "reviewed"]
    assert not capability.path.exists()
    assert (destination / "state").read_text(encoding="utf-8") == "reviewed"
    build._cleanup_scratch_capability(scratch)


@pytest.mark.parametrize("existing", [False, True], ids=["absent", "present"])
def test_final_bundle_verifier_binds_pre_and_post_publish_candidate_paths(
    tmp_path: Path,
    existing: bool,
) -> None:
    scratch, capability, output_parent = _create_test_bundle_capability(
        tmp_path,
        existing_destination=existing,
    )
    (capability.path / "state").write_text("new", encoding="utf-8")
    build._validate_bundle_capability(scratch, accept_tree_changes=True)
    source_candidate = capability.path
    destination = output_parent / "published"
    observed: list[tuple[Path, str]] = []

    def verifier(candidate: Path) -> None:
        assert build._verify_held_bundle_candidate(
            capability,
            candidate,
            error_message="bundle changed",
        ) == candidate
        observed.append(
            (candidate, (candidate / "state").read_text(encoding="utf-8"))
        )
        build._verify_held_bundle_candidate(
            capability,
            candidate,
            error_message="bundle changed",
        )

    build._publish_owned_bundle(
        scratch,
        capability,
        destination,
        verifier=verifier,
    )

    assert observed == [
        (source_candidate, "new"),
        (destination, "new"),
    ]
    assert (destination / "state").read_text(encoding="utf-8") == "new"
    if existing:
        retained = scratch.retained_published_directories[-1]
        assert (retained.parent_path / retained.name / "state").read_text(
            encoding="utf-8"
        ) == "old"
    else:
        assert not source_candidate.exists()

    implementation = inspect.getsource(build._build_python_sidecar_impl)
    assert "def final_verifier(candidate: Path)" in implementation
    assert "_verify_held_bundle_candidate(\n                bundle_capability,\n                candidate," in implementation
    assert "audit.audit_bundle(\n                candidate," in implementation
    build._cleanup_scratch_capability(scratch)


def _create_test_evidence_capability(
    tmp_path: Path,
    *,
    existing_destination: bool,
) -> tuple[build._ScratchCapability, build._EvidenceCapability, Path]:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    if existing_destination:
        destination = output_parent / "published-evidence"
        destination.mkdir(mode=0o700)
        (destination / "pyinstaller.log").write_text(
            "old evidence\n",
            encoding="utf-8",
        )
    scratch = build._create_private_build_root(output_parent)
    build._materialize_source_snapshot(
        scratch,
        state,
        repository_root=repository,
    )
    evidence = build._create_failure_evidence_capability(scratch)
    (evidence.path / "pyinstaller.log").write_text(
        "new evidence\n",
        encoding="utf-8",
    )
    return scratch, build._seal_failure_evidence_capability(scratch), output_parent


@pytest.mark.parametrize("existing", [False, True], ids=["absent", "present"])
@pytest.mark.parametrize("owner", ["bundle", "evidence"])
@pytest.mark.parametrize("verifier_phase", ["candidate", "post-swap"])
def test_owned_publish_verifier_failure_rolls_back_and_cleans_scratch(
    tmp_path: Path,
    existing: bool,
    owner: str,
    verifier_phase: str,
) -> None:
    if owner == "bundle":
        scratch, capability, output_parent = _create_test_bundle_capability(
            tmp_path,
            existing_destination=existing,
        )
        held = build._bundle_capability_path(capability)
        (held / "state").write_text("new", encoding="utf-8")
        build._validate_bundle_capability(scratch, accept_tree_changes=True)
        destination = output_parent / "published"
        fault_path = capability.path if verifier_phase == "candidate" else destination
        descriptors = (capability.descriptor, capability.parent_descriptor)
        publish = lambda: build._publish_owned_bundle(
            scratch,
            capability,
            destination,
            verifier=lambda path: (
                (_ for _ in ()).throw(OSError(errno.EIO, "injected verifier"))
                if path == fault_path
                else None
            ),
        )
        candidate_payload = capability.path / "state"
        destination_payload = destination / "state"
    else:
        scratch, capability, output_parent = _create_test_evidence_capability(
            tmp_path,
            existing_destination=existing,
        )
        destination = output_parent / "published-evidence"
        fault_path = capability.path if verifier_phase == "candidate" else destination
        descriptors = (capability.descriptor,)
        publish = lambda: build._publish_owned_evidence(
            scratch,
            capability,
            destination,
            verifier=lambda path: (
                (_ for _ in ()).throw(OSError(errno.EIO, "injected verifier"))
                if path == fault_path
                else None
            ),
        )
        candidate_payload = capability.path / "pyinstaller.log"
        destination_payload = destination / "pyinstaller.log"

    expected_error = (
        "candidate failed verification"
        if verifier_phase == "candidate"
        else "post-swap audit"
    )
    with pytest.raises(build.BuildError, match=expected_error) as failure:
        publish()

    assert candidate_payload.is_file(), (
        str(failure.value),
        destination.exists(),
        scratch.poisoned,
    )
    assert candidate_payload.read_text(encoding="utf-8").startswith("new")
    if existing:
        assert destination_payload.read_text(encoding="utf-8").startswith("old")
    else:
        assert not destination.exists()
    build._finish_scratch_lifecycle(scratch, failure.value)
    assert not list(output_parent.glob(build.SCRATCH_PARENT_NAME + "-*"))
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("existing", [False, True], ids=["absent", "present"])
@pytest.mark.parametrize(
    "owner,phase",
    [
        ("bundle", "prepare-entry"),
        ("bundle", "source"),
        ("bundle", "moved-binding"),
        ("bundle", "moved-tree"),
        ("bundle", "destination-parent"),
        ("bundle", "commit"),
        ("evidence", "prepare-entry"),
        ("evidence", "moved-binding"),
        ("evidence", "moved-tree"),
        ("evidence", "content"),
        ("evidence", "destination-parent"),
        ("evidence", "build-root"),
        ("evidence", "source"),
        ("evidence", "commit"),
    ],
)
@pytest.mark.parametrize("fault", ["oserror", "baseexception"])
def test_owned_publish_finalizer_fault_rolls_back_and_cleans_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
    owner: str,
    phase: str,
    fault: str,
) -> None:
    if owner == "bundle":
        scratch, capability, output_parent = _create_test_bundle_capability(
            tmp_path,
            existing_destination=existing,
        )
        held = build._bundle_capability_path(capability)
        (held / "state").write_text("new", encoding="utf-8")
        build._validate_bundle_capability(scratch, accept_tree_changes=True)
        destination = output_parent / "published"
        descriptors = (capability.descriptor, capability.parent_descriptor)
        prepare_name = "_prepare_published_bundle_ownership"
        transfer_name = "_bundle_publish_ownership_transfer"
        finalizer_error = "Published Python sidecar bundle capability changed"
        publish = lambda: build._publish_owned_bundle(
            scratch,
            capability,
            destination,
            verifier=lambda _path: None,
        )
        candidate_payload = capability.path / "state"
        destination_payload = destination / "state"
    else:
        scratch, capability, output_parent = _create_test_evidence_capability(
            tmp_path,
            existing_destination=existing,
        )
        destination = output_parent / "published-evidence"
        descriptors = (capability.descriptor,)
        prepare_name = "_prepare_published_evidence_ownership"
        transfer_name = "_evidence_publish_ownership_transfer"
        finalizer_error = "Published PyInstaller evidence capability changed"
        publish = lambda: build._publish_owned_evidence(
            scratch,
            capability,
            destination,
            verifier=lambda _path: None,
        )
        candidate_payload = capability.path / "pyinstaller.log"
        destination_payload = destination / "pyinstaller.log"

    def injected_fault() -> None:
        if fault == "oserror":
            raise OSError(errno.EIO, "injected finalizer")
        raise KeyboardInterrupt()

    fault_fired = False

    def fire_once() -> None:
        nonlocal fault_fired
        if not fault_fired:
            fault_fired = True
            injected_fault()

    if phase == "prepare-entry":
        original_prepare = getattr(build, prepare_name)

        def faulted_prepare(*args: Any, **kwargs: Any) -> Any:
            fire_once()
            return original_prepare(*args, **kwargs)

        monkeypatch.setattr(build, prepare_name, faulted_prepare)
    elif phase == "commit":
        original_factory = getattr(build, transfer_name)

        def faulted_factory(*args: Any, **kwargs: Any) -> Any:
            transfer = original_factory(*args, **kwargs)
            original_commit = transfer.commit

            def faulted_commit(publish_capability: Any) -> None:
                fire_once()
                original_commit(publish_capability)

            transfer.commit = faulted_commit
            return transfer

        monkeypatch.setattr(build, transfer_name, faulted_factory)
    elif phase == "source":
        original_validate_source = build._validate_source_snapshot

        def faulted_validate_source(*args: Any, **kwargs: Any) -> Any:
            fire_once()
            return original_validate_source(*args, **kwargs)

        monkeypatch.setattr(
            build,
            "_validate_source_snapshot",
            faulted_validate_source,
        )
    elif phase in {"moved-binding", "destination-parent", "build-root"}:
        original_capture = build._capture_bound_directory

        def faulted_capture(
            descriptor: int,
            path: Path,
            **kwargs: Any,
        ) -> Any:
            matches = (
                (phase == "moved-binding" and path == destination)
                or (phase == "destination-parent" and path == output_parent)
                or (phase == "build-root" and path == scratch.build_root)
            )
            if matches and kwargs.get("error_message") == finalizer_error:
                fire_once()
            return original_capture(descriptor, path, **kwargs)

        monkeypatch.setattr(build, "_capture_bound_directory", faulted_capture)
    elif phase == "moved-tree":
        original_tree = build._tree_metadata_snapshot

        def faulted_tree(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("error_message") == finalizer_error:
                fire_once()
            return original_tree(*args, **kwargs)

        monkeypatch.setattr(build, "_tree_metadata_snapshot", faulted_tree)
    elif phase == "content":
        original_read = build._read_held_evidence_tree

        def faulted_read(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("error_message") == finalizer_error:
                fire_once()
            return original_read(*args, **kwargs)

        monkeypatch.setattr(build, "_read_held_evidence_tree", faulted_read)
    else:
        raise AssertionError(f"unhandled publish fault phase: {phase}")

    with pytest.raises((build.BuildError, KeyboardInterrupt)) as failure:
        publish()

    assert fault_fired is True
    assert candidate_payload.is_file(), (
        str(failure.value),
        destination.exists(),
        scratch.poisoned,
    )
    assert candidate_payload.read_text(encoding="utf-8").startswith("new")
    if existing:
        assert destination_payload.read_text(encoding="utf-8").startswith("old")
    else:
        assert not destination.exists()
    build._finish_scratch_lifecycle(scratch, failure.value)
    assert not list(output_parent.glob(build.SCRATCH_PARENT_NAME + "-*"))
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("owner", ["bundle", "evidence"])
def test_owned_publish_retained_previous_replacement_is_preserved(
    tmp_path: Path,
    owner: str,
) -> None:
    if owner == "bundle":
        scratch, capability, output_parent = _create_test_bundle_capability(
            tmp_path,
            existing_destination=True,
        )
        held = build._bundle_capability_path(capability)
        (held / "state").write_text("new", encoding="utf-8")
        build._validate_bundle_capability(scratch, accept_tree_changes=True)
        destination = output_parent / "published"
        build._publish_owned_bundle(
            scratch,
            capability,
            destination,
            verifier=lambda _path: None,
        )
    else:
        scratch, capability, output_parent = _create_test_evidence_capability(
            tmp_path,
            existing_destination=True,
        )
        destination = output_parent / "published-evidence"
        build._publish_owned_evidence(
            scratch,
            capability,
            destination,
            verifier=lambda _path: None,
        )

    retained = scratch.retained_published_directories[-1]
    detached = f"detached-{retained.name}"
    os.rename(
        retained.name,
        detached,
        src_dir_fd=retained.parent_descriptor,
        dst_dir_fd=retained.parent_descriptor,
    )
    os.mkdir(retained.name, mode=0o700, dir_fd=retained.parent_descriptor)
    replacement = retained.parent_path / retained.name
    (replacement / "do-not-delete").write_text("replacement", encoding="utf-8")

    with pytest.raises(build.BuildError, match="scratch cleanup failed"):
        build._finish_scratch_lifecycle(scratch, None)

    assert (replacement / "do-not-delete").read_text(encoding="utf-8") == (
        "replacement"
    )
    assert (retained.parent_path / detached).is_dir()
    assert destination.is_dir()


@pytest.mark.parametrize("owner", ["bundle", "evidence"])
def test_owned_publish_existing_destination_is_removed_by_exact_scratch_cleanup(
    tmp_path: Path,
    owner: str,
) -> None:
    if owner == "bundle":
        scratch, capability, output_parent = _create_test_bundle_capability(
            tmp_path,
            existing_destination=True,
        )
        held = build._bundle_capability_path(capability)
        (held / "state").write_text("new", encoding="utf-8")
        build._validate_bundle_capability(scratch, accept_tree_changes=True)
        destination = output_parent / "published"
        build._publish_owned_bundle(
            scratch,
            capability,
            destination,
            verifier=lambda _path: None,
        )
    else:
        scratch, capability, output_parent = _create_test_evidence_capability(
            tmp_path,
            existing_destination=True,
        )
        destination = output_parent / "published-evidence"
        build._publish_owned_evidence(
            scratch,
            capability,
            destination,
            verifier=lambda _path: None,
        )

    retained_descriptors = tuple(
        item.descriptor for item in scratch.retained_published_directories
    )
    build._cleanup_scratch_capability(scratch)

    assert destination.is_dir()
    assert not list(output_parent.glob(build.SCRATCH_PARENT_NAME + "-*"))
    for descriptor in retained_descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("owner", ["bundle", "evidence"])
@pytest.mark.parametrize("fault", ["oserror", "baseexception"])
def test_owned_publish_retained_cleanup_fault_is_fixed_and_preserves_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner: str,
    fault: str,
) -> None:
    if owner == "bundle":
        scratch, capability, output_parent = _create_test_bundle_capability(
            tmp_path,
            existing_destination=True,
        )
        held = build._bundle_capability_path(capability)
        (held / "state").write_text("new", encoding="utf-8")
        build._validate_bundle_capability(scratch, accept_tree_changes=True)
        destination = output_parent / "published"
        build._publish_owned_bundle(
            scratch,
            capability,
            destination,
            verifier=lambda _path: None,
        )
    else:
        scratch, capability, output_parent = _create_test_evidence_capability(
            tmp_path,
            existing_destination=True,
        )
        destination = output_parent / "published-evidence"
        build._publish_owned_evidence(
            scratch,
            capability,
            destination,
            verifier=lambda _path: None,
        )

    retained = scratch.retained_published_directories[-1]
    retained_descriptor = retained.descriptor
    original_rollback = build._rollback_bound_directory

    def faulted_rollback(**kwargs: Any) -> None:
        if kwargs.get("descriptor") == retained_descriptor:
            if fault == "oserror":
                raise OSError(errno.EIO, "injected retained cleanup")
            raise KeyboardInterrupt()
        original_rollback(**kwargs)

    monkeypatch.setattr(build, "_rollback_bound_directory", faulted_rollback)

    with pytest.raises(
        build.BuildError,
        match=r"^Python sidecar scratch cleanup failed$",
    ):
        build._finish_scratch_lifecycle(scratch, None)

    assert scratch.closed is True
    assert scratch.scratch_parent.is_dir()
    assert destination.is_dir()
    with pytest.raises(OSError):
        os.fstat(retained_descriptor)


def test_source_snapshot_materialization_rejects_root_rename_recreate_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(output_parent)
    original_open = os.open
    attacked = False
    replacement_bytes = b"attacker-controlled replacement\n"

    def rename_recreate_restore(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal attacked
        if (
            not attacked
            and path == "README.md"
            and flags & os.O_CREAT
            and dir_fd is not None
        ):
            attacked = True
            build_descriptor = capability.build_root_descriptor
            os.rename(
                build.SOURCE_SNAPSHOT_NAME,
                "detached-source-snapshot",
                src_dir_fd=build_descriptor,
                dst_dir_fd=build_descriptor,
            )
            os.mkdir(
                build.SOURCE_SNAPSHOT_NAME,
                mode=0o700,
                dir_fd=build_descriptor,
            )
            replacement_descriptor = original_open(
                build.SOURCE_SNAPSHOT_NAME,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=build_descriptor,
            )
            try:
                replacement_file = original_open(
                    "README.md",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    0o600,
                    dir_fd=replacement_descriptor,
                )
                try:
                    assert os.write(replacement_file, replacement_bytes) == len(
                        replacement_bytes
                    )
                finally:
                    os.close(replacement_file)
                assert (
                    os.stat(
                        "README.md",
                        dir_fd=replacement_descriptor,
                        follow_symlinks=False,
                    ).st_size
                    == len(replacement_bytes)
                )
                os.unlink("README.md", dir_fd=replacement_descriptor)
            finally:
                os.close(replacement_descriptor)
            os.rmdir(build.SOURCE_SNAPSHOT_NAME, dir_fd=build_descriptor)
            os.rename(
                "detached-source-snapshot",
                build.SOURCE_SNAPSHOT_NAME,
                src_dir_fd=build_descriptor,
                dst_dir_fd=build_descriptor,
            )
        keyword_arguments = {} if dir_fd is None else {"dir_fd": dir_fd}
        return original_open(path, flags, mode, **keyword_arguments)

    monkeypatch.setattr(build.os, "open", rename_recreate_restore)

    try:
        with pytest.raises(
            build.BuildError,
            match=r"^Exact Git source snapshot could not be materialized$",
        ):
            build._materialize_source_snapshot(
                capability,
                state,
                repository_root=repository,
            )

        assert attacked is True
        snapshot_readme = (
            capability.build_root / build.SOURCE_SNAPSHOT_NAME / "README.md"
        )
        assert snapshot_readme.read_bytes() == b"reviewed source\n"
        assert snapshot_readme.read_bytes() != replacement_bytes
    finally:
        build._cleanup_scratch_capability(capability)


@pytest.mark.parametrize(
    "mutation",
    ["content-drift", "inode-replacement"],
)
def test_source_snapshot_validation_rejects_inflight_content_or_inode_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    state = build._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
        repository_root=repository,
    )
    output_parent = tmp_path / "generated"
    output_parent.mkdir(mode=0o755)
    capability = build._create_private_build_root(output_parent)
    snapshot = build._materialize_source_snapshot(
        capability,
        state,
        repository_root=repository,
    )
    readme = snapshot / "README.md"
    reviewed_bytes = readme.read_bytes()
    attacked = False

    if mutation == "content-drift":
        original_read = os.read
        readme_identity = (readme.stat().st_dev, readme.stat().st_ino)

        def drift_then_restore(descriptor: int, length: int) -> bytes:
            nonlocal attacked
            info = os.fstat(descriptor)
            if not attacked and (info.st_dev, info.st_ino) == readme_identity:
                attacked = True
                readme.chmod(0o644)
                readme.write_bytes(b"transient attacker bytes\n")
                readme.write_bytes(reviewed_bytes)
                readme.chmod(0o444)
            return original_read(descriptor, length)

        monkeypatch.setattr(build.os, "read", drift_then_restore)
    else:
        original_open = os.open

        def replace_after_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal attacked
            if (
                not attacked
                and path == "README.md"
                and flags & os.O_ACCMODE == os.O_RDONLY
                and not flags & os.O_CREAT
                and dir_fd is not None
            ):
                attacked = True
                opened_replacement: int | None = None
                os.fchmod(dir_fd, 0o700)
                try:
                    os.rename(
                        "README.md",
                        "detached-readme",
                        src_dir_fd=dir_fd,
                        dst_dir_fd=dir_fd,
                    )
                    replacement = original_open(
                        "README.md",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                        0o600,
                        dir_fd=dir_fd,
                    )
                    try:
                        assert os.write(replacement, reviewed_bytes) == len(
                            reviewed_bytes
                        )
                        os.fchmod(replacement, 0o444)
                    finally:
                        os.close(replacement)
                    opened_replacement = original_open(
                        "README.md",
                        flags,
                        mode,
                        dir_fd=dir_fd,
                    )
                    os.rename(
                        "README.md",
                        "discarded-replacement",
                        src_dir_fd=dir_fd,
                        dst_dir_fd=dir_fd,
                    )
                    os.rename(
                        "detached-readme",
                        "README.md",
                        src_dir_fd=dir_fd,
                        dst_dir_fd=dir_fd,
                    )
                    os.unlink("discarded-replacement", dir_fd=dir_fd)
                finally:
                    os.fchmod(dir_fd, 0o500)
                assert opened_replacement is not None
                return opened_replacement
            keyword_arguments = {} if dir_fd is None else {"dir_fd": dir_fd}
            return original_open(path, flags, mode, **keyword_arguments)

        monkeypatch.setattr(build.os, "open", replace_after_open)

    try:
        with pytest.raises(
            build.BuildError,
            match=r"^Exact Git source snapshot changed during packaging$",
        ):
            build._validate_source_snapshot(capability)
        assert attacked is True
        assert readme.read_bytes() == reviewed_bytes
    finally:
        build._cleanup_scratch_capability(capability)


def test_repository_provenance_rejects_tree_mismatch_and_dirty_source(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)

    with pytest.raises(build.BuildError, match="commit/tree"):
        build._validate_repository_state(
            {
                "LCF_SOURCE_SHA": commit,
                "LCF_SOURCE_TREE": "0" * 40,
            },
            repository_root=repository,
        )

    (repository / "README.md").write_text("dirty source\n", encoding="utf-8")
    with pytest.raises(build.BuildError):
        build._validate_repository_state(
            {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
            repository_root=repository,
        )


def test_auditor_rejects_repository_tree_and_snapshot_manifest_tamper(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    snapshot_digest = audit._git_tree_inventory_sha256(repository, commit)
    reviewed = {
        "repositoryCommit": commit,
        "repositoryTree": tree,
        "sourceSnapshotSha256": snapshot_digest,
    }

    audit._validate_repository_provenance(reviewed, repository)
    for key, value in (
        ("repositoryTree", "0" * 40),
        ("sourceSnapshotSha256", "0" * 64),
    ):
        tampered = dict(reviewed)
        tampered[key] = value
        with pytest.raises(audit.AuditError, match="provenance"):
            audit._validate_repository_provenance(tampered, repository)


@pytest.mark.parametrize("mutation", ["filter", "index-flag", "info-attributes"])
def test_standalone_auditor_reuses_the_exact_hostile_git_boundary(
    tmp_path: Path,
    mutation: str,
) -> None:
    repository = tmp_path / "repository"
    commit, tree = _create_exact_git_fixture(repository)
    reviewed = {
        "repositoryCommit": commit,
        "repositoryTree": tree,
        "sourceSnapshotSha256": build._source_snapshot_sha256(
            build._repository_tree_inventory(
                commit,
                repository_root=repository,
            )
        ),
    }
    marker = tmp_path / "filter-executed"
    if mutation == "filter":
        _fixture_git(
            repository,
            "config",
            "--local",
            "filter.hostile.clean",
            f"/bin/sh -c 'touch {marker}; cat'",
        )
    elif mutation == "index-flag":
        _fixture_git(
            repository,
            "update-index",
            "--assume-unchanged",
            "README.md",
        )
        (repository / "README.md").write_text("hidden drift\n", encoding="utf-8")
    else:
        (repository / ".git" / "info" / "attributes").write_text(
            "README.md filter=hostile\n",
            encoding="utf-8",
        )

    with pytest.raises(audit.AuditError, match="provenance"):
        audit._validate_repository_provenance(reviewed, repository)
    assert not marker.exists()


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
    build_schema = properties["build"]
    assert {"repositoryCommit", "repositoryTree", "sourceSnapshotSha256"} <= set(
        build_schema["required"]
    )
    assert build_schema["properties"]["repositoryTree"]["pattern"] == (
        "^[0-9a-f]{40}$"
    )
    assert build_schema["properties"]["sourceSnapshotSha256"] == {
        "$ref": "#/$defs/sha256"
    }
    assert "LCF_SOURCE_SHA" in toolchain["requiredCiInputs"]
    assert "LCF_SOURCE_TREE" in toolchain["requiredCiInputs"]
    assert "GITHUB_SHA" not in toolchain["requiredCiInputs"]

    provenance = definitions["pythonProvenance"]["properties"]
    assert provenance["implementation"]["const"] == python_lock["implementation"]
    assert provenance["version"]["const"] == python_lock["version"] == "3.13.14"
    assert provenance["installRoot"]["const"] == python_lock["installRoot"]
    assert python_lock["frameworkCoreFingerprintExcludedPaths"] == list(
        bootstrap.REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS
    )
    assert python_lock["frameworkCoreFingerprintSha256"] == (
        "77b58098a5ebc6890e1335eed3afaa1b9bad96029b7b5ad42e45b270b6649d10"
    )
    assert python_lock["frameworkCoreFingerprintSha256"] != (
        "ba58cfb559f29c34beb962cb5d88587e9104f5610c255a58494c2945c1e863ec"
    )
    inventory_path = (
        build.TOOLCHAIN_LOCK.parent
        / python_lock["frameworkCoreInventory"]["fileName"]
    )
    inventory_bytes = inventory_path.read_bytes()
    expected_inventory = json.loads(inventory_bytes.decode("utf-8"))
    assert len(inventory_bytes) == 615969
    assert hashlib.sha256(inventory_bytes).hexdigest() == (
        "b145fe364990e1f029d2d628c03082b039a29704acdd13a11277d14c7d89a25f"
    )
    assert python_lock["frameworkCoreInventory"] == {
        "fileName": "python-framework-sealed-inventory.json",
        "fileSize": 615969,
        "fileSha256": (
            "b145fe364990e1f029d2d628c03082b039a29704acdd13a11277d14c7d89a25f"
        ),
        "schemaVersion": 1,
        "sourcePayloadSize": 32739568,
        "sourcePayloadSha256": (
            "f922c9d7c78f3745dc453211677fbce2e4b415616556b11376a92ca7a17fc391"
        ),
        "sourceEntryCount": 3654,
        "sourceInventorySha256": (
            "863a6353e58b9c71dc44847051aa582519a66b9347d8c09915ef5254c694bb5d"
        ),
        "transformationCount": 6,
        "entryCount": 3648,
        "inventorySha256": (
            "77b58098a5ebc6890e1335eed3afaa1b9bad96029b7b5ad42e45b270b6649d10"
        ),
    }
    assert expected_inventory["schemaVersion"] == 1
    assert expected_inventory["source"] == {
        "payloadSize": python_lock["frameworkCoreInventory"][
            "sourcePayloadSize"
        ],
        "payloadSha256": python_lock["frameworkCoreInventory"][
            "sourcePayloadSha256"
        ],
        "coreEntryCount": python_lock["frameworkCoreInventory"][
            "sourceEntryCount"
        ],
        "coreInventorySha256": python_lock["frameworkCoreInventory"][
            "sourceInventorySha256"
        ],
    }
    assert len(expected_inventory["transformations"]) == 6
    assert all(
        set(transformation)
        == {"kind", "path", "type", "mode", "size", "sha256"}
        and transformation["kind"] == "remove-appledouble"
        and transformation["type"] == "file"
        and transformation["mode"] == "0664"
        and PurePosixPath(transformation["path"]).name.startswith("._")
        for transformation in expected_inventory["transformations"]
    )
    assert len(expected_inventory["entries"]) == 3648
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


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("fileName", "unreviewed-inventory.json"),
        ("fileSize", 615970),
        ("fileSha256", "0" * 64),
        ("schemaVersion", 2),
        ("sourcePayloadSize", 32739569),
        ("sourcePayloadSha256", "0" * 64),
        ("sourceEntryCount", 3655),
        ("sourceInventorySha256", "0" * 64),
        ("transformationCount", 7),
        ("entryCount", 3649),
        ("inventorySha256", "0" * 64),
        ("__missing__", None),
        ("__extra__", None),
    ),
)
def test_reviewed_framework_inventory_rejects_lock_mutation(
    field: str,
    replacement: object,
) -> None:
    toolchain = json.loads(build.TOOLCHAIN_LOCK.read_text(encoding="utf-8"))
    python_lock = copy.deepcopy(toolchain["python"])
    inventory_lock = python_lock["frameworkCoreInventory"]
    inventory_path = build.TOOLCHAIN_LOCK.parent / inventory_lock["fileName"]
    bound = bootstrap._open_bound_file(
        inventory_path,
        maximum_size=bootstrap.MAX_FRAMEWORK_CORE_INVENTORY_BYTES,
        error_message="fixture inventory",
    )
    try:
        if field == "__missing__":
            del inventory_lock["sourceEntryCount"]
        elif field == "__extra__":
            inventory_lock["unreviewed"] = True
        else:
            inventory_lock[field] = replacement
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="framework (?:inventory|core lock)",
        ):
            bootstrap._reviewed_framework_core_contract(python_lock)
            contract = bootstrap._reviewed_framework_inventory_contract(
                python_lock
            )
            bootstrap._verify_reviewed_framework_inventory_file(bound, contract)
    finally:
        os.close(bound.descriptor)


def test_reviewed_framework_inventory_binds_the_exact_file(tmp_path: Path) -> None:
    toolchain = json.loads(build.TOOLCHAIN_LOCK.read_text(encoding="utf-8"))
    python_lock = toolchain["python"]
    inventory_lock = python_lock["frameworkCoreInventory"]
    source = build.TOOLCHAIN_LOCK.parent / inventory_lock["fileName"]
    contract = bootstrap._reviewed_framework_inventory_contract(python_lock)
    exact = bootstrap._open_bound_file(
        source,
        maximum_size=bootstrap.MAX_FRAMEWORK_CORE_INVENTORY_BYTES,
        error_message="fixture inventory",
    )
    try:
        bootstrap._verify_reviewed_framework_inventory_file(exact, contract)
    finally:
        os.close(exact.descriptor)
    changed = tmp_path / inventory_lock["fileName"]
    changed.write_bytes(source.read_bytes() + b"\n")
    changed.chmod(0o600)
    bound = bootstrap._open_bound_file(
        changed,
        maximum_size=bootstrap.MAX_FRAMEWORK_CORE_INVENTORY_BYTES,
        error_message="fixture inventory",
    )
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="inventory file is inconsistent",
        ):
            bootstrap._verify_reviewed_framework_inventory_file(
                bound,
                contract,
            )
    finally:
        os.close(bound.descriptor)


@pytest.mark.parametrize(
    "mutation",
    (
        "symlink-mode",
        "extra-field",
        "non-appledouble-path",
        "unsafe-path",
        "reverse-order",
        "duplicate-path",
        "retained-removal",
        "source-count",
    ),
)
def test_reviewed_framework_inventory_rejects_transformation_schema_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    toolchain = json.loads(build.TOOLCHAIN_LOCK.read_text(encoding="utf-8"))
    contract = copy.deepcopy(toolchain["python"]["frameworkCoreInventory"])
    source = build.TOOLCHAIN_LOCK.parent / contract["fileName"]
    inventory = json.loads(source.read_text(encoding="utf-8"))

    if mutation == "symlink-mode":
        inventory["transformations"][0] = {
            "kind": "symlink-mode",
            "path": "Frameworks/Tcl.framework/Headers",
            "type": "symlink",
            "target": "Versions/Current/Headers",
            "fromMode": "0775",
            "toMode": "0777",
        }
    elif mutation == "extra-field":
        inventory["transformations"][0]["unreviewed"] = True
    elif mutation == "non-appledouble-path":
        inventory["transformations"][0]["path"] = (
            "Frameworks/Tcl.framework/Versions/8.6/tclConfig.sh"
        )
    elif mutation == "unsafe-path":
        inventory["transformations"][0]["path"] = "../._outside"
    elif mutation == "reverse-order":
        inventory["transformations"].reverse()
    elif mutation == "duplicate-path":
        inventory["transformations"][1] = copy.deepcopy(
            inventory["transformations"][0]
        )
    elif mutation == "retained-removal":
        removal = inventory["transformations"][0]
        inventory["entries"][0] = {
            "path": removal["path"],
            "mode": "0644",
            "type": "file",
            "size": removal["size"],
            "sha256": removal["sha256"],
        }
        digest = hashlib.sha256(
            bootstrap._canonical_json_bytes(inventory["entries"])
        ).hexdigest()
        inventory["inventorySha256"] = digest
        contract["inventorySha256"] = digest
    elif mutation == "source-count":
        inventory["source"]["coreEntryCount"] += 1
        contract["sourceEntryCount"] += 1
    else:  # pragma: no cover - exhaustive fixture guard
        raise AssertionError(f"unsupported mutation: {mutation}")

    payload = bootstrap._canonical_json_bytes(inventory) + b"\n"
    contract["fileSize"] = len(payload)
    contract["fileSha256"] = hashlib.sha256(payload).hexdigest()
    changed = tmp_path / contract["fileName"]
    changed.write_bytes(payload)
    changed.chmod(0o600)
    bound = bootstrap._open_bound_file(
        changed,
        maximum_size=bootstrap.MAX_FRAMEWORK_CORE_INVENTORY_BYTES,
        error_message="fixture inventory",
    )
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="inventory file is inconsistent",
        ):
            bootstrap._verify_reviewed_framework_inventory_file(bound, contract)
    finally:
        os.close(bound.descriptor)


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
    payload = (
        b'{"revision":4,"collections":[],"embedding":'
        b'{"mode":"lexical","profile":null}}'
    )
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
            "embedding": "lexical",
        }
    ]
    assert connection.responses
    assert connection.responses[0].startswith(b"HTTP/1.1 200 OK\r\n")
    response_body = connection.responses[0].split(b"\r\n\r\n", 1)[1]
    assert json.loads(response_body) == {
        "indexed": True,
        "revision": 4,
        "collections": 0,
        "update": {
            "indexed": 0,
            "updated": 0,
            "unchanged": 0,
            "removed": 0,
        },
        "embedding": {
            "status": "stale",
            "profile": None,
            "revision": None,
            "model_status": "not_requested",
            "error": None,
        },
    }


def test_frozen_smoke_broker_rejects_nonlexical_embedding_mode() -> None:
    import threading

    capability = "a" * 43
    stop = threading.Event()
    request = _broker_request(capability=capability).replace(
        b'"mode":"lexical"',
        b'"mode":"rebuild"',
    )
    connection = _BrokerConnectionFixture(request)
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
    assert connection.responses[0].startswith(
        b"HTTP/1.1 400 Bad Request\r\n"
    )


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


def test_selected_source_coordinates_require_exact_checkout_inputs() -> None:
    exact_source = "a" * 40
    exact_tree = "c" * 40

    assert build._selected_source_commit(
        {
            "LCF_SOURCE_SHA": exact_source,
            "LCF_SOURCE_TREE": exact_tree,
            "GITHUB_SHA": "b" * 40,
        }
    ) == exact_source
    assert build._selected_source_tree(
        {"LCF_SOURCE_SHA": exact_source, "LCF_SOURCE_TREE": exact_tree}
    ) == exact_tree
    with pytest.raises(build.BuildError, match="LCF_SOURCE_SHA"):
        build._selected_source_commit({"GITHUB_SHA": "b" * 40})
    with pytest.raises(build.BuildError, match="LCF_SOURCE_TREE"):
        build._selected_source_tree({"LCF_SOURCE_SHA": exact_source})


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
    tree = "c" * 40
    epoch = 1_800_000_000
    install_root = "/Library/Frameworks/Python.framework/Versions/3.13"
    environment = {
        "LCF_SOURCE_SHA": commit,
        "LCF_SOURCE_TREE": tree,
        "GITHUB_SHA": "b" * 40,
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
            "LCF_SOURCE_SHA",
            "LCF_SOURCE_TREE",
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

    def git_output(*arguments: str, **_: Any) -> str:
        if arguments == ("rev-parse", "HEAD"):
            return commit
        if arguments in {
            ("rev-parse", "HEAD^{tree}"),
            ("rev-parse", f"{commit}^{{tree}}"),
            ("write-tree",),
        }:
            return tree
        if arguments in {
            ("diff-files", "--quiet"),
            ("diff-index", "--cached", "--quiet", commit, "--"),
            ("status", "--porcelain=v2", "--untracked-files=all"),
            ("submodule", "status", "--recursive"),
        }:
            return ""
        if arguments == ("show", "-s", "--format=%ct", "HEAD"):
            return str(epoch)
        raise AssertionError(arguments)

    monkeypatch.setattr(build, "_run_checked", native_output)
    monkeypatch.setattr(build, "_git_output", git_output)
    monkeypatch.setattr(
        build,
        "_validate_local_git_configuration",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        build,
        "_validate_git_info_overrides",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        build,
        "_validate_git_index",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        build,
        "_validate_tracked_worktree",
        lambda *_args, **_kwargs: None,
    )
    inventory = (
        build._TreeEntry(
            path="README.md",
            mode="100644",
            object_type="blob",
            object_id="d" * 40,
        ),
    )
    monkeypatch.setattr(
        build,
        "_repository_tree_inventory",
        lambda *_args, **_kwargs: inventory,
    )

    release = build.validate_release_environment(environment, toolchain)

    assert release["repositoryCommit"] == commit
    assert release["repositoryTree"] == tree
    assert release["sourceSnapshotSha256"] == build._source_snapshot_sha256(
        inventory
    )
    assert release["runnerImage"] == "macos-15"
    assert release["xcodeVersion"] == "16.4"
    assert release["sdkVersion"] == "15.5"


def _test_framework_root() -> PurePosixPath:
    base = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    return PurePosixPath(base.parents[1].as_posix())


def _create_real_venv_with_production_child(root: Path) -> None:
    hostile_parent_umask = os.umask(0o002)
    try:
        with build._translate_cleanup_signals():
            bootstrap._run_owned_process(
                (
                    sys.executable,
                    "-m",
                    "venv",
                    "--without-pip",
                    str(root),
                ),
                cwd=root.parent,
                environment=dict(os.environ),
                pass_fds=(),
                timeout=60,
                label="Real test venv creation",
                build=build,
            )
    finally:
        os.umask(hostile_parent_umask)


def test_real_venv_seal_verify_execute_and_restore_for_exact_cleanup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "real-venv"
    _create_real_venv_with_production_child(root)
    assert any(path.is_symlink() for path in root.rglob("*"))
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        activation = root / "bin" / "activate"
        activation.chmod(0o664)
        bootstrap._privatize_installed_tree(root, descriptor, build)
        assert all(
            not stat.S_IMODE(path.lstat().st_mode) & 0o077
            for path in (root, *root.rglob("*"))
            if not path.is_symlink()
        )
        seal = bootstrap.seal_installed_tree(
            root,
            descriptor,
            reviewed_framework_root=_test_framework_root(),
        )
        assert bootstrap.verify_installed_tree(
            root,
            descriptor,
            content_sha256=seal.content_sha256,
            identity_sha256=seal.identity_sha256,
            reviewed_framework_root=_test_framework_root(),
        ) == seal
        completed = subprocess.run(
            [str(root / "bin" / "python"), "-I", "-c", "print('sealed')"],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        assert completed.stdout == "sealed\n"
        bootstrap._make_installed_tree_cleanup_writable(descriptor)
        directories = [
            root,
            *[
                item
                for item in root.rglob("*")
                if item.is_dir() and not item.is_symlink()
            ],
        ]
        assert all(stat.S_IMODE(path.lstat().st_mode) == 0o700 for path in directories)
    finally:
        os.close(descriptor)


def test_installed_tree_seal_rejects_same_version_content_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "venv"
    _create_real_venv_with_production_child(root)
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        bootstrap._privatize_installed_tree(root, descriptor, build)
        seal = bootstrap.seal_installed_tree(
            root,
            descriptor,
            reviewed_framework_root=_test_framework_root(),
        )
        configuration = root / "pyvenv.cfg"
        original = configuration.read_bytes()
        configuration.chmod(0o600)
        configuration.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        configuration.chmod(0o400)
        with pytest.raises(bootstrap.ToolchainBootstrapError, match="seal changed"):
            bootstrap.verify_installed_tree(
                root,
                descriptor,
                content_sha256=seal.content_sha256,
                identity_sha256=seal.identity_sha256,
                reviewed_framework_root=_test_framework_root(),
            )
        bootstrap._make_installed_tree_cleanup_writable(descriptor)
    finally:
        os.close(descriptor)


def test_installed_tree_privatization_normalizes_modes_and_breaks_hardlinks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    nested = root / "bin"
    nested.mkdir(mode=0o700)
    nested.chmod(0o775)
    external = tmp_path / "external-tool"
    external.write_bytes(b"reviewed tool\n")
    external.chmod(0o755)
    installed = nested / "tool"
    installed.hardlink_to(external)
    executable = nested / "runner"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o775)
    link = nested / "python"
    link.symlink_to("runner")
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        bootstrap._privatize_installed_tree(root, descriptor, build)
        assert stat.S_IMODE(root.lstat().st_mode) == 0o700
        assert stat.S_IMODE(nested.lstat().st_mode) == 0o700
        assert stat.S_IMODE(installed.lstat().st_mode) == 0o700
        assert stat.S_IMODE(executable.lstat().st_mode) == 0o700
        assert installed.stat().st_nlink == 1
        assert external.stat().st_nlink == 1
        assert stat.S_IMODE(external.stat().st_mode) == 0o755
        external.write_bytes(b"external drift\n")
        assert installed.read_bytes() == b"reviewed tool\n"
        assert link.is_symlink()
        seal = bootstrap.seal_installed_tree(root, descriptor)
        modes = {entry["path"]: entry["mode"] for entry in seal.entries}
        assert modes["bin/tool"] == "0500"
        assert modes["bin/runner"] == "0500"
        assert modes["bin/python"] == "0777"
        bootstrap._make_installed_tree_cleanup_writable(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("initial_mode", "private_mode", "sealed_mode"),
    (
        (0o640, 0o600, "0400"),
        (0o644, 0o600, "0400"),
        (0o660, 0o600, "0400"),
        (0o700, 0o700, "0500"),
        (0o711, 0o700, "0500"),
        (0o755, 0o700, "0500"),
        (0o775, 0o700, "0500"),
    ),
)
def test_installed_tree_privatization_canonicalizes_producer_file_modes(
    tmp_path: Path,
    initial_mode: int,
    private_mode: int,
    sealed_mode: str,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    tool = root / "tool"
    tool.write_bytes(b"reviewed\n")
    tool.chmod(initial_mode)
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        bootstrap._privatize_installed_tree(root, descriptor, build)
        assert stat.S_IMODE(tool.lstat().st_mode) == private_mode
        seal = bootstrap.seal_installed_tree(root, descriptor)
        entry = next(item for item in seal.entries if item["path"] == "tool")
        assert entry["mode"] == sealed_mode
        bootstrap._make_installed_tree_cleanup_writable(descriptor)
    finally:
        os.close(descriptor)


def test_installed_tree_privatization_breaks_two_internal_hardlinks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    first = root / "first"
    first.write_bytes(b"same reviewed bytes\n")
    first.chmod(0o640)
    second = root / "second"
    second.hardlink_to(first)
    original_inode = first.stat().st_ino
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        bootstrap._privatize_installed_tree(root, descriptor, build)
        assert first.read_bytes() == second.read_bytes() == b"same reviewed bytes\n"
        assert first.stat().st_nlink == second.stat().st_nlink == 1
        assert first.stat().st_ino != second.stat().st_ino
        assert original_inode in {first.stat().st_ino, second.stat().st_ino}
        seal = bootstrap.seal_installed_tree(root, descriptor)
        assert len([item for item in seal.entries if item["type"] == "file"]) == 2
        bootstrap._make_installed_tree_cleanup_writable(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("unsafe_mode", (0o660, 0o775))
def test_installed_tree_privatization_rejects_writable_external_hardlink(
    tmp_path: Path,
    unsafe_mode: int,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    external = tmp_path / "external"
    external.write_bytes(b"untrusted alias\n")
    external.chmod(unsafe_mode)
    installed = root / "tool"
    installed.hardlink_to(external)
    original = external.lstat()
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="producer hardlink is writable",
        ):
            bootstrap._privatize_installed_tree(root, descriptor, build)
        assert installed.stat().st_ino == external.stat().st_ino == original.st_ino
        assert stat.S_IMODE(external.stat().st_mode) == unsafe_mode
        assert external.read_bytes() == b"untrusted alias\n"
        assert not list(root.glob(".lcf-private-*"))
    finally:
        os.close(descriptor)


def test_installed_tree_privatization_exchange_failure_removes_private_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    external = tmp_path / "external"
    external.write_bytes(b"reviewed alias\n")
    external.chmod(0o640)
    installed = root / "tool"
    installed.hardlink_to(external)
    original = external.lstat()

    def fail_exchange(*_args: Any) -> None:
        raise build.BuildError("synthetic exchange failure")

    monkeypatch.setattr(build, "_exchange_at", fail_exchange)
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="private copy failed",
        ):
            bootstrap._privatize_installed_tree(
                root,
                descriptor,
                build,
            )
        assert installed.stat().st_ino == external.stat().st_ino == original.st_ino
        assert stat.S_IMODE(external.stat().st_mode) == 0o640
        assert external.read_bytes() == b"reviewed alias\n"
        assert not list(root.glob(".lcf-private-*"))
    finally:
        os.close(descriptor)


def test_installed_tree_privatization_post_exchange_failure_removes_old_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    external = tmp_path / "external"
    external.write_bytes(b"reviewed alias\n")
    external.chmod(0o640)
    installed = root / "tool"
    installed.hardlink_to(external)
    original_exchange = build._exchange_at

    def exchange_then_fail(*args: Any) -> None:
        original_exchange(*args)
        raise build.BuildError("synthetic post-exchange failure")

    monkeypatch.setattr(build, "_exchange_at", exchange_then_fail)
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="private copy failed",
        ):
            bootstrap._privatize_installed_tree(root, descriptor, build)
        assert installed.read_bytes() == b"reviewed alias\n"
        assert installed.stat().st_nlink == 1
        assert external.read_bytes() == b"reviewed alias\n"
        assert external.stat().st_nlink == 1
        assert installed.stat().st_ino != external.stat().st_ino
        assert not list(root.glob(".lcf-private-*"))
    finally:
        os.close(descriptor)


def test_installed_tree_seal_rejects_regular_hardlink_without_privatization(
    tmp_path: Path,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    first = root / "first"
    first.write_bytes(b"shared inode\n")
    first.chmod(0o600)
    second = root / "second"
    second.hardlink_to(first)
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="Installed toolchain file is unsafe",
        ):
            bootstrap.seal_installed_tree(root, descriptor)
        assert first.stat().st_ino == second.stat().st_ino
        assert first.stat().st_nlink == second.stat().st_nlink == 2
        assert stat.S_IMODE(first.stat().st_mode) == 0o600
    finally:
        os.close(descriptor)


def _stat_result_with(
    info: os.stat_result,
    *,
    mode: int | None = None,
    inode: int | None = None,
    uid: int | None = None,
    gid: int | None = None,
) -> os.stat_result:
    values, attributes = info.__reduce__()[1]
    values = list(values)
    if mode is not None:
        values[stat.ST_MODE] = mode
    if inode is not None:
        values[stat.ST_INO] = inode
    if uid is not None:
        values[stat.ST_UID] = uid
    if gid is not None:
        values[stat.ST_GID] = gid
    return os.stat_result(values, dict(attributes))


@pytest.mark.parametrize("raw_mode", (0o700, 0o755, 0o777))
def test_installed_tree_symlink_raw_metadata_is_portable_and_mode_is_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_mode: int,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    tool = root / "tool.py"
    tool.write_text("reviewed\n", encoding="ascii")
    tool.chmod(0o600)
    link = root / "python"
    link.symlink_to(tool.name)
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    original_stat = os.stat
    actual_link_info = link.lstat()
    portable_link_info = _stat_result_with(
        actual_link_info,
        mode=stat.S_IFLNK | raw_mode,
        uid=os.geteuid() + 100,
        gid=os.getegid() + 100,
    )
    assert portable_link_info.st_mtime_ns == actual_link_info.st_mtime_ns
    assert portable_link_info.st_ctime_ns == actual_link_info.st_ctime_ns
    assert bootstrap._symlink_identity(portable_link_info) == (
        bootstrap._symlink_identity(actual_link_info)
    )

    def portable_symlink_stat(
        path: str | bytes | int,
        *args: Any,
        **kwargs: Any,
    ) -> os.stat_result:
        observed = original_stat(path, *args, **kwargs)
        if (
            path == link.name
            and kwargs.get("dir_fd") == descriptor
            and kwargs.get("follow_symlinks") is False
        ):
            return _stat_result_with(
                observed,
                mode=stat.S_IFLNK | raw_mode,
                uid=os.geteuid() + 100,
                gid=os.getegid() + 100,
            )
        return observed

    monkeypatch.setattr(bootstrap.os, "stat", portable_symlink_stat)
    try:
        seal = bootstrap.seal_installed_tree(root, descriptor)
        link_entry = next(entry for entry in seal.entries if entry["path"] == link.name)
        assert link_entry == {
            "path": link.name,
            "mode": "0777",
            "type": "symlink",
            "size": len(tool.name),
            "target": tool.name,
        }
        assert bootstrap.verify_installed_tree(
            root,
            descriptor,
            content_sha256=seal.content_sha256,
            identity_sha256=seal.identity_sha256,
        ) == seal
        bootstrap._make_installed_tree_cleanup_writable(descriptor)
    finally:
        os.close(descriptor)


def test_installed_tree_symlink_identity_drift_after_readlink_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    tool = root / "tool.py"
    tool.write_text("reviewed\n", encoding="ascii")
    tool.chmod(0o600)
    link = root / "python"
    link.symlink_to(tool.name)
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    original_stat = os.stat
    original_readlink = os.readlink
    readlink_completed = False

    def drifting_stat(
        path: str | bytes | int,
        *args: Any,
        **kwargs: Any,
    ) -> os.stat_result:
        observed = original_stat(path, *args, **kwargs)
        if (
            readlink_completed
            and path == link.name
            and kwargs.get("dir_fd") == descriptor
            and kwargs.get("follow_symlinks") is False
        ):
            return _stat_result_with(observed, inode=observed.st_ino + 1)
        return observed

    def completing_readlink(
        path: str | bytes,
        *args: Any,
        **kwargs: Any,
    ) -> str | bytes:
        nonlocal readlink_completed
        target = original_readlink(path, *args, **kwargs)
        if path == link.name and kwargs.get("dir_fd") == descriptor:
            readlink_completed = True
        return target

    monkeypatch.setattr(bootstrap.os, "stat", drifting_stat)
    monkeypatch.setattr(bootstrap.os, "readlink", completing_readlink)
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="Installed toolchain symlink changed",
        ):
            bootstrap.seal_installed_tree(root, descriptor)
    finally:
        os.close(descriptor)


def test_installed_tree_non_symlink_group_write_remains_rejected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    tool = root / "tool.py"
    tool.write_text("reviewed\n", encoding="ascii")
    tool.chmod(0o620)
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="Installed toolchain tree has unsafe ownership or mode",
        ):
            bootstrap.seal_installed_tree(root, descriptor)
    finally:
        os.close(descriptor)


def test_installed_tree_seal_rejects_root_replacement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    (root / "tool.py").write_text("reviewed\n", encoding="ascii")
    descriptor = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    seal = bootstrap.seal_installed_tree(root, descriptor)
    detached = tmp_path / "detached-installed"
    root.rename(detached)
    root.mkdir(mode=0o700)
    (root / "do-not-consume").write_text("replacement\n", encoding="ascii")
    (root / "do-not-consume").chmod(0o400)
    root.chmod(0o500)
    try:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="root is unsafe|cannot be inventoried",
        ):
            bootstrap.verify_installed_tree(
                root,
                descriptor,
                content_sha256=seal.content_sha256,
                identity_sha256=seal.identity_sha256,
            )
        assert (root / "do-not-consume").read_text(encoding="ascii") == (
            "replacement\n"
        )
    finally:
        bootstrap._make_installed_tree_cleanup_writable(descriptor)
        os.close(descriptor)
        root.chmod(0o700)


@pytest.mark.parametrize("failure", [False, True])
def test_held_toolchain_root_restores_seal_and_has_no_residue(
    tmp_path: Path,
    failure: bool,
) -> None:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(mode=0o700)
    try:
        with build._translate_cleanup_signals():
            with bootstrap._held_toolchain_root(runner_temp, build) as capability:
                installed, descriptor, _snapshot = bootstrap._create_private_child(
                    capability, "installed", build
                )
                nested = installed / "lib"
                nested.mkdir(mode=0o700)
                (nested / "tool.py").write_text("sealed\n", encoding="ascii")
                bootstrap.seal_installed_tree(installed, descriptor)
                if failure:
                    raise RuntimeError("synthetic toolchain failure")
    except RuntimeError:
        if not failure:
            raise
    assert not list(runner_temp.glob(f"{bootstrap.TOOLCHAIN_ROOT_PREFIX}*"))


def test_held_toolchain_root_replacement_is_preserved_and_cleanup_fails_closed(
    tmp_path: Path,
) -> None:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(mode=0o700)
    replacement: Path | None = None
    detached: Path | None = None
    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="exact cleanup failed",
    ):
        with build._translate_cleanup_signals():
            with bootstrap._held_toolchain_root(runner_temp, build) as capability:
                installed, descriptor, _snapshot = bootstrap._create_private_child(
                    capability,
                    "installed",
                    build,
                )
                (installed / "tool.py").write_text("sealed\n", encoding="ascii")
                bootstrap.seal_installed_tree(installed, descriptor)
                detached = runner_temp / f"detached-{capability.name}"
                capability.path.rename(detached)
                capability.path.mkdir(mode=0o700)
                replacement = capability.path
                (replacement / "do-not-delete").write_text(
                    "replacement\n",
                    encoding="ascii",
                )
                raise RuntimeError("force cleanup")

    assert replacement is not None and detached is not None
    assert (replacement / "do-not-delete").read_text(encoding="ascii") == (
        "replacement\n"
    )
    assert detached.is_dir()


@pytest.mark.parametrize(
    "signal_name",
    ["SIGINT", "SIGTERM", *(["SIGHUP"] if hasattr(signal, "SIGHUP") else [])],
)
def test_held_toolchain_root_signal_cleanup_has_no_residue(
    tmp_path: Path,
    signal_name: str,
) -> None:
    runner_temp = tmp_path / signal_name / "runner-temp"
    runner_temp.mkdir(mode=0o700, parents=True)
    script = f"""
import json,os,signal,sys
from pathlib import Path
sys.path.insert(0, {json.dumps(str(TOOLS_ROOT))})
import bootstrap_python_sidecar as bootstrap
import build_python_sidecar as build
runner = Path({json.dumps(str(runner_temp))})
error = None
try:
    with build._translate_cleanup_signals():
        with bootstrap._held_toolchain_root(runner, build):
            os.kill(os.getpid(), getattr(signal, {json.dumps(signal_name)}))
except build.BuildError as exc:
    error = str(exc)
print(json.dumps({{"error": error, "residue": sorted(p.name for p in runner.iterdir())}}))
"""
    assert _run_signal_probe(script) == {
        "error": build._INTERRUPTED_ERROR,
        "residue": [],
    }


def _synthetic_framework_inventory(
    root: Path,
    *,
    reviewed_broken_symlinks: Mapping[str, str] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    exclusions = tuple(
        PurePosixPath(item).parts
        for item in bootstrap.REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS
    )
    reviewed_broken = dict(reviewed_broken_symlinks or {})
    entries: list[dict[str, Any]] = []
    for item_path in sorted(
        root.rglob("*"),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        relative_path = item_path.relative_to(root)
        if any(
            relative_path.parts[: len(excluded)] == excluded
            for excluded in exclusions
        ):
            continue
        info = item_path.lstat()
        entry: dict[str, Any] = {
            "path": relative_path.as_posix(),
            "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        }
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(item_path)
            entry.update(
                {
                    "type": "symlink",
                    "target": target,
                    "sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
                }
            )
            try:
                item_path.resolve(strict=True)
            except (OSError, RuntimeError):
                if reviewed_broken.get(entry["path"]) != target:
                    raise AssertionError("synthetic broken symlink is not reviewed")
                entry["broken"] = True
        elif stat.S_ISDIR(info.st_mode):
            entry["type"] = "directory"
        elif stat.S_ISREG(info.st_mode):
            payload = item_path.read_bytes()
            entry.update(
                {
                    "type": "file",
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        else:
            raise AssertionError("synthetic inventory contains a special file")
        entries.append(entry)
    inventory_sha256 = hashlib.sha256(
        bootstrap._canonical_json_bytes(entries)
    ).hexdigest()
    manifest = {
        "schemaVersion": 1,
        "source": {
            "payloadSize": FRAMEWORK_COMPONENT_FIXTURE["payloadSize"],
            "payloadSha256": FRAMEWORK_COMPONENT_FIXTURE["payloadSha256"],
            "coreEntryCount": len(entries),
            "coreInventorySha256": inventory_sha256,
        },
        "transformations": [],
        "entryCount": len(entries),
        "inventorySha256": inventory_sha256,
        "entries": entries,
    }
    payload = bootstrap._canonical_json_bytes(manifest) + b"\n"
    contract = {
        "fileName": bootstrap.REVIEWED_FRAMEWORK_CORE_INVENTORY_NAME,
        "fileSize": len(payload),
        "fileSha256": hashlib.sha256(payload).hexdigest(),
        "schemaVersion": 1,
        "sourcePayloadSize": FRAMEWORK_COMPONENT_FIXTURE["payloadSize"],
        "sourcePayloadSha256": FRAMEWORK_COMPONENT_FIXTURE["payloadSha256"],
        "sourceEntryCount": len(entries),
        "sourceInventorySha256": inventory_sha256,
        "transformationCount": 0,
        "entryCount": len(entries),
        "inventorySha256": inventory_sha256,
    }
    return payload, contract


def _synthetic_reviewed_framework(
    tmp_path: Path,
) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "Python.framework" / "Versions" / "3.13"
    launcher = root / "bin" / "python3.13"
    launcher.parent.mkdir(mode=0o700, parents=True)
    launcher_payload = b"synthetic python launcher\n"
    launcher.write_bytes(launcher_payload)
    launcher.chmod(0o755)
    framework_payload = b"synthetic framework dylib\n"
    (root / "Python").write_bytes(framework_payload)
    (root / "Python").chmod(0o644)
    stdlib = root / "lib" / "python3.13"
    stdlib.mkdir(mode=0o755, parents=True)
    (stdlib / "json.py").write_text("reviewed = True\n", encoding="ascii")
    (stdlib / "json.py").chmod(0o644)
    _inventory_payload, inventory_contract = _synthetic_framework_inventory(root)
    python_lock = {
        "interpreterRelativePath": "bin/python3.13",
        "interpreterSize": len(launcher_payload),
        "interpreterSha256": hashlib.sha256(launcher_payload).hexdigest(),
        "frameworkBinaryRelativePath": "Python",
        "frameworkBinarySize": len(framework_payload),
        "frameworkBinarySha256": hashlib.sha256(framework_payload).hexdigest(),
        "frameworkCoreFingerprintExcludedPaths": list(
            bootstrap.REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS
        ),
        "frameworkCoreFingerprintSha256": build.fingerprint_install_root(
            root,
            excluded_paths=bootstrap.REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS,
        ),
        "frameworkCoreInventory": inventory_contract,
        "reviewedBrokenSymlinks": [],
    }
    return root, python_lock


def test_reviewed_framework_seal_accepts_real_python_org_modes_only_after_seal(
    tmp_path: Path,
) -> None:
    root, python_lock = _synthetic_reviewed_framework(tmp_path)
    (root / "bin" / "python3.13").chmod(0o775)
    (root / "Python").chmod(0o664)
    (root / "lib" / "python3.13" / "json.py").chmod(0o664)

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="writable or privileged|execution closure is unsafe",
    ):
        bootstrap._verify_reviewed_framework_seal(
            root,
            python_lock=python_lock,
            expected_owner=os.geteuid(),
        )

    for path in (root, *root.rglob("*")):
        if not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o022)
    bootstrap._verify_reviewed_framework_seal(
        root,
        python_lock=python_lock,
        expected_owner=os.geteuid(),
    )


def test_reviewed_framework_core_fingerprint_rejects_unlisted_stdlib_drift(
    tmp_path: Path,
) -> None:
    root, python_lock = _synthetic_reviewed_framework(tmp_path)
    bootstrap._verify_reviewed_framework_core(
        root,
        python_lock=python_lock,
        build=build,
    )
    site_packages = root / "lib" / "python3.13" / "site-packages"
    site_packages.mkdir()
    (site_packages / "dynamic.py").write_text("dynamic = True\n", encoding="ascii")
    bootstrap._verify_reviewed_framework_core(
        root,
        python_lock=python_lock,
        build=build,
    )

    (root / "lib" / "python3.13" / "json.py").write_text(
        "reviewed = False\n",
        encoding="ascii",
    )
    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="core fingerprint changed",
    ):
        bootstrap._verify_reviewed_framework_core(
            root,
            python_lock=python_lock,
            build=build,
        )


@pytest.mark.parametrize(
    ("listing", "unsafe"),
    (
        (b"drwxr-xr-x@ 1 root wheel 0 Jan 1 00:00 reviewed\n", False),
        (
            b"drwxr-xr-x@ 1 root wheel 0 Jan 1 00:00 reviewed\n"
            b" 0: group:everyone allow add_file\n",
            True,
        ),
    ),
)
def test_reviewed_framework_acl_seal_reads_acl_entries_not_mode_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    listing: bytes,
    unsafe: bool,
) -> None:
    root, _python_lock = _synthetic_reviewed_framework(tmp_path)
    monkeypatch.setattr(bootstrap.sys, "platform", "darwin")
    identity = (1, 2, stat.S_IFREG | 0o755, 0, 0, 1, 1, 1, 1)
    monkeypatch.setattr(bootstrap, "_exec_target_identity", lambda _path: identity)
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=("/bin/ls",),
            returncode=0,
            stdout=listing,
            stderr=b"",
        ),
    )

    if unsafe:
        with pytest.raises(
            bootstrap.ToolchainBootstrapError,
            match="ACL seal is unsafe",
        ):
            bootstrap._verify_reviewed_framework_acl_seal(root)
    else:
        bootstrap._verify_reviewed_framework_acl_seal(root)


@pytest.mark.parametrize(
    "mutation",
    (
        "group-write",
        "hidden-hardlink",
        "special",
        "escaping-symlink",
        "pyc",
        "pyo",
        "bare-pyc-directory",
        "uppercase-bytecode-cache",
        "bytecode-cache-directory",
    ),
)
def test_reviewed_framework_seal_rejects_dependency_alias_and_layout_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    root, python_lock = _synthetic_reviewed_framework(tmp_path)
    dependency = root / "lib" / "python3.13" / "json.py"
    if mutation == "group-write":
        dependency.chmod(0o664)
    elif mutation == "hidden-hardlink":
        os.link(dependency, tmp_path / "hidden-framework-alias")
    elif mutation == "special":
        os.mkfifo(root / "lib" / "python3.13" / "producer.pipe", 0o600)
    elif mutation == "escaping-symlink":
        (root / "lib" / "escape").symlink_to("../../../outside")
    elif mutation in {"pyc", "pyo"}:
        (root / "lib" / "python3.13" / f"legacy.{mutation}").write_bytes(
            b"unreviewed executable bytecode\n"
        )
    elif mutation == "bare-pyc-directory":
        (root / "lib" / "python3.13" / ".pyc").mkdir()
    elif mutation == "uppercase-bytecode-cache":
        cache = root / "lib" / "python3.13" / "__PYCACHE__"
        cache.mkdir()
        (cache / "JSON.CPYTHON-313.PYC").write_bytes(
            b"unreviewed executable bytecode\n"
        )
    else:
        cache = root / "lib" / "python3.13" / "__pycache__"
        cache.mkdir()
        (cache / "unexpected.txt").write_text("residue\n", encoding="ascii")

    with pytest.raises(bootstrap.ToolchainBootstrapError):
        bootstrap._verify_reviewed_framework_seal(
            root,
            python_lock=python_lock,
            expected_owner=os.geteuid(),
        )


def _configure_reviewed_python_installer_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure_label: str | None = None,
    launcher_drift: str | None = None,
    package_drift: bool = False,
    source_drift: bool = False,
) -> tuple[
    dict[str, str],
    Path,
    Path,
    Path,
    list[tuple[str, ...]],
    list[str],
]:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(mode=0o700)
    source_root = tmp_path / "exact-source"
    lock_path = (
        source_root
        / "backend"
        / "packaging"
        / "python-sidecar-toolchain.lock.json"
    )
    lock_path.parent.mkdir(mode=0o700, parents=True)
    framework_root = tmp_path / "Python.framework" / "Versions" / "3.13"
    monkeypatch.setattr(
        bootstrap,
        "DEFAULT_REVIEWED_FRAMEWORK_ROOT",
        PurePosixPath(framework_root.as_posix()),
    )
    interpreter = framework_root / "bin" / "python3.13"
    interpreter.parent.mkdir(mode=0o700, parents=True)
    interpreter_payload = b"#!/bin/sh\nexit 0\n"
    interpreter.write_bytes(interpreter_payload)
    interpreter.chmod(0o755)
    framework_binary = framework_root / "Python"
    framework_payload = b"synthetic framework binary\n"
    framework_binary.write_bytes(framework_payload)
    framework_binary.chmod(0o644)
    framework_core_fingerprint = build.fingerprint_install_root(
        framework_root,
        excluded_paths=bootstrap.REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS,
    )
    inventory_payload, inventory_contract = _synthetic_framework_inventory(
        framework_root
    )
    inventory_path = lock_path.parent / inventory_contract["fileName"]
    inventory_path.write_bytes(inventory_payload)
    inventory_path.chmod(0o600)
    monkeypatch.setattr(bootstrap.sys, "executable", str(interpreter))
    monkeypatch.setattr(
        bootstrap,
        "_reviewed_framework_owner",
        lambda: os.geteuid(),
    )
    package_payload = b"reviewed synthetic installer package\n"
    package_name = "python-3.13.14-macos11.pkg"
    lock_path.write_bytes(
        bootstrap._canonical_json_bytes(
            {
                "python": {
                    "installRoot": str(framework_root),
                    "interpreterRelativePath": "bin/python3.13",
                    "interpreterSize": len(interpreter_payload),
                    "interpreterSha256": hashlib.sha256(
                        interpreter_payload
                    ).hexdigest(),
                    "frameworkBinaryRelativePath": "Python",
                    "frameworkBinarySize": len(framework_payload),
                    "frameworkBinarySha256": hashlib.sha256(
                        framework_payload
                    ).hexdigest(),
                    "frameworkCoreFingerprintExcludedPaths": list(
                        bootstrap.REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS
                    ),
                    "frameworkCoreFingerprintSha256": (
                        framework_core_fingerprint
                    ),
                    "frameworkCoreInventory": inventory_contract,
                    "reviewedBrokenSymlinks": [],
                    "distribution": {
                        "installerPackageName": package_name,
                        "installerPackageSha256": hashlib.sha256(
                            package_payload
                        ).hexdigest(),
                        "installMethod": (
                            "macos-installer-no-op-framework-component"
                        ),
                        "frameworkComponent": copy.deepcopy(
                            FRAMEWORK_COMPONENT_FIXTURE
                        ),
                    },
                }
            }
        )
        + b"\n"
    )
    lock_path.chmod(0o600)
    source_descriptor = os.open(
        source_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    bound_lock = bootstrap._open_bound_file(
        lock_path,
        maximum_size=bootstrap.MAX_TREE_FILE_BYTES,
        error_message="fixture lock",
    )
    bound_inventory = bootstrap._open_bound_file(
        inventory_path,
        maximum_size=bootstrap.MAX_FRAMEWORK_CORE_INVENTORY_BYTES,
        error_message="fixture inventory",
    )
    source = bootstrap._SourceSeal(
        root=source_root,
        descriptor=source_descriptor,
        identity=bootstrap._identity(os.fstat(source_descriptor)),
        repository_commit="1" * 40,
        repository_tree="2" * 40,
        source_snapshot_sha256="3" * 64,
        files=(bound_lock, bound_inventory),
    )
    monkeypatch.setattr(bootstrap, "_validate_source_root", lambda *_args: source)
    source_revalidations = 0

    def revalidate_source(*_args: Any) -> None:
        nonlocal source_revalidations
        source_revalidations += 1
        if source_drift and source_revalidations == 2:
            raise bootstrap.ToolchainBootstrapError(
                "Reviewed exact source input changed"
            )

    monkeypatch.setattr(bootstrap, "_revalidate_source_seal", revalidate_source)
    events: list[str] = []
    verify_seal = bootstrap._verify_reviewed_framework_seal
    verify_core = bootstrap._verify_reviewed_framework_core

    def observe_seal(*args: Any, **kwargs: Any) -> None:
        events.append("seal")
        verify_seal(*args, **kwargs)

    def observe_core(*args: Any, **kwargs: Any) -> None:
        events.append("core")
        verify_core(*args, **kwargs)

    monkeypatch.setattr(
        bootstrap,
        "_verify_reviewed_framework_seal",
        observe_seal,
    )
    monkeypatch.setattr(
        bootstrap,
        "_verify_reviewed_framework_core",
        observe_core,
    )

    def extract_package(
        _archive: Path,
        _hash_manifest: Path,
        output: Path,
        *,
        toolchain: Mapping[str, Any],
    ) -> Path:
        assert toolchain["python"]["distribution"]["installerPackageName"] == (
            package_name
        )
        assert toolchain["python"]["distribution"]["installMethod"] == (
            "macos-installer-no-op-framework-component"
        )
        assert toolchain["python"]["distribution"]["frameworkComponent"] == (
            FRAMEWORK_COMPONENT_FIXTURE
        )
        events.append("extract")
        output.write_bytes(
            package_payload + (b"package drift\n" if package_drift else b"")
        )
        output.chmod(0o600)
        return output

    monkeypatch.setattr(
        build,
        "extract_reviewed_installer_package",
        extract_package,
    )
    calls: list[tuple[str, ...]] = []

    def run_process(
        arguments: Sequence[str],
        **kwargs: Any,
    ) -> str:
        command = tuple(arguments)
        calls.append(command)
        label = str(kwargs["label"])
        event = {
            "Python installer signature verification": "signature",
            "Python installer policy assessment": "policy",
            "Installed framework interpreter verification": "observer",
        }[label]
        events.append(event)
        if failure_label == label:
            raise bootstrap.ToolchainBootstrapError(f"{label} failed")
        if (
            launcher_drift is not None
            and label == "Python installer signature verification"
        ):
            if launcher_drift == "name":
                replacement = interpreter.with_name("python3.13.replacement")
                replacement.write_bytes(interpreter_payload)
                replacement.chmod(0o755)
                os.replace(replacement, interpreter)
            else:
                descriptor = os.open(
                    interpreter,
                    os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                )
                try:
                    os.pwrite(descriptor, b"X", 0)
                finally:
                    os.close(descriptor)
            bootstrap._revalidate_held_executable(
                kwargs["launcher_binding"],
                error_message="Reviewed Python installer launcher is unsafe",
            )
        if label == "Installed framework interpreter verification":
            return json.dumps(
                {
                    "implementation": "CPython",
                    "version": "3.13.14",
                    "system": "Darwin",
                    "machine": "arm64",
                    "basePrefix": str(framework_root),
                    "baseExecutable": str(interpreter),
                    "executable": str(interpreter),
                    "cacheTag": "cpython-313",
                    "gilDisabled": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        return ""

    monkeypatch.setattr(bootstrap, "_run_owned_process", run_process)
    monkeypatch.setattr(
        build,
        "verify_python_install_binding",
        lambda *_args, **_kwargs: events.append("binding") or "f" * 64,
    )
    archive = tmp_path / "python.tar.gz"
    hashes = tmp_path / "hashes.sha256"
    return (
        {"RUNNER_TEMP": str(runner_temp)},
        archive,
        hashes,
        runner_temp,
        calls,
        events,
    )


def test_reviewed_python_verification_uses_only_audit_commands_and_cleans_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment, archive, hashes, runner_temp, calls, events = (
        _configure_reviewed_python_installer_fixture(tmp_path, monkeypatch)
    )

    assert bootstrap.install_reviewed_python(
        environment,
        archive=archive,
        hash_manifest=hashes,
    ) == "f" * 64

    interpreter = str(
        tmp_path
        / "Python.framework"
        / "Versions"
        / "3.13"
        / "bin"
        / "python3.13"
    )
    assert tuple(command[0] for command in calls) == (
        "/usr/sbin/pkgutil",
        "/usr/sbin/spctl",
        interpreter,
    )
    package_path = calls[0][-1]
    assert calls[0] == (
        "/usr/sbin/pkgutil",
        "--check-signature",
        package_path,
    )
    assert calls[1] == (
        "/usr/sbin/spctl",
        "--assess",
        "--type",
        "install",
        "--verbose=4",
        package_path,
    )
    assert calls[2][:4] == (interpreter, "-I", "-S", "-c")
    forbidden = {
        "/usr/bin/sudo",
        "/usr/sbin/installer",
        "/usr/sbin/chown",
        "/bin/chmod",
        "/usr/bin/find",
    }
    assert not forbidden.intersection(
        argument for command in calls for argument in command
    )
    assert events == [
        "extract",
        "seal",
        "core",
        "signature",
        "policy",
        "seal",
        "core",
        "observer",
        "binding",
    ]
    assert not list(runner_temp.glob(f"{bootstrap.INSTALLER_ROOT_PREFIX}*"))


@pytest.mark.parametrize(
    "failure_label",
    (
        "Python installer signature verification",
        "Python installer policy assessment",
    ),
)
def test_reviewed_python_distribution_audit_failure_never_runs_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_label: str,
) -> None:
    environment, archive, hashes, runner_temp, calls, events = (
        _configure_reviewed_python_installer_fixture(
            tmp_path,
            monkeypatch,
            failure_label=failure_label,
        )
    )

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match=f"{failure_label} failed",
    ):
        bootstrap.install_reviewed_python(
            environment,
            archive=archive,
            hash_manifest=hashes,
        )

    assert "observer" not in events
    assert all(command[0] != str(Path(sys.executable)) for command in calls)
    assert not list(runner_temp.glob(f"{bootstrap.INSTALLER_ROOT_PREFIX}*"))


@pytest.mark.parametrize(
    "launcher_drift",
    ("name", "bytes"),
)
def test_reviewed_python_launcher_drift_is_rejected_before_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launcher_drift: str,
) -> None:
    environment, archive, hashes, runner_temp, _calls, events = (
        _configure_reviewed_python_installer_fixture(
            tmp_path,
            monkeypatch,
            launcher_drift=launcher_drift,
        )
    )

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="launcher is unsafe",
    ):
        bootstrap.install_reviewed_python(
            environment,
            archive=archive,
            hash_manifest=hashes,
        )

    assert "observer" not in events
    assert not list(runner_temp.glob(f"{bootstrap.INSTALLER_ROOT_PREFIX}*"))


@pytest.mark.parametrize(
    "drift",
    ("package", "source"),
)
def test_reviewed_python_package_or_source_drift_cleans_private_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    environment, archive, hashes, runner_temp, _calls, events = (
        _configure_reviewed_python_installer_fixture(
            tmp_path,
            monkeypatch,
            package_drift=drift == "package",
            source_drift=drift == "source",
        )
    )

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match=(
            "installer package changed"
            if drift == "package"
            else "source input changed"
        ),
    ):
        bootstrap.install_reviewed_python(
            environment,
            archive=archive,
            hash_manifest=hashes,
        )

    assert "observer" not in events
    assert not list(runner_temp.glob(f"{bootstrap.INSTALLER_ROOT_PREFIX}*"))


def _configure_exact_toolchain_build_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure_label: str | None = None,
    signal_name: str | None = None,
) -> tuple[dict[str, str], Path, list[str]]:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(mode=0o700)
    source_root = tmp_path / "exact-source"
    packaging_root = source_root / "backend" / "packaging"
    packaging_root.mkdir(mode=0o700, parents=True)
    framework_root = tmp_path / "Python.framework" / "Versions" / "3.13"
    monkeypatch.setattr(
        bootstrap,
        "DEFAULT_REVIEWED_FRAMEWORK_ROOT",
        PurePosixPath(framework_root.as_posix()),
    )
    framework_python = framework_root / "bin" / "python3.13"
    framework_python.parent.mkdir(mode=0o700, parents=True)
    framework_python_payload = b"#!/bin/sh\nexit 0\n"
    framework_python.write_bytes(framework_python_payload)
    framework_python.chmod(0o755)
    framework_binary_payload = b"synthetic framework binary\n"
    (framework_root / "Python").write_bytes(framework_binary_payload)
    (framework_root / "Python").chmod(0o644)
    framework_core_fingerprint = build.fingerprint_install_root(
        framework_root,
        excluded_paths=bootstrap.REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS,
    )
    inventory_payload, inventory_contract = _synthetic_framework_inventory(
        framework_root
    )
    build_lock_path = packaging_root / "build-requirements.lock"
    build_lock_path.write_bytes(
        (PROJECT_ROOT / "backend" / "packaging" / "build-requirements.lock").read_bytes()
    )
    uv_lock_path = source_root / "backend" / "uv.lock"
    uv_lock_path.write_bytes(b"version = 1\n")
    toolchain_lock_path = packaging_root / "python-sidecar-toolchain.lock.json"
    inventory_path = packaging_root / inventory_contract["fileName"]
    inventory_path.write_bytes(inventory_payload)
    toolchain_lock_path.write_bytes(
        bootstrap._canonical_json_bytes(
            {
                "python": {
                    "installRoot": str(framework_root),
                    "interpreterRelativePath": "bin/python3.13",
                    "interpreterSize": len(framework_python_payload),
                    "interpreterSha256": hashlib.sha256(
                        framework_python_payload
                    ).hexdigest(),
                    "frameworkBinaryRelativePath": "Python",
                    "frameworkBinarySize": len(framework_binary_payload),
                    "frameworkBinarySha256": hashlib.sha256(
                        framework_binary_payload
                    ).hexdigest(),
                    "frameworkCoreFingerprintExcludedPaths": list(
                        bootstrap.REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS
                    ),
                    "frameworkCoreFingerprintSha256": (
                        framework_core_fingerprint
                    ),
                    "frameworkCoreInventory": inventory_contract,
                    "reviewedBrokenSymlinks": [],
                }
            }
        )
        + b"\n"
    )
    for path in (
        build_lock_path,
        uv_lock_path,
        inventory_path,
        toolchain_lock_path,
    ):
        path.chmod(0o600)
    source_descriptor = os.open(
        source_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    bound_files = tuple(
        bootstrap._open_bound_file(
            path,
            maximum_size=bootstrap.MAX_TREE_FILE_BYTES,
            error_message="fixture source",
        )
        for path in (
            build_lock_path,
            uv_lock_path,
            inventory_path,
            toolchain_lock_path,
        )
    )
    source = bootstrap._SourceSeal(
        root=source_root,
        descriptor=source_descriptor,
        identity=bootstrap._identity(os.fstat(source_descriptor)),
        repository_commit="1" * 40,
        repository_tree="2" * 40,
        source_snapshot_sha256="3" * 64,
        files=bound_files,
    )
    monkeypatch.setattr(bootstrap, "_validate_source_root", lambda *_args: source)
    monkeypatch.setattr(bootstrap, "_revalidate_source_seal", lambda *_args: None)
    monkeypatch.setattr(
        build,
        "verify_python_install_binding",
        lambda *_args, **_kwargs: "f" * 64,
    )
    monkeypatch.setattr(bootstrap.sys, "executable", str(framework_python))
    monkeypatch.setattr(
        bootstrap,
        "_reviewed_framework_owner",
        lambda: os.geteuid(),
    )
    labels: list[str] = []

    def create_synthetic_venv(root: Path) -> None:
        binary_root = root / "bin"
        binary_root.mkdir(mode=0o700, exist_ok=True)
        python_link = binary_root / "python"
        if not python_link.exists() and not python_link.is_symlink():
            python_link.symlink_to(framework_python)
        configuration = root / "pyvenv.cfg"
        configuration.write_text("version = 3.13.14\n", encoding="ascii")
        configuration.chmod(0o600)

    def run_process(arguments: Sequence[str], **kwargs: Any) -> str:
        label = str(kwargs["label"])
        labels.append(label)
        if signal_name is not None and label == "Exact Python sidecar inner build":
            os.kill(os.getpid(), getattr(signal, signal_name))
        if failure_label == label:
            raise bootstrap.ToolchainBootstrapError(f"{label} failed")
        if label == "Python bootstrap venv creation":
            create_synthetic_venv(Path(arguments[-1]))
        elif label == "Hash-locked Python bootstrap install":
            uv = Path(arguments[0]).parent / "uv"
            uv.write_bytes(b"#!/bin/sh\nexit 0\n")
            uv.chmod(0o700)
        elif label == "Exact uv runtime export":
            return "fixture-runtime==1.0 --hash=sha256:" + "a" * 64 + "\n"
        elif label == "Python build venv creation":
            create_synthetic_venv(Path(arguments[-1]))
        elif label == "Complete hash-locked Python build install":
            installed = Path(arguments[0]).parents[1] / "installed-package.txt"
            installed.write_text("fixture==1.0\n", encoding="ascii")
            installed.chmod(0o600)
        elif label == "Exact Python sidecar inner build":
            return "built\n"
        return ""

    monkeypatch.setattr(bootstrap, "_run_owned_process", run_process)
    environment = {
        "RUNNER_TEMP": str(runner_temp),
        "LCF_PYTHON_INSTALL_ROOT": str(framework_root),
        "LCF_REVIEWED_BUILD_PYTHON": str(framework_python),
    }
    return environment, runner_temp, labels


def test_exact_toolchain_build_success_seals_and_cleans_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment, runner_temp, labels = _configure_exact_toolchain_build_fixture(
        tmp_path,
        monkeypatch,
    )

    assert bootstrap.build_with_exact_toolchain(environment) == "built\n"

    assert labels == [
        "Python bootstrap venv creation",
        "Hash-locked Python bootstrap install",
        "Exact uv runtime export",
        "Python build venv creation",
        "Complete hash-locked Python build install",
        "Exact Python sidecar inner build",
    ]
    assert not list(runner_temp.glob(f"{bootstrap.TOOLCHAIN_ROOT_PREFIX}*"))


def test_exact_toolchain_build_failure_cleans_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment, runner_temp, _labels = _configure_exact_toolchain_build_fixture(
        tmp_path,
        monkeypatch,
        failure_label="Complete hash-locked Python build install",
    )

    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="Complete hash-locked Python build install failed",
    ):
        bootstrap.build_with_exact_toolchain(environment)

    assert not list(runner_temp.glob(f"{bootstrap.TOOLCHAIN_ROOT_PREFIX}*"))


@pytest.mark.parametrize(
    "signal_name",
    ["SIGINT", "SIGTERM", *(["SIGHUP"] if hasattr(signal, "SIGHUP") else [])],
)
def test_exact_toolchain_build_signal_cleans_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signal_name: str,
) -> None:
    environment, runner_temp, _labels = _configure_exact_toolchain_build_fixture(
        tmp_path,
        monkeypatch,
        signal_name=signal_name,
    )

    with pytest.raises(build.BuildError, match=build._INTERRUPTED_ERROR):
        bootstrap.build_with_exact_toolchain(environment)

    assert not list(runner_temp.glob(f"{bootstrap.TOOLCHAIN_ROOT_PREFIX}*"))


def test_exact_source_bound_file_revalidation_rejects_pre_spawn_drift(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "build-requirements.lock"
    lock.write_bytes(b"locked\n")
    lock.chmod(0o600)
    bound = bootstrap._open_bound_file(
        lock,
        maximum_size=1024,
        error_message="lock unsafe",
    )
    try:
        lock.write_bytes(b"drift!\n")
        with pytest.raises(bootstrap.ToolchainBootstrapError, match="lock changed"):
            bootstrap._revalidate_bound_file(
                bound,
                maximum_size=1024,
                error_message="lock changed",
            )
    finally:
        os.close(bound.descriptor)


def test_bootstrap_rejects_missing_or_non_module_exact_source_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="Reviewed exact source root is unavailable",
    ):
        bootstrap._validate_source_root({}, build)

    unrelated = tmp_path / "private-exact-looking-root"
    unrelated.mkdir(mode=0o700)
    with pytest.raises(
        bootstrap.ToolchainBootstrapError,
        match="must run from the reviewed exact source root",
    ):
        bootstrap._validate_source_root(
            {"LCF_REVIEWED_SOURCE_ROOT": str(unrelated)},
            build,
        )


def test_toolchain_environment_is_closed_against_config_injection(
    tmp_path: Path,
) -> None:
    environment = bootstrap._sanitized_environment(
        home=tmp_path / "home",
        cache=tmp_path / "cache",
        temporary=tmp_path / "tmp",
    )
    assert environment["PIP_CONFIG_FILE"] == "/dev/null"
    assert environment["UV_NO_CONFIG"] == "1"
    assert environment["PIP_ONLY_BINARY"] == ":all:"
    assert environment["UV_NO_BUILD"] == "1"
    assert not {"PYTHONPATH", "PIP_INDEX_URL", "UV_INDEX_URL"}.intersection(environment)


def _toolchain_evidence_fixture(
    root: Path,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    versions = build.parse_build_requirements(
        PROJECT_ROOT / "backend" / "packaging" / "build-requirements.lock"
    )
    tools = {
        audit.BUILD_TOOL_EVIDENCE_KEYS[name]: version
        for name, version in sorted(versions.items())
    }
    content = hashlib.sha256(
        audit.canonical_json_bytes({"schemaVersion": 1, "entries": files})
    ).hexdigest()
    summary = {
        "buildRequirementsLockSha256": audit.sha256_file(
            PROJECT_ROOT / "backend" / "packaging" / "build-requirements.lock"
        ),
        "runtimeLockSha256": audit.sha256_file(PROJECT_ROOT / "backend" / "uv.lock"),
        "runtimeRequirementsSha256": "3" * 64,
        "installedTreeContentSha256": content,
        "buildTools": tools,
    }
    evidence = {
        "$schema": audit.TOOLCHAIN_EVIDENCE_SCHEMA,
        "schemaVersion": 1,
        **summary,
        "files": files,
    }
    (root / audit.TOOLCHAIN_EVIDENCE_ARTIFACT).write_bytes(
        audit.canonical_json_bytes(evidence) + b"\n"
    )
    return {
        "build": {"pythonToolchain": summary},
        "artifacts": {
            "spdxSbom": "sbom.spdx.json",
            "thirdPartyNotices": "THIRD-PARTY-NOTICES.txt",
            "licensesDirectory": "licenses",
            "pythonBuildToolchain": audit.TOOLCHAIN_EVIDENCE_ARTIFACT,
        },
    }


def test_toolchain_evidence_rejects_owner_write_after_digest_reseal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    manifest = _toolchain_evidence_fixture(
        root,
        [{"path": ".", "type": "directory", "mode": "0700", "size": 0}],
    )
    with pytest.raises(audit.AuditError, match="entry is malformed|directory mode"):
        audit._validate_toolchain_evidence_artifact(
            root, manifest, repository_root=PROJECT_ROOT
        )


@pytest.mark.parametrize(
    "target",
    [
        "../../outside",
        "/etc/passwd",
        "/Library/Frameworks/Python.framework/Versions/3.13/../../etc/passwd",
    ],
)
def test_toolchain_evidence_rejects_symlink_escape_after_digest_reseal(
    tmp_path: Path,
    target: str,
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    manifest = _toolchain_evidence_fixture(
        root,
        [
            {"path": ".", "type": "directory", "mode": "0500", "size": 0},
            {
                "path": "bin/python",
                "type": "symlink",
                "mode": "0777",
                "size": len(target.encode("utf-8")),
                "target": target,
            },
        ],
    )
    with pytest.raises(audit.AuditError, match="symlink"):
        audit._validate_toolchain_evidence_artifact(
            root, manifest, repository_root=PROJECT_ROOT
        )


def test_toolchain_evidence_rejects_manifest_tamper(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    manifest = _toolchain_evidence_fixture(
        root,
        [{"path": ".", "type": "directory", "mode": "0500", "size": 0}],
    )
    manifest["build"]["pythonToolchain"]["runtimeRequirementsSha256"] = "4" * 64
    with pytest.raises(audit.AuditError, match="differs from the manifest"):
        audit._validate_toolchain_evidence_artifact(
            root, manifest, repository_root=PROJECT_ROOT
        )


def test_toolchain_evidence_rejects_impossible_inventory_hierarchy(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    manifest = _toolchain_evidence_fixture(
        root,
        [
            {"path": ".", "type": "directory", "mode": "0500", "size": 0},
            {
                "path": "missing/leaf.py",
                "type": "file",
                "mode": "0400",
                "size": 1,
                "sha256": hashlib.sha256(b"x").hexdigest(),
            },
        ],
    )

    with pytest.raises(audit.AuditError, match="hierarchy"):
        audit._validate_toolchain_evidence_artifact(
            root,
            manifest,
            repository_root=PROJECT_ROOT,
        )


def test_build_manifest_consumes_explicit_toolchain_evidence_without_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(audit, "build_file_inventory", lambda _root: [])
    monkeypatch.setattr(
        audit,
        "scan_macho_inventory",
        lambda _root, **_kwargs: [],
    )
    monkeypatch.setattr(audit, "validate_native_inventory", lambda *_args: None)
    monkeypatch.setattr(
        audit,
        "normalized_inventory_sha256",
        lambda *_args: "9" * 64,
    )
    evidence = {
        "buildRequirementsLockSha256": "1" * 64,
        "runtimeLockSha256": "2" * 64,
        "runtimeRequirementsSha256": "3" * 64,
        "installedTreeContentSha256": "4" * 64,
        "buildTools": {
            key: "fixture"
            for key in build.BUILD_TOOL_EVIDENCE_KEYS.values()
        },
    }

    bundle_descriptor = os.open(
        bundle,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        manifest = build._build_manifest(
        bundle=bundle,
        bundle_descriptor=bundle_descriptor,
        versions={
            "productVersion": "0.1.0",
            "pythonDistributionVersion": "3.13.14",
            "desktopProtocol": 1,
            "databaseSchema": 1,
        },
        toolchain={
            "target": {"os": "macos", "architecture": "arm64"},
            "tools": {
                "uv": "0.11.29",
                "pyinstaller": "6.21.0",
                "pyinstallerHooksContrib": "2026.6",
            },
        },
        release={"repositoryCommit": "a" * 40},
        python_provenance={"distribution": "fixture"},
        python_fingerprint="5" * 64,
        components=[],
        artifacts={
            "spdxSbom": "sbom.spdx.json",
            "thirdPartyNotices": "THIRD-PARTY-NOTICES.txt",
            "licensesDirectory": "licenses",
            "pythonBuildToolchain": build.TOOLCHAIN_EVIDENCE_ARTIFACT,
        },
        frozen_smoke={"status": "pass"},
        toolchain_evidence=evidence,
        source_root=PROJECT_ROOT,
        )
    finally:
        os.close(bundle_descriptor)

    assert manifest["build"]["pythonToolchain"] == evidence
    assert manifest["artifacts"]["pythonBuildToolchain"] == (
        build.TOOLCHAIN_EVIDENCE_ARTIFACT
    )


def test_make_uses_only_exact_bootstrap_without_repo_toolchain_scratch() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "python-sidecar-toolchain:" not in makefile
    assert ".python-sidecar-build-venv" not in makefile
    assert ".python-sidecar-build" not in makefile
    assert '"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py"' in makefile
    assert "--install-reviewed-python" in makefile
