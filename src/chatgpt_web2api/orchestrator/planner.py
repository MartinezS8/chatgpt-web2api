"""Bounded local replanning proposals; no automatic remote sends or task claims."""
from __future__ import annotations

import hashlib
import time

from .store import Store


class Planner:
    def __init__(self, store: Store):
        self.store = store
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_fix_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_task_id TEXT NOT NULL,
                reviewer_task_id TEXT NOT NULL,
                cycle INTEGER NOT NULL,
                head_sha TEXT NOT NULL,
                prompt_sha256 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                created_at REAL NOT NULL,
                UNIQUE(target_task_id,cycle)
            )""")

    def propose_mock_fix(self, *, target_task_id: str, reviewer_task_id: str,
                         head_sha: str, proposed_prompt: str, max_cycles: int = 3) -> dict:
        if not 1 <= max_cycles <= 5 or not proposed_prompt.strip() or len(proposed_prompt.encode()) > 1024 * 1024:
            raise ValueError("invalid bounded fix proposal")
        digest = hashlib.sha256(proposed_prompt.encode()).hexdigest()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            decision = db.execute("""SELECT * FROM orchestrator_review_decisions
                WHERE target_task_id=? AND reviewer_task_id=?""", (target_task_id, reviewer_task_id)).fetchone()
            if not decision or decision["decision"] != "changes_requested" or decision["head_sha"] != head_sha:
                raise ValueError("fix requires sealed changes-requested review of exact head")
            if decision["assurance"] != "offline_mock_only":
                raise ValueError("unexpected review assurance")
            current = db.execute("SELECT * FROM orchestrator_fix_proposals WHERE target_task_id=? ORDER BY cycle DESC LIMIT 1",
                                 (target_task_id,)).fetchone()
            if current and current["reviewer_task_id"] == reviewer_task_id:
                if current["prompt_sha256"] != digest or current["head_sha"] != head_sha:
                    raise ValueError("existing proposal conflicts with new prompt/head")
                return {"id": current["id"], "cycle": current["cycle"], "created": False,
                        "status": "proposed", "may_dispatch": False}
            cycle = 1 if current is None else current["cycle"] + 1
            if cycle > max_cycles:
                raise ValueError("fix/review loop budget exhausted")
            db.execute("""INSERT INTO orchestrator_fix_proposals
                (target_task_id,reviewer_task_id,cycle,head_sha,prompt_sha256,created_at)
                VALUES (?,?,?,?,?,?)""", (target_task_id, reviewer_task_id, cycle,
                                               head_sha, digest, time.time()))
            ident = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            return {"id": ident, "cycle": cycle, "created": True,
                    "status": "proposed", "may_dispatch": False}

    def list(self, target_task_id: str) -> list[dict]:
        with self.store._connect() as db:
            return [dict(x) for x in db.execute("""SELECT * FROM orchestrator_fix_proposals
                WHERE target_task_id=? ORDER BY cycle""", (target_task_id,))]

