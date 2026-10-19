"""Crash-conservative, SQLite-backed mock attachment upload intents.

This module NEVER sends data to a provider. Any uncertain attachment upload is
quarantined; no claim, lease expiry, or restart grants another attempt.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time

from .store import Store

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class UploadIntents:
    """One durable attachment intent per task; files are sent sequentially."""

    def __init__(self, store: Store, packages):
        if store.path != packages.store.path:
            raise ValueError("upload intent and package must share one SQLite authority")
        self.store = store
        self.packages = packages
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orchestrator_upload_intents (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                    upload_id TEXT NOT NULL UNIQUE,
                    worker_id TEXT NOT NULL,
                    package_sha256 TEXT NOT NULL,
                    claim_token_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('reserved', 'ready_mock', 'unknown')),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orchestrator_upload_parts (
                    task_id TEXT NOT NULL REFERENCES orchestrator_upload_intents(task_id),
                    attachment_sha256 TEXT NOT NULL,
                    name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending', 'inflight', 'acked')),
                    remote_id TEXT UNIQUE,
                    ordinal INTEGER NOT NULL,
                    PRIMARY KEY(task_id,attachment_sha256)
                );
            """)

    @staticmethod
    def _token_hash(token: str) -> str:
        if not isinstance(token, str) or not token:
            raise ValueError("fenced claim token required")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _require_binding(self, db, task_id: str, worker_id: str, token_hash: str) -> None:
        row = db.execute("""SELECT t.state,t.claim_token,t.lease_until,
            a.worker_id,w.transport,w.enabled FROM tasks t
            LEFT JOIN orchestrator_worker_assignments a
              ON a.task_id=t.task_id AND a.state='active'
            LEFT JOIN orchestrator_workers w ON w.worker_id=a.worker_id
            WHERE t.task_id=?""", (task_id,)).fetchone()
        if (row is None or row["state"] != "reserved" or
                not row["claim_token"] or
                hashlib.sha256(row["claim_token"].encode()).hexdigest() != token_hash or
                row["lease_until"] is None or row["lease_until"] <= time.time() or
                row["worker_id"] != worker_id or row["transport"] != "mock" or
                row["enabled"] != 1):
            raise ValueError("stale reservation or untrusted mock worker binding")

    @staticmethod
    def _public(row, new: bool = False) -> dict:
        return {"task_id": row["task_id"], "upload_id": row["upload_id"],
                "status": row["status"], "created": new,
                "assurance": "offline_mock_only", "live_send_permitted": False}

    def reserve(self, *, task_id: str, worker_id: str, claim_token: str) -> dict:
        """Atomically reserve *one* upload attempt. Existing attempts never resend."""
        token_hash = self._token_hash(claim_token)
        manifest = self.packages.read(task_id, verify_blobs=True)
        if not _SHA256.fullmatch(manifest["package_sha256"]):
            raise ValueError("invalid sealed package digest")
        parts = manifest["attachments"]
        if len(parts) != len({x["sha256"] for x in parts}):
            raise ValueError("duplicate attachment content")
        for att in parts:
            if (not _SHA256.fullmatch(att["sha256"]) or
                    not isinstance(att.get("size"), int) or att["size"] < 0 or
                    not isinstance(att.get("name"), str) or not att["name"] or
                    not isinstance(att.get("media_type"), str) or not att["media_type"]):
                raise ValueError("invalid attachment manifest")
        now = time.time()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_binding(db, task_id, worker_id, token_hash)
            old = db.execute("SELECT * FROM orchestrator_upload_intents WHERE task_id=?",
                             (task_id,)).fetchone()
            if old:
                if (old["worker_id"] != worker_id or old["claim_token_hash"] != token_hash or
                        old["package_sha256"] != manifest["package_sha256"]):
                    raise ValueError("upload intent belongs to a different claim or package")
                return self._public(old)
            upload_id = secrets.token_hex(20)
            status = "reserved" if parts else "ready_mock"
            db.execute("""INSERT INTO orchestrator_upload_intents
                (task_id,upload_id,worker_id,package_sha256,claim_token_hash,
                 status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)""",
                (task_id,upload_id,worker_id,manifest["package_sha256"],token_hash,
                 status,now,now))
            for i, att in enumerate(parts):
                db.execute("""INSERT INTO orchestrator_upload_parts
                   (task_id,attachment_sha256,name,media_type,size,state,ordinal)
                   VALUES(?,?,?,?,?,'pending',?)""",
                   (task_id, att["sha256"], att["name"], att["media_type"],att["size"],i))
            self.store._event(db, task_id, "upload.intent", f"files={len(parts)}")
            row = db.execute("SELECT * FROM orchestrator_upload_intents WHERE task_id=?",
                             (task_id,)).fetchone()
            return self._public(row, new=True)

    def reserve_next(self, *, task_id: str, upload_id: str,
                     worker_id: str, claim_token: str) -> dict | None:
        token_hash = self._token_hash(claim_token)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM orchestrator_upload_intents WHERE task_id=?",
                             (task_id,)).fetchone()
            if (row is None or row["upload_id"] != upload_id or
                    row["worker_id"] != worker_id or row["claim_token_hash"] != token_hash):
                raise ValueError("upload intent identity mismatch")
            if row["status"] == "ready_mock":
                return None
            if row["status"] != "reserved":
                raise ValueError("unknown upload status requires external reconciliation")
            self._require_binding(db, task_id, worker_id, token_hash)
            active = db.execute("SELECT 1 FROM orchestrator_upload_parts WHERE task_id=? AND state='inflight'",
                                (task_id,)).fetchone()
            if active:
                raise ValueError("attachment upload already in flight")
            part = db.execute("""SELECT * FROM orchestrator_upload_parts
                WHERE task_id=? AND state='pending' ORDER BY ordinal LIMIT 1""",
                              (task_id,)).fetchone()
            if part is None:
                raise ValueError("upload intent has no remaining pending part")
            db.execute("UPDATE orchestrator_upload_parts SET state='inflight' WHERE task_id=? AND attachment_sha256=?",
                       (task_id,part["attachment_sha256"]))
            self.store._event(db, task_id, "upload.part_intent", f"index={part['ordinal']}")
            return {"name":part["name"],"sha256":part["attachment_sha256"],
                    "size":part["size"],"media_type":part["media_type"],
                    "live_send_permitted":False}

    def acknowledge(self, *, task_id: str, upload_id: str, worker_id: str,
                    claim_token: str, attachment_sha256: str, receipt: dict) -> bool:
        token_hash = self._token_hash(claim_token)
        if not isinstance(receipt, dict):
            raise ValueError("invalid mock receipt")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute("SELECT * FROM orchestrator_upload_intents WHERE task_id=?",
                                (task_id,)).fetchone()
            if (record is None or record["upload_id"] != upload_id or
                    record["worker_id"] != worker_id or record["claim_token_hash"] != token_hash):
                raise ValueError("upload intent identity mismatch")
            part = db.execute("""SELECT * FROM orchestrator_upload_parts
                WHERE task_id=? AND attachment_sha256=?""",
                (task_id,attachment_sha256)).fetchone()
            if part is None:
                raise ValueError("attachment is not in sealed manifest")
            if part["state"] == "acked":
                if record["status"] != "unknown" and part["remote_id"] == receipt.get("remote_id"):
                    return False
                raise ValueError("conflicting or quarantined upload receipt")
            if record["status"] != "reserved" or part["state"] != "inflight":
                raise ValueError("attachment was not authorized for a single upload")
            self._require_binding(db, task_id, worker_id, token_hash)
            remote = receipt.get("remote_id")
            if (receipt.get("sha256") != part["attachment_sha256"] or
                    receipt.get("size") != part["size"] or
                    receipt.get("media_type") != part["media_type"] or
                    not isinstance(remote,str) or not remote.startswith("fake:") or
                    len(remote) > 160):
                raise ValueError("partial or mismatched mock upload receipt")
            db.execute("""UPDATE orchestrator_upload_parts SET state='acked',remote_id=?
                WHERE task_id=? AND attachment_sha256=?""",
                (remote,task_id,attachment_sha256))
            remaining = db.execute("""SELECT COUNT(*) FROM orchestrator_upload_parts
                WHERE task_id=? AND state != 'acked'""",(task_id,)).fetchone()[0]
            if not remaining:
                db.execute("""UPDATE orchestrator_upload_intents SET status='ready_mock',updated_at=?
                    WHERE task_id=?""",(time.time(),task_id))
            self.store._event(db,task_id,"upload.part_ack",f"index={part['ordinal']}")
            return True

    def quarantine(self, *, task_id: str, upload_id: str, reason: str = "uncertain_receipt") -> bool:
        if not isinstance(reason,str) or not reason or len(reason)>128:
            raise ValueError("invalid quarantine reason")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM orchestrator_upload_intents WHERE task_id=?",
                             (task_id,)).fetchone()
            if row is None or row["upload_id"] != upload_id:
                raise ValueError("unknown upload attempt")
            if row["status"] == "unknown":
                return False
            if row["status"] == "ready_mock":
                raise ValueError("completed mock upload is immutable")
            db.execute("UPDATE orchestrator_upload_intents SET status='unknown',updated_at=? WHERE task_id=?",
                       (time.time(),task_id))
            self.store._event(db,task_id,"upload.unknown",reason)
            return True

    def get(self, task_id: str) -> dict | None:
        with self.store._connect() as db:
            row = db.execute("SELECT * FROM orchestrator_upload_intents WHERE task_id=?",
                             (task_id,)).fetchone()
            return self._public(row) if row is not None else None

    def receipts(self, task_id: str) -> list[dict]:
        with self.store._connect() as db:
            return [dict(r) for r in db.execute("""SELECT attachment_sha256 AS sha256,
                name,media_type,size,remote_id,state,ordinal
                FROM orchestrator_upload_parts WHERE task_id=? ORDER BY ordinal""",(task_id,))]
