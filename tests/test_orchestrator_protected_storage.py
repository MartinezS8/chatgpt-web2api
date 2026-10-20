"""Offline tests for the explicit private-workspace storage boundary."""
from __future__ import annotations

from pathlib import Path

import pytest

import chatgpt_web2api.orchestrator.storage_policy as storage_policy_module
import chatgpt_web2api.orchestrator.store as store_module
from chatgpt_web2api.orchestrator.observer import Observer
from chatgpt_web2api.orchestrator.outbox import DispatchOutbox
from chatgpt_web2api.orchestrator.private_workspace import PrivateStorageContext
from chatgpt_web2api.orchestrator.scheduler import Scheduler
from chatgpt_web2api.orchestrator.stage_maintenance import cleanup_managed_stages
from chatgpt_web2api.orchestrator.storage_hardening import (
    snapshot_sqlite_same_directory,
)
from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.task_packages import TaskPackages
from chatgpt_web2api.orchestrator.worker_registry import WorkerRegistry


def _context(base: Path) -> PrivateStorageContext:
    root = base / "private-workspace"
    root.mkdir(parents=True)
    blobs = root / "blobs"
    blobs.mkdir()
    return PrivateStorageContext(root, root / "controller.sqlite3", blobs)


def _install_loader(monkeypatch, context: PrivateStorageContext):
    calls: list[str] = []

    def load(label: str) -> PrivateStorageContext:
        calls.append(label)
        return context

    monkeypatch.setattr(storage_policy_module, "load_private_workspace", load)
    return calls


def _make_policy(monkeypatch, tmp_path: Path):
    context = _context(tmp_path)
    calls = _install_loader(monkeypatch, context)
    policy = storage_policy_module.PrivateStoragePolicy.open("test-workspace")
    return context, policy, calls


def _forbid_sqlite_connect(monkeypatch):
    calls: list[tuple[tuple, dict]] = []

    def forbidden_connect(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("SQLite must not be opened after storage policy denial")

    monkeypatch.setattr(store_module.sqlite3, "connect", forbidden_connect)
    return calls


def test_policy_reloads_native_context_and_rejects_a_forged_context(
    tmp_path, monkeypatch
):
    trusted = _context(tmp_path / "trusted")
    forged = _context(tmp_path / "forged")
    current = [trusted]
    calls: list[str] = []

    def load(label: str) -> PrivateStorageContext:
        calls.append(label)
        return current[0]

    monkeypatch.setattr(storage_policy_module, "load_private_workspace", load)
    policy = storage_policy_module.PrivateStoragePolicy.open("test-workspace")
    assert calls == ["test-workspace"]
    assert policy.check() is trusted
    assert calls == ["test-workspace", "test-workspace"]

    forged_policy = storage_policy_module.PrivateStoragePolicy(
        "test-workspace", forged
    )
    with pytest.raises(PermissionError, match="binding changed"):
        forged_policy.check()
    assert calls == ["test-workspace", "test-workspace", "test-workspace"]

    current[0] = forged
    with pytest.raises(PermissionError, match="binding changed"):
        policy.check()
    assert calls[-1] == "test-workspace"


def test_external_database_is_rejected_before_sqlite_connect(tmp_path, monkeypatch):
    _, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    outside = tmp_path / "outside" / "controller.sqlite3"
    connect_calls = _forbid_sqlite_connect(monkeypatch)

    with pytest.raises(ValueError, match="protected database"):
        Store(outside, storage_policy=policy)

    assert connect_calls == []
    assert not outside.parent.exists()


def test_external_blob_root_is_rejected_without_creating_it(tmp_path, monkeypatch):
    context, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    store = Store(context.database, storage_policy=policy)
    outside = tmp_path / "outside" / "blobs"

    with pytest.raises(ValueError, match="protected blobs"):
        TaskPackages(store, outside)

    assert not outside.exists()
    assert not outside.parent.exists()


def test_policy_revocation_after_store_creation_prevents_sqlite_connect(
    tmp_path, monkeypatch
):
    context, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    store = Store(context.database, storage_policy=policy)
    replacement = _context(tmp_path / "replacement")
    monkeypatch.setattr(
        storage_policy_module,
        "load_private_workspace",
        lambda _label: replacement,
    )
    connect_calls = _forbid_sqlite_connect(monkeypatch)

    with pytest.raises(PermissionError, match="binding changed"):
        store.get("missing")

    assert connect_calls == []


def test_mutated_store_path_is_rejected_before_sqlite_connect(tmp_path, monkeypatch):
    context, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    store = Store(context.database, storage_policy=policy)
    outside = tmp_path / "outside" / "mutated.sqlite3"
    store.path = str(outside)
    connect_calls = _forbid_sqlite_connect(monkeypatch)

    with pytest.raises(ValueError, match="protected database"):
        store.get("missing")

    assert connect_calls == []
    assert not outside.exists()


def test_protected_package_rejects_external_source_without_writing_blobs(
    tmp_path, monkeypatch
):
    context, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    store = Store(context.database, storage_policy=policy)
    store.create(TaskSpec("task", "project", "implement", "safe prompt"))
    packages = TaskPackages(store, context.blobs)
    allowed_root = context.root / "inputs"
    allowed_root.mkdir()
    external_root = tmp_path / "external"
    external_root.mkdir()
    external_source = external_root / "attachment.txt"
    external_source.write_text("synthetic attachment", encoding="utf-8")
    same_workspace_source_root = context.root / "other-inputs"
    same_workspace_source_root.mkdir()
    same_workspace_source = same_workspace_source_root / "attachment.txt"
    same_workspace_source.write_text("also synthetic", encoding="utf-8")

    with pytest.raises(ValueError, match="protected input"):
        packages.seal(
            "task", "safe prompt", [external_source], allowed_root=allowed_root
        )

    with pytest.raises(ValueError, match="protected input"):
        packages.seal("task", "safe prompt", [], allowed_root=external_root)

    with pytest.raises(ValueError, match="attachment must be under allowed_root"):
        packages.seal(
            "task", "safe prompt", [same_workspace_source], allowed_root=allowed_root
        )

    assert list(context.blobs.iterdir()) == []
    with pytest.raises(ValueError, match="not sealed"):
        packages.read("task")


def test_legacy_store_and_packages_remain_unprotected(tmp_path):
    store = Store(tmp_path / "legacy.sqlite3")
    packages = TaskPackages(store, tmp_path / "legacy-blobs")

    assert store.storage_policy is None
    assert packages.storage_policy is None


def test_protected_policy_cannot_be_removed_from_store(tmp_path, monkeypatch):
    context, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    store = Store(context.database, storage_policy=policy)

    with pytest.raises(AttributeError):
        store.storage_policy = None

    assert store.storage_policy is policy


def test_duck_typed_storage_policy_is_rejected_before_sqlite_connect(
    tmp_path, monkeypatch
):
    context, _, _ = _make_policy(monkeypatch, tmp_path / "private")

    class DuckPolicy:
        def check(self):
            return context

        def database(self, path):
            return Path(path)

    connect_calls = _forbid_sqlite_connect(monkeypatch)
    with pytest.raises(TypeError, match="native-validated storage policy"):
        Store(context.database, storage_policy=DuckPolicy())

    assert connect_calls == []


def test_mixed_store_policies_are_rejected_before_scheduler_or_outbox_writes(
    tmp_path, monkeypatch
):
    context, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    protected_store = Store(context.database, storage_policy=policy)
    legacy_store = Store(context.database)
    assert protected_store.path == legacy_store.path
    protected_packages = TaskPackages(protected_store, context.blobs)
    legacy_packages = TaskPackages(legacy_store, context.blobs)
    legacy_registry = WorkerRegistry(legacy_store)

    connect_calls = _forbid_sqlite_connect(monkeypatch)
    with pytest.raises(ValueError, match="outbox storage policies must match"):
        DispatchOutbox(protected_store, legacy_packages)
    with pytest.raises(ValueError, match="scheduler storage policies must match"):
        Scheduler(protected_store, legacy_registry, protected_packages)

    assert connect_calls == []


def test_external_database_backup_is_rejected_before_lock_or_stage_creation(
    tmp_path, monkeypatch
):
    context, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()
    outside_database = outside_directory / "controller.sqlite3"
    Store(outside_database)

    with pytest.raises(ValueError, match="protected database"):
        snapshot_sqlite_same_directory(
            outside_database, "backup.sqlite3", storage_policy=policy
        )

    assert outside_database.is_file()
    assert not (outside_directory / ".orchestrator-stage.lock").exists()
    assert list(outside_directory.glob(".sqlite-snapshot-v2-*")) == []
    assert not (outside_directory / "backup.sqlite3").exists()


def test_external_stage_cleanup_is_rejected_before_lock_creation(
    tmp_path, monkeypatch
):
    _, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    outside = tmp_path / "outside-stages"
    outside.mkdir()
    stale_stage = outside / f".staged-v2-{'0' * 32}"
    stale_stage.write_text("synthetic stage", encoding="utf-8")

    with pytest.raises(ValueError, match="private workspace"):
        cleanup_managed_stages(outside, min_age_seconds=0, dry_run=False,
                               storage_policy=policy)

    assert stale_stage.is_file()
    assert not (outside / ".orchestrator-stage.lock").exists()


def test_observer_read_after_policy_revocation_is_refused_before_connect(
    tmp_path, monkeypatch
):
    context, policy, _ = _make_policy(monkeypatch, tmp_path / "private")
    store = Store(context.database, storage_policy=policy)
    store.create(TaskSpec("task", "project", "implement", "safe prompt"))
    observer = Observer(context.database, storage_policy=policy)
    replacement = _context(tmp_path / "replacement")
    monkeypatch.setattr(
        storage_policy_module,
        "load_private_workspace",
        lambda _label: replacement,
    )
    connect_calls = _forbid_sqlite_connect(monkeypatch)

    with pytest.raises(PermissionError, match="binding changed"):
        observer.status("project")

    assert connect_calls == []

