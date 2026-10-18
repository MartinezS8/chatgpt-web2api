"""Durable, conservative SQLite task/lease store (Python 3.11 stdlib)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TaskState(str, Enum):
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
          TaskState.RESULT_RECEIVED.value, TaskState.VERIFIED.value)


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


def _overlaps(a: str, b: str) -> bool:
    """Scopes are canonical strings: repo:path or db:environment (prefix tree)."""
    if a == b:
        return True
    # Require a delimiter so repo:src/a does not conflict with repo:src/abc.
    return a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")


class Store:
    def __init__(self, database: str | Path):
        self.path = str(database)
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
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
                    updated_at REAL NOT NULL
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
        for scope in spec.write_scopes:
            if not scope.startswith(("repo:", "db:", "env:", "shared:")) or ".." in scope:
                raise ValueError(f"invalid write scope: {scope}")
        digest = hashlib.sha256(spec.prompt.encode("utf-8")).hexdigest()
        record = (spec.task_id, spec.project_id, spec.role, digest,
                  json.dumps(spec.dependencies), json.dumps(spec.write_scopes),
                  spec.baseline_sha, spec.review_of, TaskState.QUEUED.value, time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM tasks WHERE task_id=?", (spec.task_id,)).fetchone()
            if existing:
                expected = (spec.project_id, spec.role, digest,
                            json.dumps(spec.dependencies), json.dumps(spec.write_scopes),
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

    def claim(self, project_id: str, max_slots: int = 5):
        """Atomically reserve one eligible task and its project-scoped slot."""
        if not 1 <= max_slots <= 5:
            raise ValueError("max_slots must be between 1 and 5")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = [dict(r) for r in db.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY task_id", (project_id,))]
            active = [r for r in rows if r["state"] in ACTIVE]
            if len(active) >= max_slots:
                return None
            occupied_slots = {r["slot"] for r in rows if r["slot"] is not None}
            slots = [s for s in range(1, max_slots + 1) if s not in occupied_slots]
            if not slots:
                return None
            by_id = {r["task_id"]: r for r in rows}
            for row in rows:
                if row["state"] != TaskState.QUEUED.value:
                    continue
                deps = json.loads(row["dependencies"])
                if not all(by_id.get(d, {}).get("state") == TaskState.FINISHED.value for d in deps):
                    continue
                scopes = json.loads(row["write_scopes"])
                if any(_overlaps(s, occupied) for x in active for occupied in json.loads(x["write_scopes"]) for s in scopes):
                    continue
                # DB resources are exclusive to an environment and require a separate
                # project/environment name; no optimistic sharing by concurrent agents.
                db.execute("UPDATE tasks SET state=?,slot=?,updated_at=? WHERE task_id=?",
                           (TaskState.RESERVED.value, slots[0], time.time(), row["task_id"]))
                self._event(db, row["task_id"], "reserved", f"slot={slots[0]}")
                return self.get_row(db, row["task_id"])
            return None

    @staticmethod
    def get_row(db, task_id):
        return dict(db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

    def transition(self, task_id: str, expected: TaskState, target: TaskState, **fields):
        allowed = {
            TaskState.RESERVED: {TaskState.DISPATCHING, TaskState.NEEDS_HUMAN},
            TaskState.DISPATCHING: {TaskState.IN_PROGRESS, TaskState.UNKNOWN_DELIVERY},
            TaskState.IN_PROGRESS: {TaskState.RESULT_RECEIVED, TaskState.UNKNOWN_DELIVERY},
            TaskState.UNKNOWN_DELIVERY: {TaskState.IN_PROGRESS, TaskState.NEEDS_HUMAN},
            TaskState.RESULT_RECEIVED: {TaskState.VERIFIED, TaskState.NEEDS_HUMAN},
            TaskState.VERIFIED: {TaskState.FINISHED, TaskState.NEEDS_HUMAN},
            TaskState.NEEDS_HUMAN: {TaskState.FINISHED},
        }
        if target not in allowed.get(expected, set()):
            raise ValueError(f"forbidden transition {expected} -> {target}")
        valid_fields = {"conversation_id", "delivery_id", "evidence_ref", "error"}
        if set(fields) - valid_fields:
            raise ValueError("unexpected transition fields")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.get_row(db, task_id)
            if row["state"] != expected.value:
                return False
            updates = {"state": target.value, "updated_at": time.time(), **fields}
            if target == TaskState.FINISHED:
                updates["slot"] = None
            clauses = ", ".join(f"{k}=?" for k in updates)
            db.execute(f"UPDATE tasks SET {clauses} WHERE task_id=?",
                       (*updates.values(), task_id))
            self._event(db, task_id, target.value)
        return True

    def recover(self, project_id: str):
        """Never auto-retry uncertain sends; requeue only pre-dispatch claims."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            reserved = db.execute("SELECT task_id FROM tasks WHERE project_id=? AND state=?",
                                  (project_id, TaskState.RESERVED.value)).fetchall()
            for row in reserved:
                db.execute("UPDATE tasks SET state=?,slot=NULL,updated_at=? WHERE task_id=?",
                           (TaskState.QUEUED.value, time.time(), row["task_id"]))
                self._event(db, row["task_id"], "requeued_pre_dispatch")
            rows = db.execute("SELECT task_id FROM tasks WHERE project_id=? AND state=?",
                              (project_id, TaskState.DISPATCHING.value)).fetchall()
            for row in rows:
                db.execute("UPDATE tasks SET state=?,error=?,updated_at=? WHERE task_id=?",
                           (TaskState.UNKNOWN_DELIVERY.value, "dispatch result unknown after restart",
                            time.time(), row["task_id"]))
                self._event(db, row["task_id"], "unknown_after_restart")
            return len(rows)