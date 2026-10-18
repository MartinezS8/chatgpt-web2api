"""Offline behavioral tests; no browser, ChatGPT or GitHub credentials needed."""
import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from chatgpt_web2api.orchestrator import Controller, Store, TaskSpec, TaskState
from chatgpt_web2api.orchestrator.controller import DeliveryAck, TransportResult


class StubTransport:
    def __init__(self):
        self.calls = []
        self.fail_send = False
        self.mismatch = False
    def send(self, task, prompt):
        self.calls.append(task["task_id"])
        if self.fail_send:
            raise TimeoutError("unknown if delivered")
        return DeliveryAck(f"conversation-{task['task_id']}", f"delivery-{task['task_id']}")
    def poll(self, task):
        return TransportResult("completed", "wrong" if self.mismatch else task["conversation_id"],
                               task["delivery_id"], "sha:0123456789abcdef")


class TestOnlyVerifier:
    def verify(self, task, result):
        return result.evidence_ref == "sha:0123456789abcdef"


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Store(Path(self.temp.name) / "tasks.sqlite")

    def task(self, key, **kw):
        self.db.create(TaskSpec(key, "sample", "implement", f"prompt-{key}", **kw))

    def test_idempotent_task_creation_and_collision(self):
        self.task("a")
        self.assertFalse(self.db.create(TaskSpec("a", "sample", "implement", "prompt-a")))
        with self.assertRaises(ValueError):
            self.db.create(TaskSpec("a", "sample", "implement", "different"))

    def test_dependency_dag_blocks_until_completion(self):
        self.task("a")
        self.task("b", dependencies=("a",))
        self.assertEqual(self.db.claim("sample")["task_id"], "a")
        self.assertIsNone(self.db.claim("sample"))

    def test_write_scopes_and_distinct_slots(self):
        self.task("a", write_scopes=("repo:src/api",))
        self.task("b", write_scopes=("repo:src/api/auth",))
        self.task("c", write_scopes=("repo:src/ui",))
        a = self.db.claim("sample")
        c = self.db.claim("sample")
        self.assertEqual([a["task_id"], c["task_id"]], ["a", "c"])
        self.assertNotEqual(a["slot"], c["slot"])
        self.assertIsNone(self.db.claim("sample"))

    def test_five_slot_limit(self):
        for n in range(7): self.task(f"t{n}")
        claims = [self.db.claim("sample") for _ in range(7)]
        self.assertEqual(sum(item is not None for item in claims), 5)
        self.assertIsNone(self.db.claim("sample"))

    def test_concurrent_claims_no_double_reservation(self):
        for n in range(12): self.task(f"t{n}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(lambda _: self.db.claim("sample"), range(12)))
        actual = [r for r in results if r]
        self.assertEqual(len(actual), 5)
        self.assertEqual(len({r["task_id"] for r in actual}), 5)
        self.assertEqual(len({r["slot"] for r in actual}), 5)

    def test_crash_unknown_delivery_never_auto_retry(self):
        self.task("a")
        self.db.claim("sample")
        self.db.transition("a", TaskState.RESERVED, TaskState.DISPATCHING)
        self.assertEqual(self.db.recover("sample"), 1)
        self.assertEqual(self.db.get("a")["state"], "unknown_delivery")
        self.assertIsNone(self.db.claim("sample"))

    def test_verified_evidence_completes(self):
        self.task("a")
        transport = StubTransport()
        control = Controller(self.db, transport, TestOnlyVerifier())
        self.assertEqual(control.dispatch("sample", {"a": "prompt-a"}), "a")
        self.assertEqual(control.poll("sample"), ["a"])
        self.assertEqual(self.db.get("a")["state"], "finished")
        self.assertIsNone(self.db.get("a")["slot"])

    def test_no_self_reported_success_by_default(self):
        self.task("a")
        control = Controller(self.db, StubTransport())
        control.dispatch("sample", {"a": "prompt-a"})
        self.assertEqual(control.poll("sample"), [])
        self.assertEqual(self.db.get("a")["state"], "needs_human")

    def test_correlation_mismatch_does_not_accept(self):
        self.task("a")
        transport = StubTransport()
        control = Controller(self.db, transport, TestOnlyVerifier())
        control.dispatch("sample", {"a": "prompt-a"})
        transport.mismatch = True
        control.poll("sample")
        self.assertEqual(self.db.get("a")["state"], "unknown_delivery")

    def test_failed_send_is_not_retried(self):
        self.task("a")
        transport = StubTransport()
        transport.fail_send = True
        control = Controller(self.db, transport)
        control.dispatch("sample", {"a": "prompt-a"})
        self.assertEqual(self.db.get("a")["state"], "unknown_delivery")
        self.assertEqual(transport.calls, ["a"])
        self.assertIsNone(control.dispatch("sample", {"a":"prompt-a"}))

    def test_create_rejects_same_id_changed_scope(self):
        self.task("a", write_scopes=("repo:src/a",))
        with self.assertRaises(ValueError):
            self.db.create(TaskSpec("a", "sample", "implement", "prompt-a",
                                    write_scopes=("repo:src/b",)))

    def test_pre_send_reservation_is_requeued_on_recovery(self):
        self.task("a")
        self.db.claim("sample")
        self.assertEqual(self.db.recover("sample"), 0)
        self.assertEqual(self.db.get("a")["state"], "queued")
        self.assertIsNone(self.db.get("a")["slot"])
        self.assertEqual(self.db.claim("sample")["task_id"], "a")

    def test_prompt_checksum_error_blocks_send(self):
        self.task("a")
        transport = StubTransport()
        control = Controller(self.db, transport)
        control.dispatch("sample", {"a": "different"})
        self.assertEqual(self.db.get("a")["state"], "needs_human")
        self.assertEqual(transport.calls, [])

    def test_reviewer_cannot_write(self):
        with self.assertRaises(ValueError):
            self.db.create(TaskSpec("review", "sample", "review", "check", write_scopes=("repo:src",)))


if __name__ == "__main__":
    unittest.main()