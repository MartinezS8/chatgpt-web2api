"""Native, disposable tests: main-file pinning is not a SQLite VFS boundary."""
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

import chatgpt_web2api.orchestrator.private_workspace as private_workspace_module
from chatgpt_web2api.orchestrator.observer import Observer
from chatgpt_web2api.orchestrator.storage_hardening import (
    create_private_windows_workspace,
    snapshot_sqlite_same_directory,
)
from chatgpt_web2api.orchestrator.storage_policy import (
    PrivateStoragePolicy,
    _current_windows_sid,
)
from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.windows_database_pin import (
    _database_initialization_mutex_name,
    pin_database,
    serialize_database_initialization,
)

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


def test_protected_migration_pins_rollback_journal_before_sqlite_open(monkeypatch, tmp_path):
    workspace = create_private_windows_workspace("pin-journal-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        journal = Path(str(policy.context.database) + "-journal")
        outside = tmp_path.resolve(strict=True) / "outside-journal-target.bin"
        outside.write_bytes(b"synthetic marker must remain unchanged")
        before = outside.read_bytes()
        original = sqlite3.connect
        attempts = []

        def guarded_connect(*args, **kwargs):
            if str(args[0]) == str(policy.context.database) and not attempts:
                assert journal.is_file()
                denied = _attempt_delete(journal)
                attempts.append(denied)
                if not denied and not journal.exists():
                    journal.symlink_to(outside)
            return original(*args, **kwargs)

        monkeypatch.setattr("chatgpt_web2api.orchestrator.store.sqlite3.connect", guarded_connect)
        store = Store(policy.context.database, storage_policy=policy)
        assert attempts == [True], "migration journal must resist replacement before SQLite opens"
        assert not journal.is_symlink()
        assert not journal.exists() or journal.is_file()
        assert outside.read_bytes() == before
        with store._connect() as database:
            assert database.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            assert database.execute(
                "SELECT version FROM orchestrator_schema_versions WHERE component='task-store'"
            ).fetchone()[0] == 2
    finally:
        shutil.rmtree(workspace.root)


def test_protected_migration_crash_recovers_persist_journal_and_uncommitted_pages():
    workspace = create_private_windows_workspace("pin-migration-crash-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        database = policy.context.database
        with closing(sqlite3.connect(database)) as seeded:
            seeded.execute("""CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, role TEXT NOT NULL,
                prompt_sha TEXT NOT NULL, dependencies TEXT NOT NULL,
                write_scopes TEXT NOT NULL, baseline_sha TEXT NOT NULL,
                review_of TEXT, state TEXT NOT NULL, slot INTEGER,
                conversation_id TEXT, delivery_id TEXT, evidence_ref TEXT,
                error TEXT, updated_at REAL NOT NULL
            )""")
            seeded.execute(
                """INSERT INTO tasks(task_id,project_id,role,prompt_sha,dependencies,
                   write_scopes,baseline_sha,state,updated_at)
                   VALUES ('active','project','implement','sha','[]','[]','','in_progress',1)"""
            )
            seeded.execute("CREATE TABLE recovery_probe (payload BLOB NOT NULL)")
            seeded.executemany(
                "INSERT INTO recovery_probe(payload) VALUES (zeroblob(1200))",
                [()] * 6000,
            )
            seeded.commit()
        program = r"""
import os, sqlite3, sys
from chatgpt_web2api.orchestrator.storage_policy import PrivateStoragePolicy
from chatgpt_web2api.orchestrator.store import Store

class CrashDuringMigration(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        cursor = super().execute(sql, parameters)
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("UPDATE TASKS SET STATE=?,ERROR=?,LEASE_UNTIL=NULL WHERE STATE IN ("):
            # Force journaled database-page writes outside the migrated table,
            # then terminate before the Store context commits.
            super().execute("UPDATE recovery_probe SET payload=zeroblob(2500)")
            os._exit(23)
        return cursor

real_connect = sqlite3.connect
def crash_connect(*args, **kwargs):
    kwargs["factory"] = CrashDuringMigration
    database = real_connect(*args, **kwargs)
    database.execute("PRAGMA cache_size=5")
    database.execute("PRAGMA cache_spill=ON")
    return database

sqlite3.connect = crash_connect
policy = PrivateStoragePolicy.open(sys.argv[1])
Store(policy.context.database, storage_policy=policy)
os._exit(24)
"""
        env = os.environ.copy()
        source_root = str(Path(__file__).resolve().parents[1] / "src")
        env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
        child = subprocess.run(
            [sys.executable, "-c", program, workspace.root.name],
            capture_output=True, text=True, timeout=45, env=env,
        )
        assert child.returncode == 23, child.stderr
        journal = Path(str(database) + "-journal")
        assert journal.is_file() and journal.stat().st_size > 512
        assert journal.read_bytes().startswith(bytes.fromhex("d9d505f920a163d7"))

        Store(database, storage_policy=policy)
        with closing(sqlite3.connect(database)) as initialized:
            # The migration retried, while the separate in-flight table write
            # was restored from the real hot PERSIST-mode rollback journal.
            assert initialized.execute(
                "SELECT sum(length(payload)) FROM recovery_probe"
            ).fetchone()[0] == 6000 * 1200
            assert initialized.execute(
                "SELECT state FROM tasks WHERE task_id='active'"
            ).fetchone()[0] == "needs_human"
            version = initialized.execute(
                "SELECT version FROM orchestrator_schema_versions WHERE component='task-store'"
            ).fetchone()[0]
            assert version == 2
            assert initialized.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert initialized.execute("PRAGMA foreign_key_check").fetchone() is None
        assert not journal.exists() or not journal.read_bytes().startswith(
            bytes.fromhex("d9d505f920a163d7")
        )
    finally:
        shutil.rmtree(workspace.root)


def test_protected_startup_recovers_legacy_delete_hot_journal():
    workspace = create_private_windows_workspace("pin-legacy-hot-journal-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        database = policy.context.database
        with closing(sqlite3.connect(database)) as seeded:
            seeded.execute("CREATE TABLE payloads(id INTEGER PRIMARY KEY, payload BLOB NOT NULL)")
            seeded.executemany(
                "INSERT INTO payloads(payload) VALUES (zeroblob(1200))",
                [()] * 6000,
            )
            seeded.commit()
        program = r"""
import os, sqlite3, sys
database = sqlite3.connect(sys.argv[1], isolation_level=None)
database.execute("PRAGMA cache_size=5")
database.execute("PRAGMA cache_spill=ON")
database.execute("BEGIN IMMEDIATE")
database.execute("UPDATE payloads SET payload=zeroblob(2500)")
os._exit(23)
"""
        child = subprocess.run(
            [sys.executable, "-c", program, str(database)],
            capture_output=True, text=True, timeout=30,
        )
        assert child.returncode == 23, child.stderr
        journal = Path(str(database) + "-journal")
        assert journal.is_file() and journal.stat().st_size > 512
        assert journal.read_bytes().startswith(bytes.fromhex("d9d505f920a163d7"))

        Store(database, storage_policy=policy)
        with closing(sqlite3.connect(database)) as recovered:
            assert recovered.execute(
                "SELECT sum(length(payload)) FROM payloads"
            ).fetchone()[0] == 6000 * 1200
            assert recovered.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert recovered.execute("PRAGMA foreign_key_check").fetchone() is None
        assert not journal.exists() or not journal.read_bytes().startswith(
            bytes.fromhex("d9d505f920a163d7")
        )
    finally:
        shutil.rmtree(workspace.root)


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_protected_startup_rejects_preexisting_rollback_journal_alias(
    link_kind, monkeypatch, tmp_path,
):
    workspace = create_private_windows_workspace("pin-journal-alias-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        outside = tmp_path.resolve(strict=True) / "outside-journal-marker.bin"
        outside.write_bytes(b"marker must remain unchanged")
        journal = Path(str(policy.context.database) + "-journal")
        if link_kind == "symlink":
            journal.symlink_to(outside)
        else:
            os.link(outside, journal)
        before = outside.read_bytes()
        connect_calls = []
        original = sqlite3.connect

        def guarded_connect(*args, **kwargs):
            connect_calls.append(args[0])
            return original(*args, **kwargs)

        monkeypatch.setattr("chatgpt_web2api.orchestrator.store.sqlite3.connect", guarded_connect)
        with pytest.raises((ValueError, PermissionError)):
            Store(policy.context.database, storage_policy=policy)
        assert connect_calls == [], "unsafe journal aliases must be rejected before SQLite opens"
        assert outside.read_bytes() == before
    finally:
        shutil.rmtree(workspace.root)


def test_protected_startup_recovers_abandoned_initialization_mutex(monkeypatch):
    workspace = create_private_windows_workspace("pin-abandoned-init-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        sid = _current_windows_sid()
        name = _database_initialization_mutex_name(policy.context.database, sid)
        import ctypes as c
        from ctypes import wintypes as w

        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]
        kernel.CreateMutexW.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle.restype = w.BOOL
        # Keep the object alive after the child process exits, so the next
        # waiter can observe abandonment instead of creating a new mutex.
        keeper = kernel.CreateMutexW(None, False, name)
        assert keeper
        program = r"""
import os, sys
from chatgpt_web2api.orchestrator.storage_policy import PrivateStoragePolicy
policy = PrivateStoragePolicy.open(sys.argv[1])
with policy.database_initialization(policy.context.database):
    print("owns initialization mutex", flush=True)
    os._exit(23)
"""
        env = os.environ.copy()
        source_root = str(Path(__file__).resolve().parents[1] / "src")
        env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
        try:
            child = subprocess.run(
                [sys.executable, "-c", program, workspace.root.name],
                capture_output=True, text=True, timeout=30, env=env,
            )
            assert child.returncode == 23, child.stderr
            assert "owns initialization mutex" in child.stdout

            abandoned_observations = []

            @contextmanager
            def observe_abandonment(*args, **kwargs):
                with serialize_database_initialization(*args, **kwargs) as abandoned:
                    abandoned_observations.append(abandoned)
                    yield abandoned

            monkeypatch.setattr(
                "chatgpt_web2api.orchestrator.windows_database_pin.serialize_database_initialization",
                observe_abandonment,
            )
            # WAIT_ABANDONED grants ownership, then Store runs integrity and
            # schema checks before using the database.
            Store(policy.context.database, storage_policy=policy)
            assert abandoned_observations == [True]
            with closing(sqlite3.connect(policy.context.database)) as database:
                assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert database.execute("PRAGMA foreign_key_check").fetchone() is None
                assert database.execute(
                    "SELECT version FROM orchestrator_schema_versions WHERE component='task-store'"
                ).fetchone()[0] == 2
        finally:
            assert kernel.CloseHandle(keeper)
    finally:
        shutil.rmtree(workspace.root)


def test_initialization_mutex_fails_closed_on_kernel_object_name_collision(tmp_path):
    import ctypes as c
    from ctypes import wintypes as w

    database = (tmp_path / "collision.sqlite3").absolute()
    sid = "S-1-5-21-123-456-789-1001"
    name = _database_initialization_mutex_name(database, sid)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateEventW.argtypes = [c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]
    kernel.CreateEventW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    collision = kernel.CreateEventW(None, False, False, name)
    assert collision
    try:
        with pytest.raises(OSError):
            with serialize_database_initialization(database, sid=sid):
                pytest.fail("a kernel object collision must not enter the protected operation")
    finally:
        assert kernel.CloseHandle(collision)


def test_five_processes_can_initialize_same_protected_store(tmp_path):
    workspace = create_private_windows_workspace("pin-parallel-init-" + uuid.uuid4().hex[:10])
    processes = []
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        gate = tmp_path.resolve(strict=True) / "start-initializers"
        ready_paths = [tmp_path.resolve(strict=True) / f"initializer-{index}.ready" for index in range(5)]
        source_root = str(Path(__file__).resolve().parents[1] / "src")
        env = os.environ.copy()
        env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
        program = r"""
import sys, time
from pathlib import Path
from chatgpt_web2api.orchestrator.storage_policy import PrivateStoragePolicy
from chatgpt_web2api.orchestrator.store import Store
policy = PrivateStoragePolicy.open(sys.argv[1])
gate = Path(sys.argv[2])
ready = Path(sys.argv[3])
ready.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 30
while not gate.exists():
    if time.monotonic() >= deadline:
        raise TimeoutError("parallel init gate was not released")
    time.sleep(0.01)
try:
    Store(policy.context.database, storage_policy=policy)
except Exception as error:
    print("sqlite_error", getattr(error, "sqlite_errorcode", None),
          getattr(error, "sqlite_errorname", None), repr(error), flush=True)
    raise
print("initialized")
"""
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", program, workspace.root.name,
                 str(gate), str(ready_paths[index])],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
            )
            for index in range(5)
        ]
        ready_deadline = time.monotonic() + 45
        while not all(path.exists() for path in ready_paths):
            if time.monotonic() >= ready_deadline:
                raise TimeoutError("five protected initializers did not reach the start barrier")
            time.sleep(0.01)
        gate.write_text("go", encoding="utf-8")
        results = []
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=120)
                results.append((process.returncode, stdout, stderr))
        except Exception:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=15)
            raise
        failures = [
            f"exit={code}\nstdout={stdout}\nstderr={stderr}"
            for code, stdout, stderr in results
            if code != 0 or "initialized" not in stdout
        ]
        if failures:
            pytest.fail("parallel initializer failure:\n" + "\n".join(failures))

        store = Store(policy.context.database, storage_policy=policy)
        with store._connect() as database:
            assert database.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert database.execute("PRAGMA foreign_key_check").fetchone() is None
            assert database.execute(
                "SELECT version FROM orchestrator_schema_versions WHERE component='task-store'"
            ).fetchone()[0] == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=15)
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


@pytest.mark.parametrize("operation", ["store", "observer", "backup"])
def test_policy_pins_wal_and_shm_before_sqlite_opens(monkeypatch, operation):
    workspace = create_private_windows_workspace("pin-sidecars-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        store = Store(policy.context.database, storage_policy=policy)
        store.create(TaskSpec("sidecar", "p", "implement", "synthetic"))
        observer = Observer(store.path, storage_policy=policy)
        original = sqlite3.connect
        checked = []

        def guarded_connect(*args, **kwargs):
            path = str(args[0])
            if path in (store.path, policy.context.database.as_uri() + "?mode=ro"):
                for suffix in ("-wal", "-shm"):
                    assert _attempt_delete(Path(store.path + suffix)), f"{suffix} must be pinned before SQLite open"
                checked.append(True)
            return original(*args, **kwargs)

        monkeypatch.setattr("sqlite3.connect", guarded_connect)
        if operation == "store":
            assert store.get("sidecar")["task_id"] == "sidecar"
        elif operation == "observer":
            assert observer.status("p")["tasks"] == 1
        else:
            assert snapshot_sqlite_same_directory(store.path, "backup.sqlite3", storage_policy=policy).is_file()
        assert checked
        # Pins must release after SQLite closes, including its sidecar handles.
        for suffix in ("-wal", "-shm"):
            Path(store.path + suffix).unlink()
    finally:
        shutil.rmtree(workspace.root)


@pytest.mark.parametrize("commit", [False, True])
def test_protected_wal_pins_recover_after_owned_child_crash(commit):
    workspace = create_private_windows_workspace("pin-crash-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        store = Store(policy.context.database, storage_policy=policy)
        with store._connect() as database:
            database.execute("CREATE TABLE synthetic_crash(value TEXT)")
        program = """
import os,sys
from chatgpt_web2api.orchestrator.storage_policy import PrivateStoragePolicy
from chatgpt_web2api.orchestrator.store import Store
policy = PrivateStoragePolicy.open(sys.argv[1])
store = Store(policy.context.database, storage_policy=policy)
with store._connect() as database:
    database.execute('BEGIN IMMEDIATE')
    database.execute("INSERT INTO synthetic_crash VALUES ('synthetic')")
    if sys.argv[2] == 'commit':
        database.execute('COMMIT')
    os._exit(23)
"""
        child = subprocess.run(
            [sys.executable, "-c", program, workspace.root.name, "commit" if commit else "rollback"],
            capture_output=True, text=True, timeout=45,
        )
        assert child.returncode == 23, child.stderr
        reopened = Store(policy.context.database, storage_policy=policy)
        with reopened._connect() as database:
            assert database.execute("SELECT count(*) FROM synthetic_crash").fetchone()[0] == int(commit)
            assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert database.execute("PRAGMA foreign_key_check").fetchone() is None
    finally:
        shutil.rmtree(workspace.root)
