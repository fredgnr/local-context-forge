from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.config import Settings
from app.facts import FactsBundle
from app.generation import (
    GenerationContext,
    OllamaGenerator,
    _context_payload,
    _minimal_codex_environment,
    generation_evidence_ranges,
)
from app.utils import portable_path_key, safe_page_path


def _oversized_context(tmp_path: Path) -> GenerationContext:
    long_text = "public API evidence " * 5_000
    files = [
        {
            "path": f"src/package_{index}/" + "x" * 240 + ".py",
            "language": "Python",
            "role": "source",
        }
        for index in range(1_000)
    ]
    symbols = [
        {
            "name": f"symbol_{index}",
            "kind": "function",
            "path": f"src/module_{index}.py",
            "line": 1,
            "end_line": 3,
            "signature": "def symbol(" + "argument, " * 100 + ")",
            "docstring": long_text,
            "role": "source",
        }
        for index in range(1_000)
    ]
    evidence = [
        {
            "path": f"src/module_{index}.py",
            "language": "Python",
            "role": "source",
            "content": long_text,
            "truncated": False,
        }
        for index in range(20)
    ]
    existing = [
        {
            "path": f"api/module-{index}.md",
            "title": f"Module {index}",
            "kind": "api",
            "summary": "summary",
            "markdown": long_text,
            "source_refs": [
                {"path": f"src/module_{index}.py", "line_start": 1, "line_end": 3}
            ],
        }
        for index in range(20)
    ]
    facts = FactsBundle(
        root=tmp_path,
        manifest={
            "file_count": len(files),
            "languages": {"Python": len(files)},
            "files": files,
        },
        symbols=symbols,
        evidence={"files": evidence},
    )
    return GenerationContext(
        library_name="Oversized",
        library_slug="oversized",
        version="main+git.123456789abc",
        source_sha="123456789abcdef",
        facts=facts,
        existing_wiki=existing,
    )


def test_model_payload_has_component_and_final_hard_budgets(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_enabled=False,
    )
    payload = _context_payload(_oversized_context(tmp_path), settings)
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= settings.max_model_payload_bytes
    assert (
        len(json.dumps(payload["manifest"]["files"], ensure_ascii=False).encode())
        <= settings.max_model_manifest_bytes
    )
    assert (
        len(json.dumps(payload["symbols"], ensure_ascii=False).encode())
        <= settings.max_model_symbols_bytes
    )
    assert (
        len(json.dumps(payload["evidence_files"], ensure_ascii=False).encode())
        <= settings.max_model_evidence_bytes
    )
    assert (
        len(json.dumps(payload["existing_wiki"], ensure_ascii=False).encode())
        <= settings.max_existing_wiki_bytes
    )


def test_symbol_fact_only_allows_its_visible_declaration_line(
    tmp_path: Path,
) -> None:
    context = GenerationContext(
        library_name="Scoped",
        library_slug="scoped",
        version="v1",
        source_sha="abc",
        facts=FactsBundle(
            root=tmp_path,
            manifest={"file_count": 1, "languages": {"Python": 1}, "files": []},
            symbols=[
                {
                    "name": "visible_signature",
                    "kind": "function",
                    "path": "module.py",
                    "line": 10,
                    "end_line": 40,
                    "signature": "def visible_signature(value: str) -> str",
                    "docstring": "A bounded derived docstring.",
                    "role": "source",
                }
            ],
            evidence={"files": []},
        ),
        existing_wiki=[],
    )
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_enabled=False,
    )

    assert generation_evidence_ranges(context, settings, "ollama") == [
        {
            "path": "module.py",
            "line_start": 10,
            "line_end": 10,
            "origins": ["symbol"],
        }
    ]


def test_codex_environment_drops_cloud_ci_and_api_secrets(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("SAFE_LOCALE", "en_US.UTF-8")
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_enabled=False,
        codex_env_allowlist=(
            "SAFE_LOCALE",
            "OPENAI_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "GITHUB_TOKEN",
            "CI",
        ),
    )
    environment = _minimal_codex_environment(settings)
    assert environment["SAFE_LOCALE"] == "en_US.UTF-8"
    assert environment["NO_COLOR"] == "1"
    assert "OPENAI_API_KEY" not in environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment
    assert "GITHUB_TOKEN" not in environment
    assert "CI" not in environment


def test_ollama_request_sets_context_and_output_limits(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_enabled=False,
        ollama_num_ctx=32_768,
        ollama_num_predict=8_192,
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"message": {"content": json.dumps({"pages": [{}]})}}
            ).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.generation.urllib.request.urlopen", fake_urlopen)
    pages = OllamaGenerator(settings).generate(_oversized_context(tmp_path))
    assert pages == [{}]
    options = captured["body"]["options"]
    assert options["num_ctx"] == 32_768
    assert options["num_predict"] == 8_192


@pytest.mark.parametrize(
    "path",
    [
        "CON.md",
        "api/NUL.txt.md",
        "api:client.md",
        "api/client?.md",
        "api/trailing./page.md",
        "facts/client.md",
        "index.md",
        "log.md",
    ],
)
def test_wiki_page_paths_are_portable_and_do_not_shadow_metadata(path: str) -> None:
    with pytest.raises(ValueError):
        safe_page_path(path)


def test_portable_page_collision_key_normalizes_case_and_unicode() -> None:
    assert portable_path_key("API/Café.md") == portable_path_key(
        "api/Cafe\u0301.md"
    )
