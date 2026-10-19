"""Local test-only callback adapter, delegating terminal state to the V5 outbox.

This module has NO HTTP endpoint or real provider callback authentication.
Progress events are advisory; only the pre-existing correlated outbox can
advance an accepted delivery to RESULT_RECEIVED. Never finalize here.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol

from .store import Store


class CorrelatedOutbox(Protocol):
    def get(self, attempt_id: str) -> dict | None: ...
    def complete(self, attempt_id: str, conversation_id: str, delivery_id: str,
                 result_ref: str) -> bool: ...


@dataclass(frozen=True)
class Callback:
    event_id: str
    attempt_id: str
    conversation_id: str
    delivery_id: str
    sequence: int
    kind: str
    result_ref: str | None = None


class CallbackPolicy:
    def __init__(self, store: Store, outbox: CorrelatedOutbox):
        self.store, self.outbox = store, outbox
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_progress_inbox (
                attempt_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                conversation_id TEXT NOT NULL,
                delivery_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(attempt_id,event_id),
                UNIQUE(attempt_id,sequence)
            )""")

    def ingest(self, event: Callback, *, source: str = "") -> bool:
        """Accept deterministic *mock* events; no live source supported.

        Returns True for a new event or new confirmed completion; False for
        exact repeats. Conflicting duplicates and mismatched IDs fail closed.
        """
        if source != "mock":
            raise PermissionError("real callback sources require authenticated transport gate")
        if (not event.event_id or len(event.event_id) > 128 or event.sequence < 0
                or event.kind not in {"progress", "completed"}):
            raise ValueError("invalid callback envelope")
        receipt = self.outbox.get(event.attempt_id)
        if not receipt or receipt["status"] not in {"accepted", "completed"}:
            raise ValueError("attempt has no acknowledged remote delivery")
        if (receipt["conversation_id"] != event.conversation_id
                or receipt["delivery_id"] != event.delivery_id):
            raise ValueError("callback remote turn identity mismatch")
        if event.kind == "completed":
            if not event.result_ref:
                raise ValueError("completion requires immutable result reference")
            # Outbox.complete is the single canonical state transition and
            # already emits an idempotent durable 'turn.completed' event.
            return self.outbox.complete(event.attempt_id, event.conversation_id,
                                        event.delivery_id, event.result_ref)
        if receipt["status"] == "completed":
            raise ValueError("progress after terminal completion")
        if event.result_ref is not None:
            raise ValueError("progress must not assert completion evidence")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Re-read the canonical outbox under the write lock. A completion
            # racing with a progress notification must never be followed by
            # an apparently live progress event.
            live = db.execute("""SELECT status,conversation_id,delivery_id
                FROM orchestrator_dispatch_attempts WHERE attempt_id=?""",
                (event.attempt_id,)).fetchone()
            if (live is None or live["status"] != "accepted"
                    or live["conversation_id"] != event.conversation_id
                    or live["delivery_id"] != event.delivery_id):
                raise ValueError("delivery is no longer active")
            existing = db.execute("""SELECT * FROM orchestrator_progress_inbox
                WHERE attempt_id=? AND event_id=?""",
                (event.attempt_id, event.event_id)).fetchone()
            if existing:
                if (existing["sequence"] != event.sequence
                        or existing["conversation_id"] != event.conversation_id
                        or existing["delivery_id"] != event.delivery_id
                        or existing["kind"] != event.kind):
                    raise ValueError("conflicting duplicate event ID")
                return False
            maximum = db.execute("SELECT MAX(sequence) FROM orchestrator_progress_inbox WHERE attempt_id=?",
                                 (event.attempt_id,)).fetchone()[0]
            if maximum is not None and event.sequence <= maximum:
                raise ValueError("out-of-order progress event")
            db.execute("""INSERT INTO orchestrator_progress_inbox
                (attempt_id,event_id,sequence,conversation_id,delivery_id,kind,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (event.attempt_id, event.event_id, event.sequence,
                 event.conversation_id, event.delivery_id, event.kind, time.time()))
            # Does not imply the remote model completed or passed review.
            db.execute("""INSERT OR IGNORE INTO orchestrator_delivery_events
                (event_key,task_id,attempt_id,kind,payload,at)
                SELECT ?,task_id,?, 'turn.progress', ?,?
                FROM orchestrator_dispatch_attempts WHERE attempt_id=?""",
                (f"{event.attempt_id}/progress/{event.event_id}", event.attempt_id,
                 json.dumps({"sequence":event.sequence}), time.time(), event.attempt_id))
            return True