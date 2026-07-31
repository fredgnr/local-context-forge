from __future__ import annotations

import shutil
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
from conftest import create_fixture_repository


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


def test_local_git_core_worktree_indirection_is_rejected(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    subprocess.run(
        ["git", "config", "core.worktree", str(tmp_path / "outside")],
        cwd=repository,
        check=True,
    )

    with pytest.raises(SourceError, match="core.worktree"):
        create_snapshot(
            _settings(tmp_path / "data", tmp_path),
            "worktree-config",
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


def test_git_archive_disables_http_redirects(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(_manager, method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return object()

    monkeypatch.setattr(source_module.urllib3.PoolManager, "request", fake_request)
    manager = source_module._DeadlinePoolManager(timeout_seconds=30)
    manager.request("GET", "https://github.com/example/repository.git/info/refs")

    assert captured["redirect"] is False
    timeout = captured["timeout"]
    assert timeout.connect_timeout <= 10
    assert timeout.read_timeout <= 60
    retries = manager.connection_pool_kw["retries"]
    assert retries.total == 0
    assert retries.redirect == 0
    assert manager.connection_pool_kw["cert_reqs"] == "CERT_REQUIRED"
    assert manager.connection_pool_kw["ca_certs"] == source_module.certifi.where()
    assert isinstance(manager, source_module.urllib3.PoolManager)
    assert not isinstance(manager, source_module.urllib3.ProxyManager)


def test_controlled_remote_transport_enforces_overall_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter((100.0, 131.0))
    monkeypatch.setattr(source_module.time, "monotonic", lambda: next(clock))
    manager = source_module._DeadlinePoolManager(timeout_seconds=30)

    with pytest.raises(
        source_module.urllib3.exceptions.TimeoutError,
        match="overall deadline",
    ):
        manager.request(
            "GET", "https://github.com/example/repository.git/info/refs"
        )


def test_https_snapshot_uses_controlled_transport_and_remote_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    calls: dict[str, object] = {}

    class FakeHttpsClient(source_module.Urllib3HttpGitClient):
        def __init__(self):
            self.closed = False

        def clone(self, path, target, **kwargs):
            calls["clone_path"] = path
            calls["clone_kwargs"] = kwargs
            shutil.copytree(repository, target)

            class Cloned:
                def close(self):
                    calls["clone_closed"] = True

            return Cloned()

        def close(self):
            self.closed = True

    client = FakeHttpsClient()

    def fake_transport(source, **kwargs):
        calls["source"] = source
        calls["transport_kwargs"] = kwargs
        return client, "/example/widgets.git"

    monkeypatch.setattr(source_module, "get_transport_and_path", fake_transport)
    snapshot = create_snapshot(
        _settings(tmp_path / "data"),
        "remote",
        "https://github.com/example/widgets.git",
        "main",
    )

    assert snapshot.source_kind == "git-remote"
    assert (snapshot.repo_path / "widgets.py").is_file()
    assert calls["clone_path"] == "/example/widgets.git"
    clone_kwargs = calls["clone_kwargs"]
    assert clone_kwargs["checkout"] is False
    assert clone_kwargs["origin"] == "origin"
    assert clone_kwargs["protocol_version"] == 2
    assert callable(clone_kwargs["progress"])
    transport = calls["transport_kwargs"]
    assert isinstance(transport["config"], source_module.ConfigFile)
    assert isinstance(
        transport["pool_manager"], source_module._DeadlinePoolManager
    )
    assert transport["operation"] == "pull"
    assert calls["clone_closed"] is True
    assert client.closed is True


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


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "--help",
        "develop\n--help",
        "bad\0ref",
        "HEAD~1",
        "refs/heads/../escape",
        "refs/replace/1234",
        "refs/remotes/upstream/main",
        "release@{1}",
    ],
)
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


def test_annotated_tag_peels_and_conflicting_branch_is_ambiguous(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    tagged = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "tag", "-a", "release", "-m", "release"],
        cwd=repository,
        check=True,
    )

    assert _resolve_git_commit(repository, "release") == tagged
    assert _resolve_git_commit(repository, "refs/tags/release") == tagged

    (repository / "README.md").write_text("# later\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "later"], cwd=repository, check=True)
    branch = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "branch", "release"], cwd=repository, check=True)

    assert _resolve_git_commit(repository, "refs/heads/release") == branch
    assert _resolve_git_commit(repository, "refs/tags/release") == tagged
    with pytest.raises(SourceError, match="Ambiguous Git ref"):
        _resolve_git_commit(repository, "release")


def test_sha256_git_repository_snapshot_keeps_full_commit_identity(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "sha256-repository"
    subprocess.run(
        ["git", "init", "--object-format=sha256", "-b", "main", str(repository)],
        check=True,
        stdout=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=repository, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repository,
        check=True,
    )
    (repository / "README.md").write_text("# SHA-256\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "sha256 fixture"],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
    )

    snapshot = create_snapshot(
        _settings(tmp_path / "data", tmp_path),
        "sha256",
        str(repository),
    )

    assert len(snapshot.source_sha) == 64
    assert (snapshot.repo_path / "README.md").read_text(encoding="utf-8") == (
        "# SHA-256\n"
    )


def test_local_snapshot_does_not_expand_repository_config_includes(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    sentinel = tmp_path / "config-program-ran"
    included = tmp_path / "included.gitconfig"
    included.write_text(
        (
            "[core]\n"
            f"\tworktree = {tmp_path / 'outside'}\n"
            "[filter \"unsafe\"]\n"
            f"\tclean = sh -c 'touch {sentinel}'\n"
        ),
        encoding="utf-8",
    )
    with (repository / ".git" / "config").open("a", encoding="utf-8") as handle:
        handle.write(f"\n[include]\n\tpath = {included}\n")

    snapshot = create_snapshot(
        _settings(tmp_path / "data", tmp_path),
        "included-config",
        str(repository),
    )

    assert (snapshot.repo_path / "README.md").is_file()
    assert not sentinel.exists()


def test_git_snapshot_rejects_symlink_that_escapes_tree(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    (repository / "escape").symlink_to("../../outside")
    subprocess.run(["git", "add", "escape"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "unsafe symlink"],
        cwd=repository,
        check=True,
    )

    with pytest.raises(SourceError, match="Unsafe symlink"):
        source_module._archive_git(
            _settings(tmp_path / "data", tmp_path),
            repository,
            "HEAD",
            tmp_path / "destination",
        )


def test_git_snapshot_rejects_missing_required_object(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    blob = subprocess.run(
        ["git", "rev-parse", "HEAD:widgets.py"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    object_path = repository / ".git" / "objects" / blob[:2] / blob[2:]
    assert object_path.is_file()
    object_path.unlink()

    with pytest.raises(SourceError, match="missing.*required.*object"):
        source_module._archive_git(
            _settings(tmp_path / "data", tmp_path),
            repository,
            "HEAD",
            tmp_path / "destination",
        )
