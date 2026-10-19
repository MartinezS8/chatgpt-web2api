"""Offline behavioral tests; no browser, ChatGPT or GitHub credentials needed."""
import concurrent.futures
import sqlite3
import time
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
        self.db.transition("a", TaskState.RESERVED, TaskState.DISPATCHING,
                           claim_token=self.db.get("a")["claim_token"])
        self.assertEqual(self.db.recover("sample", now=time.time() + 1000), 1)
        self.assertEqual(self.db.get("a")["state"], "unknown_delivery")
        self.assertIsNone(self.db.claim("sample"))

    def test_verified_evidence_completes(self):
        self.task("a")
        transport = StubTransport()
        control = Controller(self.db, transport, TestOnlyVerifier(), offline_test_mode=True)
        self.assertEqual(control.dispatch("sample", {"a": "prompt-a"}), "a")
        self.assertEqual(control.poll("sample"), ["a"])
        self.assertEqual(self.db.get("a")["state"], "verified")
        self.assertIsNotNone(self.db.get("a")["slot"])
        with self.assertRaisesRegex(PermissionError, "finalization is disabled"):
            self.db.finalize_verified("a", claim_token=self.db.get("a")["claim_token"],
                                      reviewer_ref="review:independent-commit", approved_by="operator")
        self.assertEqual(self.db.get("a")["state"], "verified")
        self.assertIsNotNone(self.db.get("a")["slot"])

    def test_legacy_controller_cannot_dispatch_or_poll_by_default(self):
        self.task("a")
        transport = StubTransport()
        controller = Controller(self.db, transport)
        with self.assertRaisesRegex(PermissionError, "Legacy Controller transport is disabled"):
            controller.dispatch("sample", {"a": "prompt-a"})
        with self.assertRaises(PermissionError):
            controller.poll("sample")
        self.assertEqual(transport.calls, [])
        self.assertEqual(self.db.get("a")["state"], "queued")
        self.assertEqual(self.db.events("a")[-1]["kind"], "created")

    def test_no_self_reported_success_by_default(self):
        self.task("a")
        control = Controller(self.db, StubTransport(), offline_test_mode=True)
        control.dispatch("sample", {"a": "prompt-a"})
        self.assertEqual(control.poll("sample"), [])
        self.assertEqual(self.db.get("a")["state"], "needs_human")

    def test_correlation_mismatch_does_not_accept(self):
        self.task("a")
        transport = StubTransport()
        control = Controller(self.db, transport, TestOnlyVerifier(), offline_test_mode=True)
        control.dispatch("sample", {"a": "prompt-a"})
        transport.mismatch = True
        control.poll("sample")
        self.assertEqual(self.db.get("a")["state"], "unknown_delivery")

    def test_failed_send_is_not_retried(self):
        self.task("a")
        transport = StubTransport()
        transport.fail_send = True
        control = Controller(self.db, transport, offline_test_mode=True)
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
        # A live pre-send reservation must not be force-requeued.
        self.assertEqual(self.db.recover("sample"), 0)
        self.assertEqual(self.db.get("a")["state"], "reserved")
        self.assertEqual(self.db.recover("sample", now=time.time() + 1000), 0)
        self.assertEqual(self.db.get("a")["state"], "queued")
        self.assertIsNone(self.db.get("a")["slot"])
        self.assertEqual(self.db.claim("sample")["task_id"], "a")

    def test_prompt_checksum_error_blocks_send(self):
        self.task("a")
        transport = StubTransport()
        control = Controller(self.db, transport, offline_test_mode=True)
        control.dispatch("sample", {"a": "different"})
        self.assertEqual(self.db.get("a")["state"], "needs_human")
        self.assertEqual(transport.calls, [])

    def test_needs_human_keeps_resource_quarantined(self):
        self.task("a", write_scopes=("repo:src/api",))
        self.task("b", write_scopes=("repo:src/api/route",))
        first = self.db.claim("sample")
        self.assertTrue(self.db.transition("a", TaskState.RESERVED, TaskState.NEEDS_HUMAN,
                                           claim_token=first["claim_token"], error="ambiguous"))
        self.assertIsNone(self.db.claim("sample"))

    def test_needs_human_cannot_finalize_without_review(self):
        self.task("a")
        token = self.db.claim("sample")["claim_token"]
        self.db.transition("a", TaskState.RESERVED, TaskState.NEEDS_HUMAN,
                           claim_token=token)
        with self.assertRaises(ValueError):
            self.db.transition("a", TaskState.NEEDS_HUMAN, TaskState.FINISHED,
                               claim_token=token)
        with self.assertRaises(PermissionError):
            self.db.finalize_verified("a", claim_token=token,
                                      reviewer_ref="review:arbitrary", approved_by="operator")

    def test_cross_project_global_resource_exclusion(self):
        self.db.create(TaskSpec("a", "project-1", "implement", "hello", write_scopes=("db:prod",)))
        self.db.create(TaskSpec("b", "project-2", "implement", "world", write_scopes=("db:PROD",)))
        self.assertIsNotNone(self.db.claim("project-1"))
        self.assertIsNone(self.db.claim("project-2"))

    def test_root_and_malformed_paths_fail_closed(self):
        for scope in ("repo:", "repo:../secret", "repo:/etc", "repo:src/*",
                      "repo:src//api", "repo:src/./api", "repo:src/../api", "repo:src\\api"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.db.create(TaskSpec(f"invalid-{scope}", "sample", "implement",
                                        "prompt", write_scopes=(scope,)))

    def test_case_and_prefix_overlap(self):
        self.task("a", write_scopes=("repo:src/api",))
        self.task("b", write_scopes=("repo:SRC/API/auth",))
        self.assertEqual(self.db.claim("sample")["task_id"], "a")
        self.assertIsNone(self.db.claim("sample"))

    def test_race_recover_revokes_reserved_before_send(self):
        class RecoverBeforeTransitionStore(Store):
            def transition(inner, task_id, expected, target, **kwargs):
                if expected == TaskState.RESERVED and target == TaskState.DISPATCHING:
                    inner.recover("sample", now=time.time() + 500)
                return super().transition(task_id, expected, target, **kwargs)
        db = RecoverBeforeTransitionStore(self.db.path)
        self.task("a")
        transport = StubTransport()
        result = Controller(db, transport, offline_test_mode=True).dispatch("sample", {"a": "prompt-a"})
        self.assertEqual(result, "a")
        self.assertEqual(transport.calls, [])
        self.assertEqual(db.get("a")["state"], "queued")

    def test_stale_token_cannot_advance_another_claim(self):
        self.task("a")
        old = self.db.claim("sample")
        self.db.recover("sample", now=time.time() + 500)
        current = self.db.claim("sample")
        self.assertNotEqual(old["claim_token"], current["claim_token"])
        self.assertFalse(self.db.transition("a", TaskState.RESERVED, TaskState.DISPATCHING,
                                            claim_token=old["claim_token"]))
        self.assertTrue(self.db.transition("a", TaskState.RESERVED, TaskState.DISPATCHING,
                                           claim_token=current["claim_token"]))

    def test_live_lease_not_recovered(self):
        self.task("a")
        token = self.db.claim("sample")["claim_token"]
        self.db.transition("a", TaskState.RESERVED, TaskState.DISPATCHING,
                           claim_token=token)
        self.assertEqual(self.db.recover("sample"), 0)
        self.assertEqual(self.db.get("a")["state"], "dispatching")

    def test_v3_legacy_migration_quarantines_active_rows(self):
        path = Path(self.temp.name) / "legacy.sqlite"
        with sqlite3.connect(path) as conn:
            conn.execute("""CREATE TABLE tasks(task_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,
                role TEXT NOT NULL,prompt_sha TEXT NOT NULL, dependencies TEXT NOT NULL,
                write_scopes TEXT NOT NULL,baseline_sha TEXT NOT NULL,review_of TEXT,
                state TEXT NOT NULL,slot INTEGER,conversation_id TEXT,delivery_id TEXT,
                evidence_ref TEXT,error TEXT,updated_at REAL NOT NULL)""")
            conn.execute("""INSERT INTO tasks(task_id,project_id,role,prompt_sha,dependencies,
                write_scopes,baseline_sha,state,slot,updated_at) VALUES
                ('legacy','old','implement','sha','[]','["repo:src"]','','reserved',1,0)""")
        upgraded = Store(path)
        self.assertEqual(upgraded.get("legacy")["state"], "needs_human")
        self.assertIsNone(upgraded.claim("old"))

    def test_verified_must_not_release_resource_until_approval(self):
        self.task("a", write_scopes=("repo:src/api",))
        self.task("b", write_scopes=("repo:src/api",))
        control = Controller(self.db, StubTransport(), TestOnlyVerifier(), offline_test_mode=True)
        control.dispatch("sample", {"a": "prompt-a"})
        self.assertEqual(control.poll("sample"), ["a"])
        self.assertIsNone(self.db.claim("sample"))
        token = self.db.get("a")["claim_token"]
        for reviewer, operator in (("", "operator"), ("review:commit", "operator"),
                                   ("review:commit", "root")):
            with self.assertRaises(PermissionError):
                self.db.finalize_verified("a", claim_token=token,
                                          reviewer_ref=reviewer, approved_by=operator)
        self.assertEqual(self.db.get("a")["state"], "verified")
        self.assertIsNone(self.db.claim("sample"))  # unresolved write lock stays held

    def test_reserved_lease_expiration_prevents_send_intent(self):
        self.task("a")
        claim = self.db.claim("sample")
        with self.db._connect() as connection:
            connection.execute("UPDATE tasks SET lease_until=? WHERE task_id=?",
                               (time.time() - 1, "a"))
        self.assertFalse(self.db.transition("a", TaskState.RESERVED,
                         TaskState.DISPATCHING, claim_token=claim["claim_token"]))

    def test_reviewer_cannot_write(self):
        with self.assertRaises(ValueError):
            self.db.create(TaskSpec("review", "sample", "review", "check", write_scopes=("repo:src",)))


if __name__ == "__main__":
    unittest.main()
