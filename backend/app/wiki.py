from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from dulwich.index import Index, index_entry_from_stat
from dulwich.objects import Blob, Commit
from dulwich.object_store import iter_tree_contents
from dulwich.repo import Repo

from .config import Settings
from .dulwich_support import ControlledGitError, ControlledRepo, open_controlled_repo
from .utils import (
    atomic_write_json,
    atomic_write_text,
    safe_page_path,
    slugify,
    utcnow,
)

_GIT_LOCK = threading.Lock()


class WikiError(RuntimeError):
    pass


class WikiStore:
    def __init__(self, settings: Settings, library_slug: str):
        self.settings = settings
        self.library_slug = library_slug
        self.root = settings.wiki_dir / library_slug

    def version_root(self, version: str) -> Path:
        digest = hashlib.sha256(version.encode("utf-8")).hexdigest()[:10]
        return self.root / "versions" / f"{slugify(version)}--{digest}"

    def initialize(self) -> None:
        if self.root.is_symlink():
            raise WikiError("Wiki repository root must not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._git(["init", "-b", "main"])
        try:
            self._git(["rev-parse", "--verify", "HEAD"])
            return
        except WikiError:
            pass

        # Recover an interrupted first initialization. Publication does not
        # write version files until this initial commit exists, so an unborn
        # repository may contain only the generated README and .git metadata.
        unexpected = sorted(
            item.name
            for item in self.root.iterdir()
            if item.name not in {".git", "README.md"}
        )
        if unexpected:
            raise WikiError(
                "Incomplete Wiki initialization contains unexpected files: "
                + ", ".join(unexpected)
            )
        atomic_write_text(
            self.root / "README.md",
            (
                f"# {self.library_slug} API Wiki\n\n"
                "This repository is generated from immutable source snapshots. "
                "Every page has a typed JSON sidecar under `facts/`.\n"
            ),
        )
        self._git(["add", "README.md"])
        staged = {
            item
            for item in self._git(["diff", "--cached", "--name-only"]).splitlines()
            if item
        }
        if staged != {"README.md"}:
            raise WikiError(
                "Refusing to initialize Wiki with unexpected staged files"
            )
        self._git(["commit", "-m", "Initialize generated API wiki"])

    def _git(self, arguments: list[str], *, allow_empty: bool = False) -> str:
        """Execute the former CLI seam through a strict Dulwich allowlist."""

        del allow_empty
        try:
            if arguments == ["init", "-b", "main"]:
                self._initialize_repository()
                return ""
            with self._open_repository() as repo:
                if arguments in (
                    ["rev-parse", "--verify", "HEAD"],
                    ["rev-parse", "HEAD"],
                ):
                    return self._head_commit(repo)
                if arguments == ["status", "--porcelain"]:
                    return self._status(repo)
                if len(arguments) == 2 and arguments[0] == "add":
                    self._stage(repo, arguments[1])
                    return ""
                if arguments == ["diff", "--cached", "--name-only"]:
                    return "\n".join(self._staged_paths(repo))
                if (
                    len(arguments) == 3
                    and arguments[:2] == ["commit", "-m"]
                ):
                    return self._commit(repo, arguments[2])
                if (
                    len(arguments) == 3
                    and arguments[:2] == ["reset", "--hard"]
                ):
                    self._reset_hard(repo, arguments[2])
                    return ""
                if (
                    len(arguments) == 4
                    and arguments[:3] == ["clean", "-fd", "--"]
                ):
                    self._clean_scope(repo, arguments[3])
                    return ""
        except WikiError:
            raise
        except Exception as error:
            raise WikiError(
                f"Controlled Wiki Git operation failed: {error}"
            ) from error
        raise WikiError(
            f"Unsupported controlled Wiki Git operation: {' '.join(arguments)}"
        )

    def _initialize_repository(self) -> None:
        marker = self.root / ".git"
        if marker.exists() or marker.is_symlink():
            raise WikiError("Wiki Git repository is already initialized")
        try:
            repo = Repo.init(
                self.root,
                default_branch=b"main",
                object_format="sha1",
            )
            repo.close()
        except Exception as error:
            raise WikiError(f"Git initialization failed: {error}") from error
        if not marker.is_dir():
            raise WikiError("Git initialization did not create .git")

    def _validate_metadata(self) -> None:
        if self.root.is_symlink() or not self.root.is_dir():
            raise WikiError("Wiki repository root must be a local directory")
        marker = self.root / ".git"
        if marker.is_symlink() or not marker.is_dir():
            raise WikiError("Wiki .git metadata must be a local directory")
        config_path = marker / "config"
        if config_path.is_symlink() or (
            config_path.exists() and not config_path.is_file()
        ):
            raise WikiError("Wiki Git config must be a regular local file")
        if (marker / "commondir").exists():
            raise WikiError("Wiki Git common-directory indirection is not accepted")
        if (marker / "objects" / "info" / "alternates").exists():
            raise WikiError("Wiki Git alternate object stores are not accepted")
        for required_directory in (marker / "objects", marker / "refs"):
            if required_directory.is_symlink() or not required_directory.is_dir():
                raise WikiError("Wiki Git metadata must stay inside the repository")
        head = marker / "HEAD"
        if head.is_symlink() or not head.is_file():
            raise WikiError("Wiki Git HEAD must be a regular local file")
        for current_root, directory_names, file_names in os.walk(
            marker, followlinks=False
        ):
            for name in [*directory_names, *file_names]:
                if (Path(current_root) / name).is_symlink():
                    raise WikiError("Wiki Git metadata must not contain symlinks")

    def _open_repository(self) -> ControlledRepo:
        self._validate_metadata()
        config_path = self.root / ".git" / "config"
        atomic_write_text(
            config_path,
            (
                "[core]\n"
                "\trepositoryformatversion = 0\n"
                "\tfilemode = true\n"
                "\tbare = false\n"
                "\tlogallrefupdates = true\n"
                f"\thooksPath = {os.devnull}\n"
                "\tfsmonitor = false\n"
                f"\tattributesFile = {os.devnull}\n"
                "[user]\n"
                "\tname = Local Context Forge\n"
                "\temail = local-context-forge@localhost\n"
                "[credential]\n"
                "\thelper =\n"
            ),
        )
        try:
            repo = open_controlled_repo(self.root)
        except ControlledGitError as error:
            raise WikiError(str(error)) from error
        if repo.refs.read_ref(b"HEAD") != b"ref: refs/heads/main":
            repo.close()
            raise WikiError("Wiki Git HEAD must remain on the main branch")
        return repo

    @staticmethod
    def _head_commit(repo: ControlledRepo) -> str:
        try:
            object_id = repo.refs[b"HEAD"]
            value = repo.object_store[object_id]
        except KeyError as error:
            raise WikiError("Wiki Git HEAD does not exist") from error
        if not isinstance(value, Commit):
            raise WikiError("Wiki Git HEAD is not a commit")
        return value.id.decode("ascii")

    @staticmethod
    def _open_index(repo: ControlledRepo) -> Index:
        return repo.open_index(config=repo.get_config_stack())

    def _head_entries(
        self, repo: ControlledRepo
    ) -> dict[str, tuple[int, bytes, Blob]]:
        try:
            head = repo.object_store[repo.refs[b"HEAD"]]
        except KeyError:
            return {}
        if not isinstance(head, Commit):
            raise WikiError("Wiki Git HEAD is not a commit")
        entries: dict[str, tuple[int, bytes, Blob]] = {}
        portable_seen: dict[str, str] = {}
        try:
            iterator = iter_tree_contents(
                repo.object_store, head.tree, include_trees=False
            )
            for entry in iterator:
                if entry.path is None or entry.mode is None or entry.sha is None:
                    raise WikiError("Wiki Git tree contains an incomplete entry")
                relative = self._decode_repo_path(entry.path)
                self._record_portable_path(relative, portable_seen)
                if entry.mode not in {0o100644, 0o100755}:
                    raise WikiError(
                        f"Wiki Git tree contains unsupported entry: {relative}"
                    )
                blob = repo.object_store[entry.sha]
                if not isinstance(blob, Blob):
                    raise WikiError(
                        f"Wiki Git tree entry is not a blob: {relative}"
                    )
                entries[relative] = (entry.mode, entry.sha, blob)
        except WikiError:
            raise
        except Exception as error:
            raise WikiError(f"Wiki Git tree is unreadable: {error}") from error
        return entries

    def _index_entries(
        self, repo: ControlledRepo
    ) -> dict[str, tuple[int, bytes]]:
        entries: dict[str, tuple[int, bytes]] = {}
        portable_seen: dict[str, str] = {}
        index = self._open_index(repo)
        for encoded, entry in index.items():
            relative = self._decode_repo_path(encoded)
            self._record_portable_path(relative, portable_seen)
            if entry.mode not in {0o100644, 0o100755}:
                raise WikiError(
                    f"Wiki Git index contains unsupported entry: {relative}"
                )
            entries[relative] = (entry.mode, entry.sha)
        return entries

    def _worktree_files(
        self,
    ) -> dict[str, tuple[Path, os.stat_result, int]]:
        files: dict[str, tuple[Path, os.stat_result, int]] = {}
        portable_seen: dict[str, str] = {}
        for current_root, directory_names, file_names in os.walk(
            self.root, followlinks=False
        ):
            current = Path(current_root)
            if current == self.root:
                directory_names[:] = sorted(
                    name for name in directory_names if name != ".git"
                )
            else:
                directory_names[:] = sorted(directory_names)
            for name in list(directory_names):
                directory = current / name
                if directory.is_symlink():
                    raise WikiError("Wiki working tree must not contain symlinks")
                relative_directory = directory.relative_to(self.root).as_posix()
                self._decode_repo_path(relative_directory.encode("utf-8"))
                self._record_portable_path(
                    relative_directory, portable_seen
                )
            for name in sorted(file_names):
                path = current / name
                relative = path.relative_to(self.root).as_posix()
                self._decode_repo_path(relative.encode("utf-8"))
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise WikiError(
                        f"Wiki working tree contains unsupported entry: {relative}"
                    )
                self._record_portable_path(relative, portable_seen)
                mode = 0o100755 if metadata.st_mode & 0o111 else 0o100644
                files[relative] = (path, metadata, mode)
        return files

    @staticmethod
    def _decode_repo_path(path: bytes) -> str:
        try:
            relative = path.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WikiError("Wiki Git paths must be valid UTF-8") from error
        parts = relative.split("/")
        if (
            not relative
            or relative.startswith("/")
            or any(
                part in {"", ".", ".."} or part.casefold() == ".git"
                for part in parts
            )
            or "\0" in relative
        ):
            raise WikiError(f"Unsafe Wiki Git path: {relative!r}")
        return relative

    def _local_worktree_path(
        self, relative: str, *, allow_leaf_symlink: bool = False
    ) -> Path:
        """Resolve a lexical worktree path without following symlink ancestors."""

        relative = self._decode_repo_path(relative.encode("utf-8"))
        if self.root.is_symlink() or not self.root.is_dir():
            raise WikiError("Wiki repository root must be a local directory")
        parts = relative.split("/")
        current = self.root
        for index, part in enumerate(parts):
            current /= part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                break
            is_leaf = index == len(parts) - 1
            if stat.S_ISLNK(metadata.st_mode):
                if is_leaf and allow_leaf_symlink:
                    break
                raise WikiError(
                    f"Wiki worktree path contains a symlink: {relative}"
                )
            if not is_leaf and not stat.S_ISDIR(metadata.st_mode):
                raise WikiError(
                    f"Wiki worktree path has a non-directory ancestor: {relative}"
                )
        return self.root.joinpath(*parts)

    @staticmethod
    def _record_portable_path(
        relative: str, seen: dict[str, str]
    ) -> None:
        key = unicodedata.normalize("NFC", relative).casefold()
        previous = seen.get(key)
        if previous is not None and previous != relative:
            raise WikiError(
                "Wiki contains paths that collide on portable filesystems: "
                f"{previous!r} and {relative!r}"
            )
        seen[key] = relative

    @staticmethod
    def _blob_id(path: Path) -> bytes:
        try:
            return Blob.from_string(path.read_bytes()).id
        except OSError as error:
            raise WikiError(f"Wiki file is unreadable: {path.name}") from error

    def _status(self, repo: ControlledRepo) -> str:
        head = {
            path: (mode, object_id)
            for path, (mode, object_id, _blob) in self._head_entries(repo).items()
        }
        index = self._index_entries(repo)
        worktree = self._worktree_files()
        lines: list[str] = []
        for relative in sorted(set(head) | set(index)):
            if head.get(relative) == index.get(relative):
                continue
            status = "A" if relative not in head else "D" if relative not in index else "M"
            lines.append(f"{status}  {relative}")
        for relative in sorted(index):
            current = worktree.get(relative)
            if current is None:
                lines.append(f" D {relative}")
                continue
            path, _metadata, mode = current
            indexed_mode, indexed_id = index[relative]
            if mode != indexed_mode or self._blob_id(path) != indexed_id:
                lines.append(f" M {relative}")
        for relative in sorted(set(worktree) - set(index)):
            lines.append(f"?? {relative}")
        return "\n".join(lines)

    def _staged_paths(self, repo: ControlledRepo) -> list[str]:
        head = {
            path: (mode, object_id)
            for path, (mode, object_id, _blob) in self._head_entries(repo).items()
        }
        index = self._index_entries(repo)
        return sorted(
            relative
            for relative in set(head) | set(index)
            if head.get(relative) != index.get(relative)
        )

    def _stage(self, repo: ControlledRepo, requested: str) -> None:
        if requested not in {".", "README.md"}:
            raise WikiError(f"Unsupported Wiki stage path: {requested}")
        worktree = self._worktree_files()
        index = self._open_index(repo)
        if requested == ".":
            index.clear()
            selected = sorted(worktree)
        else:
            selected = [requested]
            if requested not in worktree:
                try:
                    del index[requested.encode("utf-8")]
                except KeyError:
                    pass
        for relative in selected:
            path, metadata, mode = worktree[relative]
            blob = Blob.from_string(path.read_bytes())
            repo.object_store.add_object(blob)
            index[relative.encode("utf-8")] = index_entry_from_stat(
                metadata, blob.id, mode=mode
            )
        index.write()

    def _commit(self, repo: ControlledRepo, message: str) -> str:
        if not self._staged_paths(repo):
            raise WikiError("Nothing staged for Wiki commit")
        index = self._open_index(repo)
        commit = Commit()
        commit.tree = index.commit(repo.object_store)
        try:
            previous = repo.refs[b"HEAD"]
        except KeyError:
            previous = None
        commit.parents = [] if previous is None else [previous]
        identity = b"Local Context Forge <local-context-forge@localhost>"
        timestamp = int(time.time())
        commit.author = identity
        commit.committer = identity
        commit.author_time = timestamp
        commit.commit_time = timestamp
        commit.author_timezone = 0
        commit.commit_timezone = 0
        commit.message = message.encode("utf-8")
        repo.object_store.add_object(commit)
        updated = repo.refs.set_if_equals(
            b"HEAD",
            previous,
            commit.id,
            committer=identity,
            message=b"commit: " + commit.message,
            timestamp=timestamp,
            timezone=0,
        )
        if not updated:
            raise WikiError("Wiki Git HEAD changed during commit")
        return commit.id.decode("ascii")

    def _reset_hard(self, repo: ControlledRepo, target_commit: str) -> None:
        try:
            target_id = target_commit.encode("ascii")
            target = repo.object_store[target_id]
        except (KeyError, UnicodeEncodeError) as error:
            raise WikiError(
                f"Wiki rollback target does not exist: {target_commit}"
            ) from error
        if not isinstance(target, Commit):
            raise WikiError("Wiki rollback target is not a commit")
        target_entries = self._head_entries_for_commit(repo, target)
        current_index = self._index_entries(repo)

        removed: list[Path] = []
        for relative in sorted(set(current_index) - set(target_entries), reverse=True):
            path = self._local_worktree_path(
                relative, allow_leaf_symlink=True
            )
            if not path.exists() and not path.is_symlink():
                continue
            if path.is_symlink() or path.is_file():
                path.unlink()
                removed.append(path.parent)
            else:
                raise WikiError(
                    f"Refusing to replace unexpected Wiki directory: {relative}"
                )
        for relative, (mode, object_id, blob) in sorted(target_entries.items()):
            path = self._local_worktree_path(
                relative, allow_leaf_symlink=True
            )
            self._atomic_write_bytes(path, blob.data)
            path.chmod(0o755 if mode & 0o111 else 0o644)

        index = self._open_index(repo)
        index.clear()
        for relative, (mode, object_id, _blob) in sorted(target_entries.items()):
            path = self._local_worktree_path(relative)
            index[relative.encode("utf-8")] = index_entry_from_stat(
                path.stat(), object_id, mode=mode
            )
        index.write()
        try:
            current_head = repo.refs[b"HEAD"]
        except KeyError:
            current_head = None
        identity = b"Local Context Forge <local-context-forge@localhost>"
        if not repo.refs.set_if_equals(
            b"HEAD",
            current_head,
            target.id,
            committer=identity,
            message=b"reset: controlled Wiki publication rollback",
            timestamp=int(time.time()),
            timezone=0,
        ):
            raise WikiError("Wiki Git HEAD changed during rollback")
        for directory in removed:
            self._prune_empty_directories(directory)

    def _head_entries_for_commit(
        self, repo: ControlledRepo, commit: Commit
    ) -> dict[str, tuple[int, bytes, Blob]]:
        entries: dict[str, tuple[int, bytes, Blob]] = {}
        portable_seen: dict[str, str] = {}
        try:
            for entry in iter_tree_contents(
                repo.object_store, commit.tree, include_trees=False
            ):
                if entry.path is None or entry.mode is None or entry.sha is None:
                    raise WikiError("Wiki Git tree contains an incomplete entry")
                relative = self._decode_repo_path(entry.path)
                self._record_portable_path(relative, portable_seen)
                if entry.mode not in {0o100644, 0o100755}:
                    raise WikiError(
                        f"Wiki Git tree contains unsupported entry: {relative}"
                    )
                blob = repo.object_store[entry.sha]
                if not isinstance(blob, Blob):
                    raise WikiError(
                        f"Wiki Git tree entry is not a blob: {relative}"
                    )
                entries[relative] = (entry.mode, entry.sha, blob)
        except WikiError:
            raise
        except Exception as error:
            raise WikiError(f"Wiki Git tree is unreadable: {error}") from error
        return entries

    def _clean_scope(self, repo: ControlledRepo, relative_scope: str) -> None:
        relative = self._decode_repo_path(relative_scope.encode("utf-8"))
        scope = self._local_worktree_path(relative)
        if not scope.exists() and not scope.is_symlink():
            return
        if scope.is_symlink() or not scope.is_dir():
            raise WikiError("Wiki clean scope must be a local directory")
        tracked = set(self._head_entries(repo))
        for _current_root, directory_names, _file_names in os.walk(
            scope, topdown=True, followlinks=False
        ):
            if any(name.casefold() == ".git" for name in directory_names):
                raise WikiError(
                    "Refusing to clean a nested Git repository from the Wiki"
                )
        for current_root, directory_names, file_names in os.walk(
            scope, topdown=False, followlinks=False
        ):
            current = Path(current_root)
            for name in file_names:
                path = current / name
                item = path.relative_to(self.root).as_posix()
                if item not in tracked:
                    path.unlink()
            for name in directory_names:
                directory = current / name
                if directory.is_symlink():
                    item = directory.relative_to(self.root).as_posix()
                    if item in tracked:
                        raise WikiError("Tracked Wiki paths must not be symlinks")
                    directory.unlink()
                elif not any(directory.iterdir()):
                    directory.rmdir()
        if scope.exists() and not any(scope.iterdir()):
            scope.rmdir()

    def _prune_empty_directories(self, directory: Path) -> None:
        while directory != self.root and directory.is_relative_to(self.root):
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent

    @staticmethod
    def _atomic_write_bytes(path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def git_status(self) -> str:
        if not (self.root / ".git").exists():
            return "wiki Git repository is not initialized"
        return self._git(["status", "--porcelain"])

    @staticmethod
    def render_markdown(page: dict[str, Any]) -> str:
        metadata = {
            "title": page["title"],
            "kind": page["kind"],
            "version": page["version"],
            "source_sha": page["source_sha"],
            "tags": page.get("tags", []),
            "source_refs": page.get("source_refs", []),
        }
        # JSON values are valid YAML scalars and avoid ad-hoc escaping bugs.
        front_matter = ["---"]
        for key, value in metadata.items():
            front_matter.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        front_matter.extend(["---", "", page["markdown"].rstrip(), ""])
        return "\n".join(front_matter)

    def publish(
        self,
        page: dict[str, Any],
        *,
        all_pages: list[dict[str, Any]],
        proposal_id: str,
    ) -> dict[str, str]:
        with _GIT_LOCK:
            self.initialize()
            version_root = self.version_root(page["version"])
            previous_commit = self._git(["rev-parse", "HEAD"])
            dirty = self._git(["status", "--porcelain"])
            if dirty:
                raise WikiError(
                    "Wiki Git working tree is dirty; run lint and reconcile it "
                    "before publishing"
                )
            relative = safe_page_path(page["path"])
            markdown_path = version_root / relative
            sidecar_path = version_root / "facts" / Path(relative).with_suffix(".json")
            try:
                atomic_write_text(markdown_path, self.render_markdown(page))
                atomic_write_json(
                    sidecar_path,
                    {
                        "schema_version": 1,
                        "path": relative,
                        "title": page["title"],
                        "kind": page["kind"],
                        "summary": page["summary"],
                        "tags": page.get("tags", []),
                        "version": page["version"],
                        "source_sha": page["source_sha"],
                        "source_refs": page.get("source_refs", []),
                        "proposal_id": proposal_id,
                        "published_at": utcnow(),
                    },
                )
                self._write_index(version_root, page["version"], all_pages)
                self._append_log(version_root, page, proposal_id)
                self._git(["add", "."])
                status = self._git(["status", "--porcelain"])
                if status:
                    if any(
                        line.startswith((" ", "??"))
                        for line in status.splitlines()
                    ):
                        raise WikiError(
                            "Wiki Git working tree changed while publication "
                            "files were being staged"
                        )
                    self._git(
                        [
                            "commit",
                            "-m",
                            f"Publish {page['version']}/{relative}",
                        ]
                    )
                commit = self._git(["rev-parse", "HEAD"])
            except Exception:
                self._rollback_locked(previous_commit, version_root)
                raise
            return {
                "markdown_path": str(markdown_path),
                "sidecar_path": str(sidecar_path),
                "git_commit": commit,
                "previous_git_commit": previous_commit,
            }

    def rollback_publication(
        self,
        *,
        previous_commit: str,
        published_commit: str,
        version: str,
    ) -> None:
        """Compensate a Git publication when the SQLite commit fails."""

        with _GIT_LOCK:
            current_commit = self._git(["rev-parse", "HEAD"])
            if current_commit != published_commit:
                raise WikiError(
                    "Refusing publication rollback because Wiki HEAD changed"
                )
            self._rollback_locked(previous_commit, self.version_root(version))

    def _rollback_locked(self, previous_commit: str, version_root: Path) -> None:
        self._git(["reset", "--hard", previous_commit])
        try:
            relative_version = version_root.relative_to(self.root).as_posix()
        except ValueError as error:
            raise WikiError("Version root is outside the Wiki repository") from error
        self._git(["clean", "-fd", "--", relative_version])

    def _write_index(
        self, version_root: Path, version: str, pages: list[dict[str, Any]]
    ) -> None:
        lines = [
            f"# API wiki index — {version}",
            "",
            (
                "Generated pages passed schema and source-reference checks; "
                "factual claims still require human review."
            ),
            "",
        ]
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for page in pages:
            by_kind.setdefault(page["kind"], []).append(page)
        for kind in sorted(by_kind):
            lines.extend([f"## {kind.title()}", ""])
            for page in sorted(by_kind[kind], key=lambda item: item["path"]):
                lines.append(f"- [{page['title']}]({page['path']}) — {page['summary']}")
            lines.append("")
        atomic_write_text(version_root / "index.md", "\n".join(lines).rstrip() + "\n")
        atomic_write_json(
            version_root / "index.json",
            {
                "schema_version": 1,
                "version": version,
                "pages": [
                    {
                        "path": page["path"],
                        "title": page["title"],
                        "kind": page["kind"],
                        "summary": page["summary"],
                        "tags": page.get("tags", []),
                        "source_sha": page["source_sha"],
                    }
                    for page in sorted(pages, key=lambda item: item["path"])
                ],
            },
        )

    def _append_log(
        self, version_root: Path, page: dict[str, Any], proposal_id: str
    ) -> None:
        log_path = version_root / "log.md"
        if log_path.exists():
            existing = log_path.read_text(encoding="utf-8")
        else:
            existing = f"# Publication log — {page['version']}\n\n"
        entry = (
            f"- {utcnow()} — published `{page['path']}` from "
            f"`{page['source_sha'][:12]}` (proposal `{proposal_id}`)\n"
        )
        atomic_write_text(log_path, existing + entry)
