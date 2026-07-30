from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings
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
) -> subprocess.CompletedProcess[bytes]:
    environment = _git_environment()
    try:
        return subprocess.run(
            [
                "git",
                "-c",
                "credential.helper=",
                "-c",
                "core.hooksPath=" + os.devnull,
                "-c",
                "http.followRedirects=false",
                *arguments,
            ],
            cwd=cwd,
            check=True,
            capture_output=True,
            timeout=timeout,
            env=environment,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        stderr = getattr(error, "stderr", b"")
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise SourceError(detail or f"git {' '.join(arguments)} failed") from error


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
    try:
        inside = (
            _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path, timeout=20)
            .stdout.decode("utf-8", errors="replace")
            .strip()
        )
        if inside != "true":
            return None
        root = (
            _run_git(["rev-parse", "--show-toplevel"], cwd=path, timeout=20)
            .stdout.decode("utf-8", errors="replace")
            .strip()
        )
        return Path(root).resolve() if root else None
    except SourceError:
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

    for arguments in (
        ["--absolute-git-dir"],
        ["--git-common-dir"],
        ["--git-path", "objects"],
    ):
        value = (
            _run_git(["rev-parse", *arguments], cwd=repository, timeout=20)
            .stdout.decode("utf-8", errors="replace")
            .strip()
        )
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = repository / candidate
        try:
            candidate.resolve().relative_to(repository)
        except ValueError as error:
            raise SourceError(
                "Local Git metadata or object storage escapes the authorized "
                "repository directory"
            ) from error


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
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as handle:
        archive_path = Path(handle.name)
    try:
        with archive_path.open("wb") as handle:
            try:
                environment = _git_environment()
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "credential.helper=",
                        "-c",
                        "core.hooksPath=" + os.devnull,
                        "-c",
                        "http.followRedirects=false",
                        "archive",
                        "--format=tar",
                        source_sha,
                    ],
                    cwd=repository,
                    check=True,
                    stdout=handle,
                    stderr=subprocess.PIPE,
                    timeout=300,
                    env=environment,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                stderr = getattr(error, "stderr", b"")
                detail = stderr.decode("utf-8", errors="replace").strip()
                raise SourceError(detail or "git archive failed") from error
        # The tar stream has small header/padding overhead above regular file
        # bytes. Reject an obviously oversized stream before parsing members.
        archive_ceiling = (
            settings.max_snapshot_bytes
            + settings.max_snapshot_files * 2048
            + 10 * 1024 * 1024
        )
        if archive_path.stat().st_size > archive_ceiling:
            raise SourceError(
                "Git archive exceeds the configured snapshot resource limits"
            )
        _safe_extract(
            archive_path,
            destination,
            max_files=settings.max_snapshot_files,
            max_bytes=settings.max_snapshot_bytes,
        )
        tree = _run_git(
            ["ls-tree", "-r", "-z", "--full-tree", source_sha],
            cwd=repository,
            timeout=300,
        ).stdout
        submodules = [
            record.split(b"\t", 1)[1].decode("utf-8", errors="replace")
            for record in tree.split(b"\0")
            if record.startswith(b"160000 ") and b"\t" in record
        ]
        if submodules:
            preview = ", ".join(submodules[:5])
            raise SourceError(
                "Git submodules are not materialized by git archive "
                f"({preview}). Export a complete worktree without its parent "
                ".git directory into an allowed imports directory."
            )
        lfs_pointers: list[str] = []
        signature = b"version https://git-lfs.github.com/spec/v1\n"
        for path in sorted(destination.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                with path.open("rb") as handle:
                    prefix = handle.read(200)
            except OSError:
                continue
            if prefix.startswith(signature) and b"\noid sha256:" in prefix:
                lfs_pointers.append(path.relative_to(destination).as_posix())
                if len(lfs_pointers) >= 5:
                    break
        if lfs_pointers:
            raise SourceError(
                "Git LFS pointer files are not materialized by git archive "
                f"({', '.join(lfs_pointers)}). Export a fully smudged worktree "
                "without its parent .git directory into an allowed imports "
                "directory."
            )
    finally:
        archive_path.unlink(missing_ok=True)
    return source_sha, _list_sensitive_paths(destination)


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


def _validate_git_ref(ref: str) -> str:
    if (
        not ref
        or ref.startswith("-")
        or any(character in ref for character in ("\0", "\r", "\n"))
    ):
        raise SourceError("Invalid Git ref")
    return ref


def _resolve_git_commit(repository: Path, ref: str) -> str:
    ref = _validate_git_ref(ref)
    candidates = [ref]
    if not ref.startswith("refs/") and ref != "HEAD":
        candidates.extend(
            [
                f"refs/tags/{ref}",
                f"refs/heads/{ref}",
                f"refs/remotes/origin/{ref}",
            ]
        )
    resolved: list[str] = []
    for candidate in candidates:
        try:
            value = (
                _run_git(
                    [
                        "rev-parse",
                        "--verify",
                        "--quiet",
                        "--end-of-options",
                        f"{candidate}^{{commit}}",
                    ],
                    cwd=repository,
                    timeout=30,
                )
                .stdout.decode()
                .strip()
            )
        except SourceError:
            continue
        if value and value not in resolved:
            resolved.append(value)
    if not resolved:
        raise SourceError(f"Git ref does not exist: {ref}")
    if len(resolved) > 1:
        raise SourceError(
            f"Ambiguous Git ref {ref!r}; use an explicit refs/... name or commit SHA"
        )
    return resolved[0]


def _paths_overlap(left: Path, right: Path) -> bool:
    try:
        common = Path(os.path.commonpath((str(left), str(right))))
    except ValueError:
        return False
    return common == left or common == right


def validate_local_source(settings: Settings, source: str) -> Path:
    """Resolve and authorize a read-only local import directory."""

    source_path = Path(source).expanduser().resolve()
    if source_path == Path(source_path.anchor):
        raise SourceError("Refusing to ingest a filesystem root")
    data_dir = settings.data_dir.expanduser().resolve()
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
    if not source_path.exists() or not source_path.is_dir():
        raise SourceError(f"Source directory does not exist: {source_path}")
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
            _run_git(
                [
                    "clone",
                    "--quiet",
                    "--no-checkout",
                    "--filter=blob:none",
                    source,
                    str(clone_path),
                ],
                timeout=900,
            )
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
