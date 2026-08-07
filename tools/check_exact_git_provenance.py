#!/usr/bin/env python3
"""Verify and emit the exact clean Git commit/tree packaging boundary."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path


_BUILD_SCRIPT = Path(__file__).resolve().with_name("build_python_sidecar.py")
_SPECIFICATION = importlib.util.spec_from_file_location(
    "lcf_exact_git_build_boundary", _BUILD_SCRIPT
)
if _SPECIFICATION is None or _SPECIFICATION.loader is None:
    raise RuntimeError("exact Git provenance implementation is unavailable")
sidecar = importlib.util.module_from_spec(_SPECIFICATION)
sys.modules[_SPECIFICATION.name] = sidecar
_SPECIFICATION.loader.exec_module(sidecar)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the exact clean Git packaging provenance"
    )
    parser.add_argument(
        "--emit-github-env",
        action="store_true",
        help="print only the fixed provenance key/value lines",
    )
    parser.add_argument(
        "--expected-tag",
        help="also require this exact tag to resolve to the source commit",
    )
    return parser


def inspect(environment: dict[str, str]) -> dict[str, object]:
    commit = environment.get("LCF_SOURCE_SHA", "").lower()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise sidecar.BuildError("Exact source commit is missing or invalid")
    tree = sidecar._git_output("rev-parse", f"{commit}^{{tree}}").lower()
    selected_tree = environment.get("LCF_SOURCE_TREE", "").lower()
    if selected_tree and selected_tree != tree:
        raise sidecar.BuildError("Exact source tree differs from the selected commit")
    state = sidecar._validate_repository_state(
        {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree}
    )
    selected_snapshot = environment.get("LCF_SOURCE_SNAPSHOT_SHA256", "").lower()
    if selected_snapshot and selected_snapshot != state["sourceSnapshotSha256"]:
        raise sidecar.BuildError("Exact source snapshot digest differs")
    package_lock_entry = next(
        (
            entry
            for entry in state["sourceInventory"]
            if entry.path == "web/package-lock.json"
        ),
        None,
    )
    if (
        package_lock_entry is None
        or package_lock_entry.mode != "100644"
        or package_lock_entry.object_type != "blob"
    ):
        raise sidecar.BuildError("Reviewed renderer package lock is missing")
    package_lock_bytes = sidecar._git_bytes(
        "cat-file", "blob", package_lock_entry.object_id
    )
    object_digest = hashlib.sha1(
        b"blob "
        + str(len(package_lock_bytes)).encode("ascii")
        + b"\0"
        + package_lock_bytes
    ).hexdigest()
    if object_digest != package_lock_entry.object_id:
        raise sidecar.BuildError("Reviewed renderer package lock object differs")
    renderer_package_lock_sha256 = hashlib.sha256(package_lock_bytes).hexdigest()
    selected_package_lock = environment.get(
        "LCF_RENDERER_PACKAGE_LOCK_SHA256", ""
    ).lower()
    if (
        selected_package_lock
        and selected_package_lock != renderer_package_lock_sha256
    ):
        raise sidecar.BuildError("Reviewed renderer package lock digest differs")
    epoch = int(sidecar._git_output("show", "-s", "--format=%ct", commit))
    selected_epoch = environment.get("LCF_SOURCE_DATE_EPOCH", "")
    if selected_epoch and selected_epoch != str(epoch):
        raise sidecar.BuildError("Exact source epoch differs from the selected commit")
    if epoch < 100_000_000:
        raise sidecar.BuildError("Exact source epoch is invalid")
    return {
        "repositoryCommit": commit,
        "repositoryTree": tree,
        "sourceSnapshotSha256": state["sourceSnapshotSha256"],
        "sourceDateEpoch": epoch,
        "rendererPackageLockSha256": renderer_package_lock_sha256,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = inspect(dict(os.environ))
        if arguments.expected_tag:
            if (
                re.fullmatch(
                    r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?",
                    arguments.expected_tag,
                )
                is None
                or sidecar._git_output(
                    "rev-parse", f"refs/tags/{arguments.expected_tag}^{{commit}}"
                ).lower()
                != result["repositoryCommit"]
            ):
                raise sidecar.BuildError(
                    "Exact release tag differs from the source commit"
                )
    except (sidecar.BuildError, ValueError):
        print("exact Git provenance check failed", file=sys.stderr)
        return 2
    if arguments.emit_github_env:
        print(f"LCF_SOURCE_SHA={result['repositoryCommit']}")
        print(f"LCF_SOURCE_TREE={result['repositoryTree']}")
        print(f"LCF_SOURCE_SNAPSHOT_SHA256={result['sourceSnapshotSha256']}")
        print(f"LCF_SOURCE_DATE_EPOCH={result['sourceDateEpoch']}")
        print(
            "LCF_RENDERER_PACKAGE_LOCK_SHA256="
            f"{result['rendererPackageLockSha256']}"
        )
    else:
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
