"""PR-04 bounded offline review/fix planning; no live model calls.

Review tasks have no write scopes and no dependency on FINISHED because the
implementer stays VERIFIED (with scopes held) until a separate approval.
Fix tasks inherit scopes and will remain blocked while the original holds them.
"""
from __future__ import annotations

import hashlib
import re
import time

from .evidence import EvidenceLedger
from .review_policy import ReviewLedger
from .store import Store, TaskSpec, TaskState

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class BoundedPlanner:
    def __init__(self, store: Store, evidence: EvidenceLedger,
                 reviews: ReviewLedger, *, max_fix_rounds: int = 2):
        if (store.path != evidence.store.path or store.path != reviews.store.path or
                not 1 <= max_fix_rounds <= 3):
            raise ValueError("invalid planner authority or round budget")
        self.store, self.evidence, self.reviews = store,evidence,reviews
        self.max_fix_rounds = max_fix_rounds
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orchestrator_fix_plans (
                    original_task_id TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    review_id TEXT NOT NULL UNIQUE,
                    fix_task_id TEXT NOT NULL UNIQUE,
                    planned_at REAL NOT NULL,
                    PRIMARY KEY(original_task_id,round)
                );
            """)

    def review_task(self, target_task_id: str, review_task_id: str) -> dict:
        if not isinstance(review_task_id,str) or not _ID.fullmatch(review_task_id):
            raise ValueError("invalid review task ID")
        evidence=self.evidence.assert_fresh(target_task_id)
        target=self.store.get(target_task_id)
        if target is None or target["role"]!="implement":
            raise ValueError("review target must be an implementation")
        # Do not set dependencies=(target_task_id,): the implementation is
        # VERIFIED but not FINISHED, awaiting review. This would deadlock.
        prompt=(f"Independently review implementation task {target_task_id} on immutable "
                f"head {evidence['head_sha']} and evidence {evidence['snapshot_sha256']}. "
                "Do not mutate repository or environment. Return findings with exact commit SHA.")
        created=self.store.create(TaskSpec(
            task_id=review_task_id,project_id=target["project_id"],role="review",
            prompt=prompt,review_of=target_task_id,
            baseline_sha=evidence["head_sha"],write_scopes=()))
        return {"task_id":review_task_id,"created":created,"role":"review",
                "write_scopes":[],"depends_on":[],"prompt":prompt,
                "needs_sealed_package":True,"remote_send_permitted":False}

    def propose_fix(self, root_task_id: str, fix_task_id: str,
                    review_id: str, prompt: str) -> dict:
        """Queue a bounded fix **proposal**, never release parent's write lock."""
        if (not isinstance(fix_task_id,str) or not _ID.fullmatch(fix_task_id) or
                not isinstance(prompt,str) or not prompt.strip() or len(prompt)>65536):
            raise ValueError("invalid fix task or prompt")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            original=db.execute("SELECT * FROM tasks WHERE task_id=?",(root_task_id,)).fetchone()
            review=db.execute("SELECT * FROM orchestrator_review_decisions WHERE review_id=?",
                              (review_id,)).fetchone()
            evidence=db.execute("SELECT * FROM orchestrator_verified_evidence WHERE task_id=?",
                                (root_task_id,)).fetchone()
            if (original is None or original["role"]!="implement" or
                    original["state"] != TaskState.VERIFIED.value or
                    review is None or review["target_task_id"]!=root_task_id or
                    review["verdict"]!="changes_requested" or evidence is None or
                    review["evidence_sha256"]!=evidence["snapshot_sha256"]):
                raise ValueError("fix requires matching verified target and rejected review")
            old=db.execute("SELECT * FROM orchestrator_fix_plans WHERE review_id=?",(review_id,)).fetchone()
            if old:
                task=db.execute("SELECT * FROM tasks WHERE task_id=?",(old["fix_task_id"],)).fetchone()
                if (old["fix_task_id"]!=fix_task_id or task is None or
                        task["prompt_sha"]!=hashlib.sha256(prompt.encode()).hexdigest()):
                    raise ValueError("conflicting idempotent fix request")
                return {"fix_task_id":fix_task_id,"round":old["round"],"created":False,
                        "blocked_until_parent_reconciled":True}
            prior=db.execute("SELECT COUNT(*) FROM orchestrator_fix_plans WHERE original_task_id=?",
                             (root_task_id,)).fetchone()[0]
            if prior>=self.max_fix_rounds:
                raise ValueError("bounded review/fix round budget exhausted")
            if db.execute("SELECT 1 FROM tasks WHERE task_id=?",(fix_task_id,)).fetchone():
                raise ValueError("fix task ID already exists")
            now=time.time()
            digest=hashlib.sha256(prompt.encode()).hexdigest()
            db.execute("""INSERT INTO tasks(task_id,project_id,role,prompt_sha,dependencies,
                write_scopes,baseline_sha,review_of,state,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (fix_task_id,original["project_id"],"implement",digest,"[]",
                 original["write_scopes"],evidence["head_sha"],None,TaskState.QUEUED.value,now))
            db.execute("INSERT INTO orchestrator_fix_plans VALUES(?,?,?,?,?)",
                       (root_task_id,prior+1,review_id,fix_task_id,now))
            self.store._event(db,fix_task_id,"fix.proposed",f"root={root_task_id};round={prior+1}")
            return {"fix_task_id":fix_task_id,"round":prior+1,"created":True,
                    "blocked_until_parent_reconciled":True,"remote_send_permitted":False}