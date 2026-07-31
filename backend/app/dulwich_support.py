from __future__ import annotations

import os
import stat
from pathlib import Path

import dulwich
from dulwich.config import ConfigFile, StackedConfig
from dulwich.repo import Repo

EXPECTED_DULWICH_VERSION = (1, 2, 11)

if tuple(dulwich.__version__) != EXPECTED_DULWICH_VERSION:
    installed = ".".join(str(part) for part in dulwich.__version__)
    expected = ".".join(str(part) for part in EXPECTED_DULWICH_VERSION)
    raise RuntimeError(
        f"Local Context Forge requires Dulwich {expected}; found {installed}"
    )


class ControlledGitError(RuntimeError):
    pass


def _read_object_format(root: Path) -> str:
    """Read only the repository format, without expanding config includes."""

    config_path = root / ".git" / "config"
    try:
        metadata = config_path.lstat()
    except FileNotFoundError:
        return "sha1"
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ControlledGitError("Git config must be a regular local file")
    try:
        config = ConfigFile.from_path(config_path, expand_includes=False)
    except (OSError, ValueError) as error:
        raise ControlledGitError(f"Git config is unreadable: {error}") from error

    try:
        format_version = int(
            config.get((b"core",), b"repositoryformatversion").decode("ascii")
        )
    except KeyError:
        format_version = 0
    except (UnicodeDecodeError, ValueError) as error:
        raise ControlledGitError("Git repository format version is invalid") from error
    if format_version not in {0, 1}:
        raise ControlledGitError(
            f"Unsupported Git repository format version: {format_version}"
        )

    try:
        object_format = config.get((b"extensions",), b"objectformat").decode("ascii")
    except KeyError:
        object_format = "sha1"
    except UnicodeDecodeError as error:
        raise ControlledGitError("Git object format is invalid") from error
    object_format = object_format.lower()
    if object_format not in {"sha1", "sha256"}:
        raise ControlledGitError(f"Unsupported Git object format: {object_format}")
    if format_version == 0 and object_format != "sha1":
        raise ControlledGitError(
            "Git SHA-256 repositories must use repository format version 1"
        )
    return object_format


def _controlled_config(root: Path) -> ConfigFile:
    """Build the complete config visible to product Git operations."""

    object_format = _read_object_format(root)
    config = ConfigFile()
    if object_format == "sha256":
        config.set((b"core",), b"repositoryformatversion", b"1")
        config.set((b"extensions",), b"objectformat", b"sha256")
    else:
        config.set((b"core",), b"repositoryformatversion", b"0")
    config.set((b"core",), b"bare", b"false")
    config.set((b"core",), b"filemode", b"true")
    config.set((b"core",), b"precomposeunicode", b"false")
    config.set((b"core",), b"trustctime", b"true")
    config.path = os.fspath(root / ".git" / "config")
    return config


class ControlledRepo(Repo):
    """A Repo whose config stack never reaches repository includes or the host."""

    def __init__(self, root: Path, config: ConfigFile):
        self._lcf_config = config
        super().__init__(root)

    def get_config(self) -> ConfigFile:
        return self._lcf_config

    def get_config_stack(self) -> StackedConfig:
        return StackedConfig([self._lcf_config], writable=self._lcf_config)


def open_controlled_repo(root: Path) -> ControlledRepo:
    root = root.resolve()
    marker = root / ".git"
    try:
        metadata = marker.lstat()
    except FileNotFoundError as error:
        raise ControlledGitError("Git repository has no .git directory") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ControlledGitError("Git metadata must be a standalone local directory")
    config = _controlled_config(root)
    try:
        return ControlledRepo(root, config)
    except Exception as error:
        raise ControlledGitError(f"Git repository is unreadable: {error}") from error
