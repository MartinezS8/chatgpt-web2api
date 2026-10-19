"""PR-04: simulated event adapter (not an authenticated webhook endpoint).

Progress is advisory only. Confirmed completion is handled exclusively by the
existing DispatchOutbox.complete(), which requires a previously accepted remote
conversation/message pair. No callback itself is proof of a code change.
"""
from __future__ import annotations

import json
import re
import time

from .store import Store

_EVENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class CallbackBridge:
    def __init__(self, store: Store, outbox, *, mode: str = "mock"):
        if mode != "mock":
            raise PermissionError("no authenticated live callback source is configured")
        if store.path != outbox.store.path:
            raise ValueError("callback and outbox must share database")
        self.store, self.outbox = store, outbox
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orchestrator_callback_progress (
                    attempt_id TEXT PRIMARY KEY, seq INTEGER NOT NULL,
                    conversation_id TEXT NOT NULL, delivery_id TEXT NOT NULL,
                    updated_at REAL NOT NULL);
            """)

    def progress(self, attempt_id: str, conversation_id: str, delivery_id: str,
                 *, event_id: str, sequence: int, summary: str) -> bool:
        if (not all((attempt_id, conversation_id, delivery_id)) or
                not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id) or
                type(sequence) is not int or sequence < 1 or not isinstance(summary,str) or
                len(summary) > 256):
            raise ValueError("invalid advisory progress callback")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ack = db.execute("""SELECT task_id,status,conversation_id,delivery_id
                FROM orchestrator_dispatch_attempts WHERE attempt_id=?""",(attempt_id,)).fetchone()
            if (ack is None or ack["status"] != "accepted" or
                    ack["conversation_id"] != conversation_id or ack["delivery_id"] != delivery_id):
                raise ValueError("progress doesn't match acknowledged attempt")
            key = f"{attempt_id}/callback.progress/{event_id}"
            old_event = db.execute("""SELECT payload FROM orchestrator_delivery_events
                WHERE event_key=?""",(key,)).fetchone()
            payload = json.dumps({"sequence":sequence,"summary":summary},
                                 sort_keys=True,separators=(",", ":"))
            if old_event:
                if old_event["payload"] != payload:
                    raise ValueError("same callback ID with different payload")
                return False
            existing = db.execute("SELECT seq FROM orchestrator_callback_progress WHERE attempt_id=?",
                                  (attempt_id,)).fetchone()
            if existing and sequence <= existing["seq"]:
                raise ValueError("out-of-order callback sequence")
            db.execute("""INSERT INTO orchestrator_callback_progress
                (attempt_id,seq,conversation_id,delivery_id,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(attempt_id) DO UPDATE SET seq=excluded.seq,
                updated_at=excluded.updated_at""",(attempt_id,sequence,conversation_id,delivery_id,time.time()))
            db.execute("""INSERT INTO orchestrator_delivery_events
                (event_key,task_id,attempt_id,kind,payload,at) VALUES(?,?,?,?,?,?)""",
                (key,ack["task_id"],attempt_id,"callback.progress",payload,time.time()))
            return True

    def complete(self, attempt_id: str, conversation_id: str, delivery_id: str,
                 result_ref: str) -> bool:
        """Records an exact-matched completed turn; *never* verifies or approves work."""
        if not all((attempt_id,conversation_id,delivery_id,result_ref)):
            raise ValueError("complete event requires remote identity and result reference")
        return self.outbox.complete(attempt_id,conversation_id,delivery_id,result_ref)