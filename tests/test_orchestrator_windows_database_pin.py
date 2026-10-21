"""Native, disposable tests: main-file pinning is not a SQLite VFS boundary."""
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import chatgpt_web2api.orchestrator.private_workspace as private_workspace_module
from chatgpt_web2api.orchestrator.observer import Observer
from chatgpt_web2api.orchestrator.storage_hardening import (
    create_private_windows_workspace,
    snapshot_sqlite_same_directory,
)
from chatgpt_web2api.orchestrator.storage_policy import PrivateStoragePolicy
from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.windows_database_pin import pin_database

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows sharing semantics")


def _attempt_delete(path):
    result = subprocess.run(
        [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).unlink()", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode != 0 and "WinError 32" in result.stderr


def test_protected_store_pins_before_sqlite_open(monkeypatch):
    workspace = create_private_windows_workspace("pin-" + uuid.uuid4().hex[:12])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        store = Store(policy.context.database, storage_policy=policy)
        original = sqlite3.connect
        attempts = []

        def checked_connect(*args, **kwargs):
            if str(args[0]) == store.path:
                denied = _attempt_delete(Path(store.path))
                attempts.append(denied)
                assert denied, "main DB was replaceable after protected preflight"
            return original(*args, **kwargs)

        monkeypatch.setattr("chatgpt_web2api.orchestrator.store.sqlite3.connect", checked_connect)
        store.create(TaskSpec("pinned", "p", "implement", "synthetic"))
        assert attempts and all(attempts)
        # Connection and native pin must both be closed on return.
        moved = policy.context.database.with_suffix(".released")
        policy.context.database.rename(moved)
        moved.rename(policy.context.database)
    finally:
        shutil.rmtree(workspace.root)


def test_pin_creation_identity_and_release_after_exception(tmp_path):
    root = tmp_path.resolve(strict=True)
    database = root / "synthetic.sqlite3"
    identity = None
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with pin_database(database, create=True) as identity:
            assert len(identity) == 3
            assert _attempt_delete(database)
            with pin_database(database) as second_identity:
                assert second_identity == identity
            # The first handle still blocks deletion after an inner close.
            assert _attempt_delete(database)
            raise RuntimeError("synthetic failure")
    database.unlink()
    assert not database.exists()


def test_pin_rejects_hardlink_without_changing_content(tmp_path):
    root = tmp_path.resolve(strict=True)
    source = root / "synthetic.txt"
    source.write_bytes(b"unchanged")
    alias = root / "controller.sqlite3"
    os.link(source, alias)
    with pytest.raises(ValueError, match="multiply linked"):
        with pin_database(alias):
            pytest.fail("hardlink must not enter pinned operation")
    assert source.read_bytes() == b"unchanged"
    alias.unlink()  # rejected acquisition must release all handles
    source.unlink()


def test_pin_rejects_symlink_without_changing_target(tmp_path):
    root = tmp_path.resolve(strict=True)
    source = root / "synthetic.txt"
    source.write_bytes(b"unchanged")
    alias = root / "controller.sqlite3"
    try:
        alias.symlink_to(source)
    except OSError as exc:
        pytest.skip(f"symlink privilege unavailable: {exc.winerror}")
    with pytest.raises(ValueError, match="reparse"):
        with pin_database(alias):
            pytest.fail("symlink must not enter pinned operation")
    assert source.read_bytes() == b"unchanged"
    alias.unlink()


def test_pin_allows_wal_backup_and_blocks_direct_parent_rename(tmp_path):
    root = tmp_path.resolve(strict=True) / "private space-ü"
    root.mkdir()
    database = root / "synthetic.sqlite3"
    with pin_database(database, create=True):
        child = subprocess.run(
            [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).rename(sys.argv[2])",
             str(root), str(root.with_name("moved"))], capture_output=True, text=True, timeout=15,
        )
        assert child.returncode != 0 and "WinError 32" in child.stderr
        writer = sqlite3.connect(database)
        try:
            assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
            writer.execute("CREATE TABLE synthetic(value TEXT)")
            writer.execute("INSERT INTO synthetic VALUES ('committed')")
            writer.commit()
            reader = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            backup = sqlite3.connect(root / "backup.sqlite3")
            try:
                assert reader.execute("SELECT value FROM synthetic").fetchone()[0] == "committed"
                writer.backup(backup)
                assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert backup.execute("SELECT value FROM synthetic").fetchone()[0] == "committed"
            finally:
                backup.close()
                reader.close()
        finally:
            writer.close()
    root.rename(root.with_name("released"))


def test_protected_connect_failure_releases_pins(monkeypatch):
    workspace = create_private_windows_workspace("pin-fail-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        store = Store(policy.context.database, storage_policy=policy)

        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("synthetic open failure")

        monkeypatch.setattr("chatgpt_web2api.orchestrator.store.sqlite3.connect", fail)
        with pytest.raises(sqlite3.OperationalError, match="synthetic open failure"):
            with store._connect():
                pytest.fail("failed connection must not enter operation")
        policy.context.database.unlink()
    finally:
        shutil.rmtree(workspace.root)


@pytest.mark.parametrize("operation", ["observer", "backup"])
def test_protected_reader_and_backup_pin_existing_database(monkeypatch, operation):
    workspace = create_private_windows_workspace("pin-read-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        store = Store(policy.context.database, storage_policy=policy)
        store.create(TaskSpec("read", "p", "implement", "synthetic"))
        observer = Observer(store.path, storage_policy=policy)
        original = sqlite3.connect
        attempts = []

        def checked_connect(*args, **kwargs):
            path = str(args[0])
            if path == store.path or path == policy.context.database.as_uri() + "?mode=ro":
                attempts.append(_attempt_delete(policy.context.database))
                assert attempts[-1], "protected source must be pinned before SQLite opens"
            return original(*args, **kwargs)

        monkeypatch.setattr("sqlite3.connect", checked_connect)
        if operation == "observer":
            assert observer.status("p")["tasks"] == 1
        else:
            result = snapshot_sqlite_same_directory(store.path, "backup.sqlite3", storage_policy=policy)
            assert result.is_file()
        assert attempts and all(attempts)
        policy.context.database.unlink()
    finally:
        shutil.rmtree(workspace.root)


def test_pin_missing_read_source_does_not_create_file(tmp_path):
    database = tmp_path.resolve(strict=True) / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        with pin_database(database):
            pytest.fail("read pins must never create missing databases")
    assert not database.exists()


def test_main_pin_does_not_claim_sidecar_delete_denial(tmp_path):
    """Executable limitation: the main-file pin does not pin sibling names."""
    database = tmp_path.resolve(strict=True) / "synthetic.sqlite3"
    sidecar = Path(str(database) + "-wal")
    with pin_database(database, create=True):
        sidecar.write_bytes(b"synthetic-not-a-live-wal")
        sidecar.unlink()
        assert not sidecar.exists()
        assert _attempt_delete(database)


def test_first_store_initialization_pins_new_database_and_parent(monkeypatch):
    workspace = create_private_windows_workspace("pin-new-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        assert not policy.context.database.exists()
        original = sqlite3.connect
        attempts = []

        def checked_connect(*args, **kwargs):
            assert policy.context.database.is_file()
            assert _attempt_delete(policy.context.database)
            child = subprocess.run(
                [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).rename(sys.argv[2])",
                 str(policy.context.root), str(policy.context.root.with_name("moved-" + uuid.uuid4().hex))],
                capture_output=True, text=True, timeout=15,
            )
            assert child.returncode != 0 and "WinError 32" in child.stderr
            attempts.append(True)
            return original(*args, **kwargs)

        monkeypatch.setattr("sqlite3.connect", checked_connect)
        Store(policy.context.database, storage_policy=policy)
        assert attempts
    finally:
        shutil.rmtree(workspace.root)


def test_pin_rejects_network_namespace_before_creating_files():
    with pytest.raises(ValueError, match="local drive"):
        with pin_database(Path(r"\\synthetic-invalid-host\share\missing.sqlite3"), create=True):
            pytest.fail("network paths must not enter native acquisition")


@pytest.mark.parametrize("fault", ["once", "always", "permission", "source"])
def test_native_inventory_restarts_only_for_disappearing_sidecars(monkeypatch, fault):
    workspace = create_private_windows_workspace("pin-scan-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        root = workspace.root.resolve(strict=True)
        sidecar = root / ("source.txt" if fault == "source" else "controller.sqlite3-shm")
        sidecar.write_bytes(b"synthetic-not-live-shm")
        original = private_workspace_module._check_child_acl
        attempts = []
        scans = []
        original_load = private_workspace_module._load_private_workspace_once

        def load(label):
            scans.append(label)
            return original_load(label)

        monkeypatch.setattr(private_workspace_module, "_load_private_workspace_once", load)

        def inspect(path, sid):
            if path == sidecar:
                attempts.append(True)
                if fault == "permission":
                    raise PermissionError("synthetic ACL denial")
                if fault == "always":
                    raise FileNotFoundError(2, "synthetic sidecar disappearance", str(path))
                sidecar.unlink()
            return original(path, sid)

        monkeypatch.setattr(private_workspace_module, "_check_child_acl", inspect)
        if fault == "once":
            result = private_workspace_module.load_private_workspace(workspace.root.name)
            assert result.root == root
            assert len(attempts) == 1
            assert len(scans) == 2, "retry must repeat the entire native validation"
        elif fault == "always":
            with pytest.raises(FileNotFoundError):
                private_workspace_module.load_private_workspace(workspace.root.name)
            assert len(attempts) == 3, "unstable sidecars must fail after bounded full scans"
            assert len(scans) == 3
        elif fault == "source":
            with pytest.raises(FileNotFoundError):
                private_workspace_module.load_private_workspace(workspace.root.name)
            assert len(attempts) == len(scans) == 1
        else:
            with pytest.raises(PermissionError, match="synthetic ACL denial"):
                private_workspace_module.load_private_workspace(workspace.root.name)
            assert len(attempts) == 1, "ACL denial must not be retried or ignored"
    finally:
        shutil.rmtree(workspace.root)
