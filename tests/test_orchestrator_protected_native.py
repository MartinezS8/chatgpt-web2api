"""Real native policy roundtrip on a newly provisioned disposable workspace."""
import hashlib
import os
import shutil
import uuid

import pytest

from chatgpt_web2api.orchestrator.storage_hardening import (
    create_private_windows_workspace,
    snapshot_sqlite_same_directory,
)
from chatgpt_web2api.orchestrator.storage_policy import PrivateStoragePolicy
from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.task_packages import TaskPackages


@pytest.mark.skipif(os.name != "nt", reason="native Windows ACL policy")
def test_native_protected_roundtrip():
    label = "protected-" + uuid.uuid4().hex[:12]
    workspace = create_private_windows_workspace(label)
    restored = None
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(label)
        store = Store(policy.context.database, storage_policy=policy)
        packages = TaskPackages(store, policy.context.blobs)
        source = policy.context.root / "synthetic.txt"
        source.write_text("synthetic", encoding="utf-8")
        store.create(TaskSpec("native", "p", "implement", "prompt"))
        packages.seal("native", "prompt", [source], allowed_root=policy.context.root)
        assert packages.read("native")["attachments"][0]["sha256"] == hashlib.sha256(b"synthetic").hexdigest()
        backup = snapshot_sqlite_same_directory(store.path, "test-backup.sqlite3", storage_policy=policy)
        assert backup.is_file()
        policy.check()
        restored_label = "restore-" + uuid.uuid4().hex[:12]
        restored = create_private_windows_workspace(restored_label)
        restored.blobs.mkdir()
        shutil.copyfile(backup, restored.database)
        for blob in policy.context.blobs.iterdir():
            if len(blob.name) == 64:
                shutil.copyfile(blob, restored.blobs / blob.name)
        reopened_policy = PrivateStoragePolicy.open(restored_label)
        reopened = Store(reopened_policy.context.database, storage_policy=reopened_policy)
        assert TaskPackages(reopened, reopened_policy.context.blobs).read("native")["task_id"] == "native"
        with reopened._connect() as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("PRAGMA foreign_key_check").fetchone() is None
    finally:
        if restored is not None:
            shutil.rmtree(restored.root)
        shutil.rmtree(workspace.root)
