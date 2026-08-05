#!/usr/bin/env python3
"""Run the QMD worker source tier without lifecycle builds or model access."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "desktop" / "workers" / "qmd"
NETWORK_TRAP = ROOT / "desktop" / "scripts" / "qmdNetworkTrap.mjs"
EXPECTED_NODE = "v22.23.2"
EXPECTED_SKIP_REASON = (
    "better-sqlite3 native binding is not built in source checkout"
)
ISOLATED_ROOTS = [
    ("isolated HOME", "HOME", "home"),
    ("isolated XDG_CACHE_HOME", "XDG_CACHE_HOME", "cache"),
    ("isolated XDG_CONFIG_HOME", "XDG_CONFIG_HOME", "config"),
    ("isolated XDG_DATA_HOME", "XDG_DATA_HOME", "data"),
    ("isolated TMPDIR", "TMPDIR", "tmp"),
]
MODEL_SCAN_SCOPE = [label for label, _, _ in ISOLATED_ROOTS]
MODEL_SUFFIXES = {".bin", ".gguf", ".onnx", ".safetensors", ".tflite"}
MODEL_CACHE_NAMES = {"huggingface", "models", "node-llama-cpp", "transformers"}
SUMMARY_KEYS = ("tests", "pass", "fail", "cancelled", "skipped", "todo")


def model_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MODEL_SUFFIXES
    )


def model_cache_paths(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_dir() and path.name.lower() in MODEL_CACHE_NAMES
    )


def scoped_paths(
    isolated_root: Path, roots: list[Path], scanner: Callable[[Path], list[str]]
) -> list[str]:
    discovered: list[str] = []
    for root in roots:
        for relative in scanner(root):
            discovered.append(str((root / relative).relative_to(isolated_root)))
    return sorted(discovered)


def parse_test_summary(output: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    for key in SUMMARY_KEYS:
        matches = re.findall(rf"^# {key} (\d+)\s*$", output, re.MULTILINE)
        if not matches:
            raise ValueError(f"Node test output is missing the {key!r} summary")
        if len(matches) != 1:
            raise ValueError(f"Node test output contains duplicate {key!r} summaries")
        summary[key] = int(matches[0])
    return summary


def build_environment(isolated_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    isolated_environment: dict[str, str] = {}
    for _, environment_name, directory_name in ISOLATED_ROOTS:
        path = isolated_root / directory_name
        path.mkdir(parents=True, exist_ok=True)
        isolated_environment[environment_name] = str(path)
    environment.update(
        {
            "CI": "true",
            **isolated_environment,
            "LCF_QMD_SOURCE_TEST": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "npm_config_offline": "true",
            "NODE_OPTIONS": "",
        }
    )
    return environment


def run(node: str, result_path: Path | None) -> int:
    version = subprocess.run(
        [node, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    node_version = version.stdout.strip()
    if version.returncode != 0 or node_version != EXPECTED_NODE:
        print(
            f"ERROR: QMD source CI requires Node {EXPECTED_NODE.removeprefix('v')}; "
            f"observed {node_version or 'unavailable'}",
            file=sys.stderr,
        )
        return 2

    with tempfile.TemporaryDirectory(prefix="lcf-qmd-source-") as temporary:
        isolated_root = Path(temporary)
        environment = build_environment(isolated_root)
        scan_roots = [Path(environment[name]) for _, name, _ in ISOLATED_ROOTS]
        before = scoped_paths(isolated_root, scan_roots, model_files)
        cache_paths_before = scoped_paths(isolated_root, scan_roots, model_cache_paths)
        command = [
            node,
            "--import",
            str(NETWORK_TRAP),
            "--test",
            *sorted(str(path) for path in (WORKER / "test").glob("*.test.mjs")),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        output = completed.stdout + completed.stderr
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        after = scoped_paths(isolated_root, scan_roots, model_files)
        cache_paths_after = scoped_paths(isolated_root, scan_roots, model_cache_paths)

        errors: list[str] = []
        try:
            summary = parse_test_summary(output)
        except ValueError as error:
            summary = {key: -1 for key in SUMMARY_KEYS}
            errors.append(str(error))

        if completed.returncode != 0:
            errors.append(f"Node test process exited {completed.returncode}")
        if summary["fail"] != 0 or summary["cancelled"] != 0 or summary["todo"] != 0:
            errors.append(f"unexpected Node test summary: {summary}")
        if summary["skipped"] != 1:
            errors.append(f"expected exactly one allowlisted skip, observed {summary['skipped']}")
        if summary["tests"] != summary["pass"] + summary["skipped"]:
            errors.append("test total does not equal pass + skipped")
        skip_lines = re.findall(r"^.*# SKIP (.+?)\s*$", output, re.MULTILINE)
        if skip_lines != [EXPECTED_SKIP_REASON]:
            errors.append(f"the sole # SKIP reason is not allowlisted: {skip_lines}")
        if "LCF_QMD_NETWORK_TRAP=active:source-test" not in output:
            errors.append("QMD source network trap did not report active")
        if "LCF_QMD_NETWORK_POLICY=deny-external-allow-af-unix" not in output:
            errors.append("QMD source network policy marker is absent")
        created = sorted(set(after) - set(before))
        if created:
            errors.append(f"model-like files were created: {created}")
        created_cache_paths = sorted(set(cache_paths_after) - set(cache_paths_before))
        if created_cache_paths:
            errors.append(f"model cache paths were created: {created_cache_paths}")

        result = {
            "schema_version": 2,
            "node_version": node_version.removeprefix("v"),
            "command": "node --import desktop/scripts/qmdNetworkTrap.mjs --test "
            "desktop/workers/qmd/test/*.test.mjs",
            "tests": summary,
            "allowed_skip_reason": EXPECTED_SKIP_REASON,
            "network_trap": "active" if not errors or "LCF_QMD_NETWORK_TRAP=active:source-test" in output else "inactive",
            "network_policy": "deny-external-allow-af-unix",
            "model_scan": {
                "scope": MODEL_SCAN_SCOPE,
                "repository_worktree_scanned": False,
                "global_tmp_scanned": False,
                "model_files_before": len(before),
                "model_files_after": len(after),
                "model_files_created": len(created),
                "model_file_paths_created": created,
                "model_cache_paths_before": len(cache_paths_before),
                "model_cache_paths_after": len(cache_paths_after),
                "model_cache_paths_created": len(created_cache_paths),
                "model_cache_path_names_created": created_cache_paths,
            },
            "result": "pass" if not errors else "fail",
            "errors": errors,
        }
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        print(f"LCF_QMD_SOURCE_RESULT={serialized}")
        if result_path is not None:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(serialized + "\n", encoding="utf-8")
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", default=os.environ.get("NODE", "node"))
    parser.add_argument("--result", type=Path)
    arguments = parser.parse_args()
    return run(arguments.node, arguments.result)


if __name__ == "__main__":
    raise SystemExit(main())
