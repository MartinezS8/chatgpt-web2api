"""Persist review-gate verdicts without performing merges or external writes.

Do not call Store.finalize_verified from a chat response. The historical
string-only finalization hook is NOT provider authentication. A future
production-only gate must connect this module to an authorized EvidenceReader
and remove or guard that legacy bypass.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .evidence import EvidenceReader, EvidenceVerdict, github_result_ref, verify_github_review
from .store import Store, TaskState


@dataclass(frozen=True)
class ReviewRequest:
    task_id: str
    repository_id: int
    pull_number: int
    expected_head_sha: str
    required_checks: tuple[str, ...]
    allowed_reviewers: frozenset[int] | None = None


class ReviewPolicy:
    def __init__(self, store: Store):
        self.store = store
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_review_verdicts (
                task_id TEXT NOT NULL,
                repository_id INTEGER NOT NULL,
                pull_number INTEGER NOT NULL,
                head_sha TEXT NOT NULL,
                reviewer_user_id INTEGER NOT NULL,
                observed_at REAL NOT NULL,
                PRIMARY KEY(task_id, repository_id, pull_number, head_sha)
            )""")

    def assess(self, request: ReviewRequest, reader: EvidenceReader) -> EvidenceVerdict:
        """Verify fresh provider snapshot; record a fact, DO NOT release locks.

        Reader trust and access control must be enforced by the future live
        adapter. Offline test readers prove policy logic only.
        """
        expected_ref = github_result_ref(
            request.repository_id, request.pull_number, request.expected_head_sha
        )
        # No need to request provider data when task isn't eligible.
        task = self.store.get(request.task_id)
        if task is None or task["state"] != TaskState.VERIFIED.value:
            return EvidenceVerdict(False, "task_not_verified", request.expected_head_sha)
        if task["evidence_ref"] != expected_ref:
            return EvidenceVerdict(False, "task_evidence_ref_mismatch", request.expected_head_sha)
        snapshot = reader.get_pull_request(request.repository_id, request.pull_number)
        verdict = verify_github_review(
            snapshot,
            repository_id=request.repository_id,
            pull_number=request.pull_number,
            expected_sha=request.expected_head_sha,
            required_checks=request.required_checks,
            allowed_reviewers=request.allowed_reviewers,
        )
        if not verdict.approved:
            return verdict
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT state,evidence_ref FROM tasks WHERE task_id=?", (request.task_id,)).fetchone()
            if (current is None or current["state"] != TaskState.VERIFIED.value
                    or current["evidence_ref"] != expected_ref):
                return EvidenceVerdict(False, "task_changed_during_review", request.expected_head_sha)
            db.execute("""INSERT INTO orchestrator_review_verdicts
                (task_id,repository_id,pull_number,head_sha,reviewer_user_id,observed_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(task_id,repository_id,pull_number,head_sha)
                DO UPDATE SET reviewer_user_id=excluded.reviewer_user_id,
                              observed_at=excluded.observed_at""",
                (request.task_id, request.repository_id, request.pull_number,
                 request.expected_head_sha, verdict.reviewer_user_id, time.time()))
            self.store._event(db, request.task_id, "review.evidence_validated", expected_ref)
        return verdict

    def recorded(self, task_id: str) -> list[dict]:
        with self.store._connect() as db:
            return [dict(x) for x in db.execute(
                "SELECT * FROM orchestrator_review_verdicts WHERE task_id=? ORDER BY observed_at",
                (task_id,))]