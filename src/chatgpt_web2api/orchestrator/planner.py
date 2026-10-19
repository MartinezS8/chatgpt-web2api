"""Bounded local fix proposals (no auto scheduling or remote code changes)."""
from __future__ import annotations

import hashlib
import time

from .store import Store


class RepairPlanner:
    def __init__(self, store: Store, max_cycles: int = 2):
        if not 1 <= max_cycles <= 5:
            raise ValueError("invalid repair cycle limit")
        self.store, self.max_cycles = store, max_cycles
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_repair_proposals (
                proposal_id TEXT PRIMARY KEY, target_task_id TEXT NOT NULL,
                review_task_id TEXT NOT NULL UNIQUE,
                iteration INTEGER NOT NULL, source_head_sha TEXT NOT NULL,
                prompt TEXT NOT NULL, prompt_sha256 TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state='proposed'),
                created_at REAL NOT NULL,
                UNIQUE(target_task_id,iteration))""")

    def propose(self, review_task_id: str, prompt: str) -> dict:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 32768:
            raise ValueError("repair prompt must be nonempty and <=32 KiB")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            obs=db.execute("SELECT * FROM orchestrator_review_observations WHERE review_task_id=?",
                           (review_task_id,)).fetchone()
            if obs is None or obs["decision"] != "changes_requested":
                raise ValueError("cannot plan fix without recorded changes_requested review")
            task=db.execute("SELECT * FROM tasks WHERE task_id=?", (obs["target_task_id"],)).fetchone()
            if task is None or task["state"] != "verified":
                raise ValueError("target is not in reviewed verified state")
            verified=db.execute("SELECT head_sha FROM orchestrator_verified_evidence WHERE task_id=?",
                                (obs["target_task_id"],)).fetchone()
            if verified is None or verified["head_sha"] != obs["commit_sha"]:
                raise ValueError("review is stale relative to evidence")
            previous=db.execute("SELECT * FROM orchestrator_repair_proposals WHERE review_task_id=?",
                                (review_task_id,)).fetchone()
            if previous:
                if previous["prompt"] != prompt:
                    raise ValueError("cannot overwrite immutable repair plan")
                return {"proposal_id": previous["proposal_id"],
                        "target_task_id": previous["target_task_id"],
                        "iteration": previous["iteration"],
                        "source_head_sha": previous["source_head_sha"],
                        "state": previous["state"], "created": False}
            count=db.execute("SELECT COUNT(*) FROM orchestrator_repair_proposals WHERE target_task_id=?",
                             (obs["target_task_id"],)).fetchone()[0]
            if count >= self.max_cycles:
                raise ValueError("repair budget exceeded; manual intervention required")
            ident=hashlib.sha256((review_task_id+":"+obs["commit_sha"]).encode()).hexdigest()[:24]
            digest=hashlib.sha256(prompt.encode()).hexdigest()
            now=time.time()
            db.execute("""INSERT INTO orchestrator_repair_proposals
                (proposal_id,target_task_id,review_task_id,iteration,source_head_sha,
                 prompt,prompt_sha256,state,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (ident,obs["target_task_id"],review_task_id,count+1,obs["commit_sha"],
                 prompt,digest,"proposed",now))
            self.store._event(db,obs["target_task_id"],"repair.proposed",ident)
            return {"proposal_id":ident,"target_task_id":obs["target_task_id"],
                    "iteration":count+1,"source_head_sha":obs["commit_sha"],
                    "state":"proposed","created":True}

    def list(self, target_task_id: str) -> list[dict]:
        """Redact prompts; only trusted controller may retrieve full proposal content."""
        with self.store._connect() as db:
            return [dict(x) for x in db.execute(
                "SELECT proposal_id,target_task_id,review_task_id,iteration,source_head_sha,"
                "prompt_sha256,state,created_at FROM orchestrator_repair_proposals "
                "WHERE target_task_id=? ORDER BY iteration",(target_task_id,))]
