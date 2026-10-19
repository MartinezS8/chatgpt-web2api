"""PR-04 independent mock-review decisions bound to verified evidence SHA.

Recorded decisions are NOT authorization to merge or finalize tasks. A future
provider-authenticated review adapter plus explicit human approval is required.
"""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from typing import Protocol

from .evidence import EvidenceLedger
from .store import Store, TaskState

_REF = re.compile(r"^[A-Za-z0-9_.:/#-]{3,256}$")


@dataclass(frozen=True)
class ReviewReceipt:
    target_task_id: str
    review_task_id: str
    reviewer_worker_id: str
    evidence_sha256: str
    verdict: str
    review_ref: str


class ReviewProofVerifier(Protocol):
    def attest(self, receipt: ReviewReceipt) -> bool:
        """Independently establish provenance of the review; no self report."""


class DenyReviews:
    def attest(self, receipt: ReviewReceipt) -> bool:
        return False


class ReviewLedger:
    def __init__(self, store: Store, evidence: EvidenceLedger,
                 proof: ReviewProofVerifier | None = None):
        if store.path != evidence.store.path:
            raise ValueError("review/evidence must share database")
        self.store = store
        self.evidence = evidence
        self.proof = proof or DenyReviews()
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orchestrator_review_decisions (
                    review_id TEXT PRIMARY KEY,
                    review_task_id TEXT NOT NULL UNIQUE,
                    target_task_id TEXT NOT NULL,
                    reviewer_worker_id TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    verdict TEXT NOT NULL CHECK (verdict IN ('approved','changes_requested')),
                    review_ref TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
            """)

    def record(self, receipt: ReviewReceipt) -> dict:
        if (receipt.verdict not in ("approved","changes_requested") or
                not receipt.review_ref or not _REF.fullmatch(receipt.review_ref) or
                receipt.review_task_id == receipt.target_task_id):
            raise ValueError("invalid review decision")
        if not self.proof.attest(receipt):
            raise PermissionError("independent review provenance not verified")
        # Review decisions are recorded against one immutable verified evidence
        # snapshot. This point-in-time provider call is required even for an
        # approved review. It does NOT grant any external write permission.
        target_evidence = self.evidence.assert_fresh(receipt.target_task_id)
        if receipt.evidence_sha256 != target_evidence["snapshot_sha256"]:
            raise ValueError("review bound to outdated evidence")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            target = db.execute("SELECT * FROM tasks WHERE task_id=?",(receipt.target_task_id,)).fetchone()
            review = db.execute("SELECT * FROM tasks WHERE task_id=?",(receipt.review_task_id,)).fetchone()
            if (target is None or target["state"]!=TaskState.VERIFIED.value or
                    review is None or review["role"]!="review" or
                    review["review_of"]!=receipt.target_task_id or
                    review["project_id"]!=target["project_id"] or
                    review["state"]!=TaskState.VERIFIED.value or
                    review["write_scopes"] not in ("[]", "()")):
                raise ValueError("review task is not a distinct verified read-only review")
            ledger = db.execute("SELECT snapshot_sha256 FROM orchestrator_verified_evidence WHERE task_id=?",
                                (receipt.target_task_id,)).fetchone()
            if ledger is None or ledger["snapshot_sha256"]!=receipt.evidence_sha256:
                raise ValueError("target provider evidence changed")
            worker = db.execute("SELECT * FROM orchestrator_workers WHERE worker_id=?",
                                (receipt.reviewer_worker_id,)).fetchone()
            if (worker is None or worker["role"]!="review" or
                    worker["project_id"]!=target["project_id"] or not worker["enabled"]):
                raise ValueError("reviewer identity is not a registered review worker")
            bound = db.execute("""SELECT a.worker_id FROM orchestrator_worker_assignments a
                WHERE a.task_id=?""",(receipt.review_task_id,)).fetchone()
            producer = db.execute("""SELECT a.worker_id FROM orchestrator_worker_assignments a
                WHERE a.task_id=?""",(receipt.target_task_id,)).fetchone()
            producer_worker = (db.execute("SELECT * FROM orchestrator_workers WHERE worker_id=?",
                                          (producer["worker_id"],)).fetchone() if producer else None)
            if (bound is None or bound["worker_id"]!=receipt.reviewer_worker_id or
                    producer is None or producer_worker is None or
                    producer_worker["role"] != "implement" or
                    producer_worker["account_id"] != worker["account_id"] or
                    producer_worker["session_key"] == worker["session_key"] or
                    producer["worker_id"]==receipt.reviewer_worker_id):
                raise ValueError("reviewer was not assigned independently of implementer")
            prior = db.execute("SELECT * FROM orchestrator_review_decisions WHERE review_task_id=?",
                               (receipt.review_task_id,)).fetchone()
            if prior:
                if (prior["target_task_id"],prior["reviewer_worker_id"],prior["evidence_sha256"],
                    prior["verdict"],prior["review_ref"]) != (receipt.target_task_id,
                    receipt.reviewer_worker_id,receipt.evidence_sha256,receipt.verdict,receipt.review_ref):
                    raise ValueError("immutable review decision conflict")
                return {**dict(prior),"created":False,"authorizes_merge":False}
            review_id = secrets.token_hex(16)
            db.execute("""INSERT INTO orchestrator_review_decisions
               VALUES(?,?,?,?,?,?,?,?)""",(review_id,receipt.review_task_id,
               receipt.target_task_id,receipt.reviewer_worker_id,receipt.evidence_sha256,
               receipt.verdict,receipt.review_ref,time.time()))
            self.store._event(db,receipt.target_task_id,"review.recorded",review_id)
            return {"review_id":review_id,"review_task_id":receipt.review_task_id,
                    "target_task_id":receipt.target_task_id,"verdict":receipt.verdict,
                    "evidence_sha256":receipt.evidence_sha256,"created":True,
                    "authorizes_merge":False}

    def latest(self, target_task_id: str) -> dict | None:
        with self.store._connect() as db:
            row = db.execute("""SELECT * FROM orchestrator_review_decisions
                WHERE target_task_id=? ORDER BY created_at DESC,review_id DESC LIMIT 1""",
                (target_task_id,)).fetchone()
            return dict(row) if row else None