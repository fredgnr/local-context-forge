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
    def test_model_scan_scope_is_explicit_and_bounded(self) -> None:
        self.assertEqual(
            RUNNER.MODEL_SCAN_SCOPE,
            [
                "isolated HOME",
                "isolated XDG_CACHE_HOME",
                "isolated XDG_CONFIG_HOME",
                "isolated XDG_DATA_HOME",
                "isolated TMPDIR",
            ],
        )
        self.assertNotIn("repository worktree", RUNNER.MODEL_SCAN_SCOPE)
        self.assertNotIn("global TMPDIR", RUNNER.MODEL_SCAN_SCOPE)

    def test_scan_scope_is_derived_from_actual_isolated_environment_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = RUNNER.build_environment(root)
            for label, name, directory in RUNNER.ISOLATED_ROOTS:
                self.assertIn(label, RUNNER.MODEL_SCAN_SCOPE)
                self.assertEqual(Path(environment[name]), root / directory)
                self.assertTrue((root / directory).is_dir())

    def test_scanner_visits_only_the_five_declared_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = RUNNER.build_environment(root)
            roots = [Path(environment[name]) for _, name, _ in RUNNER.ISOLATED_ROOTS]
            (root / "outside.gguf").write_bytes(b"outside declared scope")
            (roots[1] / "inside.gguf").write_bytes(b"inside declared scope")
            observed = RUNNER.scoped_paths(root, roots, RUNNER.model_files)
            self.assertEqual(observed, ["cache/inside.gguf"])

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

    def test_duplicate_summary_field_fails(self) -> None:
        output = (
            "# tests 1\n# pass 1\n# fail 0\n# cancelled 0\n"
            "# skipped 0\n# todo 0\n# pass 1\n"
        )
        with self.assertRaisesRegex(ValueError, "duplicate 'pass'"):
            RUNNER.parse_test_summary(output)

    def test_model_file_and_cache_paths_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models = root / "cache" / "models"
            models.mkdir(parents=True)
            (models / "embedding.gguf").write_bytes(b"fixture")
            self.assertEqual(RUNNER.model_cache_paths(root), ["cache/models"])
            self.assertEqual(RUNNER.model_files(root), ["cache/models/embedding.gguf"])

    def test_model_cache_name_matching_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Transformers").mkdir()
            self.assertEqual(RUNNER.model_cache_paths(root), ["Transformers"])


if __name__ == "__main__":
    unittest.main()
