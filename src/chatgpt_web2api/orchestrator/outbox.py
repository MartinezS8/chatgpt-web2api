"""Durable local dispatch intent + append-only event stream (no transport calls).

No exactly-once guarantee for external effects. An unacknowledged dispatch
is *unknown*, not permission to retry. Events contain no prompts/credentials.
"""
from __future__ import annotations

import hashlib
import secrets
import time

from .store import Store, TaskState
from .task_packages import TaskPackages, _stable_json


class DispatchOutbox:
    def __init__(self, store: Store, packages: TaskPackages):
        if store.path != packages.store.path:
            raise ValueError("store/package DB must match")
        self.store, self.packages = store, packages
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orchestrator_dispatch_attempts (
                    attempt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE,
                    package_sha256 TEXT NOT NULL, claim_token_hash TEXT NOT NULL,
                    status TEXT NOT NULL, conversation_id TEXT, delivery_id TEXT,
                    result_ref TEXT, error_code TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS ux_remote_delivery
                   ON orchestrator_dispatch_attempts(conversation_id,delivery_id)
                   WHERE conversation_id IS NOT NULL AND delivery_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS orchestrator_delivery_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE, task_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS orchestrator_event_cursors (
                    consumer_id TEXT PRIMARY KEY, event_id INTEGER NOT NULL);
            """)

    def _event(self, db, attempt: str, task: str, kind: str, body: dict | None = None) -> None:
        key = f"{attempt}/{kind}"
        db.execute("INSERT OR IGNORE INTO orchestrator_delivery_events(event_key,task_id,attempt_id,kind,payload,at) VALUES (?,?,?,?,?,?)",
                   (key,task,attempt,kind,_stable_json(body or {}),time.time()))

    def begin(self, task_id: str, claim_token: str) -> dict:
        if not claim_token:
            raise ValueError("claim token required")
        package = self.packages.read(task_id, verify_blobs=True)  # fail BEFORE write intent
        now=time.time()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task=db.execute("SELECT * FROM tasks WHERE task_id=?",(task_id,)).fetchone()
            if task is None:
                raise ValueError("unknown task")
            existing=db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE task_id=?",(task_id,)).fetchone()
            if existing:
                # Read is idempotent but NEVER grants a second right to call external send.
                if existing["package_sha256"] != package["package_sha256"]:
                    raise ValueError("outbox attempt package mismatch")
                return {"attempt_id":existing["attempt_id"],"status":existing["status"],"new_send_permit":False}
            if task["state"]!=TaskState.RESERVED.value or task["claim_token"]!=claim_token or not task["lease_until"] or task["lease_until"]<=now:
                raise ValueError("no current fenced and unexpired claim")
            attempt=secrets.token_hex(20)
            token_hash=hashlib.sha256(claim_token.encode()).hexdigest()
            db.execute("INSERT INTO orchestrator_dispatch_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (attempt,task_id,package["package_sha256"],token_hash,"intent",None,None,None,None,now,now))
            db.execute("UPDATE tasks SET state=?,claim_version=claim_version+1,updated_at=? WHERE task_id=?",
                       (TaskState.DISPATCHING.value,now,task_id))
            self._event(db,attempt,task_id,"dispatch.intent",{"package_sha256":package["package_sha256"]})
        # This flag is valid only for this *in-process* return. Never persist
        # or reconstruct a new send permit after a crash or lost response.
        return {"attempt_id":attempt,"status":"intent","new_send_permit":True}

    def get(self, attempt_id: str) -> dict | None:
        with self.store._connect() as db:
            row=db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE attempt_id=?",(attempt_id,)).fetchone()
            if row is None:
                return None
            data=dict(row)
            data.pop("claim_token_hash",None)
            return data

    def accept(self, attempt_id: str, claim_token: str, conversation_id: str, delivery_id: str) -> bool:
        if not all((claim_token,conversation_id,delivery_id)):
            raise ValueError("confirmed conversation, delivery and token required")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rec=db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE attempt_id=?",(attempt_id,)).fetchone()
            if rec is None:
                raise ValueError("attempt not found")
            if hashlib.sha256(claim_token.encode()).hexdigest()!=rec["claim_token_hash"]:
                raise ValueError("claim mismatch")
            if rec["status"]=="accepted":
                if rec["conversation_id"] != conversation_id or rec["delivery_id"] != delivery_id:
                    raise ValueError("conflicting remote delivery acknowledgment")
                return False
            if rec["status"]!="intent":
                raise ValueError("attempt cannot be acknowledged from this state")
            task=db.execute("SELECT * FROM tasks WHERE task_id=?",(rec["task_id"],)).fetchone()
            if task is None or task["state"]!=TaskState.DISPATCHING.value or task["claim_token"]!=claim_token:
                raise ValueError("dispatch no longer owned; reconcile manually")
            now=time.time()
            db.execute("UPDATE orchestrator_dispatch_attempts SET status=?,conversation_id=?,delivery_id=?,updated_at=? WHERE attempt_id=?",
                       ("accepted",conversation_id,delivery_id,now,attempt_id))
            db.execute("UPDATE tasks SET state=?,conversation_id=?,delivery_id=?,claim_version=claim_version+1,updated_at=? WHERE task_id=?",
                       (TaskState.IN_PROGRESS.value,conversation_id,delivery_id,now,rec["task_id"]))
            self._event(db,attempt_id,rec["task_id"],"delivery.accepted",{"conversation_id":conversation_id,"delivery_id":delivery_id})
            return True

    def complete(self, attempt_id: str, conversation_id: str, delivery_id: str,
                 result_ref: str) -> bool:
        if not result_ref:
            raise ValueError("result reference required")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rec=db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE attempt_id=?",(attempt_id,)).fetchone()
            if rec is None:
                raise ValueError("attempt not found")
            if rec["conversation_id"]!=conversation_id or rec["delivery_id"]!=delivery_id:
                raise ValueError("completion does not match acknowledged remote turn")
            if rec["status"]=="completed":
                if rec["result_ref"]!=result_ref:
                    raise ValueError("completion evidence mismatch")
                return False
            if rec["status"]!="accepted":
                raise ValueError("completion without accepted delivery")
            task=db.execute("SELECT * FROM tasks WHERE task_id=?",(rec["task_id"],)).fetchone()
            if task is None or task["state"]!=TaskState.IN_PROGRESS.value:
                raise ValueError("task no longer in progress")
            now=time.time()
            db.execute("UPDATE orchestrator_dispatch_attempts SET status='completed',result_ref=?,updated_at=? WHERE attempt_id=?",
                       (result_ref,now,attempt_id))
            db.execute("UPDATE tasks SET state=?,evidence_ref=?,claim_version=claim_version+1,updated_at=? WHERE task_id=?",
                       (TaskState.RESULT_RECEIVED.value,result_ref,now,rec["task_id"]))
            self._event(db,attempt_id,rec["task_id"],"turn.completed",{"result_ref":result_ref})
            return True

    def mark_unknown(self, attempt_id: str, error_code: str="uncertain_transport") -> bool:
        if not error_code or len(error_code)>128:
            raise ValueError("invalid error code")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rec=db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE attempt_id=?",(attempt_id,)).fetchone()
            if rec is None:
                raise ValueError("attempt not found")
            if rec["status"]=="unknown":
                return False
            if rec["status"]!="intent":
                raise ValueError("only unacknowledged intents can become unknown")
            now=time.time()
            db.execute("UPDATE orchestrator_dispatch_attempts SET status='unknown',error_code=?,updated_at=? WHERE attempt_id=?",
                       (error_code,now,attempt_id))
            db.execute("UPDATE tasks SET state=?,error=?,claim_version=claim_version+1,lease_until=NULL,updated_at=? WHERE task_id=? AND state=?",
                       (TaskState.UNKNOWN_DELIVERY.value,error_code,now,rec["task_id"],TaskState.DISPATCHING.value))
            self._event(db,attempt_id,rec["task_id"],"delivery.unknown",{"error_code":error_code})
            return True

    def reconcile_stale(self, seconds: float=300, *, now:float|None=None) -> int:
        if seconds<1:
            raise ValueError("invalid stale threshold")
        now=time.time() if now is None else now
        with self.store._connect() as db:
            items=[r[0] for r in db.execute("SELECT attempt_id FROM orchestrator_dispatch_attempts WHERE status='intent' AND created_at<=?",(now-seconds,))]
        changed=0
        for attempt in items:
            try:
                if self.mark_unknown(attempt,"unconfirmed_intent_after_recovery"):
                    changed+=1
            except ValueError:
                pass
        return changed

    def events(self, after_id: int=0, limit:int=100) -> list[dict]:
        if after_id<0 or not 1<=limit<=1000:
            raise ValueError("invalid cursor/limit")
        with self.store._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM orchestrator_delivery_events WHERE id>? ORDER BY id LIMIT ?",(after_id,limit))]

    def acknowledge_event(self, consumer_id: str, event_id: int) -> bool:
        if not consumer_id or len(consumer_id)>128 or event_id<=0:
            raise ValueError("invalid consumer or event")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT event_id FROM orchestrator_event_cursors WHERE consumer_id=?",(consumer_id,)).fetchone()
            previous=row["event_id"] if row else 0
            if event_id==previous:
                return False
            nxt=db.execute("SELECT id FROM orchestrator_delivery_events WHERE id>? ORDER BY id LIMIT 1",(previous,)).fetchone()
            if nxt is None or nxt["id"]!=event_id:
                raise ValueError("out-of-order event acknowledgment")
            db.execute("INSERT INTO orchestrator_event_cursors(consumer_id,event_id) VALUES (?,?) ON CONFLICT(consumer_id) DO UPDATE SET event_id=excluded.event_id",(consumer_id,event_id))
            return True

    def consumer_events(self, consumer_id: str, limit:int=100) -> list[dict]:
        with self.store._connect() as db:
            row=db.execute("SELECT event_id FROM orchestrator_event_cursors WHERE consumer_id=?",(consumer_id,)).fetchone()
            after=row["event_id"] if row else 0
        return self.events(after,limit)