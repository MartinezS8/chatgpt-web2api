"""Authenticated *local adapter* callback inbox; no network or web automation.

An HMAC proves possession of the controller/adapter secret, NOT authenticity of
an upstream provider response. Only separately authorized transports may mint
these events. Completion requires exact outbox correlation and moves the task
only to result_received; it never grants verification or review approval.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Literal

from .store import Store

_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class CallbackEnvelope:
    event_id: str
    attempt_id: str
    conversation_id: str
    delivery_id: str
    kind: Literal["progress", "completed"]
    result_ref: str = ""
    progress: int = 0

    def validate(self) -> None:
        for field in ("event_id", "attempt_id", "conversation_id", "delivery_id"):
            if not _ID.fullmatch(getattr(self, field)):
                raise ValueError(f"invalid callback {field}")
        if self.kind not in ("progress", "completed"):
            raise ValueError("unsupported callback kind")
        if not 0 <= self.progress <= 100:
            raise ValueError("invalid progress range")
        if self.kind == "progress" and self.result_ref:
            raise ValueError("progress must not carry completion evidence")
        if self.kind == "completed" and (not self.result_ref or len(self.result_ref) > 256):
            raise ValueError("completion requires bounded result_ref")

    def sign(self, secret: bytes) -> str:
        """Test/authorized adapter helper; never export shared secret to web UI."""
        if len(secret) < 32:
            raise ValueError("callback HMAC key must be >=32 bytes")
        self.validate()
        return hmac.new(secret, _canonical(asdict(self)), hashlib.sha256).hexdigest()


class CallbackInbox:
    def __init__(self, store: Store, outbox, secret: bytes):
        if len(secret) < 32:
            raise ValueError("callback HMAC key must be >=32 bytes")
        if store.path != outbox.store.path:
            raise ValueError("callback and outbox must use one SQLite authority")
        self.store, self.outbox, self._secret = store, outbox, secret
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_callback_receipts (
                event_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, kind TEXT NOT NULL,
                received_at REAL NOT NULL)""")

    def apply(self, event: CallbackEnvelope, signature: str) -> bool:
        event.validate()
        expected = event.sign(self._secret)
        if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
            raise PermissionError("unauthenticated adapter callback")
        digest = hashlib.sha256(_canonical(asdict(event))).hexdigest()
        # A received event is not a provider-verified output; outbox state is
        # the sole local correlation authority. Do not re-send on errors.
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prev = db.execute("SELECT payload_sha256 FROM orchestrator_callback_receipts WHERE event_id=?",
                              (event.event_id,)).fetchone()
            if prev is not None:
                if prev["payload_sha256"] != digest:
                    raise ValueError("callback ID collision with different payload")
                return False
            attempt = db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE attempt_id=?",
                                 (event.attempt_id,)).fetchone()
            if attempt is None or attempt["status"] not in ("accepted", "completed"):
                raise ValueError("callback has no acknowledged dispatch")
            if (attempt["conversation_id"] != event.conversation_id or
                    attempt["delivery_id"] != event.delivery_id):
                raise ValueError("callback references another remote turn")
            if event.kind == "progress" and attempt["status"] != "accepted":
                raise ValueError("late progress after completed turn")
            if event.kind == "completed":
                if attempt["status"] == "completed":
                    if attempt["result_ref"] != event.result_ref:
                        raise ValueError("conflicting duplicate completion")
                else:
                    task = db.execute("SELECT state FROM tasks WHERE task_id=?",
                                      (attempt["task_id"],)).fetchone()
                    if task is None or task["state"] != "in_progress":
                        raise ValueError("completion cannot advance current task state")
                    now = time.time()
                    db.execute("UPDATE orchestrator_dispatch_attempts SET status='completed',result_ref=?,updated_at=? WHERE attempt_id=?",
                               (event.result_ref, now, event.attempt_id))
                    db.execute("UPDATE tasks SET state='result_received',evidence_ref=?,claim_version=claim_version+1,updated_at=? WHERE task_id=?",
                               (event.result_ref, now, attempt["task_id"]))
                    db.execute("""INSERT OR IGNORE INTO orchestrator_delivery_events
                        (event_key,task_id,attempt_id,kind,payload,at)
                        VALUES (?,?,?,?,?,?)""",
                        (f"{event.attempt_id}/turn.completed", attempt["task_id"],
                         event.attempt_id,"turn.completed",json.dumps({"result_ref":event.result_ref}),now))
            now = time.time()
            db.execute("INSERT INTO orchestrator_callback_receipts VALUES (?,?,?,?,?)",
                       (event.event_id, event.attempt_id, digest, event.kind, now))
            # A progress notification can be lost without blocking completion.
            # Never persist raw prompts/output or untrusted progress prose.
            db.execute("""INSERT INTO orchestrator_delivery_events
                (event_key,task_id,attempt_id,kind,payload,at) VALUES (?,?,?,?,?,?)""",
                (f"callback/{event.event_id}", attempt["task_id"], event.attempt_id,
                 f"callback.{event.kind}", json.dumps({"progress":event.progress}), now))
            return True

    def receipts(self, attempt_id: str) -> list[dict]:
        with self.store._connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT event_id,attempt_id,kind,received_at FROM orchestrator_callback_receipts "
                "WHERE attempt_id=? ORDER BY received_at,event_id", (attempt_id,))]
