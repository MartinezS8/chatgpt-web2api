"""Conservative local supervisor with pause/throttle, no remote cancellation."""
from __future__ import annotations

import time

from .store import Store
from .worker_registry import WorkerRegistry


class Supervisor:
    def __init__(self, store: Store, registry: WorkerRegistry):
        if store.path != registry.store.path:
            raise ValueError("supervisor must share registry database")
        self.store, self.registry = store, registry

    def pause(self, account_id: str) -> dict:
        """Prevent NEW claims. Existing work is NOT cancelled or retried."""
        return self.registry.control(account_id, paused=True)

    def resume(self, account_id: str) -> dict:
        """Resume scheduling only; no uncertain sends are repeated."""
        return self.registry.control(account_id, paused=False)

    def throttle(self, account_id: str, seconds: float) -> dict:
        if not 1 <= seconds <= 86400:
            raise ValueError("invalid account throttle")
        return self.registry.control(account_id, throttle_until=time.time() + seconds)

    def scan(self, account_id: str, *, stale_after: int = 300,
             now: float | None = None) -> list[dict]:
        """Persist one alert per stale assignment; quarantine by retention.

        Do not infer remote message failure from a missed heartbeat. The
        existing task/worker leases and write scopes remain held. Explicit
        operator/provider reconciliation is required to free them.
        """
        if stale_after < 30:
            raise ValueError("stale threshold too short")
        now = time.time() if now is None else now
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            stale = [dict(r) for r in db.execute("""SELECT
                a.task_id,a.worker_id,t.state AS task_state,w.last_heartbeat
                FROM orchestrator_worker_assignments a
                JOIN orchestrator_workers w ON w.worker_id=a.worker_id
                JOIN tasks t ON t.task_id=a.task_id
                WHERE a.state='active' AND w.account_id=?
                AND w.last_heartbeat<? AND t.state NOT IN ('finished','queued')""",
                 (account_id,now-stale_after))]
            for item in stale:
                db.execute("""INSERT OR IGNORE INTO orchestrator_supervisor_alerts
                    (worker_id,task_id,reason,created_at) VALUES (?,?,?,?)""",
                    (item["worker_id"],item["task_id"],"stale_heartbeat",now))
            return stale

    def alerts(self, account_id: str) -> list[dict]:
        with self.store._connect() as db:
            return [dict(r) for r in db.execute("""SELECT a.* FROM orchestrator_supervisor_alerts a
                JOIN orchestrator_workers w ON w.worker_id=a.worker_id
                WHERE w.account_id=? ORDER BY a.id""",(account_id,))]