"""Atomic, bounded *local* scheduler. NEVER sends a remote message.

DispatchOutbox.begin() remains the only issuer of a future send intent;
no code in this module imports a CDP driver, talks to ChatGPT, or uploads.
"""
from __future__ import annotations

import json
import secrets
import time

from .store import ACTIVE, Store, TaskState, _overlaps
from .task_packages import TaskPackages
from .worker_registry import WorkerRegistry


class Scheduler:
    def __init__(self, store: Store, registry: WorkerRegistry, packages):
        if (store.storage_policy is not registry.store.storage_policy
                or store.storage_policy is not getattr(packages, "storage_policy", None)):
            raise ValueError("scheduler storage policies must match")
        if store.storage_policy is not None and type(packages) is not TaskPackages:
            raise TypeError("protected scheduler requires policy-bound TaskPackages")
        if store.path != registry.store.path or store.path != packages.store.path:
            raise ValueError("scheduler authority, registry and packages must share one DB")
        self.store, self.registry, self.packages = store, registry, packages

    def claim_next(self, account_id: str, project_id: str, *, max_slots: int = 5,
                   lease_seconds: int = 180, heartbeat_age_seconds: int = 300,
                   now: float | None = None) -> dict | None:
        """Reserve one eligible sealed task and an idle mock worker atomically.

        The return value contains a claim_token ONLY for trusted controller code.
        Never expose that token via generic CLI/status commands.
        """
        if not 1 <= max_slots <= 5 or not 30 <= lease_seconds <= 3600:
            raise ValueError("invalid slot bound or lease duration")
        if heartbeat_age_seconds < 30:
            raise ValueError("invalid heartbeat liveness window")
        now = time.time() if now is None else now
        # Pre-check immutable packages outside the write transaction. An upload
        # or future outbox must re-check every content hash again before send.
        with self.store._connect() as read_db:
            pending = [r[0] for r in read_db.execute(
                "SELECT task_id FROM tasks WHERE project_id=? AND state='queued' ORDER BY task_id",
                (project_id,))]
        verified_packages = set()
        for task_id in pending:
            try:
                self.packages.read(task_id, verify_blobs=True)
                verified_packages.add(task_id)
            except (OSError, ValueError):
                continue  # Missing/corrupt inputs can never be scheduled.
        if not verified_packages:
            return None
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ctl = db.execute("SELECT * FROM orchestrator_account_controls WHERE account_id=?",
                             (account_id,)).fetchone()
            if ctl is None or ctl["paused"] or ctl["throttle_until"] > now:
                return None
            # Release confirmed *local* unused reservations. Unknown and
            # unresolved states deliberately never release a worker here.
            db.execute("""UPDATE orchestrator_worker_assignments
                SET state='released',released_at=? WHERE state='active' AND task_id IN
                (SELECT task_id FROM tasks WHERE state IN ('finished','queued'))""", (now,))
            busy_count = db.execute("""SELECT COUNT(*) FROM orchestrator_worker_assignments a
                JOIN orchestrator_workers w ON w.worker_id=a.worker_id
                WHERE a.state='active' AND w.account_id=?""", (account_id,)).fetchone()[0]
            if busy_count >= max_slots:
                return None
            tasks = [dict(r) for r in db.execute(
                "SELECT * FROM tasks WHERE project_id=? ORDER BY task_id",(project_id,))]
            occupied = {r["slot"] for r in tasks if r["slot"] is not None}
            slots = [x for x in range(1, max_slots + 1) if x not in occupied]
            if not slots:
                return None
            done = {x["task_id"] for x in tasks if x["state"] == TaskState.FINISHED.value}
            held = [json.loads(r[0]) for r in db.execute(
                "SELECT write_scopes FROM tasks WHERE state IN (" +
                ",".join("?" for _ in ACTIVE) + ")", ACTIVE)]
            workers = [dict(r) for r in db.execute("""SELECT w.* FROM orchestrator_workers w
                WHERE w.account_id=? AND w.project_id=? AND w.enabled=1
                AND w.transport='mock' AND w.last_heartbeat>=?
                AND NOT EXISTS (SELECT 1 FROM orchestrator_worker_assignments a
                    WHERE a.worker_id=w.worker_id AND a.state='active')
                ORDER BY w.worker_id""", (account_id,project_id,now-heartbeat_age_seconds))]
            for task in tasks:
                if task["state"] != TaskState.QUEUED.value or task["task_id"] not in verified_packages:
                    continue
                if not set(json.loads(task["dependencies"])).issubset(done):
                    continue
                scopes = json.loads(task["write_scopes"])
                if any(_overlaps(a,b) for a in scopes for group in held for b in group):
                    continue
                selected = next((w for w in workers if w["role"] == task["role"]), None)
                if selected is None:
                    continue
                token = secrets.token_hex(24)
                update = db.execute("""UPDATE tasks SET state=?,slot=?,claim_token=?,
                    claim_version=claim_version+1,lease_until=?,updated_at=?
                    WHERE task_id=? AND state='queued'""",
                    (TaskState.RESERVED.value,slots[0],token,now+lease_seconds,
                     now,task["task_id"]))
                if update.rowcount != 1:
                    raise RuntimeError("claim CAS unexpectedly failed")
                row = self.store.get_row(db,task["task_id"])
                # An expired *pre-send* claim is requeued by Store.recover().
                # The historical assignment is then 'released' above.  The
                # task_id is the assignment's PRIMARY KEY, so a fresh INSERT
                # alone would fail on legitimate recovery.  Only replace a
                # previously released assignment: never steal an active one.
                assigned = db.execute("""INSERT INTO orchestrator_worker_assignments
                     (task_id,worker_id,claim_version,state,created_at)
                     VALUES (?,?,?,'active',?)
                     ON CONFLICT(task_id) DO UPDATE SET
                       worker_id=excluded.worker_id,
                       claim_version=excluded.claim_version,
                       state='active',
                       created_at=excluded.created_at,
                       released_at=NULL
                     WHERE orchestrator_worker_assignments.state='released'""",
                           (task["task_id"],selected["worker_id"],row["claim_version"],now))
                if assigned.rowcount != 1:
                    raise RuntimeError("active worker assignment could not be fenced")
                self.store._event(db,task["task_id"],"worker.assigned",selected["worker_id"])
                return {"task":row,"worker_id":selected["worker_id"],
                        "session_key":selected["session_key"],"remote_send_permitted":False}
            return None
