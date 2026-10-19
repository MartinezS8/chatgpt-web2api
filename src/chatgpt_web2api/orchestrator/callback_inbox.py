"""PR-04 offline callback inbox. No network endpoint, browser, or callback authentication.

MCP progress notifications are advisory. A completion is accepted only through
DispatchOutbox's acknowledged attempt/conversation/message correlation. An
authorized transport MUST provide authenticated provenance before enabling this.
"""
from __future__ import annotations

import hashlib
import json
import time

from .store import Store

_ALLOWED = frozenset({"progress", "heartbeat"})


class CallbackInbox:
    def __init__(self, store: Store, outbox):
        if store.path != outbox.store.path:
            raise ValueError("callback and outbox must use the same SQLite authority")
        self.store, self.outbox = store, outbox
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_callback_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(attempt_id, sequence)
            )""")

    def _check_bound(self, db, attempt_id, worker_id, conversation_id, delivery_id, *, allow_completed=False):
        rec = db.execute("""SELECT a.task_id,a.status,a.conversation_id,a.delivery_id,
            w.worker_id,w.transport FROM orchestrator_dispatch_attempts a
            JOIN orchestrator_worker_assignments wa ON wa.task_id=a.task_id AND wa.state='active'
            JOIN orchestrator_workers w ON w.worker_id=wa.worker_id
            WHERE a.attempt_id=?""", (attempt_id,)).fetchone()
        if (rec is None or rec["worker_id"] != worker_id or rec["transport"] != "mock"
                or rec["conversation_id"] != conversation_id or rec["delivery_id"] != delivery_id
                or (rec["status"] != "accepted" and not (allow_completed and rec["status"] == "completed"))):
            raise ValueError("callback lacks an acknowledged, mock-only worker binding")
        return rec

    def progress(self, *, attempt_id: str, worker_id: str, conversation_id: str,
                 delivery_id: str, sequence: int, kind: str, message: str) -> bool:
        """Persist advisory telemetry. Never transitions a task to completed."""
        if kind not in _ALLOWED or not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ValueError("invalid advisory callback")
        if not isinstance(message, str) or len(message.encode("utf-8")) > 2048:
            raise ValueError("callback message too long")
        digest = hashlib.sha256(json.dumps([kind, message], ensure_ascii=False).encode()).hexdigest()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_bound(db, attempt_id, worker_id, conversation_id, delivery_id)
            existing = db.execute("SELECT * FROM orchestrator_callback_inbox WHERE attempt_id=? AND sequence=?",
                                  (attempt_id, sequence)).fetchone()
            if existing:
                if existing["payload_sha256"] != digest or existing["worker_id"] != worker_id:
                    raise ValueError("conflicting replayed callback sequence")
                return False
            highest = db.execute("SELECT MAX(sequence) FROM orchestrator_callback_inbox WHERE attempt_id=?",
                                 (attempt_id,)).fetchone()[0]
            if highest is not None and sequence < highest:
                raise ValueError("out-of-order callback sequence")
            db.execute("""INSERT INTO orchestrator_callback_inbox
                (attempt_id,worker_id,sequence,kind,payload_sha256,message,created_at)
                VALUES(?,?,?,?,?,?,?)""", (attempt_id, worker_id, sequence, kind,
                                             digest, message, time.time()))
            return True

    def complete_mock(self, *, attempt_id: str, worker_id: str,
                      conversation_id: str, delivery_id: str, result_ref: str) -> bool:
        """Only for offline fake transport tests. No provider assurance implied."""
        with self.store._connect() as db:
            self._check_bound(db, attempt_id, worker_id, conversation_id, delivery_id, allow_completed=True)
        return self.outbox.complete(attempt_id, conversation_id, delivery_id, result_ref)

    def events(self, after_id: int = 0, limit: int = 100) -> list[dict]:
        if not isinstance(after_id, int) or after_id < 0 or not 1 <= limit <= 500:
            raise ValueError("invalid event cursor or limit")
        with self.store._connect() as db:
            return [dict(r) for r in db.execute("""SELECT id,attempt_id,worker_id,sequence,
                kind,message,created_at FROM orchestrator_callback_inbox
                WHERE id>? ORDER BY id LIMIT ?""", (after_id, limit))]

