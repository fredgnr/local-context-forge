from __future__ import annotations

import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from app.config import Settings
from app.dulwich_support import EXPECTED_DULWICH_VERSION
from app.service import AppService
from conftest import create_fixture_repository


def test_product_git_path_trap_rollback_and_c_git_interoperability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git_binary = shutil.which("git")
    assert git_binary is not None
    real_run = subprocess.run
    repository = create_fixture_repository(tmp_path)
    trap = tmp_path / "empty-path"
    trap.mkdir()
    data = tmp_path / "data"
    settings = Settings(
        data_dir=data,
        database_path=data / "metadata.sqlite3",
        qmd_enabled=False,
        ctags_enabled=False,
        local_source_roots=(tmp_path,),
    )

    def fail_product_subprocess(*_args, **_kwargs):
        raise AssertionError("product code attempted to launch a subprocess")

    with monkeypatch.context() as product_trap:
        product_trap.setenv("PATH", str(trap))
        product_trap.setattr(subprocess, "run", fail_product_subprocess)
        product_trap.setattr(subprocess, "Popen", fail_product_subprocess)

        service = AppService(settings)
        library = service.create_library(
            {"name": "Path Trap Widgets", "source": str(repository)}
        )
        queued = service.create_ingest_job(
            library["id"],
            version="path-trap",
            ref="HEAD",
            provider="mock",
            auto_publish=False,
        )
        completed = service.run_ingest_job(queued["id"])
        assert completed["status"] == "completed", completed
        proposals = service.list_proposals(library["id"], status="pending")
        assert proposals

        original_transaction = service.db.transaction

        @contextmanager
        def failed_transaction():
            raise RuntimeError("fixture sqlite failure")
            yield

        product_trap.setattr(service.db, "transaction", failed_transaction)
        with pytest.raises(RuntimeError, match="fixture sqlite failure"):
            service.publish_proposal(proposals[0]["id"], reindex=False)
        product_trap.setattr(service.db, "transaction", original_transaction)
        assert service.get_proposal(proposals[0]["id"])["status"] == "pending"
        assert service.list_pages(library["id"]) == []

        for proposal in proposals:
            service.publish_proposal(proposal["id"], reindex=False)
        lint = service.lint(library["id"], completed["version"])
        assert lint["ok"], lint

    wiki_root = settings.wiki_dir / library["slug"]
    commands = (
        ["fsck", "--strict", "--no-dangling"],
        ["log", "--format=%H", "main"],
        ["rev-list", "--count", "main"],
        ["status", "--porcelain"],
    )
    results = [
        real_run(
            [git_binary, "-C", str(wiki_root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        for arguments in commands
    ]
    assert results[0].stdout == ""
    assert len(results[1].stdout.splitlines()) == len(proposals) + 1
    assert results[2].stdout.strip() == str(len(proposals) + 1)
    assert results[3].stdout == ""
    assert EXPECTED_DULWICH_VERSION == (1, 2, 11)
