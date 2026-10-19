"""Strict mock-only upload and per-message app selection readiness checks.

This is NOT a ChatGPT upload implementation. It binds a sealed local package
and explicitly simulated worker capabilities to transport mock receipts.
Never authorizes remote message sending, provider writes or approval clicks.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Protocol

from .store import Store
from .upload_intents import UploadIntents


class MockAttachmentAdapter(Protocol):
    def upload(self, attachment: dict, blob_path: str) -> dict: ...


class MockCapabilityAdapter(Protocol):
    def snapshot(self, worker_id: str, task_id: str) -> dict: ...


class UploadPreflight:
    def __init__(self, store: Store, packages):
        if store.path != packages.store.path:
            raise ValueError("package and preflight must share one controller DB")
        self.store, self.packages = store, packages
        self.intents = UploadIntents(store, packages)
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_mock_upload_preflight (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                worker_id TEXT NOT NULL, package_sha256 TEXT NOT NULL,
                receipts_json TEXT NOT NULL, capability_digest TEXT NOT NULL,
                model TEXT NOT NULL, effort TEXT NOT NULL,
                apps_json TEXT NOT NULL, assurance TEXT NOT NULL, created_at REAL NOT NULL
            )""")

    @staticmethod
    def _hash(x: dict) -> str:
        return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def check_mock(self, *, task_id: str, worker_id: str, model: str, effort: str,
                   required_apps: tuple[str, ...], capability: MockCapabilityAdapter,
                   uploader: MockAttachmentAdapter) -> dict:
        if not model or not effort or any(not app or not isinstance(app,str) for app in required_apps):
            raise ValueError("invalid capability requirements")
        if len(set(required_apps)) != len(required_apps):
            raise ValueError("duplicate required app")
        task = self.store.get(task_id)
        if not task or task["state"] != "reserved":
            raise ValueError("only an active reserved task can be preflighted")
        package = self.packages.read(task_id, verify_blobs=True)
        caps = capability.snapshot(worker_id, task_id)
        if caps.get("transport") != "mock" or caps.get("worker_id") != worker_id:
            raise ValueError("unverified or nonmock transport capabilities")
        if caps.get("model") != model or caps.get("effort") != effort:
            raise ValueError("requested model/effort is not confirmed exactly")
        if caps.get("user_approval_pending", False):
            raise ValueError("interactive approval required: no automatic click")
        available = set(caps.get("available_apps", ()))
        selected = set(caps.get("selected_apps_this_message", ()))
        if not set(required_apps).issubset(available & selected):
            raise ValueError("required apps not available and selected for this message")
        if not caps.get("upload_supported") and package["attachments"]:
            raise ValueError("selected transport does not support uploads")
        with self.store._connect() as db:
            assignment = db.execute("""SELECT a.worker_id, w.enabled,w.transport FROM
                orchestrator_worker_assignments a JOIN orchestrator_workers w ON a.worker_id=w.worker_id
                WHERE a.task_id=? AND a.state='active'""",(task_id,)).fetchone()
            if (assignment is None or assignment["worker_id"] != worker_id or not assignment["enabled"]
                    or assignment["transport"] != "mock"):
                raise ValueError("task not assigned to this enabled mock worker")
        # Repeated preflight for the same sealed package is a read-only
        # idempotency check. Never re-upload attachments on an ordinary retry.
        # This is a mock-only gate; concurrent/unknown live upload receipts
        # will additionally need a durable inflight lease in PR-06B.
        capability_digest = self._hash(caps)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM orchestrator_mock_upload_preflight WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if previous:
                expected = {
                    "worker_id": worker_id,
                    "package_sha256": package["package_sha256"],
                    "capability_digest": capability_digest,
                    "model": model,
                    "effort": effort,
                    "apps": list(required_apps),
                }
                recorded = {
                    "worker_id": previous["worker_id"],
                    "package_sha256": previous["package_sha256"],
                    "capability_digest": previous["capability_digest"],
                    "model": previous["model"],
                    "effort": previous["effort"],
                    "apps": json.loads(previous["apps_json"]),
                }
                if recorded != expected:
                    raise ValueError("sealed preflight does not match current inputs")
                self.intents.assert_ready_locked(
                    db, task_id=task_id, worker_id=worker_id,
                    claim_token=task["claim_token"],
                    package_sha256=package["package_sha256"],
                )
                return {
                    "created": False, "mock_ready": True,
                    "live_send_permitted": False,
                    "attachment_count": len(json.loads(previous["receipts_json"])),
                    "assurance": "offline_mock_only",
                }
        # PR-16: every mock upload must have an atomic durable per-file
        # intent *before* the side effect. Concurrent/unknown attempts are
        # never replayed, even if the final preflight seal is missing.
        receipts = self.intents.perform_mock(
            task_id=task_id, worker_id=worker_id,
            claim_token=task["claim_token"], uploader=uploader,
        )
        cap_digest=capability_digest
        snapshot={"worker_id":worker_id,"package_sha256":package["package_sha256"],
                  "receipts":receipts,"capability_digest":cap_digest,"model":model,
                  "effort":effort,"apps":list(required_apps)}
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # A suspended/expired task must not receive a stale preflight record.
            row=db.execute("""SELECT t.state,a.worker_id FROM tasks t LEFT JOIN
                orchestrator_worker_assignments a ON a.task_id=t.task_id AND a.state='active'
                WHERE t.task_id=?""",(task_id,)).fetchone()
            if not row or row["state"] != "reserved" or row["worker_id"] != worker_id:
                raise ValueError("task reservation changed during upload preflight")
            # Prevent a stale claim/version from sealing a readiness result,
            # even when a worker was reassigned between mock ACK and persistence.
            self.intents.assert_ready_locked(
                db, task_id=task_id, worker_id=worker_id,
                claim_token=task["claim_token"],
                package_sha256=package["package_sha256"],
            )
            old=db.execute("SELECT * FROM orchestrator_mock_upload_preflight WHERE task_id=?",(task_id,)).fetchone()
            if old:
                previous={"worker_id":old["worker_id"],"package_sha256":old["package_sha256"],
                          "receipts":json.loads(old["receipts_json"]),"capability_digest":old["capability_digest"],
                          "model":old["model"],"effort":old["effort"],"apps":json.loads(old["apps_json"])}
                if previous != snapshot:
                    raise ValueError("sealed preflight cannot be changed")
                return {"created":False,"mock_ready":True,"live_send_permitted":False,
                        "attachment_count":len(receipts),"assurance":"offline_mock_only"}
            db.execute("""INSERT INTO orchestrator_mock_upload_preflight
                VALUES(?,?,?,?,?,?,?,?,?,?)""",(task_id,worker_id,package["package_sha256"],
                        json.dumps(receipts,sort_keys=True),cap_digest,model,effort,
                        json.dumps(list(required_apps)),"offline_mock_only",time.time()))
        return {"created":True,"mock_ready":True,"live_send_permitted":False,
                "attachment_count":len(receipts),"assurance":"offline_mock_only"}

    def get(self, task_id: str) -> dict | None:
        with self.store._connect() as db:
            row=db.execute("""SELECT task_id,worker_id,package_sha256,model,effort,
                apps_json,assurance,created_at FROM orchestrator_mock_upload_preflight
                WHERE task_id=?""",(task_id,)).fetchone()
            if not row:
                return None
            public=dict(row)
            public["required_apps"]=json.loads(public.pop("apps_json"))
            public["live_send_permitted"]=False
            return public

