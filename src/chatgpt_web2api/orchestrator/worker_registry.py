"""Persistent logical worker identities; registration is NOT transport authorization.

Only deterministic mock workers can become schedulable in PR-03. Real
ChatGPT/Codex transport identities must be verified by later integration gates.
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass

from .store import Store

_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")
_ROLES = frozenset({"implement", "review", "planning"})
_TRANSPORTS = frozenset({"mock", "codex_app_server", "chatgpt_ui"})


def _identity(value: str, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"invalid {name}: expected opaque identifier (max 128 chars)")
    return value


@dataclass(frozen=True)
class WorkerSpec:
    worker_id: str
    account_id: str
    project_id: str
    role: str
    transport: str
    session_key: str
    enabled: bool = True


class WorkerRegistry:
    """One SQLite authority; separate database files do not share locks."""

    def __init__(self, store: Store):
        self.store = store
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orchestrator_workers (
                    worker_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    role TEXT NOT NULL, transport TEXT NOT NULL,
                    session_key TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    last_heartbeat REAL NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(account_id, transport, session_key)
                );
                CREATE INDEX IF NOT EXISTS ix_orch_workers_account
                    ON orchestrator_workers(account_id, project_id, role);
                CREATE TABLE IF NOT EXISTS orchestrator_worker_assignments (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                    worker_id TEXT NOT NULL REFERENCES orchestrator_workers(worker_id),
                    claim_version INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('active','released')),
                    created_at REAL NOT NULL, released_at REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_orch_worker_active
                    ON orchestrator_worker_assignments(worker_id) WHERE state='active';
                CREATE TABLE IF NOT EXISTS orchestrator_account_controls (
                    account_id TEXT PRIMARY KEY,
                    paused INTEGER NOT NULL DEFAULT 0,
                    throttle_until REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orchestrator_supervisor_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(worker_id, task_id, reason)
                );
            """)

    def register(self, spec: WorkerSpec) -> bool:
        for name in ("worker_id", "account_id", "project_id", "session_key"):
            _identity(getattr(spec, name), name)
        if spec.role not in _ROLES or spec.transport not in _TRANSPORTS:
            raise ValueError("unknown worker role or transport")
        if spec.enabled and spec.transport != "mock":
            raise ValueError("live transports are not authorized in PR-03")
        if spec.transport == "mock" and not spec.session_key.startswith("fake:"):
            raise ValueError("mock sessions must explicitly use fake: keys")
        if spec.transport != "mock" and spec.session_key == "stdio-singleton":
            # Single stdio connection is not a remote conversation ID.
            raise ValueError("stdio-singleton is not an independent remote session")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM orchestrator_workers WHERE worker_id=?",
                             (spec.worker_id,)).fetchone()
            same = (spec.account_id, spec.project_id, spec.role,
                    spec.transport, spec.session_key, int(spec.enabled))
            if old:
                current = tuple(old[k] for k in ("account_id", "project_id", "role",
                                                  "transport", "session_key", "enabled"))
                if current != same:
                    raise ValueError("worker ID already registered with different identity")
                return False
            # Account-wide *logical* cap; not a claim about model/plan concurrency.
            count = db.execute("SELECT COUNT(*) FROM orchestrator_workers WHERE account_id=?",
                               (spec.account_id,)).fetchone()[0]
            if count >= 5:
                raise ValueError("maximum of five registered logical workers per account")
            now = time.time()
            try:
                db.execute("""INSERT INTO orchestrator_workers
                     (worker_id,account_id,project_id,role,transport,session_key,enabled,
                      last_heartbeat,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                           (spec.worker_id, *same, now, now))
            except sqlite3.IntegrityError as exc:
                raise ValueError("worker session identity already bound") from exc
            db.execute("INSERT OR IGNORE INTO orchestrator_account_controls(account_id,updated_at) VALUES (?,?)",
                       (spec.account_id, now))
            return True

    def get(self, worker_id: str) -> dict | None:
        with self.store._connect() as db:
            row = db.execute("SELECT * FROM orchestrator_workers WHERE worker_id=?", (worker_id,)).fetchone()
            return dict(row) if row else None

    def list(self, account_id: str) -> list[dict]:
        with self.store._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM orchestrator_workers WHERE account_id=? ORDER BY worker_id",
                (account_id,))]

    def assignments(self, account_id: str, active_only: bool = True) -> list[dict]:
        with self.store._connect() as db:
            stmt = """SELECT a.task_id,a.worker_id,a.claim_version,a.state,a.created_at,
                a.released_at,t.state AS task_state,t.project_id
                FROM orchestrator_worker_assignments a
                JOIN orchestrator_workers w ON w.worker_id=a.worker_id
                JOIN tasks t ON t.task_id=a.task_id
                WHERE w.account_id=?"""
            if active_only:
                stmt += " AND a.state='active'"
            return [dict(x) for x in db.execute(stmt + " ORDER BY a.created_at,a.task_id",(account_id,))]

    def heartbeat(self, worker_id: str, *, at: float | None = None) -> bool:
        """Local process liveness hint; not a remotely authenticated callback."""
        at = time.time() if at is None else at
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute("UPDATE orchestrator_workers SET last_heartbeat=MAX(last_heartbeat,?) WHERE worker_id=?",
                             (at, worker_id))
            return cur.rowcount == 1

    def set_enabled(self, worker_id: str, enabled: bool) -> bool:
        """Enable or disable a logical worker without releasing its assignment.

        Disabling prevents future claims. Any active assignment remains held
        for explicit recovery/reconciliation; this method does not cancel or
        retry work. Only mock workers may be enabled in this release.
        """
        _identity(worker_id, "worker_id")
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT transport, enabled FROM orchestrator_workers WHERE worker_id=?",
                (worker_id,),
            ).fetchone()
            if row is None:
                return False
            if enabled and row["transport"] != "mock":
                raise ValueError("live transports are not authorized in PR-03")
            if bool(row["enabled"]) == enabled:
                return False
            db.execute(
                "UPDATE orchestrator_workers SET enabled=? WHERE worker_id=?",
                (int(enabled), worker_id),
            )
            return True

    def control(self, account_id: str, *, paused: bool | None = None,
                throttle_until: float | None = None) -> dict:
        _identity(account_id, "account_id")
        if throttle_until is not None and throttle_until < 0:
            raise ValueError("negative throttle timestamp")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO orchestrator_account_controls(account_id,updated_at) VALUES(?,?)",
                       (account_id, time.time()))
            if paused is not None:
                db.execute("UPDATE orchestrator_account_controls SET paused=?,updated_at=? WHERE account_id=?",
                           (int(paused), time.time(), account_id))
            if throttle_until is not None:
                db.execute("UPDATE orchestrator_account_controls SET throttle_until=?,updated_at=? WHERE account_id=?",
                           (throttle_until, time.time(), account_id))
            return dict(db.execute("SELECT * FROM orchestrator_account_controls WHERE account_id=?", (account_id,)).fetchone())
