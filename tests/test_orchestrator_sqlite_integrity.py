"""SQLite connection integrity settings for local orchestration state."""
from __future__ import annotations

import sqlite3

import pytest

from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.worker_registry import WorkerRegistry, WorkerSpec


def test_store_enables_foreign_keys_and_rejects_orphan_assignments(tmp_path):
    store = Store(tmp_path / "controller.sqlite3")
    registry = WorkerRegistry(store)
    store.create(TaskSpec("known-task", "project", "implement", "synthetic prompt"))
    registry.register(WorkerSpec(
        "known-worker", "account", "project", "implement", "mock", "fake:known-worker"
    ))

    with store._connect() as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO orchestrator_worker_assignments
                   (task_id, worker_id, claim_version, state, created_at)
                   VALUES ('missing-task', 'known-worker', 1, 'active', 1.0)"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO orchestrator_worker_assignments
                   (task_id, worker_id, claim_version, state, created_at)
                   VALUES ('known-task', 'missing-worker', 1, 'active', 1.0)"""
            )
