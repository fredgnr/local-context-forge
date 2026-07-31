from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import tarfile
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import certifi
import urllib3
from dulwich.client import Urllib3HttpGitClient, get_transport_and_path
from dulwich.config import ConfigFile
from dulwich.objects import Blob, Commit, Tag, Tree, S_ISGITLINK
from dulwich.object_store import iter_tree_contents
from dulwich.refs import check_ref_format

from .config import Settings
from .dulwich_support import ControlledGitError, ControlledRepo, open_controlled_repo
from .utils import atomic_write_json, utcnow

IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".next",
    ".cache",
}

SENSITIVE_DIRECTORY_NAMES = {
    ".aws",
    ".azure",
    ".codex",
    ".gcp",
    ".kube",
    ".secrets",
    ".ssh",
    "secrets",
}
SENSITIVE_FILE_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "auth.json",
    "credentials",
    "credentials.json",
    "service-account.json",
    "terraform.tfstate",
    "id_ed25519",
    "id_rsa",
}
SENSITIVE_SUFFIXES = {
    ".jks",
    ".key",
    ".p12",
    ".pem",
    ".pfx",
    ".tfvars",
}


@dataclass(slots=True)
class Snapshot:
    source_sha: str
    repo_path: Path
    metadata_path: Path
    source_kind: str
    ref: str


class SourceError(RuntimeError):
    pass


@dataclass(slots=True)
class _GitResult:
    """Compatibility result for the former subprocess monkeypatch seam."""

    stdout: bytes
    stderr: bytes = b""
    returncode: int = 0


def sensitive_path_reason(relative: Path | str) -> str | None:
    path = Path(relative)
    lowered_parts = tuple(part.lower() for part in path.parts)
    if any(part in SENSITIVE_DIRECTORY_NAMES for part in lowered_parts[:-1]):
        return "sensitive-directory"
    name = path.name.lower()
    safe_env_templates = {".env.example", ".env.sample", ".env.template"}
    if name in SENSITIVE_FILE_NAMES or (
        name.startswith(".env.") and name not in safe_env_templates
    ):
        return "sensitive-filename"
    if any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
        return "sensitive-suffix"
    if name.startswith("terraform.tfstate."):
        return "sensitive-filename"
    if "secret" in name and path.suffix.lower() in {".json", ".yaml", ".yml"}:
        return "sensitive-filename"
    return None


def _run_git(
    arguments: list[str], *, cwd: Path | None = None, timeout: int = 300
) -> _GitResult:
    """Run a small, semantic Dulwich allowlist.

    The name and return shape are retained for tests that monkeypatch the old
    seam. No executable lookup or child process occurs here.
    """

    del timeout
    if cwd is None:
        raise SourceError("A repository path is required for Git inspection")
    repository = cwd.resolve()
    if arguments == ["rev-parse", "--is-inside-work-tree"]:
        root = _git_repository_root(repository)
        return _GitResult(b"true\n" if root is not None else b"false\n")
    if arguments == ["rev-parse", "--show-toplevel"]:
        root = _git_repository_root(repository)
        if root is None:
            raise SourceError("Not a Git working tree")
        return _GitResult(os.fsencode(root) + b"\n")

    with _open_source_repository(repository) as repo:
        if arguments == ["rev-parse", "--absolute-git-dir"]:
            return _GitResult(os.fsencode(repository / ".git") + b"\n")
        if arguments == ["rev-parse", "--git-common-dir"]:
            return _GitResult(os.fsencode(repository / ".git") + b"\n")
        if arguments == ["rev-parse", "--git-path", "objects"]:
            return _GitResult(os.fsencode(repository / ".git" / "objects") + b"\n")
        if (
            len(arguments) >= 2
            and arguments[0] == "rev-parse"
            and arguments[-1].endswith("^{commit}")
        ):
            candidate = arguments[-1][: -len("^{commit}")]
            resolved = _resolve_candidate_commit(repo, candidate)
            if resolved is None:
                raise SourceError(f"Git ref does not exist: {candidate}")
            return _GitResult(resolved.encode("ascii") + b"\n")
        if (
            len(arguments) == 5
            and arguments[:4] == ["ls-tree", "-r", "-z", "--full-tree"]
        ):
            commit = _commit_object(repo, arguments[4])
            records: list[bytes] = []
            for entry in iter_tree_contents(
                repo.object_store, commit.tree, include_trees=False
            ):
                if entry.path is None or entry.mode is None or entry.sha is None:
                    raise SourceError("Git tree contains an incomplete entry")
                object_type = (
                    b"commit" if S_ISGITLINK(entry.mode) else b"blob"
                )
                records.append(
                    f"{entry.mode:o} ".encode("ascii")
                    + object_type
                    + b" "
                    + entry.sha
                    + b"\t"
                    + entry.path
                    + b"\0"
                )
            return _GitResult(b"".join(records))
    raise SourceError(f"Unsupported controlled Git operation: {' '.join(arguments)}")


def _git_environment() -> dict[str, str]:
    """Return a deterministic Git environment without caller-supplied overrides."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ALLOW_PROTOCOL": "https:file",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
    )
    return environment


def _git_repository_root(path: Path) -> Path | None:
    current = path.resolve()
    for candidate in (current, *current.parents):
        marker = candidate / ".git"
        if marker.exists() or marker.is_symlink():
            return candidate
    return None


def _validate_local_git_repository(repository: Path) -> None:
    """Reject Git metadata indirection that can escape the authorized source."""

    repository = repository.resolve()
    marker = repository / ".git"
    if marker.is_symlink() or not marker.is_dir():
        raise SourceError(
            "A local Git source must contain a standalone .git directory; "
            "linked worktrees and gitdir pointer files are not accepted. Export "
            "a materialized worktree without its parent .git metadata instead."
        )
    config = marker / "config"
    if config.exists() and (config.is_symlink() or not config.is_file()):
        raise SourceError("Local Git .git/config must be a regular file")
    if (marker / "commondir").exists():
        raise SourceError("Local Git common-directory indirection is not accepted")
    if (marker / "objects" / "info" / "alternates").exists():
        raise SourceError("Local Git alternate object stores are not accepted")
    for required_directory in (marker / "objects", marker / "refs"):
        if required_directory.is_symlink() or not required_directory.is_dir():
            raise SourceError(
                "Local Git metadata or object storage escapes the authorized "
                "repository directory"
            )
    head = marker / "HEAD"
    if head.is_symlink() or not head.is_file():
        raise SourceError("Local Git HEAD must be a regular local file")

    for current_root, directory_names, file_names in os.walk(
        marker, followlinks=False
    ):
        for name in [*directory_names, *file_names]:
            candidate = Path(current_root) / name
            if candidate.is_symlink():
                raise SourceError(
                    "Local Git metadata must not contain symlinks or escape "
                    "the authorized repository directory"
                )

    if config.exists():
        try:
            local_config = ConfigFile.from_path(config, expand_includes=False)
        except (OSError, ValueError) as error:
            raise SourceError(f"Local Git config is unreadable: {error}") from error
        try:
            local_config.get((b"core",), b"worktree")
        except KeyError:
            pass
        else:
            raise SourceError("Local Git core.worktree indirection is not accepted")
        if local_config.get_boolean((b"core",), b"bare", False):
            raise SourceError("A bare Git repository is not an accepted local source")


def _open_source_repository(repository: Path) -> ControlledRepo:
    _validate_local_git_repository(repository)
    try:
        return open_controlled_repo(repository)
    except ControlledGitError as error:
        raise SourceError(str(error)) from error


def _safe_extract(
    archive_path: Path,
    destination: Path,
    *,
    max_files: int,
    max_bytes: int,
) -> None:
    destination_resolved = destination.resolve()
    with tarfile.open(archive_path, "r") as archive:
        members = archive.getmembers()
        if len(members) > max_files:
            raise SourceError(
                f"Source snapshot exceeds LCF_MAX_SNAPSHOT_FILES ({max_files})"
            )
        regular_bytes = sum(member.size for member in members if member.isreg())
        if regular_bytes > max_bytes:
            raise SourceError(
                f"Source snapshot exceeds LCF_MAX_SNAPSHOT_BYTES ({max_bytes})"
            )
        seen: set[str] = set()
        portable_seen: dict[str, str] = {}
        for member in members:
            if not (
                member.isdir()
                or member.isreg()
                or member.issym()
                or member.islnk()
            ):
                raise SourceError(
                    f"Unsupported special file in git archive: {member.name}"
                )
            if member.name in seen:
                raise SourceError(f"Duplicate path in git archive: {member.name}")
            seen.add(member.name)
            portable_name = unicodedata.normalize(
                "NFC", member.name.rstrip("/")
            ).casefold()
            previous_name = portable_seen.get(portable_name)
            if previous_name is not None:
                raise SourceError(
                    "Git archive contains paths that collide on portable "
                    f"filesystems: {previous_name!r} and {member.name!r}"
                )
            portable_seen[portable_name] = member.name.rstrip("/")
            member_path = (destination / member.name).resolve()
            if not member_path.is_relative_to(destination_resolved):
                raise SourceError(f"Unsafe path in git archive: {member.name}")
            if member.issym():
                link_target = (
                    destination / Path(member.name).parent / member.linkname
                ).resolve()
                if not link_target.is_relative_to(destination_resolved):
                    raise SourceError(f"Unsafe symlink in git archive: {member.name}")
            if member.islnk():
                link_target = (destination / member.linkname).resolve()
                if not link_target.is_relative_to(destination_resolved):
                    raise SourceError(f"Unsafe hardlink in git archive: {member.name}")
        archive.extractall(destination, filter="data")


def _list_sensitive_paths(root: Path) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        reason = sensitive_path_reason(relative)
        if not reason or not (path.is_file() or path.is_symlink()):
            continue
        skipped.append({"path": relative.as_posix(), "reason": reason})
    return skipped


def _archive_git(
    settings: Settings, repository: Path, ref: str, destination: Path
) -> tuple[str, list[dict[str, str]]]:
    source_sha = _resolve_git_commit(repository, ref)
    prepared: list[tuple[str, int, bytes | None]] = []
    portable_seen: dict[str, str] = {}
    byte_count = 0
    submodules: list[str] = []
    lfs_pointers: list[str] = []
    signature = b"version https://git-lfs.github.com/spec/v1\n"

    try:
        with _open_source_repository(repository) as repo:
            commit = _commit_object(repo, source_sha)
            entries = iter_tree_contents(
                repo.object_store, commit.tree, include_trees=True
            )
            file_count = 0
            for entry in entries:
                if entry.path == b"" and entry.mode is not None and stat.S_ISDIR(
                    entry.mode
                ):
                    continue
                file_count += 1
                if file_count > settings.max_snapshot_files:
                    raise SourceError(
                        "Source snapshot exceeds "
                        f"LCF_MAX_SNAPSHOT_FILES ({settings.max_snapshot_files})"
                    )
                if entry.path is None or entry.mode is None or entry.sha is None:
                    raise SourceError("Git tree contains an incomplete entry")
                relative = _decode_git_tree_path(entry.path)
                portable_key = unicodedata.normalize("NFC", relative).casefold()
                previous = portable_seen.get(portable_key)
                if previous is not None:
                    raise SourceError(
                        "Git archive contains paths that collide on portable "
                        f"filesystems: {previous!r} and {relative!r}"
                    )
                portable_seen[portable_key] = relative

                if entry.mode == 0o160000:
                    submodules.append(relative)
                    continue
                if entry.mode == 0o040000:
                    tree = repo.object_store[entry.sha]
                    if not isinstance(tree, Tree):
                        raise SourceError(
                            f"Git tree entry has an invalid object: {relative}"
                        )
                    prepared.append((relative, entry.mode, None))
                    continue
                if entry.mode not in {0o100644, 0o100755, 0o120000}:
                    raise SourceError(
                        f"Unsupported special file in git archive: {relative}"
                    )
                blob = repo.object_store[entry.sha]
                if not isinstance(blob, Blob):
                    raise SourceError(
                        f"Git file entry has an invalid object: {relative}"
                    )
                data = blob.data
                if entry.mode in {0o100644, 0o100755}:
                    byte_count += len(data)
                    if byte_count > settings.max_snapshot_bytes:
                        raise SourceError(
                            "Source snapshot exceeds "
                            f"LCF_MAX_SNAPSHOT_BYTES ({settings.max_snapshot_bytes})"
                        )
                    if (
                        data[:200].startswith(signature)
                        and b"\noid sha256:" in data[:200]
                        and len(lfs_pointers) < 5
                    ):
                        lfs_pointers.append(relative)
                else:
                    _validate_git_symlink(relative, data)
                prepared.append((relative, entry.mode, data))
    except SourceError:
        raise
    except Exception as error:
        raise SourceError(
            "Git repository has a missing or invalid required snapshot object"
        ) from error

    if submodules:
        preview = ", ".join(submodules[:5])
        raise SourceError(
            "Git submodules are not materialized by git archive "
            f"({preview}). Export a complete worktree without its parent "
            ".git directory into an allowed imports directory."
        )
    if lfs_pointers:
        raise SourceError(
            "Git LFS pointer files are not materialized by git archive "
            f"({', '.join(lfs_pointers)}). Export a fully smudged worktree "
            "without its parent .git directory into an allowed imports "
            "directory."
        )

    for relative, mode, data in prepared:
        target = destination.joinpath(*relative.split("/"))
        if mode == 0o040000:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        assert data is not None
        if mode == 0o120000:
            os.symlink(data.decode("utf-8"), target)
        else:
            target.write_bytes(data)
            target.chmod(0o755 if mode & 0o111 else 0o644)
    return source_sha, _list_sensitive_paths(destination)


def _decode_git_tree_path(path: bytes) -> str:
    try:
        decoded = path.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceError("Git tree paths must be valid UTF-8") from error
    parts = decoded.split("/")
    if (
        not decoded
        or decoded.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or any(part.casefold() == ".git" for part in parts)
        or "\0" in decoded
    ):
        raise SourceError(f"Unsafe path in git archive: {decoded!r}")
    return decoded


def _validate_git_symlink(relative: str, target: bytes) -> None:
    try:
        decoded_target = target.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceError(
            f"Unsafe symlink in git archive: {relative}"
        ) from error
    if (
        not decoded_target
        or "\0" in decoded_target
        or decoded_target.startswith("/")
        or len(target) > 4096
    ):
        raise SourceError(f"Unsafe symlink in git archive: {relative}")
    combined = posixpath.normpath(
        posixpath.join(posixpath.dirname(relative), decoded_target)
    )
    if combined == ".." or combined.startswith("../") or combined.startswith("/"):
        raise SourceError(f"Unsafe symlink in git archive: {relative}")


def _iter_source_files(source: Path):
    for root, directory_names, file_names in os.walk(source):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in IGNORED_DIRECTORIES and not (Path(root) / name).is_symlink()
        )
        for name in sorted(file_names):
            if name in IGNORED_DIRECTORIES:
                continue
            path = Path(root) / name
            if not path.is_file() or path.is_symlink():
                continue
            yield path


def _hash_directory(
    source: Path, *, max_files: int, max_bytes: int
) -> str:
    digest = hashlib.sha256()
    byte_count = 0
    portable_seen: dict[str, str] = {}
    for file_count, path in enumerate(_iter_source_files(source), start=1):
        if file_count > max_files:
            raise SourceError(
                f"Source snapshot exceeds LCF_MAX_SNAPSHOT_FILES ({max_files})"
            )
        relative = path.relative_to(source).as_posix()
        portable_key = unicodedata.normalize("NFC", relative).casefold()
        previous = portable_seen.get(portable_key)
        if previous is not None:
            raise SourceError(
                "Source contains paths that collide on portable filesystems: "
                f"{previous!r} and {relative!r}"
            )
        portable_seen[portable_key] = relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                byte_count += len(chunk)
                if byte_count > max_bytes:
                    raise SourceError(
                        "Source snapshot exceeds "
                        f"LCF_MAX_SNAPSHOT_BYTES ({max_bytes})"
                    )
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_directory(
    settings: Settings, source: Path, destination: Path
) -> tuple[str, list[dict[str, str]]]:
    resource_limits = {
        "max_files": settings.max_snapshot_files,
        "max_bytes": settings.max_snapshot_bytes,
    }
    source_sha_before = _hash_directory(source, **resource_limits)
    skipped: list[dict[str, str]] = []
    for path in _iter_source_files(source):
        relative = path.relative_to(source)
        reason = sensitive_path_reason(relative)
        if reason:
            skipped.append({"path": relative.as_posix(), "reason": reason})
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        shutil.copymode(path, target, follow_symlinks=False)
    copied_sha = _hash_directory(destination, **resource_limits)
    source_sha_after = _hash_directory(source, **resource_limits)
    if not (
        source_sha_before == copied_sha
        and copied_sha == source_sha_after
    ):
        raise SourceError(
            "Local source changed while the immutable snapshot was being copied. "
            "Pause writers or ingest a committed Git ref, then retry."
        )
    return copied_sha, skipped


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            if path.is_dir():
                # Keep directories traversable/removable by the service while
                # making every snapshot file non-writable.
                path.chmod(
                    stat.S_IRUSR
                    | stat.S_IWUSR
                    | stat.S_IXUSR
                    | stat.S_IRGRP
                    | stat.S_IXGRP
                )
            elif path.is_file():
                path.chmod(stat.S_IRUSR | stat.S_IRGRP)
        except OSError:
            # Read-only snapshots are an extra guard. The content hash and
            # one-shot atomic creation are the authoritative guarantees.
            pass
    try:
        root.chmod(
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP
        )
    except OSError:
        pass


def is_remote_source(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme == "https"


def is_unsupported_remote_source(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "ssh", "git"} or source.startswith("git@")


class _DeadlinePoolManager(urllib3.PoolManager):
    """HTTPS pool with redirects, proxies, retries, and unbounded waits disabled."""

    def __init__(self, *, timeout_seconds: int):
        self._deadline = time.monotonic() + timeout_seconds
        retries = urllib3.util.Retry(
            total=0,
            connect=0,
            read=0,
            redirect=0,
            status=0,
            raise_on_redirect=False,
        )
        super().__init__(
            cert_reqs="CERT_REQUIRED",
            ca_certs=certifi.where(),
            headers={"User-Agent": "Local-Context-Forge/controlled-dulwich"},
            retries=retries,
        )

    def check_deadline(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise urllib3.exceptions.TimeoutError(
                "Remote Git operation exceeded its overall deadline"
            )
        return remaining

    def request(self, method: str, url: str, **kwargs):
        remaining = self.check_deadline()
        kwargs["redirect"] = False
        kwargs["timeout"] = urllib3.util.Timeout(
            connect=min(10.0, remaining),
            read=min(60.0, remaining),
            total=remaining,
        )
        return super().request(method, url, **kwargs)


def _clone_remote_repository(
    source: str, destination: Path, *, timeout_seconds: int = 900
) -> None:
    pool = _DeadlinePoolManager(timeout_seconds=timeout_seconds)
    client = None
    try:
        config = ConfigFile()
        client, path = get_transport_and_path(
            source,
            config=config,
            operation="pull",
            pool_manager=pool,
        )
        if not isinstance(client, Urllib3HttpGitClient):
            raise SourceError("HTTPS source did not select the controlled transport")

        def check_progress(_message: bytes) -> None:
            pool.check_deadline()

        cloned = client.clone(
            path,
            str(destination),
            checkout=False,
            origin="origin",
            protocol_version=2,
            progress=check_progress,
        )
        try:
            pool.check_deadline()
        finally:
            cloned.close()
        _validate_local_git_repository(destination)
    except SourceError:
        raise
    except Exception as error:
        raise SourceError(f"Remote Git clone failed: {error}") from error
    finally:
        if client is not None:
            client.close()
        pool.clear()


def _validate_git_ref(ref: str) -> str:
    if (
        not ref
        or ref.startswith("-")
        or any(character in ref for character in ("\0", "\r", "\n"))
    ):
        raise SourceError("Invalid Git ref")
    if ref == "HEAD" or re.fullmatch(r"[0-9a-fA-F]{4,64}", ref):
        return ref
    if ref.startswith("refs/") and not ref.startswith(
        ("refs/tags/", "refs/heads/", "refs/remotes/origin/")
    ):
        raise SourceError("Invalid Git ref")
    try:
        encoded = ref.encode("utf-8")
    except UnicodeEncodeError as error:
        raise SourceError("Invalid Git ref") from error
    candidate = encoded if ref.startswith("refs/") else b"refs/heads/" + encoded
    if not check_ref_format(candidate):
        raise SourceError("Invalid Git ref")
    return ref


def _resolve_git_commit(repository: Path, ref: str) -> str:
    ref = _validate_git_ref(ref)
    candidates: list[str] = []
    if ref == "HEAD" or ref.startswith("refs/"):
        candidates.append(ref)
    else:
        if re.fullmatch(r"[0-9a-fA-F]{4,64}", ref):
            candidates.append(ref.lower())
        candidates.extend(
            (f"refs/tags/{ref}", f"refs/heads/{ref}", f"refs/remotes/origin/{ref}")
        )
    resolved: list[str] = []
    try:
        with _open_source_repository(repository) as repo:
            for candidate in candidates:
                value = _resolve_candidate_commit(repo, candidate)
                if value and value not in resolved:
                    resolved.append(value)
    except SourceError:
        raise
    except Exception as error:
        raise SourceError(f"Git repository is unreadable: {error}") from error
    if not resolved:
        raise SourceError(f"Git ref does not exist: {ref}")
    if len(resolved) > 1:
        raise SourceError(
            f"Ambiguous Git ref {ref!r}; use an explicit refs/... name or commit SHA"
        )
    return resolved[0]


def _resolve_candidate_commit(
    repo: ControlledRepo, candidate: str
) -> str | None:
    object_id: bytes | None
    encoded = candidate.encode("utf-8")
    if candidate == "HEAD" or candidate.startswith("refs/"):
        try:
            object_id = repo.refs[encoded]
        except KeyError:
            return None
    elif re.fullmatch(r"[0-9a-f]{4,64}", candidate):
        matches = list(repo.object_store.iter_prefix(encoded))
        if not matches:
            return None
        if len(matches) > 1:
            raise SourceError(
                f"Ambiguous Git ref {candidate!r}; use a full commit SHA"
            )
        object_id = matches[0]
    else:
        return None

    visited: set[bytes] = set()
    for _depth in range(16):
        if object_id in visited:
            raise SourceError(f"Git tag cycle detected while resolving {candidate!r}")
        visited.add(object_id)
        try:
            value = repo.object_store[object_id]
        except KeyError as error:
            raise SourceError(
                f"Git ref {candidate!r} points to a missing required object"
            ) from error
        if isinstance(value, Commit):
            return value.id.decode("ascii")
        if isinstance(value, Tag):
            object_id = value.object[1]
            continue
        return None
    raise SourceError(f"Git tag chain is too deep while resolving {candidate!r}")


def _commit_object(repo: ControlledRepo, source_sha: str) -> Commit:
    try:
        value = repo.object_store[source_sha.encode("ascii")]
    except (KeyError, UnicodeEncodeError) as error:
        raise SourceError(
            f"Git repository is missing required commit object {source_sha}"
        ) from error
    if not isinstance(value, Commit):
        raise SourceError(f"Git snapshot object is not a commit: {source_sha}")
    return value


def _paths_overlap(left: Path, right: Path) -> bool:
    try:
        common = Path(os.path.commonpath((str(left), str(right))))
    except ValueError:
        return False
    return common == left or common == right


def _effective_user_id() -> int | None:
    getter = getattr(os, "geteuid", None)
    if getter is None:
        return None
    try:
        return int(getter())
    except (OSError, TypeError, ValueError):
        return None


def _inside_sensitive_configuration_root(source_path: Path) -> bool:
    return any(
        part.lower() in SENSITIVE_DIRECTORY_NAMES for part in source_path.parts
    )


def validate_local_source(settings: Settings, source: str) -> Path:
    """Resolve and authorize a read-only local import directory."""

    lexical_source = Path(os.path.abspath(Path(source).expanduser()))
    if lexical_source == Path(lexical_source.anchor):
        raise SourceError("Refusing to ingest a filesystem root")
    if _inside_sensitive_configuration_root(lexical_source):
        raise SourceError(
            "Local source may not be inside a sensitive configuration directory"
        )
    data_dir = settings.data_dir.expanduser().resolve()
    if _paths_overlap(lexical_source, data_dir):
        raise SourceError("Local source and LCF_DATA_DIR must not contain one another")
    try:
        source_path = lexical_source.resolve(strict=True)
    except OSError as error:
        raise SourceError("Local source directory is unavailable") from error
    if source_path != lexical_source or lexical_source.is_symlink():
        raise SourceError("Local source path must be canonical and contain no symlinks")
    if source_path == Path(source_path.anchor):
        raise SourceError("Refusing to ingest a filesystem root")
    if _paths_overlap(source_path, data_dir):
        raise SourceError("Local source and LCF_DATA_DIR must not contain one another")
    authorized_roots: list[Path] = []
    for root in settings.local_source_roots:
        resolved_root = root.expanduser().resolve()
        if resolved_root != Path(resolved_root.anchor):
            authorized_roots.append(resolved_root)
    if not authorized_roots:
        raise SourceError(
            "Local source paths are disabled. Set LCF_LOCAL_SOURCE_ROOTS to "
            "one or more read-only import roots, such as /imports."
        )
    authorized = False
    for root in authorized_roots:
        try:
            common = Path(os.path.commonpath((str(source_path), str(root))))
        except ValueError:
            continue
        if common == root:
            authorized = True
            break
    if not authorized:
        raise SourceError(
            f"Local source is outside LCF_LOCAL_SOURCE_ROOTS: {source_path}"
        )
    if not source_path.is_dir():
        raise SourceError("Local source is not a directory")
    if settings.local_source_owner_check:
        effective_uid = _effective_user_id()
        try:
            source_uid = source_path.stat(follow_symlinks=False).st_uid
        except (AttributeError, OSError) as error:
            raise SourceError("Local source directory is unavailable") from error
        if effective_uid is None or source_uid != effective_uid:
            raise SourceError(
                "Local source directory must belong to the desktop user"
            )
    return source_path


def validate_source_location(settings: Settings, source: str) -> Path | None:
    if is_unsupported_remote_source(source):
        raise SourceError(
            "Plain HTTP, SSH, and git:// remote URLs are disabled. Use an HTTPS "
            "URL or pre-clone the repository into an allowed read-only /imports "
            "path."
        )
    if is_remote_source(source):
        parsed = urlparse(source)
        if parsed.username is not None or parsed.password is not None:
            raise SourceError(
                "HTTPS source URLs must not contain userinfo or embedded "
                "credentials; pre-clone private repositories into /imports."
            )
        hostname = (parsed.hostname or "").lower().rstrip(".")
        try:
            port = parsed.port
        except ValueError as error:
            raise SourceError("HTTPS source URL has an invalid port") from error
        if (
            not hostname
            or hostname not in settings.remote_source_hosts
            or port not in {None, 443}
        ):
            allowed = ", ".join(settings.remote_source_hosts) or "(none)"
            raise SourceError(
                "HTTPS source host/port is not allowed. "
                f"Allowed hosts: {allowed}; HTTPS port must be 443. "
                "Set LCF_REMOTE_SOURCE_HOSTS explicitly or pre-clone into /imports."
            )
        if parsed.query or parsed.fragment:
            raise SourceError(
                "HTTPS source URLs must not contain query strings or fragments; "
                "pre-clone repositories that need credential-bearing URLs."
            )
        return None
    return validate_local_source(settings, source)


def create_snapshot(
    settings: Settings, library_slug: str, source: str, ref: str = "HEAD"
) -> Snapshot:
    """Create or reuse an immutable, content-addressed source snapshot."""

    local_source = Path(source).expanduser()
    temporary_clone: tempfile.TemporaryDirectory[str] | None = None
    source_kind = "directory"
    try:
        validated_local = validate_source_location(settings, source)
        if is_remote_source(source):
            temporary_clone = tempfile.TemporaryDirectory(prefix="lcf-clone-")
            clone_path = Path(temporary_clone.name) / "repository"
            _clone_remote_repository(source, clone_path, timeout_seconds=900)
            local_source = clone_path
            source_kind = "git-remote"
        else:
            if validated_local is None:
                raise SourceError("Local source validation failed")
            local_source = validated_local

        staging_parent = settings.sources_dir / library_slug / ".staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="snapshot-", dir=staging_parent))
        staging_repo = staging / "repo"
        staging_repo.mkdir()
        try:
            git_root = _git_repository_root(local_source)
            if git_root is not None:
                if source_kind == "directory":
                    source_kind = "git-local"
                    if local_source.resolve() != git_root:
                        raise SourceError(
                            "A local Git source must be the repository top level. "
                            "For one monorepo package, export/copy that subtree to "
                            "a separate allowed import directory without the parent "
                            ".git metadata."
                        )
                    _validate_local_git_repository(git_root)
                source_sha, skipped_sensitive = _archive_git(
                    settings, git_root, ref, staging_repo
                )
            else:
                if ref != "HEAD":
                    raise SourceError("A ref can only be used with a Git repository")
                source_sha, skipped_sensitive = _copy_directory(
                    settings, local_source, staging_repo
                )

            final_root = settings.sources_dir / library_slug / source_sha
            final_repo = final_root / "repo"
            metadata_path = final_root / "snapshot.json"
            if final_root.exists():
                shutil.rmtree(staging)
            else:
                final_root.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging, final_root)
                atomic_write_json(
                    metadata_path,
                    {
                        "source": source,
                        "source_kind": source_kind,
                        "source_sha": source_sha,
                        "ref": ref,
                        "skipped_sensitive": skipped_sensitive,
                        "created_at": utcnow(),
                    },
                )
                _make_read_only(final_repo)
            return Snapshot(
                source_sha=source_sha,
                repo_path=final_repo,
                metadata_path=metadata_path,
                source_kind=source_kind,
                ref=ref,
            )
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    finally:
        if temporary_clone:
            temporary_clone.cleanup()


def snapshot_metadata(snapshot: Snapshot) -> dict[str, object]:
    try:
        return json.loads(snapshot.metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "source_sha": snapshot.source_sha,
            "source_kind": snapshot.source_kind,
            "ref": snapshot.ref,
        }
