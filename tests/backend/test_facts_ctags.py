from __future__ import annotations

import json
import subprocess
from pathlib import Path

import app.facts as facts_module
from app.config import Settings
from app.facts import extract_facts


def test_universal_ctags_json_is_normalized_and_bounded(
    tmp_path: Path, monkeypatch
) -> None:
    repository = tmp_path / "repo"
    source = repository / "src" / "api.ts"
    source.parent.mkdir(parents=True)
    source.write_text(
        "export function greet(name: string): string {\n  return `hello ${name}`;\n}\n",
        encoding="utf-8",
    )
    outside = tmp_path / "secret.ts"
    outside.write_text("export function secret() {}\n", encoding="utf-8")
    records = [
        {
            "_type": "tag",
            "name": "greet",
            "path": "src/api.ts",
            "line": 1,
            "end": 3,
            "kind": "function",
            "signature": "(name: string)",
        },
        {
            "_type": "tag",
            "name": "greet",
            "path": "src/api.ts",
            "line": 1,
            "end": 3,
            "kind": "function",
        },
        {
            "_type": "tag",
            "name": "secret",
            "path": "../secret.ts",
            "line": 1,
            "kind": "function",
        },
        {
            "_type": "tag",
            "name": "bad_line",
            "path": "src/api.ts",
            "line": 99,
            "kind": "function",
        },
    ]
    called: dict[str, object] = {}

    def fake_run(command, **kwargs):
        called["command"] = command
        called["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(record) for record in records),
            stderr="",
        )

    monkeypatch.setattr(facts_module.shutil, "which", lambda _binary: "/usr/bin/ctags")
    monkeypatch.setattr(facts_module.subprocess, "run", fake_run)
    data = tmp_path / "data"
    settings = Settings(
        data_dir=data,
        database_path=data / "metadata.sqlite3",
        qmd_enabled=False,
        max_symbols=2,
    )
    settings.ensure_directories()
    bundle = extract_facts(settings, "fixture", "abc123", repository)

    assert bundle.manifest["symbol_extractor"] == "universal-ctags"
    assert len(bundle.symbols) == 1
    symbol = bundle.symbols[0]
    assert symbol == {
        "id": "src/api.ts:1:greet",
        "name": "greet",
        "kind": "function",
        "path": "src/api.ts",
        "line": 1,
        "end_line": 3,
        "signature": "export function greet(name: string): string {",
        "docstring": "",
        "role": "source",
    }
    assert called["kwargs"]["cwd"] == repository
    assert called["kwargs"]["timeout"] == settings.ctags_timeout_seconds
    assert "shell" not in called["kwargs"]
    assert called["command"][0] == "/usr/bin/ctags"
    assert called["command"][1:3] == ["--options=NONE", "--links=no"]


def test_sensitive_repository_files_never_enter_facts_or_evidence(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    (repository / "src").mkdir(parents=True)
    (repository / "src" / "api.py").write_text(
        "def public_api() -> str:\n    return 'ok'\n", encoding="utf-8"
    )
    (repository / ".env").write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")
    (repository / ".env.example").write_text(
        "OPENAI_API_KEY=replace-me\n", encoding="utf-8"
    )
    (repository / ".codex").mkdir()
    (repository / ".codex" / "auth.json").write_text(
        '{"token":"secret"}\n', encoding="utf-8"
    )
    (repository / "private.pem").write_text(
        "-----BEGIN PRIVATE KEY-----\nsecret\n", encoding="utf-8"
    )
    data = tmp_path / "data"
    settings = Settings(
        data_dir=data,
        database_path=data / "metadata.sqlite3",
        qmd_enabled=False,
        ctags_enabled=False,
    )
    settings.ensure_directories()
    bundle = extract_facts(settings, "fixture", "secret-test", repository)

    evidence_paths = {item["path"] for item in bundle.evidence["files"]}
    symbol_paths = {item["path"] for item in bundle.symbols}
    manifest_paths = {item["path"] for item in bundle.manifest["files"]}
    assert "src/api.py" in evidence_paths
    assert ".env.example" in evidence_paths
    for secret_path in (".env", ".codex/auth.json", "private.pem"):
        assert secret_path not in evidence_paths
        assert secret_path not in symbol_paths
        assert secret_path not in manifest_paths
    assert {item["path"] for item in bundle.manifest["skipped_sensitive"]} == {
        ".codex/auth.json",
        ".env",
        "private.pem",
    }
