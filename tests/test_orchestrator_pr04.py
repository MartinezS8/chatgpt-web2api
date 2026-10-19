"""Offline end-to-end regressions for PR-04 callback/evidence/review/repair gates."""
from __future__ import annotations

import concurrent.futures
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.events import CallbackEnvelope, CallbackInbox
from chatgpt_web2api.orchestrator.evidence import (
    CheckProof, CommitProof, EvidenceGate, EvidenceSpec, PullProof,
)
from chatgpt_web2api.orchestrator.review_policy import ReviewObservation, ReviewPolicy
from chatgpt_web2api.orchestrator.planner import RepairPlanner

SHA_A = "a" * 40
SHA_B = "b" * 40
SECRET = b"a" * 48


class DummyOutbox:
    """Schema-compatible local stand-in; a real PR-02C integration test remains."""
    def __init__(self, store):
        self.store = store
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE orchestrator_dispatch_attempts (
                    attempt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL, conversation_id TEXT,
                    delivery_id TEXT, result_ref TEXT, updated_at REAL);
                CREATE TABLE orchestrator_delivery_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
                    task_id TEXT, attempt_id TEXT, kind TEXT, payload TEXT, at REAL);
            """)


class FakeReader:
    def __init__(self):
        self.sha = SHA_A
        self.checks_enabled = True
        self.state = "open"

    def commit(self, repo_id, sha):
        return CommitProof(repo_id, sha, sha in (SHA_A, SHA_B))

    def pull(self, repo_id, number):
        return PullProof(repo_id, number, self.sha, self.state)

    def checks(self, repo_id, sha):
        return [
            CheckProof(repo_id, sha, "build", "completed",
                       "success" if self.checks_enabled else "failure"),
            CheckProof(repo_id, sha, "security", "completed", "success"),
        ]


class PR04Offline(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / "tasks.sqlite")
        self.store.create(TaskSpec(
            "task", "p", "implement", "fix the problem",
            write_scopes=("github:repo/42",),
        ))
        self.outbox = DummyOutbox(self.store)
        self.inbox = CallbackInbox(self.store, self.outbox, SECRET)
        self.reader = FakeReader()
        self.gate = EvidenceGate(self.store, self.reader)
        self.policy = ReviewPolicy(self.store)
        self.planner = RepairPlanner(self.store, max_cycles=2)
        self.spec = EvidenceSpec(42, 3, SHA_A, ("build", "security"))
        with self.store._connect() as db:
            db.execute(
                "UPDATE tasks SET state='in_progress',claim_token='token',claim_version=3,"
                "slot=1,conversation_id='conv',delivery_id='msg' WHERE task_id='task'"
            )
            db.execute(
                "INSERT INTO orchestrator_dispatch_attempts VALUES (?,?,?,?,?,?,?)",
                ("attempt", "task", "accepted", "conv", "msg", None, 1.0),
            )

    def event(self, **changes):
        return replace(
            CallbackEnvelope("event1", "attempt", "conv", "msg", "completed",
                             self.spec.result_ref, 100),
            **changes,
        )

    def completed(self):
        event = self.event()
        self.assertTrue(self.inbox.apply(event, event.sign(SECRET)))

    def verified(self):
        self.completed()
        self.assertTrue(self.gate.verify("task", self.spec, claim_token="token"))

    def add_review(self, task_id="review1", worker_id="reviewer1",
                   decision="changes_requested"):
        with self.store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orchestrator_workers (
                    worker_id TEXT PRIMARY KEY, role TEXT, project_id TEXT);
                CREATE TABLE IF NOT EXISTS orchestrator_worker_assignments (
                    task_id TEXT PRIMARY KEY, worker_id TEXT, state TEXT);
            """)
        self.store.create(TaskSpec(
            task_id, "p", "review", f"inspect {task_id}", review_of="task"
        ))
        with self.store._connect() as db:
            db.execute("UPDATE tasks SET state='result_received' WHERE task_id=?", (task_id,))
            db.execute("INSERT INTO orchestrator_dispatch_attempts VALUES (?,?,?,?,?,?,?)",
                       ("attempt-" + task_id, task_id, "completed",
                        "review-conv-" + task_id, "review-msg-" + task_id,
                        "review_result", 1.0))
            db.execute("INSERT OR IGNORE INTO orchestrator_workers VALUES (?,?,?)",
                       (worker_id, "review", "p"))
            db.execute("INSERT INTO orchestrator_worker_assignments VALUES (?,?,?)",
                       (task_id, worker_id, "active"))
        return ReviewObservation(
            task_id, "task", worker_id, SHA_A, decision, "findings"
        )

    def test_progress_is_not_completion(self):
        event = CallbackEnvelope(
            "ev_progress", "attempt", "conv", "msg", "progress", progress=40
        )
        self.assertTrue(self.inbox.apply(event, event.sign(SECRET)))
        self.assertEqual(self.store.get("task")["state"], "in_progress")

    def test_completed_only_result_received(self):
        self.completed()
        self.assertEqual(self.store.get("task")["state"], "result_received")
        self.assertFalse(self.policy.approved_for_release("task"))

    def test_duplicate_event_is_idempotent(self):
        self.completed()
        event = self.event()
        self.assertFalse(self.inbox.apply(event, event.sign(SECRET)))
        self.assertEqual(len(self.inbox.receipts("attempt")), 1)

    def test_same_event_id_different_payload_rejected(self):
        self.completed()
        event = self.event(progress=99)
        with self.assertRaisesRegex(ValueError, "collision"):
            self.inbox.apply(event, event.sign(SECRET))

    def test_invalid_signature_rejected(self):
        with self.assertRaises(PermissionError):
            self.inbox.apply(self.event(), "0" * 64)
        self.assertEqual(self.store.get("task")["state"], "in_progress")

    def test_wrong_conversation_rejected(self):
        event = self.event(conversation_id="wrong")
        with self.assertRaisesRegex(ValueError, "another remote turn"):
            self.inbox.apply(event, event.sign(SECRET))

    def test_unacknowledged_send_rejected(self):
        with self.store._connect() as db:
            db.execute("UPDATE orchestrator_dispatch_attempts SET status='intent'")
        event = self.event()
        with self.assertRaisesRegex(ValueError, "no acknowledged dispatch"):
            self.inbox.apply(event, event.sign(SECRET))

    def test_conflicting_second_completion_rejected(self):
        self.completed()
        event = self.event(event_id="event2", result_ref="wrong")
        with self.assertRaisesRegex(ValueError, "conflicting duplicate completion"):
            self.inbox.apply(event, event.sign(SECRET))

    def test_late_progress_rejected(self):
        self.completed()
        event = CallbackEnvelope(
            "later", "attempt", "conv", "msg", "progress", progress=60
        )
        with self.assertRaisesRegex(ValueError, "late progress"):
            self.inbox.apply(event, event.sign(SECRET))

    def test_parallel_duplicate_completion_is_atomic(self):
        event = self.event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            done = list(pool.map(lambda _: self.inbox.apply(event, event.sign(SECRET)), range(2)))
        self.assertEqual(sorted(done), [False, True])

    def test_evidence_requires_successful_ci(self):
        self.completed()
        self.reader.checks_enabled = False
        with self.assertRaisesRegex(ValueError, "checks"):
            self.gate.verify("task", self.spec, claim_token="token")

    def test_evidence_wrong_pr_head_rejected(self):
        self.completed()
        self.reader.sha = SHA_B
        with self.assertRaisesRegex(ValueError, "PR head"):
            self.gate.verify("task", self.spec, claim_token="token")

    def test_evidence_duplicate_check_names_fail_closed(self):
        self.completed()
        original = self.reader.checks
        self.reader.checks = lambda repo, sha: original(repo, sha) + [
            CheckProof(repo, sha, "build", "completed", "failure")
        ]
        with self.assertRaisesRegex(ValueError, "checks"):
            self.gate.verify("task", self.spec, claim_token="token")

    def test_evidence_wrong_task_result_reference(self):
        self.completed()
        with self.assertRaisesRegex(ValueError, "result reference"):
            self.gate.verify("task", replace(self.spec, pr_number=4), claim_token="token")

    def test_evidence_wrong_locked_repository(self):
        self.completed()
        with self.store._connect() as db:
            db.execute("UPDATE tasks SET write_scopes=? WHERE task_id=?",
                       ('["github:repo/777"]', "task"))
        with self.assertRaisesRegex(ValueError, "not in declared write scope"):
            self.gate.verify("task", self.spec, claim_token="token")

    def test_verified_head_movement_invalidates_proof(self):
        self.verified()
        self.assertEqual(self.store.get("task")["state"], "verified")
        self.assertTrue(self.gate.is_current("task"))
        self.reader.sha = SHA_B
        self.assertFalse(self.gate.is_current("task"))

    def test_readonly_review_records_no_auto_approval(self):
        self.verified()
        review = self.add_review(decision="approve")
        self.assertTrue(self.policy.record(review))
        self.assertFalse(self.policy.record(review))
        self.assertEqual(self.store.get("task")["state"], "verified")
        self.assertFalse(self.policy.approved_for_release("task"))
        self.assertEqual(
            self.policy.inspection("task")[0]["authorization"], "untrusted"
        )

    def test_review_requires_completed_attempt(self):
        self.verified()
        review = self.add_review()
        with self.store._connect() as db:
            db.execute("DELETE FROM orchestrator_dispatch_attempts WHERE task_id=?",
                       (review.review_task_id,))
        with self.assertRaisesRegex(ValueError, "correlated completion"):
            self.policy.record(review)

    def test_review_wrong_commit_rejected(self):
        self.verified()
        review = replace(self.add_review(), commit_sha=SHA_B)
        with self.assertRaisesRegex(ValueError, "wrong/unverified commit"):
            self.policy.record(review)

    def test_review_unassigned_worker_rejected(self):
        self.verified()
        review = self.add_review()
        with self.store._connect() as db:
            db.execute("UPDATE orchestrator_worker_assignments SET state='released'")
        with self.assertRaisesRegex(ValueError, "not been assigned"):
            self.policy.record(review)

    def test_review_observation_cannot_be_overwritten(self):
        self.verified()
        review = self.add_review()
        self.assertTrue(self.policy.record(review))
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.policy.record(replace(review, decision="approve"))

    def test_planner_needs_changes_requested(self):
        self.verified()
        review = self.add_review(decision="approve")
        self.policy.record(review)
        with self.assertRaisesRegex(ValueError, "changes_requested"):
            self.planner.propose(review.review_task_id, "fix")

    def test_planner_only_proposes_and_redacts_prompt(self):
        self.verified()
        review = self.add_review()
        self.policy.record(review)
        proposal = self.planner.propose(review.review_task_id, "Fix bug in parser")
        self.assertTrue(proposal["created"])
        self.assertEqual(proposal["state"], "proposed")
        self.assertNotIn("prompt", self.planner.list("task")[0])
        self.assertEqual(len(self.store.all("p")), 2)
        self.assertFalse(self.planner.propose(review.review_task_id, "Fix bug in parser")["created"])

    def test_bounded_repair_cycles(self):
        self.verified()
        for name in ("review1", "review2", "review3"):
            review = self.add_review(task_id=name, worker_id="worker" + name)
            self.policy.record(review)
        self.planner.propose("review1", "one")
        self.planner.propose("review2", "two")
        with self.assertRaisesRegex(ValueError, "budget exceeded"):
            self.planner.propose("review3", "three")

    def test_review_worker_must_be_read_only(self):
        self.verified()
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.store.create(TaskSpec(
                "bad", "p", "review", "x", review_of="task",
                write_scopes=("github:repo/42",),
            ))


if __name__ == "__main__":
    unittest.main()
