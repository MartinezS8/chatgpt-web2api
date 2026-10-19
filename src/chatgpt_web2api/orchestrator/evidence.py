"""PR-04: provider-bound immutable evidence. NO live Github or CI queries.

The supplied provider adapter is the *only* trust boundary. The production
adapter must authenticate to the provider and independently fetch PR head,
commit, CI run, conclusion and provenance. An absent adapter always denies.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Protocol

from .store import Store, TaskState

_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class EvidenceClaim:
    repository_id: int
    pr_number: int
    commit_sha: str
    ci_run_id: int

    def validate(self) -> None:
        if (type(self.repository_id) is not int or self.repository_id <= 0 or
                type(self.pr_number) is not int or self.pr_number <= 0 or
                type(self.ci_run_id) is not int or self.ci_run_id <= 0 or
                not isinstance(self.commit_sha, str) or not _SHA.fullmatch(self.commit_sha)):
            raise ValueError("malformed GitHub/CI evidence identity")


@dataclass(frozen=True)
class ProviderSnapshot:
    repository_id: int
    pr_number: int
    current_head_sha: str
    ci_run_id: int
    ci_commit_sha: str
    ci_conclusion: str
    observed_at: float


class ProviderEvidenceVerifier(Protocol):
    def inspect(self, claim: EvidenceClaim) -> ProviderSnapshot | None:
        """Fetch independently, using authenticated provider access. Never trust a worker claim."""


class DenyProviderEvidence:
    def inspect(self, claim: EvidenceClaim) -> None:
        return None


class EvidenceLedger:
    def __init__(self, store: Store, provider: ProviderEvidenceVerifier | None = None):
        self.store = store
        self.provider = provider or DenyProviderEvidence()
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orchestrator_verified_evidence (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                    attempt_id TEXT NOT NULL UNIQUE,
                    repository_id INTEGER NOT NULL,
                    pr_number INTEGER NOT NULL,
                    head_sha TEXT NOT NULL,
                    ci_run_id INTEGER NOT NULL,
                    snapshot_sha256 TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    verified_at REAL NOT NULL
                );
            """)

    def inspect_provider(self, claim: EvidenceClaim) -> ProviderSnapshot:
        claim.validate()
        snap = self.provider.inspect(claim)
        if not isinstance(snap, ProviderSnapshot):
            raise PermissionError("provider verification unavailable; refusing evidence")
        if (snap.repository_id != claim.repository_id or snap.pr_number != claim.pr_number or
                snap.ci_run_id != claim.ci_run_id or snap.current_head_sha != claim.commit_sha or
                snap.ci_commit_sha != claim.commit_sha or snap.ci_conclusion != "success" or
                type(snap.observed_at) not in (int, float) or snap.observed_at <= 0 or
                snap.observed_at > time.time() + 30 or
                snap.observed_at < time.time() - 120):
            raise ValueError("provider PR head / CI evidence mismatch or non-success")
        return snap

    def verify_completed(self, task_id: str, attempt_id: str, claim_token: str,
                         claim: EvidenceClaim) -> dict:
        """Atomically promote RESULT_RECEIVED to VERIFIED only after provider proof.

        Calls the provider before opening the database write transaction.
        Evidence is *point-in-time*, and MUST be refreshed before any later
        consequential action or merge. This step performs NO external writes.
        """
        if not all((task_id, attempt_id, claim_token)):
            raise ValueError("task, attempt and fenced claim required")
        snap = self.inspect_provider(claim)
        payload = {"repository_id": snap.repository_id,
                   "pr_number": snap.pr_number,
                   "current_head_sha": snap.current_head_sha,
                   "ci_run_id": snap.ci_run_id,
                   "ci_commit_sha": snap.ci_commit_sha,
                   "ci_conclusion": snap.ci_conclusion,
                   "observed_at": snap.observed_at}
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if (task is None or task["state"] not in (TaskState.RESULT_RECEIVED.value, TaskState.VERIFIED.value)
                    or task["claim_token"] != claim_token or not task["evidence_ref"]):
                raise ValueError("completed task missing or claim revoked")
            # Tie proof to a real, acknowledged, completed outbox attempt.
            attempt = db.execute("""SELECT * FROM orchestrator_dispatch_attempts
                WHERE attempt_id=? AND task_id=?""", (attempt_id, task_id)).fetchone()
            if (attempt is None or attempt["status"] != "completed" or
                    attempt["result_ref"] != task["evidence_ref"] or
                    not attempt["conversation_id"] or not attempt["delivery_id"]):
                raise ValueError("outbox attempt/result correlation not proven")
            previous = db.execute("SELECT * FROM orchestrator_verified_evidence WHERE task_id=?",
                                  (task_id,)).fetchone()
            if previous:
                if (previous["attempt_id"] != attempt_id or previous["snapshot_sha256"] != digest):
                    # Re-verifications may happen at a later timestamp. Immutable
                    # evidence can't be silently rewritten: use a new task/version.
                    raise ValueError("immutable evidence changed; create a new review/version")
                return dict(previous)
            if task["state"] != TaskState.RESULT_RECEIVED.value:
                raise ValueError("verified task without matching ledger row")
            now = time.time()
            db.execute("""INSERT INTO orchestrator_verified_evidence
                (task_id,attempt_id,repository_id,pr_number,head_sha,ci_run_id,
                 snapshot_sha256,snapshot_json,verified_at)
                 VALUES(?,?,?,?,?,?,?,?,?)""",
                 (task_id,attempt_id,claim.repository_id,claim.pr_number,claim.commit_sha,
                  claim.ci_run_id,digest,serialized,now))
            changed = db.execute("""UPDATE tasks SET state=?,claim_version=claim_version+1,
                lease_until=NULL,updated_at=? WHERE task_id=? AND state=? AND claim_token=?""",
                (TaskState.VERIFIED.value, now,task_id,TaskState.RESULT_RECEIVED.value,claim_token))
            if changed.rowcount != 1:
                raise RuntimeError("evidence promotion was concurrently fenced")
            self.store._event(db,task_id,"evidence.provider_verified",digest)
        return {"task_id":task_id,"attempt_id":attempt_id,"repository_id":claim.repository_id,
                "pr_number":claim.pr_number,"head_sha":claim.commit_sha,
                "ci_run_id":claim.ci_run_id,"snapshot_sha256":digest,"verified_at":now}

    def get(self, task_id: str) -> dict | None:
        with self.store._connect() as db:
            row = db.execute("SELECT * FROM orchestrator_verified_evidence WHERE task_id=?",
                             (task_id,)).fetchone()
            return dict(row) if row else None

    def assert_fresh(self, task_id: str) -> dict:
        """Re-fetch before a consequential downstream decision.

        Does not confer merge permissions; requires a separate human gate.
        """
        evidence = self.get(task_id)
        if evidence is None:
            raise PermissionError("no verified evidence")
        claim = EvidenceClaim(evidence["repository_id"],evidence["pr_number"],
                              evidence["head_sha"],evidence["ci_run_id"])
        self.inspect_provider(claim)
        task = self.store.get(task_id)
        if task is None or task["state"] != TaskState.VERIFIED.value:
            raise ValueError("review target changed state")
        return evidence