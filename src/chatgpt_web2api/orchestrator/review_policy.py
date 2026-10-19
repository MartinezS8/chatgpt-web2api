"""Fail-closed, read-only independent review observation storage.

This stores *untrusted local review assertions*, not approvals. It NEVER calls
Store.finalize_verified or allows a merge. External identity and human approval
are intentionally deferred until a real, authenticated adapter exists.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal

from .store import Store

_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ReviewObservation:
    review_task_id: str
    target_task_id: str
    reviewer_worker_id: str
    commit_sha: str
    decision: Literal["approve", "changes_requested"]
    feedback: str = ""


class ReviewPolicy:
    def __init__(self, store: Store):
        self.store = store
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_review_observations (
                review_task_id TEXT PRIMARY KEY,
                target_task_id TEXT NOT NULL,
                reviewer_worker_id TEXT NOT NULL,
                commit_sha TEXT NOT NULL,
                decision TEXT NOT NULL,
                feedback TEXT NOT NULL,
                authorization TEXT NOT NULL DEFAULT 'untrusted',
                observed_at REAL NOT NULL)""")

    def record(self, entry: ReviewObservation) -> bool:
        if entry.decision not in ("approve", "changes_requested"):
            raise ValueError("unsupported review decision")
        if not _SHA.fullmatch(entry.commit_sha) or len(entry.feedback) > 4000:
            raise ValueError("invalid review content")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            review = db.execute("SELECT * FROM tasks WHERE task_id=?", (entry.review_task_id,)).fetchone()
            target = db.execute("SELECT * FROM tasks WHERE task_id=?", (entry.target_task_id,)).fetchone()
            worker = db.execute("SELECT * FROM orchestrator_workers WHERE worker_id=?",
                                (entry.reviewer_worker_id,)).fetchone()
            if review is None or target is None or worker is None:
                raise ValueError("review, target or registered worker missing")
            if (review["role"] != "review" or review["review_of"] != entry.target_task_id
                    or review["project_id"] != target["project_id"]
                    or review["write_scopes"] != "[]"
                    or target["state"] != "verified"
                    or review["state"] != "result_received"):
                raise ValueError("review not independent read-only work on a verified target")
            if worker["role"] != "review" or worker["project_id"] != review["project_id"]:
                raise ValueError("reviewer worker role/project mismatch")
            assigned = db.execute("SELECT * FROM orchestrator_worker_assignments WHERE task_id=?",
                                  (entry.review_task_id,)).fetchone()
            if (assigned is None or assigned["worker_id"] != entry.reviewer_worker_id
                    or assigned["state"] != "active"):
                raise ValueError("review worker has not been assigned to review task")
            implementation = db.execute("SELECT * FROM orchestrator_worker_assignments WHERE task_id=?",
                                        (entry.target_task_id,)).fetchone()
            if implementation is not None and implementation["worker_id"] == entry.reviewer_worker_id:
                raise ValueError("worker cannot review its own implementation")
            # Observe only after a *correlated* review task delivery was
            # completed. This is STILL not an independent provider attestation.
            delivered = db.execute("""SELECT status FROM orchestrator_dispatch_attempts
                WHERE task_id=?""", (entry.review_task_id,)).fetchone()
            if delivered is None or delivered["status"] != "completed":
                raise ValueError("review task has no correlated completion")
            proof = db.execute("SELECT head_sha FROM orchestrator_verified_evidence WHERE task_id=?",
                               (entry.target_task_id,)).fetchone()
            if proof is None or proof["head_sha"] != entry.commit_sha:
                raise ValueError("review references wrong/unverified commit")
            previous=db.execute("SELECT * FROM orchestrator_review_observations WHERE review_task_id=?",
                                (entry.review_task_id,)).fetchone()
            if previous:
                if any(previous[k] != getattr(entry, k) for k in (
                        "target_task_id", "reviewer_worker_id", "commit_sha", "decision", "feedback")):
                    raise ValueError("conflicting review observation for same task")
                return False
            db.execute("""INSERT INTO orchestrator_review_observations
                (review_task_id,target_task_id,reviewer_worker_id,commit_sha,decision,feedback,observed_at)
                VALUES (?,?,?,?,?,?,?)""",
                (entry.review_task_id,entry.target_task_id,entry.reviewer_worker_id,
                 entry.commit_sha,entry.decision,entry.feedback,time.time()))
            self.store._event(db,entry.target_task_id,"review.observed_untrusted",entry.decision)
            return True

    def inspection(self, target_task_id: str) -> list[dict]:
        with self.store._connect() as db:
            return [dict(x) for x in db.execute(
                "SELECT * FROM orchestrator_review_observations WHERE target_task_id=? ORDER BY observed_at",
                (target_task_id,))]

    def approved_for_release(self, target_task_id: str) -> bool:
        """No externally authenticated reviewer or human consent yet: NEVER true."""
        return False
