from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from host_runner.runner import HostRunner, RunnerError, validate_request

SCHEMA = {
    "type": "object",
    "required": ["pages"],
    "properties": {"pages": {"type": "array"}},
    "additionalProperties": False,
}


def request(provider: str = "auto") -> dict[str, object]:
    return {
        "id": "task_12345678",
        "task": "wiki_v1",
        "provider": provider,
        "evidence": {"manifest": ["src/client.py"]},
        "output_schema": SCHEMA,
        "timeout_seconds": 30,
    }


def fake_cli(path: Path, *, codex: bool, fail_exec: bool = False) -> None:
    if codex:
        body = f"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-test 1.0")
    raise SystemExit(0)
if args == ["login", "status"]:
    raise SystemExit(0)
if args == ["exec", "--help"]:
    print("--ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check "
          "--sandbox --output-schema --output-last-message")
    raise SystemExit(0)
if {fail_exec!s}:
    print("forced failure", file=sys.stderr)
    raise SystemExit(7)
out = args[args.index("--output-last-message") + 1]
open(out, "w", encoding="utf-8").write(json.dumps({{"pages":[]}}))
"""
    else:
        body = """#!/usr/bin/env python3
import json, sys
if sys.argv[1:] == ["--version"]:
    print("cursor-test 1.0")
    raise SystemExit(0)
if sys.argv[1:] == ["status"]:
    raise SystemExit(0)
print(json.dumps({"type":"result","result":json.dumps({"pages":[]})}))
"""
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    path.chmod(0o755)


class ValidationTests(unittest.TestCase):
    def test_unknown_command_and_path_fields_are_rejected(self) -> None:
        for field in ("command", "path"):
            payload = request()
            payload[field] = "/tmp/escape"
            with self.assertRaisesRegex(RunnerError, "unknown request fields"):
                validate_request(payload)

    def test_timeout_is_bounded(self) -> None:
        payload = request()
        payload["timeout_seconds"] = 3601
        with self.assertRaisesRegex(RunnerError, "timeout_seconds"):
            validate_request(payload)


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runner = HostRunner(self.root / "runner")
        self.codex = self.root / "codex"
        self.cursor = self.root / "cursor-agent"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def submit(self, payload: dict[str, object]) -> dict[str, object]:
        path = self.runner.inbox / f"{payload['id']}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(self.runner.process_one())
        return json.loads(
            (self.runner.outbox / f"{payload['id']}.json").read_text(
                encoding="utf-8"
            )
        )

    def test_codex_is_preferred(self) -> None:
        fake_cli(self.codex, codex=True)
        fake_cli(self.cursor, codex=False)
        with patch.dict(
            os.environ,
            {
                "LCF_CODEX_BIN": str(self.codex),
                "LCF_CURSOR_BIN": str(self.cursor),
            },
            clear=False,
        ):
            response = self.submit(request())
        self.assertEqual(response["effective_provider"], "codex_cli")
        self.assertIsNone(response["fallback_reason"])
        self.assertEqual(response["result"], {"pages": []})

    def test_auto_falls_back_only_when_codex_preflight_is_unavailable(self) -> None:
        fake_cli(self.cursor, codex=False)
        with patch.dict(
            os.environ,
            {
                "LCF_CODEX_BIN": str(self.root / "missing-codex"),
                "LCF_CURSOR_BIN": str(self.cursor),
            },
            clear=False,
        ):
            response = self.submit(request())
        self.assertEqual(response["effective_provider"], "cursor_cli")
        self.assertEqual(response["fallback_reason"], "codex_not_installed")

    def test_codex_execution_failure_does_not_fallback(self) -> None:
        fake_cli(self.codex, codex=True, fail_exec=True)
        fake_cli(self.cursor, codex=False)
        with patch.dict(
            os.environ,
            {
                "LCF_CODEX_BIN": str(self.codex),
                "LCF_CURSOR_BIN": str(self.cursor),
            },
            clear=False,
        ):
            response = self.submit(request())
        self.assertIsNone(response["effective_provider"])
        self.assertIn("Codex CLI failed", response["error"])

    def test_explicit_cursor_contract(self) -> None:
        fake_cli(self.cursor, codex=False)
        with patch.dict(
            os.environ,
            {"LCF_CURSOR_BIN": str(self.cursor)},
            clear=False,
        ):
            response = self.submit(request("cursor_cli"))
        self.assertEqual(response["effective_provider"], "cursor_cli")
        self.assertEqual(response["result"], {"pages": []})

    def test_symlink_request_is_rejected_without_following_it(self) -> None:
        outside = self.root / "outside.json"
        outside.write_text(json.dumps(request()), encoding="utf-8")
        link = self.runner.inbox / "task_12345678.json"
        link.symlink_to(outside)
        self.assertTrue(self.runner.process_one())
        response = json.loads(
            (self.runner.outbox / "task_12345678.json").read_text(encoding="utf-8")
        )
        self.assertIn("bounded regular file", response["error"])
        self.assertTrue(outside.is_file())

    def test_interrupted_working_request_fails_closed_on_restart(self) -> None:
        payload = request()
        claimed = self.runner.working / f"{payload['id']}.json"
        claimed.write_text(json.dumps(payload), encoding="utf-8")

        restarted = HostRunner(self.runner.root)
        response = json.loads(
            (restarted.outbox / f"{payload['id']}.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("restarted", response["error"])
        self.assertFalse(claimed.exists())
        self.assertTrue((restarted.failed / claimed.name).is_file())


if __name__ == "__main__":
    unittest.main()
