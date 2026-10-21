"""Offline-only SQLite migration, crash and Windows workspace boundary tests."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from chatgpt_web2api.orchestrator.storage_hardening import (
    _reject_reparse,
    acl_commands,
    create_private_windows_workspace,
    parse_current_user_sid,
    snapshot_sqlite_same_directory,
)
from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.task_packages import TaskPackages
from chatgpt_web2api.orchestrator.worker_registry import WorkerRegistry


def _legacy_db(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            role TEXT NOT NULL, prompt_sha TEXT NOT NULL,
            dependencies TEXT NOT NULL, write_scopes TEXT NOT NULL,
            baseline_sha TEXT NOT NULL, review_of TEXT,
            state TEXT NOT NULL, slot INTEGER, conversation_id TEXT,
            delivery_id TEXT, evidence_ref TEXT, error TEXT,
            updated_at REAL NOT NULL
        )""")
        db.execute("""INSERT INTO tasks(task_id,project_id,role,prompt_sha,
            dependencies,write_scopes,baseline_sha,state,slot,updated_at)
            VALUES ('legacy','project','implement','a','[]','[]','','reserved',1,0)""")


def test_schema_v2_is_recorded_and_idempotent(tmp_path):
    path = tmp_path / "test.sqlite3"
    Store(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute(
            "SELECT version FROM orchestrator_schema_versions WHERE component='task-store'"
        ).fetchone()[0] == 2
    Store(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM orchestrator_schema_versions"
        ).fetchone()[0] == 1


def test_legacy_migration_is_atomic_after_injected_update_failure(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TRIGGER fail_legacy_upgrade BEFORE UPDATE ON tasks
                      BEGIN SELECT RAISE(ABORT, 'forced rollback'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced rollback"):
        Store(path)
    with closing(sqlite3.connect(path)) as db:
        names = {col[1] for col in db.execute("PRAGMA table_info(tasks)")}
        assert "claim_token" not in names  # even ALTER TABLE rolled back
        assert db.execute("SELECT state FROM tasks").fetchone()[0] == "reserved"
        assert db.execute("""SELECT name FROM sqlite_master WHERE
                              name='orchestrator_schema_versions'""").fetchone() is None
        db.execute("DROP TRIGGER fail_legacy_upgrade")
        db.commit()
    recovered = Store(path)
    assert recovered.get("legacy")["state"] == "needs_human"
    with recovered._connect() as db:
        assert db.execute("SELECT version FROM orchestrator_schema_versions").fetchone()[0] == 2


def test_future_unknown_schema_is_rejected_without_downgrade(tmp_path):
    path = tmp_path / "future.sqlite3"
    Store(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE orchestrator_schema_versions SET version=99")
    with pytest.raises(ValueError, match="unsupported task-store schema"):
        Store(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM orchestrator_schema_versions").fetchone()[0] == 99


def test_future_unknown_schema_is_rejected_without_changing_database(tmp_path):
    path = tmp_path / "future-delete-journal.sqlite3"
    Store(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("UPDATE orchestrator_schema_versions SET version=99")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="unsupported task-store schema"):
        Store(path)

    assert path.read_bytes() == before
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert db.execute("SELECT version FROM orchestrator_schema_versions").fetchone()[0] == 99


@pytest.mark.parametrize(
    "missing_column",
    ("claim_token", "claim_version", "lease_until", "reviewer_ref", "approved_by"),
)
def test_version_2_missing_required_column_is_rejected_without_repair(
    tmp_path, missing_column
):
    path = tmp_path / f"v2-missing-{missing_column}.sqlite3"
    _legacy_db(path)
    declarations = {
        "claim_token": "TEXT",
        "claim_version": "INTEGER NOT NULL DEFAULT 0",
        "lease_until": "REAL",
        "reviewer_ref": "TEXT",
        "approved_by": "TEXT",
    }
    with closing(sqlite3.connect(path)) as db, db:
        for name, declaration in declarations.items():
            if name != missing_column:
                db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {declaration}")
        db.execute("""CREATE TABLE orchestrator_schema_versions (
            component TEXT PRIMARY KEY, version INTEGER NOT NULL, updated_at REAL NOT NULL)""")
        db.execute("INSERT INTO orchestrator_schema_versions VALUES ('task-store',2,0)")

    with closing(sqlite3.connect(path)) as db:
        before_columns = {column[1] for column in db.execute("PRAGMA table_info(tasks)")}
    with pytest.raises(ValueError, match="missing mandatory columns"):
        Store(path)
    with closing(sqlite3.connect(path)) as db:
        after_columns = {column[1] for column in db.execute("PRAGMA table_info(tasks)")}
        assert after_columns == before_columns
        assert db.execute("SELECT version FROM orchestrator_schema_versions").fetchone()[0] == 2
        assert db.execute("""SELECT 1 FROM sqlite_master WHERE name='ix_tasks_project_state'""").fetchone() is None


def test_unversioned_partial_claim_schema_quarantines_active_owner(tmp_path):
    path = tmp_path / "partial-claim.sqlite3"
    _legacy_db(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE tasks ADD COLUMN claim_token TEXT")

    store = Store(path)
    task = store.get("legacy")
    assert task["state"] == "needs_human"
    assert task["claim_version"] == 0
    assert task["lease_until"] is None
    assert task["slot"] == 1


@pytest.mark.parametrize(
    ("claim_token", "claim_version", "lease_until"),
    ((None, 1, 10_000.0), ("legacy-token", 0, 10_000.0),
     ("legacy-token", 1, None)),
)
def test_unversioned_invalid_claim_values_quarantine_active_owner(
    tmp_path, claim_token, claim_version, lease_until
):
    path = tmp_path / "invalid-claim-values.sqlite3"
    _legacy_db(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE tasks ADD COLUMN claim_token TEXT")
        db.execute("ALTER TABLE tasks ADD COLUMN claim_version INTEGER NOT NULL DEFAULT 0")
        db.execute("ALTER TABLE tasks ADD COLUMN lease_until REAL")
        db.execute("ALTER TABLE tasks ADD COLUMN reviewer_ref TEXT")
        db.execute("ALTER TABLE tasks ADD COLUMN approved_by TEXT")
        db.execute("""UPDATE tasks SET claim_token=?,claim_version=?,lease_until=?
                     WHERE task_id='legacy'""",
                   (claim_token, claim_version, lease_until))

    task = Store(path).get("legacy")
    assert task["state"] == "needs_human"
    assert task["claim_version"] == claim_version
    assert task["lease_until"] is None


def test_version_2_active_task_without_claim_fencing_is_rejected(tmp_path):
    path = tmp_path / "v2-active-without-claim.sqlite3"
    store = Store(path)
    store.create(TaskSpec("active", "project", "implement", "synthetic"))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""UPDATE tasks SET state='reserved',slot=1,claim_token=NULL,
                     claim_version=0,lease_until=NULL WHERE task_id='active'""")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="without valid claim ownership"):
        Store(path)

    assert path.read_bytes() == before


def test_legacy_orphan_fk_is_detected_before_migration(tmp_path):
    path = tmp_path / "orphan.sqlite3"
    store = Store(path)
    WorkerRegistry(store)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("""INSERT INTO orchestrator_worker_assignments
            (task_id,worker_id,claim_version,state,created_at)
            VALUES ('missing','missing',1,'active',1.0)""")
    with pytest.raises(ValueError, match="foreign-key violations"):
        Store(path)


def test_crash_after_uncommitted_sqlite_writes_is_rolled_back(tmp_path):
    path = tmp_path / "crash.sqlite3"
    store = Store(path)
    store.create(TaskSpec("task", "project", "implement", "safe"))
    command = (
        "import os,sqlite3,sys\n"
        "d=sqlite3.connect(sys.argv[1],isolation_level=None)\n"
        "d.execute('BEGIN IMMEDIATE')\n"
        "d.execute(\"UPDATE tasks SET state='dispatching' WHERE task_id='task'\")\n"
        "d.execute('CREATE TABLE half_created(x INTEGER)')\n"
        "os._exit(0)\n"
    )
    subprocess.run([sys.executable, "-c", command, str(path)],
                   check=True, timeout=20)
    recovered = Store(path)
    assert recovered.get("task")["state"] == "queued"
    with recovered._connect() as db:
        assert db.execute("""SELECT name FROM sqlite_master
                              WHERE name='half_created'""").fetchone() is None


def test_online_snapshot_is_integral_and_never_clobbers_existing(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    store.create(TaskSpec("saved", "project", "implement", "synthetic"))
    result = snapshot_sqlite_same_directory(store.path, "backup-1.sqlite3")
    with closing(sqlite3.connect(result)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT task_id FROM tasks").fetchone()[0] == "saved"
    with pytest.raises(FileExistsError):
        snapshot_sqlite_same_directory(store.path, "backup-1.sqlite3")


def test_failed_snapshot_publish_removes_staging_file(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3")

    def fail_link(*_args, **_kwargs):
        raise OSError("injected publish failure")

    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.storage_hardening.os.link", fail_link
    )
    with pytest.raises(OSError, match="injected publish"):
        snapshot_sqlite_same_directory(store.path, "backup-1.sqlite3")
    assert not (tmp_path / "backup-1.sqlite3").exists()
    assert list(tmp_path.glob(".sqlite-snapshot-*")) == []


def test_unpublished_attachment_staging_file_is_cleaned(tmp_path, monkeypatch):
    store = Store(tmp_path / "store.sqlite3")
    store.create(TaskSpec("task", "project", "implement", "synthetic"))
    pack = TaskPackages(store, tmp_path / "blobs")
    item = tmp_path / "attachment.txt"
    item.write_text("synthetic content", encoding="utf-8")

    def fail_replace(*_args, **_kwargs):
        raise OSError("injected interrupted publish")

    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.task_packages.os.replace", fail_replace
    )
    with pytest.raises(OSError, match="interrupted publish"):
        pack.seal("task", "synthetic", [item], allowed_root=tmp_path)
    assert list((tmp_path / "blobs").glob(".staged-*")) == []
    with pytest.raises(ValueError, match="not sealed"):
        pack.read("task")


def test_windows_sid_csv_and_shell_free_icacls_arguments(tmp_path):
    sid = parse_current_user_sid('"DESKTOP\\worker","S-1-5-21-1-2-3-1001"\r\n')
    assert sid == "S-1-5-21-1-2-3-1001"
    commands = acl_commands(tmp_path / "private folder", sid)
    assert len(commands) == 5
    assert all(c[0] == "icacls.exe" for c in commands)
    assert commands[0][-1] == "/inheritance:r"
    assert f"*{sid}:(OI)(CI)F" in commands[1]
    assert commands[2][-3:] == ["/remove:g", "*S-1-5-32-544", "*S-1-3-4"]
    assert commands[3][-2:] == ["/setowner", f"*{sid}"]
    with pytest.raises(ValueError):
        parse_current_user_sid('"x","invalid"')


@pytest.mark.skipif(os.name != "nt", reason="requires a native Windows ACL host")
def test_windows_workspace_name_rejection_precedes_mutation():
    with pytest.raises(ValueError, match="invalid private workspace"):
        create_private_windows_workspace("../escape")


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows ACL commands")
def test_partial_windows_acl_failure_removes_new_workspace(tmp_path, monkeypatch):
    import chatgpt_web2api.orchestrator.storage_hardening as storage_hardening

    local = tmp_path / "local-app-data"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    real_run = subprocess.run

    def fail_grant(argv, *args, **kwargs):
        if argv[0] == "icacls.exe" and "/grant:r" in argv:
            raise subprocess.CalledProcessError(1, argv)
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(storage_hardening.subprocess, "run", fail_grant)
    with pytest.raises(subprocess.CalledProcessError):
        create_private_windows_workspace("partial-acl-failure")

    assert not (local / "chatgpt-web2api" / "partial-acl-failure").exists()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows reparse-point attributes")
def test_windows_junction_attributes_are_rejected_in_storage_paths(tmp_path, monkeypatch):
    junction = tmp_path / "junction"
    junction.mkdir()
    database = junction / "state.sqlite3"
    Store(database)
    store = Store(tmp_path / "other.sqlite3")
    real_lstat = Path.lstat
    real_is_symlink = Path.is_symlink

    def junction_lstat(path):
        info = real_lstat(path)
        if path == junction:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x410)
        return info

    def junction_is_symlink(path):
        return False if path == junction else real_is_symlink(path)

    monkeypatch.setattr(Path, "lstat", junction_lstat)
    monkeypatch.setattr(Path, "is_symlink", junction_is_symlink)

    with pytest.raises(ValueError, match="Windows reparse point"):
        _reject_reparse(junction)
    with pytest.raises(ValueError, match="database path cannot traverse a reparse point"):
        snapshot_sqlite_same_directory(database, "through-junction.sqlite3")
    with pytest.raises(ValueError, match="artifact root cannot traverse a reparse point"):
        TaskPackages(store, junction / "blobs")
    assert not (junction / "through-junction.sqlite3").exists()
    assert not (junction / "blobs").exists()


def test_cli_explicit_private_workspace_uses_no_remote_transport(tmp_path, monkeypatch):
    from chatgpt_web2api.orchestrator.cli import build_parser, execute
    from chatgpt_web2api.orchestrator.storage_hardening import PrivateWorkspace

    ws = PrivateWorkspace(
        root=tmp_path / "private",
        database=tmp_path / "private" / "controller.sqlite3",
        blobs=tmp_path / "private" / "blobs",
    )
    ws.root.mkdir()
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.cli.create_private_windows_workspace",
        lambda label: ws if label == "test" else None,
    )
    parser = build_parser()
    validated = []

    def validate_initialized(label):
        assert label == "test"
        assert ws.database.is_file()
        assert ws.blobs.is_dir()
        validated.append(label)

    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.cli.load_private_workspace", validate_initialized
    )
    result = execute(parser.parse_args(["init-private-workspace", "--label", "test"]))
    assert validated == ["test"]
    assert result["remote_actions_permitted"] is False
    assert ws.database.is_file()
    assert ws.blobs.is_dir()


def test_cli_explicit_backup_has_no_remote_actions(tmp_path):
    from chatgpt_web2api.orchestrator.cli import build_parser, execute

    path = tmp_path / "store.sqlite3"
    Store(path)
    parser = build_parser()
    result = execute(parser.parse_args([
        "--db", str(path), "backup-local-db", "--filename", "before-v3.sqlite3",
    ]))
    assert result["remote_actions_permitted"] is False
    assert (tmp_path / "before-v3.sqlite3").exists()


@pytest.mark.parametrize("bad", ["../x.sqlite3", "/tmp/s.sqlite3",
                                     "file.db", "file.sqlite3/.."])
def test_backup_name_cannot_escape_database_directory(tmp_path, bad):
    store = Store(tmp_path / "state.sqlite3")
    with pytest.raises(ValueError, match="backup must be"):
        snapshot_sqlite_same_directory(store.path, bad)
