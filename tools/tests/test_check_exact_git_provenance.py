from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import check_exact_git_provenance as checker


class ExactGitProvenanceTests(unittest.TestCase):
    def _git(self, root: Path, *arguments: str) -> str:
        environment = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        }
        return subprocess.run(
            ["/usr/bin/git", "-C", str(root), *arguments],
            check=True,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def test_expected_tag_uses_the_fully_qualified_tag_ref(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lcf-exact-tag-") as raw_root:
            root = Path(raw_root).resolve(strict=True)
            self._git(root, "init", "--quiet")
            source = root / "source.txt"
            source.write_text("tagged\n", encoding="utf-8")
            self._git(root, "add", "--all")
            self._git(
                root,
                "-c",
                "user.name=LCF Test",
                "-c",
                "user.email=lcf-test@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "tagged",
            )
            tag_commit = self._git(root, "rev-parse", "HEAD")
            self._git(root, "tag", "v1.2.3", tag_commit)
            source.write_text("branch\n", encoding="utf-8")
            self._git(root, "add", "--all")
            self._git(
                root,
                "-c",
                "user.name=LCF Test",
                "-c",
                "user.email=lcf-test@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "branch",
            )
            self._git(root, "branch", "v1.2.3", "HEAD")

            calls: list[tuple[str, ...]] = []

            def git_output(*arguments: str) -> str:
                calls.append(arguments)
                return self._git(root, *arguments)

            result = {
                "repositoryCommit": tag_commit,
                "repositoryTree": "b" * 40,
                "sourceSnapshotSha256": "c" * 64,
                "sourceDateEpoch": 1_700_000_000,
                "rendererPackageLockSha256": "d" * 64,
            }
            with (
                mock.patch.object(checker, "inspect", return_value=result),
                mock.patch.object(checker.sidecar, "_git_output", git_output),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(checker.main(["--expected-tag", "v1.2.3"]), 0)
            self.assertEqual(
                calls,
                [("rev-parse", "refs/tags/v1.2.3^{commit}")],
            )


if __name__ == "__main__":
    unittest.main()
