"""Read-only Codex observer for durable task, delivery and review state.

Does not create or migrate tables, accept callbacks, invoke browser drivers,
expose prompt bodies, claim tokens, or authorize remote writes.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


class Observer:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError("controller database does not exist")

    def _read(self, query: str, params: tuple = (), *, limit: int = 100) -> list[dict]:
        """Only module-authored SELECT statements; no caller-provided SQL."""
        uri = self.path.as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5.0) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(query, (*params, limit)).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _count_or_error(value: int, maximum: int = 200) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
            raise ValueError("invalid page limit")
        return value

    def capabilities(self) -> dict:
        return {"mode": "read-only-observer", "live_transport": False,
                "remote_upload": False, "hosted_plugins": False,
                "model_or_effort_verification": False,
                "user_approval_actions": False, "browser_sessions": False,
                "methods": ["status", "events", "workers", "reviews", "proposals", "evidence", "callbacks"]}

    def status(self, project_id: str) -> dict:
        if not project_id:
            raise ValueError("project_id required")
        rows = self._read("SELECT state, COUNT(*) AS n FROM tasks WHERE project_id=? GROUP BY state ORDER BY state LIMIT ?",(project_id,),limit=20)
        return {"project_id": project_id, "states": {r["state"]:r["n"] for r in rows},
                "tasks": sum(r["n"] for r in rows)}

    def events(self, *, after: int = 0, limit: int = 100) -> dict:
        if not isinstance(after, int) or after < 0:
            raise ValueError("invalid cursor")
        limit = self._count_or_error(limit)
        rows = self._read("SELECT id,task_id,attempt_id,kind,at FROM orchestrator_delivery_events WHERE id>? ORDER BY id LIMIT ?",
                          (after,),limit=limit)
        return {"events": rows, "next_cursor": rows[-1]["id"] if rows else after}

    def callbacks(self, *, after: int = 0, limit: int = 100) -> dict:
        if not isinstance(after, int) or after < 0:
            raise ValueError("invalid cursor")
        limit = self._count_or_error(limit)
        rows=self._read("SELECT id,attempt_id,worker_id,sequence,kind,created_at FROM orchestrator_callback_inbox WHERE id>? ORDER BY id LIMIT ?",
                        (after,),limit=limit)
        return {"callbacks": rows, "next_cursor":rows[-1]["id"] if rows else after}

    def workers(self, account_id: str, limit: int = 5) -> dict:
        if not account_id:
            raise ValueError("account_id required")
        limit=self._count_or_error(limit, 5)
        rows=self._read("""SELECT worker_id,account_id,project_id,role,transport,enabled,last_heartbeat
            FROM orchestrator_workers WHERE account_id=? ORDER BY worker_id LIMIT ?""",(account_id,),limit=limit)
        return {"workers":rows, "account_id":account_id}

    def reviews(self, target_task_id: str, limit: int = 50) -> dict:
        limit=self._count_or_error(limit, 50)
        if not target_task_id: raise ValueError("target_task_id required")
        rows=self._read("""SELECT target_task_id,reviewer_task_id,head_sha,decision,assurance,created_at
            FROM orchestrator_review_decisions WHERE target_task_id=? ORDER BY created_at LIMIT ?""",
            (target_task_id,),limit=limit)
        return {"reviews":rows}

    def proposals(self, target_task_id: str, limit: int = 10) -> dict:
        limit=self._count_or_error(limit, 10)
        if not target_task_id: raise ValueError("target_task_id required")
        rows=self._read("""SELECT id,target_task_id,reviewer_task_id,cycle,head_sha,status,created_at
            FROM orchestrator_fix_proposals WHERE target_task_id=? ORDER BY id LIMIT ?""",
            (target_task_id,),limit=limit)
        return {"proposals":rows}

    def evidence(self, task_id: str) -> dict:
        if not task_id: raise ValueError("task_id required")
        rows=self._read("""SELECT task_id,repository_id,pr_number,head_sha,run_id,digest,assurance,recorded_at
            FROM orchestrator_evidence WHERE task_id=? LIMIT ?""",(task_id,),limit=1)
        return {"evidence": rows[0] if rows else None}

