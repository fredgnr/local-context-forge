from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from .config import Settings
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
        # The Wiki repository is restored from backups and is therefore data,
        # not a trusted source of executable Git configuration.  Disable hooks,
        # inherited credential helpers, prompts, and host-level configuration
        # for every operation so a restored repository cannot execute a hook or
        # silently change publication behavior.
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        git_metadata = self.root / ".git"
        if git_metadata.exists() or git_metadata.is_symlink():
            if git_metadata.is_symlink() or not git_metadata.is_dir():
                raise WikiError("Wiki .git metadata must be a local directory")
            config_path = git_metadata / "config"
            if config_path.is_symlink() or (
                config_path.exists() and not config_path.is_file()
            ):
                raise WikiError("Wiki Git config must be a regular local file")
            # This is a service-owned repository with no remotes. Rebuild its
            # local config before every Git invocation so restored include,
            # filter, fsmonitor, worktree, and credential directives cannot
            # execute programs or redirect the managed worktree.
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
            command = [
                "git",
                f"--git-dir={git_metadata}",
                f"--work-tree={self.root}",
            ]
        else:
            command = ["git"]
        command.extend(
            [
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "credential.helper=",
            *arguments,
            ]
        )
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                env=environment,
                check=not allow_empty,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if (
                arguments
                and arguments[0] == "init"
                and not (self.root / ".git").is_dir()
            ):
                # `git init` creates the metadata after command construction.
                # Canonicalization happens before the next operation.
                raise WikiError("Git initialization did not create .git")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            stderr = getattr(error, "stderr", "")
            raise WikiError(stderr.strip() or f"{' '.join(command)} failed") from error
        return result.stdout.strip()

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
