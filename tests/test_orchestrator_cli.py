"""Offline CLI end-to-end tests; no browser or network required."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from chatgpt_web2api.orchestrator.cli import main


class OrchestratorCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "controller.sqlite"
        self.prompt_file = self.root / "task.txt"
        self.prompt_file.write_text("Build an isolated unit of work", encoding="utf-8")

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--json", "--db", str(self.db), *args])
        result = json.loads(out.getvalue())
        return code, result

    def test_capabilities_without_database(self):
        code, result = self.run_cli("capabilities")
        self.assertEqual(code, 0)
        self.assertFalse(result["data"]["automatic_web_dispatch"])
        self.assertFalse(self.db.exists())

    def test_create_list_claim_and_status(self):
        args = ("create-task", "--project", "demo", "--id", "task-1", "--role", "implement",
                "--prompt-file", str(self.prompt_file), "--write-scope", "repo:src/app")
        code, result = self.run_cli(*args)
        self.assertEqual(code, 0)
        self.assertTrue(result["data"]["created"])
        self.assertFalse(result["data"]["prompt_stored"])
        code, result = self.run_cli(*args)
        self.assertFalse(result["data"]["created"])
        code, result = self.run_cli("claim", "--project", "demo")
        self.assertEqual(result["data"]["reserved"]["slot"], 1)
        code, result = self.run_cli("status", "--project", "demo")
        self.assertEqual(result["data"]["occupied_slots"], [1])
        code, result = self.run_cli("events", "--id", "task-1")
        self.assertEqual([e["kind"] for e in result["data"]["events"]], ["created", "reserved"])

    def test_read_fails_when_database_missing(self):
        code, result = self.run_cli("status", "--project", "demo")
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertFalse(self.db.exists())

    def test_review_write_scope_denied(self):
        code, result = self.run_cli("create-task", "--project", "demo", "--id", "review",
                                    "--role", "review", "--prompt-file", str(self.prompt_file),
                                    "--write-scope", "repo:src")
        self.assertEqual(code, 2)
        self.assertIn("read-only", result["error"]["message"])

    def test_recover_reservations_without_sending(self):
        self.run_cli("create-task", "--project", "demo", "--id", "task-1", "--role", "implement",
                     "--prompt-file", str(self.prompt_file))
        self.run_cli("claim", "--project", "demo")
        code, result = self.run_cli("recover", "--project", "demo")
        self.assertEqual(code, 0)
        self.assertEqual(result["data"]["uncertain_dispatches"], 0)
        code, result = self.run_cli("task", "--id", "task-1")
        self.assertEqual(result["data"]["state"], "queued")

    def test_prompt_file_size_limit(self):
        self.prompt_file.write_bytes(b"x" * (1024 * 1024 + 1))
        code, result = self.run_cli("create-task", "--project", "demo", "--id", "task-1",
                                    "--role", "implement", "--prompt-file", str(self.prompt_file))
        self.assertEqual(code, 2)
        self.assertIn("1 MiB", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()