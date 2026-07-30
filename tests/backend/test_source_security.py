from __future__ import annotations

import subprocess
import tarfile
import unicodedata
from io import BytesIO
from pathlib import Path

import app.source as source_module
import pytest
from app.config import Settings
from app.service import AppService, ValidationError
from app.source import (
    SourceError,
    _resolve_git_commit,
    _safe_extract,
    create_snapshot,
    validate_local_source,
    validate_source_location,
)
from app.validation import validate_page


def _settings(data_dir: Path, *roots: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "metadata.sqlite3",
        qmd_enabled=False,
        local_source_roots=tuple(roots),
    )


def test_local_source_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="filesystem root"):
        validate_local_source(_settings(tmp_path / "data", tmp_path), "/")


def test_local_source_equal_to_data_is_rejected(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    with pytest.raises(SourceError, match="must not contain"):
        validate_local_source(_settings(data, tmp_path), str(data))


def test_literal_data_mount_is_rejected() -> None:
    with pytest.raises(SourceError, match="must not contain"):
        validate_local_source(_settings(Path("/data"), Path("/imports")), "/data")


def test_local_source_inside_data_is_rejected(tmp_path: Path) -> None:
    data = tmp_path / "data"
    source = data / "repo"
    source.mkdir(parents=True)
    with pytest.raises(SourceError, match="must not contain"):
        validate_local_source(_settings(data, tmp_path), str(source))


def test_local_source_containing_data_is_rejected(tmp_path: Path) -> None:
    parent = tmp_path / "workspace"
    data = parent / "data"
    data.mkdir(parents=True)
    with pytest.raises(SourceError, match="must not contain"):
        validate_local_source(_settings(data, tmp_path), str(parent))


def test_local_sources_default_to_disabled(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    with pytest.raises(SourceError, match="disabled"):
        validate_local_source(_settings(tmp_path / "data"), str(source))


def test_local_source_outside_allowlist_is_rejected(tmp_path: Path) -> None:
    imports = tmp_path / "imports"
    imports.mkdir()
    outside = tmp_path / "outside" / "repo"
    outside.mkdir(parents=True)
    with pytest.raises(SourceError, match="outside"):
        validate_local_source(
            _settings(tmp_path / "data", imports),
            str(outside),
        )


def test_local_source_below_imports_is_allowed(tmp_path: Path) -> None:
    imports = tmp_path / "imports"
    source = imports / "repo"
    source.mkdir(parents=True)
    resolved = validate_local_source(
        _settings(tmp_path / "data", imports),
        str(source),
    )
    assert resolved == source.resolve()


def test_local_git_subdirectory_is_rejected_instead_of_reusing_root_snapshot(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    package = repository / "packages" / "one"
    package.mkdir(parents=True)
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=repository, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture"],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
    )

    with pytest.raises(SourceError, match="repository top level"):
        create_snapshot(
            _settings(tmp_path / "data", tmp_path),
            "scoped",
            str(package),
        )


def test_local_git_linked_worktree_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "primary"
    imports = tmp_path / "imports"
    linked = imports / "linked"
    repository.mkdir()
    imports.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=repository, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repository,
        check=True,
    )
    (repository / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture"],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "worktree", "add", "-b", "linked", str(linked)],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
    )

    with pytest.raises(SourceError, match="linked worktrees"):
        create_snapshot(
            _settings(tmp_path / "data", imports),
            "linked",
            str(linked),
        )


def test_local_git_alternate_object_store_is_rejected(tmp_path: Path) -> None:
    imports = tmp_path / "imports"
    repository = imports / "repository"
    repository.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True)
    alternates = repository / ".git" / "objects" / "info" / "alternates"
    alternates.write_text(
        str(tmp_path / "external-objects") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SourceError, match="alternate object"):
        create_snapshot(
            _settings(tmp_path / "data", imports),
            "alternates",
            str(repository),
        )


def test_git_environment_drops_inherited_git_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", "/tmp/untrusted-git-dir")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")

    environment = source_module._git_environment()

    assert "GIT_DIR" not in environment
    assert "GIT_CONFIG_COUNT" not in environment
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_OPTIONAL_LOCKS"] == "0"


@pytest.mark.parametrize(
    "source",
    [
        "http://example.com/org/repo.git",
        "ssh://git@example.com/org/repo.git",
        "git://example.com/org/repo.git",
        "git@example.com:org/repo.git",
    ],
)
def test_credential_bearing_remote_schemes_are_rejected(
    tmp_path: Path, source: str
) -> None:
    with pytest.raises(SourceError, match="disabled"):
        validate_source_location(_settings(tmp_path / "data"), source)


def test_https_userinfo_is_rejected_before_persistence(tmp_path: Path) -> None:
    source = "https://user:pass@example.com/org/repo.git"
    settings = _settings(tmp_path / "data")
    with pytest.raises(SourceError, match="userinfo"):
        validate_source_location(settings, source)
    service = AppService(settings)
    with pytest.raises(ValidationError, match="userinfo"):
        service.create_library(
            {
                "name": "private",
                "source": source,
            }
        )
    assert service.list_libraries() == []


def test_https_remote_must_use_explicit_host_allowlist(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "data")
    with pytest.raises(SourceError, match="not allowed"):
        validate_source_location(
            settings, "https://example.com/org/repository.git"
        )
    assert (
        validate_source_location(
            settings, "https://github.com/org/repository.git"
        )
        is None
    )


@pytest.mark.parametrize(
    "source",
    [
        "https://github.com:8443/org/repository.git",
        "https://github.com/org/repository.git?token=secret",
        "https://github.com/org/repository.git#fragment",
    ],
)
def test_https_remote_rejects_nonstandard_port_and_url_metadata(
    tmp_path: Path, source: str
) -> None:
    with pytest.raises(SourceError):
        validate_source_location(_settings(tmp_path / "data"), source)


def test_directory_snapshot_fails_if_source_changes_during_copy(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    hashes = iter(("before", "before", "after"))
    monkeypatch.setattr(
        source_module,
        "_hash_directory",
        lambda _path, **_limits: next(hashes),
    )

    with pytest.raises(SourceError, match="changed while"):
        source_module._copy_directory(
            _settings(tmp_path / "data", source),
            source,
            destination,
        )


def test_directory_snapshot_enforces_file_and_byte_limits(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.txt").write_text("1234", encoding="utf-8")
    (source / "two.txt").write_text("5678", encoding="utf-8")

    with pytest.raises(SourceError, match="MAX_SNAPSHOT_FILES"):
        source_module._hash_directory(source, max_files=1, max_bytes=100)
    with pytest.raises(SourceError, match="MAX_SNAPSHOT_BYTES"):
        source_module._hash_directory(source, max_files=10, max_bytes=7)


def test_directory_snapshot_rejects_portable_path_collisions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "API.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "api.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(SourceError, match="portable filesystems"):
        source_module._hash_directory(
            source, max_files=10, max_bytes=1024
        )


@pytest.mark.parametrize(
    "names",
    [
        ("API.py", "api.py"),
        ("caf\u00e9.py", unicodedata.normalize("NFD", "caf\u00e9.py")),
    ],
)
def test_git_archive_rejects_portable_path_collisions(
    tmp_path: Path, names: tuple[str, str]
) -> None:
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as bundle:
        for name in names:
            payload = b"VALUE = 1\n"
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            bundle.addfile(member, BytesIO(payload))

    with pytest.raises(SourceError, match="portable filesystems"):
        _safe_extract(
            archive,
            tmp_path / "extract",
            max_files=10,
            max_bytes=1024,
        )


def test_git_archive_disables_http_redirects(
    tmp_path: Path, monkeypatch
) -> None:
    repository = tmp_path / "repository"
    destination = tmp_path / "destination"
    repository.mkdir()
    destination.mkdir()
    commands: list[list[str]] = []

    monkeypatch.setattr(source_module, "_resolve_git_commit", lambda *_: "a" * 40)
    monkeypatch.setattr(
        source_module,
        "_safe_extract",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        source_module,
        "_run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["git"], 0, stdout=b"", stderr=b""
        ),
    )

    def fake_run(command, **kwargs):
        commands.append(command)
        kwargs["stdout"].write(b"archive")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(source_module.subprocess, "run", fake_run)
    source_module._archive_git(
        _settings(tmp_path / "data", tmp_path),
        repository,
        "HEAD",
        destination,
    )

    assert any(
        command[index : index + 2] == ["-c", "http.followRedirects=false"]
        for command in commands
        for index in range(len(command) - 1)
    )


def test_git_snapshot_rejects_submodules(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    destination = tmp_path / "destination"
    repository.mkdir()
    destination.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=repository, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repository,
        check=True,
    )
    (repository / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repository, check=True)
    empty_tree = subprocess.run(
        ["git", "mktree"],
        cwd=repository,
        input="",
        text=True,
        check=True,
        capture_output=True,
    ).stdout.strip()
    commit = subprocess.run(
        ["git", "commit-tree", empty_tree, "-m", "submodule"],
        cwd=repository,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", f"160000,{commit},vendor"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "commit", "-m", "add submodule"], cwd=repository, check=True)

    with pytest.raises(SourceError, match="submodules"):
        source_module._archive_git(
            _settings(tmp_path / "data", tmp_path),
            repository,
            "HEAD",
            destination,
        )


def test_git_snapshot_rejects_lfs_pointer(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    destination = tmp_path / "destination"
    repository.mkdir()
    destination.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=repository, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repository,
        check=True,
    )
    (repository / "model.bin").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{'a' * 64}\nsize 42\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "lfs"], cwd=repository, check=True)

    with pytest.raises(SourceError, match="LFS pointer"):
        source_module._archive_git(
            _settings(tmp_path / "data", tmp_path),
            repository,
            "HEAD",
            destination,
        )


def test_source_refs_reject_sensitive_files_and_symlink_components(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (snapshot / ".env").write_text("TOKEN=fixture\n", encoding="utf-8")
    (snapshot / "module-link.py").symlink_to("module.py")
    base_page = {
        "path": "api/module.md",
        "source_sha": "abc",
    }

    sensitive = validate_page(
        {
            **base_page,
            "source_refs": [
                {"path": ".env", "line_start": 1, "line_end": 1}
            ],
        },
        snapshot_repo=snapshot,
        source_sha="abc",
        allowed_source_ranges=[
            {"path": ".env", "line_start": 1, "line_end": 1}
        ],
    )
    assert {item["code"] for item in sensitive} >= {"sensitive-source-ref"}

    symlinked = validate_page(
        {
            **base_page,
            "source_refs": [
                {
                    "path": "module-link.py",
                    "line_start": 1,
                    "line_end": 1,
                }
            ],
        },
        snapshot_repo=snapshot,
        source_sha="abc",
        allowed_source_ranges=[
            {
                "path": "module-link.py",
                "line_start": 1,
                "line_end": 1,
            }
        ],
    )
    assert {item["code"] for item in symlinked} >= {"missing-source-path"}


@pytest.mark.parametrize("ref", ["", "--help", "develop\n--help", "bad\0ref"])
def test_invalid_git_refs_are_rejected(tmp_path: Path, ref: str) -> None:
    with pytest.raises(SourceError, match="Invalid Git ref"):
        _resolve_git_commit(tmp_path, ref)


def test_remote_tracking_branch_resolves_after_no_checkout_clone(
    tmp_path: Path,
) -> None:
    origin_work = tmp_path / "origin-work"
    origin_work.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=origin_work, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=origin_work, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=origin_work,
        check=True,
    )
    (origin_work / "README.md").write_text("# main\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=origin_work, check=True)
    subprocess.run(
        ["git", "commit", "-m", "main"],
        cwd=origin_work,
        check=True,
        stdout=subprocess.PIPE,
    )
    subprocess.run(["git", "switch", "-c", "develop"], cwd=origin_work, check=True)
    (origin_work / "README.md").write_text("# develop\n", encoding="utf-8")
    subprocess.run(
        ["git", "commit", "-am", "develop"],
        cwd=origin_work,
        check=True,
        stdout=subprocess.PIPE,
    )
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=origin_work,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "clone", "--bare", str(origin_work), str(bare)],
        check=True,
        stdout=subprocess.PIPE,
    )
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--no-checkout", str(bare), str(clone)],
        check=True,
        stdout=subprocess.PIPE,
    )
    assert _resolve_git_commit(clone, "develop") == expected
