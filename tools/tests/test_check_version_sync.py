from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "check_version_sync.py"
SPEC = importlib.util.spec_from_file_location("check_version_sync", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class VersionSyncTests(unittest.TestCase):
    def test_current_versions_are_synchronized(self) -> None:
        self.assertEqual(CHECKER.main(), 0)

    def test_retrieval_protocol_has_a_distinct_canonical_lock(self) -> None:
        versions = json.loads(CHECKER.MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(versions["desktopProtocol"], {"major": 1, "minor": 0})
        self.assertEqual(
            versions["desktopRetrievalProtocol"],
            {"major": 1, "minor": 1},
        )

    def test_python_retrieval_protocol_drift_fails(self) -> None:
        original = CHECKER._constant

        def drifted(path: Path, name: str) -> object:
            if name == "DESKTOP_RETRIEVAL_PROTOCOL_MINOR":
                return "0"
            return original(path, name)

        errors = io.StringIO()
        with mock.patch.object(CHECKER, "_constant", side_effect=drifted):
            with contextlib.redirect_stderr(errors):
                self.assertEqual(CHECKER.main(), 1)
        self.assertIn("backend retrieval protocol minor", errors.getvalue())

    def test_python_retrieval_protocol_version_drift_fails(self) -> None:
        original = CHECKER._constant

        def drifted(path: Path, name: str) -> object:
            if name == "DESKTOP_RETRIEVAL_PROTOCOL_VERSION":
                return "1.0"
            return original(path, name)

        errors = io.StringIO()
        with mock.patch.object(CHECKER, "_constant", side_effect=drifted):
            with contextlib.redirect_stderr(errors):
                self.assertEqual(CHECKER.main(), 1)
        self.assertIn("backend retrieval protocol version", errors.getvalue())

    def test_typescript_retrieval_protocol_drift_fails(self) -> None:
        original = CHECKER._typescript_string_constant

        def drifted(path: Path, name: str) -> str:
            if name == "RETRIEVAL_BROKER_PROTOCOL_VERSION":
                return "1.0"
            return original(path, name)

        errors = io.StringIO()
        with mock.patch.object(
            CHECKER,
            "_typescript_string_constant",
            side_effect=drifted,
        ):
            with contextlib.redirect_stderr(errors):
                self.assertEqual(CHECKER.main(), 1)
        self.assertIn("desktop retrieval broker protocol", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
