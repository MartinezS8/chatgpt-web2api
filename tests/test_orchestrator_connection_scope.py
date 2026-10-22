"""Connection lifetime optimization preserves policy, commits and native pins."""
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest
from test_orchestrator_mock_sandbox import sandbox as sandbox

from chatgpt_web2api.orchestrator.storage_hardening import create_private_windows_workspace
from chatgpt_web2api.orchestrator.storage_policy import PrivateStoragePolicy
from chatgpt_web2api.orchestrator.store import Store, TaskSpec


def test_scope_reuses_connection_and_closes_on_exception(sandbox, monkeypatch):
    opened = []
    original = sandbox.store._open_connection

    @contextmanager
    def tracked(**kwargs):
        with original(**kwargs) as connection:
            opened.append(connection)
            yield connection

    monkeypatch.setattr(sandbox.store, "_open_connection", tracked)
    with pytest.raises(RuntimeError, match="synthetic"):
        with sandbox.store.connection_scope():
            sandbox.store.get("01-a")
            sandbox.store.get("02-b")
            assert len(opened) == 1
            raise RuntimeError("synthetic scope interruption")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
    sandbox.store.get("01-a")
    assert len(opened) == 2


def test_operations_commit_independently_and_roll_back_all_interrupts(sandbox):
    store = sandbox.store
    with store._connect() as db:
        db.execute("CREATE TABLE scope_probe (v INTEGER)")
    with store.connection_scope():
        with store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO scope_probe VALUES(1)")
        for exception in (RuntimeError, KeyboardInterrupt):
            with pytest.raises(exception):
                with store._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("INSERT INTO scope_probe VALUES(2)")
                    raise exception()
        with pytest.raises(RuntimeError, match="nested Store"):
            with store._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO scope_probe VALUES(3)")
                store.get("01-a")
        with store._connect() as db:
            assert [row[0] for row in db.execute("SELECT v FROM scope_probe")] == [1]


def test_scoped_connections_are_thread_local(sandbox):
    barrier = Barrier(2)

    def worker(_):
        with sandbox.store.connection_scope():
            with sandbox.store._connect() as db:
                identity = id(db)
                barrier.wait(timeout=10)
                assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 5
                return identity

    with ThreadPoolExecutor(max_workers=2) as pool:
        identities = list(pool.map(worker, range(2)))
    assert len(set(identities)) == 2


def test_scope_rejects_nested_scopes_and_mode_changes(sandbox):
    with sandbox.store.connection_scope():
        with pytest.raises(RuntimeError, match="nested connection scopes"):
            with sandbox.store.connection_scope():
                pytest.fail("nested scope accepted")
        with pytest.raises(ValueError, match="mode/path/policy"):
            with sandbox.store._connect(set_wal=False):
                pytest.fail("migration mode accepted in a WAL scope")


def test_policy_denial_prevents_scoped_write(sandbox, monkeypatch):
    policy = sandbox.store.storage_policy
    original = PrivateStoragePolicy.check
    denied = False

    def checked(self):
        if denied:
            raise PermissionError("synthetic policy denial")
        return original(self)

    monkeypatch.setattr(PrivateStoragePolicy, "check", checked)
    with sandbox.store.connection_scope():
        denied = True
        with pytest.raises(PermissionError, match="synthetic policy"):
            sandbox.store.create(TaskSpec("denied", "other", "implement", "synthetic"))
        denied = False
        assert sandbox.store.get("denied") is None
        assert policy.check()


def test_unfinished_raw_transaction_cannot_commit_at_scope_exit(sandbox):
    store = sandbox.store
    with store._connect() as db:
        db.execute("CREATE TABLE scope_exit_probe (value TEXT)")
    with pytest.raises(RuntimeError, match="unfinished Store"):
        with store.connection_scope():
            db = store._connection_local.entry["db"]
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO scope_exit_probe VALUES ('must rollback')")
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM scope_exit_probe").fetchone()[0] == 0
    assert len(store.all("offline-demo")) == 5


@pytest.mark.skipif(os.name != "nt", reason="native Windows handle lifetime")
def test_native_scope_keeps_main_wal_shm_pinned_and_releases_on_error():
    workspace = create_private_windows_workspace("scope-" + uuid.uuid4().hex[:12])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        store = Store(policy.context.database, storage_policy=policy)
        with pytest.raises(RuntimeError, match="synthetic"):
            with store.connection_scope():
                store.create(TaskSpec("scope-task", "synthetic", "implement", "synthetic"))
                for suffix in ("", "-wal", "-shm"):
                    result = subprocess.run([sys.executable, "-c",
                        "import pathlib,sys; pathlib.Path(sys.argv[1]).unlink()",
                        str(policy.context.database) + suffix], capture_output=True, text=True, timeout=15)
                    assert result.returncode != 0 and "WinError 32" in result.stderr
                raise RuntimeError("synthetic scope interruption")
        assert store.get("scope-task")  # Commit belonged to create(), not outer scope.
        renamed = policy.context.database.with_suffix(".closed")
        policy.context.database.rename(renamed)
        renamed.rename(policy.context.database)
    finally:
        shutil.rmtree(workspace.root)
