"""Offline independent-review checks. Never unlock writes, merges or production actions."""
from __future__ import annotations

import hashlib
import json
import time

from .store import Store, TaskState


class ReviewLedger:
    def __init__(self, store: Store):
        self.store = store
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_review_decisions (
                target_task_id TEXT NOT NULL, reviewer_task_id TEXT NOT NULL,
                head_sha TEXT NOT NULL, evidence_digest TEXT NOT NULL,
                implement_worker_id TEXT NOT NULL, reviewer_worker_id TEXT NOT NULL,
                decision TEXT NOT NULL, decision_digest TEXT NOT NULL,
                assurance TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY(target_task_id, reviewer_task_id)
            )""")

    def record_mock(self, *, target_task_id: str, reviewer_task_id: str,
                    decision: str, head_sha: str) -> dict:
        if decision not in ("approved", "changes_requested"):
            raise ValueError("review decision must be approved or changes_requested")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            implementation = db.execute("SELECT * FROM tasks WHERE task_id=?", (target_task_id,)).fetchone()
            review = db.execute("SELECT * FROM tasks WHERE task_id=?", (reviewer_task_id,)).fetchone()
            evidence = db.execute("SELECT * FROM orchestrator_evidence WHERE task_id=?", (target_task_id,)).fetchone()
            if not implementation or not review or not evidence:
                raise ValueError("implementation, review and evidence must all exist")
            if implementation["role"] != "implement" or implementation["state"] != TaskState.VERIFIED.value:
                raise ValueError("implementation must be verified before review")
            if (review["role"] != "review" or review["review_of"] != target_task_id
                    or review["project_id"] != implementation["project_id"]):
                raise ValueError("review task must be independent and in the same project")
            if json.loads(review["write_scopes"]):
                raise ValueError("review task must be read-only")
            if review["state"] != TaskState.VERIFIED.value:
                raise ValueError("review task has not produced verified results")
            if head_sha != evidence["head_sha"] or evidence["assurance"] != "offline_mock_only":
                raise ValueError("review head or evidence assurance mismatch")
            impl_w = db.execute("SELECT worker_id FROM orchestrator_worker_assignments WHERE task_id=? AND state='active'", (target_task_id,)).fetchone()
            review_w = db.execute("SELECT worker_id FROM orchestrator_worker_assignments WHERE task_id=? AND state='active'", (reviewer_task_id,)).fetchone()
            if not impl_w or not review_w or impl_w["worker_id"] == review_w["worker_id"]:
                raise ValueError("review must be assigned to a different live worker")
            w = db.execute("""SELECT account_id,project_id,role,transport,
                enabled,session_key FROM orchestrator_workers WHERE worker_id=?""",
                           (review_w["worker_id"],)).fetchone()
            implementer = db.execute("""SELECT account_id,project_id,role,transport,
                enabled,session_key FROM orchestrator_workers WHERE worker_id=?""",
                                     (impl_w["worker_id"],)).fetchone()
            if not w or not implementer:
                raise ValueError("reviewer/implementer identity, account, project or session mismatch")
            if not w["enabled"] or not implementer["enabled"]:
                raise ValueError("review requires an enabled mock review worker and implementer")
            if (w["role"] != "review" or implementer["role"] != "implement"
                    or w["transport"] != "mock" or implementer["transport"] != "mock"
                    or w["account_id"] != implementer["account_id"]
                    or w["project_id"] != implementation["project_id"]
                    or implementer["project_id"] != implementation["project_id"]
                    or w["session_key"] == implementer["session_key"]):
                raise ValueError("reviewer/implementer identity, account, project or session mismatch")
            payload = {"target_task_id": target_task_id, "reviewer_task_id": reviewer_task_id,
                       "head_sha": head_sha, "evidence_digest": evidence["digest"],
                       "implement_worker_id": impl_w["worker_id"], "reviewer_worker_id": review_w["worker_id"],
                       "decision": decision, "assurance": "offline_mock_only"}
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            old = db.execute("SELECT decision_digest FROM orchestrator_review_decisions WHERE target_task_id=? AND reviewer_task_id=?",
                             (target_task_id, reviewer_task_id)).fetchone()
            if old:
                if old["decision_digest"] != digest:
                    raise ValueError("review decision already sealed and cannot be revised")
                return {**payload, "digest": digest, "new": False}
            db.execute("""INSERT INTO orchestrator_review_decisions VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (target_task_id, reviewer_task_id, head_sha, evidence["digest"],
                        impl_w["worker_id"], review_w["worker_id"], decision, digest,
                        "offline_mock_only", time.time()))
            return {**payload, "digest": digest, "new": True}

    def get(self, target_task_id: str, reviewer_task_id: str) -> dict | None:
        with self.store._connect() as db:
            row = db.execute("SELECT * FROM orchestrator_review_decisions WHERE target_task_id=? AND reviewer_task_id=?",
                             (target_task_id, reviewer_task_id)).fetchone()
            return dict(row) if row else None

    def production_approval_granted(self, target_task_id: str) -> bool:
        """Mock approval cannot authorize production mutation or finalize()."""
        return False

