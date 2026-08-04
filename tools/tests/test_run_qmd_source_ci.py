from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "run_qmd_source_ci.py"
SPEC = importlib.util.spec_from_file_location("run_qmd_source_ci", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class QmdSourceRunnerTests(unittest.TestCase):
    def test_node_summary_is_parsed_fail_closed(self) -> None:
        output = "\n".join(
            [
                "# tests 11",
                "# pass 10",
                "# fail 0",
                "# cancelled 0",
                "# skipped 1",
                "# todo 0",
            ]
        )
        self.assertEqual(
            RUNNER.parse_test_summary(output),
            {
                "tests": 11,
                "pass": 10,
                "fail": 0,
                "cancelled": 0,
                "skipped": 1,
                "todo": 0,
            },
        )

    def test_missing_summary_field_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "skipped"):
            RUNNER.parse_test_summary(
                "# tests 1\n# pass 1\n# fail 0\n# cancelled 0\n# todo 0\n"
            )

    def test_model_file_and_cache_paths_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models = root / "cache" / "models"
            models.mkdir(parents=True)
            (models / "embedding.gguf").write_bytes(b"fixture")
            self.assertEqual(RUNNER.model_cache_paths(root), ["cache/models"])
            self.assertEqual(RUNNER.model_files(root), ["cache/models/embedding.gguf"])


if __name__ == "__main__":
    unittest.main()
