"""Smoke tests for PR04 read-only CLI extension in isolation."""
from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from chatgpt_web2api.orchestrator.store import Store
from chatgpt_web2api.orchestrator.review_commands import (
    READ_COMMANDS, configure_review_commands, execute_review_command,
)


class ReadCommands(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.store = Store(Path(t.name) / "db.sqlite")

    def test_cli_parses_each_command(self):
        p = argparse.ArgumentParser()
        subs = p.add_subparsers(dest="command")
        configure_review_commands(subs)
        for cmd in READ_COMMANDS:
            param = "--attempt" if cmd == "callback-receipts" else "--task"
            parsed = p.parse_args((cmd, param, "dummy"))
            self.assertEqual(parsed.command, cmd)

    def test_uninitialized_read_is_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "not initialized"):
            execute_review_command(argparse.Namespace(command="evidence-snapshot", task="t"),self.store)

    def test_read_returns_no_approval_and_no_private_review_feedback(self):
        with self.store._connect() as db:
            db.execute("""CREATE TABLE orchestrator_review_observations (
                review_task_id TEXT, target_task_id TEXT, reviewer_worker_id TEXT,
                commit_sha TEXT, decision TEXT, authorization TEXT,
                observed_at REAL, feedback TEXT)""")
            db.execute("INSERT INTO orchestrator_review_observations VALUES (?,?,?,?,?,?,?,?)",
                       ("r1", "t1", "w2", "a" * 40, "approve", "untrusted",1.0, "PRIVATE"))
        result = execute_review_command(argparse.Namespace(command="review-observations",task="t1"),self.store)
        self.assertFalse(result["release_approved"])
        self.assertNotIn("PRIVATE",str(result))
        self.assertEqual(result["records"][0]["authorization"], "untrusted")


if __name__=="__main__":
    unittest.main()
