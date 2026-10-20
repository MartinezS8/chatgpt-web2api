"""Durable, conservative SQLite task/lease store (Python 3.11 stdlib)."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path


class TaskState(StrEnum):
    # Preserve the published str(TaskState.RESERVED) representation that
    # existed when this was a (str, Enum). StrEnum normally returns "reserved".
    # Serialization and string equality continue to use the string value.
    __str__ = Enum.__str__

    QUEUED = "queued"
    RESERVED = "reserved"
    DISPATCHING = "dispatching"
    IN_PROGRESS = "in_progress"
    UNKNOWN_DELIVERY = "unknown_delivery"
    RESULT_RECEIVED = "result_received"
    VERIFIED = "verified"
    FINISHED = "finished"
    NEEDS_HUMAN = "needs_human"


ACTIVE = (TaskState.RESERVED.value, TaskState.DISPATCHING.value,
          TaskState.IN_PROGRESS.value, TaskState.UNKNOWN_DELIVERY.value,
          TaskState.RESULT_RECEIVED.value, TaskState.VERIFIED.value,
          TaskState.NEEDS_HUMAN.value)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    project_id: str
    role: str
    prompt: str
    dependencies: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    baseline_sha: str = ""
    review_of: str | None = None


_SCOPES = frozenset({"repo", "db", "env", "shared", "github", "supabase", "vercel"})
_SCOPE_BODY = re.compile(r"^[a-zA-Z0-9_./:-]+$")


def canonical_scope(scope: str) -> str:
    """Fail closed on ambiguous scopes; normalize paths conservatively for Windows.

    The legacy repo:... form is a *global string namespace*, NOT proof of
    a GitHub repository identity. PR-02B must bind it to a real repository ID.
    """
    if not isinstance(scope, str) or scope.strip() != scope or ":" not in scope:
        raise ValueError(f"invalid write scope: {scope!r}")
    kind, body = scope.split(":", 1)
    if kind.lower() not in _SCOPES or not body or not _SCOPE_BODY.fullmatch(body):
        raise ValueError(f"invalid write scope: {scope!r}")
    # Do not accept aliases, shell/glob syntax, network/absolute paths or
    # path segments that can escape a declared scope.
    if body.startswith(("/", ":")) or body.endswith(("/", ":")):
        raise ValueError(f"invalid write scope: {scope!r}")
    if "//" in body or "::" in body or any(p in {"", ".", ".."} for p in body.replace(":", "/").split("/")):
        raise ValueError(f"invalid write scope: {scope!r}")
    return f"{kind.lower()}:{body.casefold()}"


def _overlaps(a: str, b: str) -> bool:
    """Conservative segment-aware overlap (including resource roots)."""
    x, y = canonical_scope(a), canonical_scope(b)
    return x == y or x.startswith(y + "/") or y.startswith(x + "/") or x.startswith(y + ":") or y.startswith(x + ":")


class Store:
    def __init__(self, database: str | Path):
        self.path = str(database)
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=WAL")
            yield db
            if db.in_transaction:
                db.commit()
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    prompt_sha TEXT NOT NULL,
                    dependencies TEXT NOT NULL,
                    write_scopes TEXT NOT NULL,
                    baseline_sha TEXT NOT NULL,
                    review_of TEXT,
                    state TEXT NOT NULL,
                    slot INTEGER,
                    conversation_id TEXT,
                    delivery_id TEXT,
                    evidence_ref TEXT,
                    error TEXT,
                    updated_at REAL NOT NULL,
                    claim_token TEXT,
                    claim_version INTEGER NOT NULL DEFAULT 0,
                    lease_until REAL,
                    reviewer_ref TEXT,
                    approved_by TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_tasks_project_state ON tasks(project_id, state);
                CREATE UNIQUE INDEX IF NOT EXISTS ux_active_slot
                ON tasks(project_id, slot) WHERE slot IS NOT NULL;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    detail TEXT,
                    at REAL NOT NULL
                );
            """)
            # Non-destructive migration for databases created by Orchestrator V3.
            existing = {r[1] for r in db.execute("PRAGMA table_info(tasks)")}
            legacy_ownership = "claim_token" not in existing
            for name, declaration in (
                ("claim_token", "TEXT"),
                ("claim_version", "INTEGER NOT NULL DEFAULT 0"),
                ("lease_until", "REAL"),
                ("reviewer_ref", "TEXT"),
                ("approved_by", "TEXT"),
            ):
                if name not in existing:
                    db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {declaration}")
            if legacy_ownership:
                # Active V3 leases had no durable owner/fencing identity.  We
                # cannot infer they are safe to resume or requeue after an
                # upgrade; require explicit operator reconciliation.
                legacy_states = (TaskState.RESERVED.value, TaskState.DISPATCHING.value,
                                 TaskState.IN_PROGRESS.value, TaskState.UNKNOWN_DELIVERY.value,
                                 TaskState.RESULT_RECEIVED.value, TaskState.VERIFIED.value)
                db.execute("UPDATE tasks SET state=?,error=?,lease_until=NULL "
                           "WHERE state IN (" + ",".join("?" for _ in legacy_states) + ")",
                           (TaskState.NEEDS_HUMAN.value,
                            "legacy V3 owner cannot be verified; reconcile manually",
                            *legacy_states))

    def _event(self, db, task_id: str, kind: str, detail: str = ""):
        db.execute("INSERT INTO events(task_id,kind,detail,at) VALUES (?,?,?,?)",
                   (task_id, kind, detail[:1000], time.time()))

    def create(self, spec: TaskSpec):
        if not spec.task_id or not spec.project_id or not spec.prompt.strip():
            raise ValueError("task_id, project_id and prompt are required")
        if spec.task_id in spec.dependencies:
            raise ValueError("a task may not depend on itself")
        if spec.role == "review" and spec.write_scopes:
            raise ValueError("review workers must be read-only")
        normalized_scopes = tuple(canonical_scope(scope) for scope in spec.write_scopes)
        if len(normalized_scopes) != len(set(normalized_scopes)):
            raise ValueError("duplicate write scopes")
        digest = hashlib.sha256(spec.prompt.encode("utf-8")).hexdigest()
        record = (spec.task_id, spec.project_id, spec.role, digest,
                  json.dumps(spec.dependencies), json.dumps(normalized_scopes),
                  spec.baseline_sha, spec.review_of, TaskState.QUEUED.value, time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM tasks WHERE task_id=?", (spec.task_id,)).fetchone()
            if existing:
                expected = (spec.project_id, spec.role, digest,
                            json.dumps(spec.dependencies), json.dumps(normalized_scopes),
                            spec.baseline_sha, spec.review_of)
                actual = tuple(existing[k] for k in ("project_id", "role", "prompt_sha",
                          "dependencies", "write_scopes", "baseline_sha", "review_of"))
                if actual != expected:
                    raise ValueError("task_id collision with a different task")
                return False
            for dep in spec.dependencies:
                parent = db.execute("SELECT project_id FROM tasks WHERE task_id=?", (dep,)).fetchone()
                if not parent or parent["project_id"] != spec.project_id:
                    raise ValueError(f"dependency must already exist in project: {dep}")
            db.execute("""INSERT INTO tasks(task_id,project_id,role,prompt_sha,
                 dependencies,write_scopes,baseline_sha,review_of,state,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?)""", record)
            self._event(db, spec.task_id, "created")
        return True

    def get(self, task_id: str):
        with self._connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    def all(self, project_id: str):
        with self._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY task_id", (project_id,))]

    def events(self, task_id: str):
        with self._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,))]

    def claim(self, project_id: str, max_slots: int = 5, lease_seconds: int = 180):
        """Reserve a project slot and globally-conflict-free resource scope atomically.

        A claim token fences all subsequent transitions. Leases are for
        pre-send dispatch coordination, not automatic external retries.
        """
        if not 1 <= max_slots <= 5 or not 30 <= lease_seconds <= 3600:
            raise ValueError("invalid slot limit or lease duration")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM tasks WHERE project_id=? ORDER BY task_id", (project_id,))]
            occupied_slots = {r["slot"] for r in rows if r["slot"] is not None}
            slots = [s for s in range(1, max_slots + 1) if s not in occupied_slots]
            if not slots:
                return None
            by_id = {r["task_id"]: r for r in rows}
            # Resources are global, not scoped by the caller's project_id.
            held = [json.loads(r[0]) for r in db.execute(
                "SELECT write_scopes FROM tasks WHERE state IN (" +
                ",".join("?" for _ in ACTIVE) + ")", ACTIVE)]
            for row in rows:
                if row["state"] != TaskState.QUEUED.value:
                    continue
                deps = json.loads(row["dependencies"])
                if not all(by_id.get(d, {}).get("state") == TaskState.FINISHED.value for d in deps):
                    continue
                scopes = json.loads(row["write_scopes"])
                if any(_overlaps(scope, other) for scope in scopes for group in held for other in group):
                    continue
                token = secrets.token_hex(24)
                now = time.time()
                db.execute("""UPDATE tasks SET state=?,slot=?,claim_token=?,
                      claim_version=claim_version+1,lease_until=?,updated_at=?
                      WHERE task_id=? AND state=?""",
                    (TaskState.RESERVED.value, slots[0], token, now + lease_seconds,
                     now, row["task_id"], TaskState.QUEUED.value))
                self._event(db, row["task_id"], "reserved", f"slot={slots[0]}")
                return self.get_row(db, row["task_id"])
            return None

    @staticmethod
    def get_row(db, task_id):
        return dict(db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

    def transition(self, task_id: str, expected: TaskState, target: TaskState,
                   *, claim_token: str | None = None, **fields):
        allowed = {
            TaskState.RESERVED: {TaskState.DISPATCHING, TaskState.NEEDS_HUMAN},
            TaskState.DISPATCHING: {TaskState.IN_PROGRESS, TaskState.UNKNOWN_DELIVERY},
            TaskState.IN_PROGRESS: {TaskState.RESULT_RECEIVED, TaskState.UNKNOWN_DELIVERY},
            TaskState.UNKNOWN_DELIVERY: {TaskState.IN_PROGRESS, TaskState.NEEDS_HUMAN},
            TaskState.RESULT_RECEIVED: {TaskState.VERIFIED, TaskState.NEEDS_HUMAN},
            TaskState.VERIFIED: {TaskState.NEEDS_HUMAN},
        }
        if target not in allowed.get(expected, set()):
            raise ValueError(f"forbidden transition {expected} -> {target}")
        valid_fields = {"conversation_id", "delivery_id", "evidence_ref", "error"}
        if set(fields) - valid_fields:
            raise ValueError("unexpected transition fields")
        if not claim_token:
            raise ValueError("a nonempty claim_token is required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise ValueError(f"unknown task: {task_id}")
            if row["state"] != expected.value or row["claim_token"] != claim_token:
                return False
            if (expected == TaskState.RESERVED and target == TaskState.DISPATCHING and
                    (row["lease_until"] is None or row["lease_until"] <= time.time())):
                return False
            updates = {"state": target.value, "updated_at": time.time(), **fields}
            if target in {TaskState.RESULT_RECEIVED, TaskState.VERIFIED, TaskState.NEEDS_HUMAN}:
                updates["lease_until"] = None
            clauses = ", ".join(f"{k}=?" for k in updates)
            cur = db.execute(f"UPDATE tasks SET {clauses}, claim_version=claim_version+1 "
                             "WHERE task_id=? AND state=? AND claim_token=? AND claim_version=?",
                             (*updates.values(), task_id, expected.value, claim_token,
                              row["claim_version"]))
            if cur.rowcount != 1:
                return False
            self._event(db, task_id, target.value)
            return True

    def finalize_verified(self, task_id: str, *, claim_token: str,
                          reviewer_ref: str, approved_by: str) -> bool:
        """DISABLED legacy entry point: assertions are not trusted approvals.

        Previously this accepted any nonempty ``reviewer_ref`` and ``approved_by``
        as sufficient to release the task's write lock. The mock review ledger
        cannot authenticate a GitHub review or a human approval. An authorized
        finalization gate must verify the current provider HEAD and successful
        CI, independent reviewer provenance, and human approval when required.

        Until that gate exists, fail closed for every caller. Preserve the
        signature for old clients, but never mutate state on this path.
        """
        raise PermissionError(
            "Legacy asserted review finalization is disabled; a provider-"
            "verified, SHA-bound independent review and authorization gate "
            "must be used before releasing a task's write lock"
        )

    def recover(self, project_id: str, *, now: float | None = None):
        """Only expire stale reservations; never re-send uncertain requests."""
        now = time.time() if now is None else now
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            reserved = db.execute("""SELECT task_id FROM tasks WHERE project_id=?
                AND state=? AND lease_until<=?""",
                (project_id, TaskState.RESERVED.value, now)).fetchall()
            for row in reserved:
                db.execute("""UPDATE tasks SET state=?,slot=NULL,claim_token=NULL,
                    claim_version=claim_version+1,lease_until=NULL,updated_at=? WHERE task_id=?""",
                    (TaskState.QUEUED.value, now, row["task_id"]))
                self._event(db, row["task_id"], "requeued_expired_pre_dispatch")
            unknowns = db.execute("""SELECT task_id FROM tasks WHERE project_id=?
                AND state=? AND lease_until<=?""",
                (project_id, TaskState.DISPATCHING.value, now)).fetchall()
            for row in unknowns:
                db.execute("""UPDATE tasks SET state=?,error=?,claim_version=claim_version+1,
                    lease_until=NULL,updated_at=? WHERE task_id=?""",
                    (TaskState.UNKNOWN_DELIVERY.value, "dispatch status unknown after lease expiry",
                     now, row["task_id"]))
                self._event(db, row["task_id"], "unknown_after_lease_expiry")
            return len(unknowns)
