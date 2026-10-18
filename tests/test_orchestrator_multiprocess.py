"""Cross-process SQLite serialization regressions; spawn-safe on Windows."""
from __future__ import annotations

import concurrent.futures
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from chatgpt_web2api.orchestrator import Store, TaskSpec


def _claim_worker(parameters: tuple[str, str]) -> str | None:
    database, project_id = parameters
    task = Store(database).claim(project_id)
    return task["task_id"] if task else None


class MultiprocessReservations(unittest.TestCase):
    def test_cross_process_claims_respect_slot_limit(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "db.sqlite")
            store = Store(path)
            for i in range(15):
                store.create(TaskSpec(f"task{i:02}", "p", "implement", f"prompt{i}"))
            with concurrent.futures.ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context("spawn")) as pool:
                claims = list(pool.map(_claim_worker, [(path, "p")] * 14))
            reserved = [x for x in claims if x is not None]
            self.assertEqual(len(reserved), 5)
            self.assertEqual(len(set(reserved)), 5)
            self.assertEqual(len({x["slot"] for x in store.all("p") if x["slot"]}), 5)

    def test_cross_process_shared_db_resource_has_one_owner(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "db.sqlite")
            store = Store(path)
            for i in range(8):
                store.create(TaskSpec(f"task{i:02}", f"project{i}", "implement",
                                      f"prompt{i}", write_scopes=("db:prod",)))
            with concurrent.futures.ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context("spawn")) as pool:
                claims = list(pool.map(_claim_worker, [(path, f"project{i}") for i in range(8)]))
            self.assertEqual(len([x for x in claims if x is not None]), 1)


if __name__ == "__main__":
    unittest.main()
