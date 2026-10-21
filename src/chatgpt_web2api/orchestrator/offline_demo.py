"""Windows-only fixed offline demo entry; never adopts an unrelated database."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager

import portalocker

from .mock_sandbox import MockSandbox
from .observer import Observer
from .storage_hardening import create_private_windows_workspace
from .storage_policy import PrivateStoragePolicy
from .store import Store
from .task_packages import TaskPackages

_MARKER = ".offline-demo-v1.json"


@contextmanager
def _cooperative_lock(policy):
    """Only cooperating demo controllers; no hostile path-swap protection."""
    root = policy.check().root
    path = root / ".offline-demo.lock"
    if not path.exists():
        try:
            with path.open("xb"):
                pass
        except FileExistsError:
            pass
    policy.source(path)
    with path.open("r+b") as stream:
        portalocker.lock(stream, portalocker.LOCK_EX | portalocker.LOCK_NB)
        try:
            policy.check()
            yield
        finally:
            portalocker.unlock(stream)


def _verify_existing_identity(policy):
    context = policy.check()
    marker_path = policy.source(context.root / _MARKER)
    if marker_path.stat().st_size > 1024:
        raise ValueError("invalid demo workspace marker")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if (not isinstance(marker, dict) or set(marker) != {"schema", "label", "nonce"}
            or marker["schema"] != 1 or marker["label"] != policy.label
            or not isinstance(marker["nonce"], str)
            or not re.fullmatch(r"[0-9a-f]{32}", marker["nonce"])):
        raise ValueError("invalid demo workspace marker")
    # Check the owned DB identity WITHOUT creating/migrating an unrelated DB.
    observer = Observer(context.database, storage_policy=policy)
    identities = observer._read("SELECT nonce FROM orchestrator_demo_identity LIMIT ?", limit=2)
    if identities != [{"nonce": marker["nonce"]}]:
        raise ValueError("demo database nonce mismatch")
    return marker["nonce"]


def _open_existing(policy):
    nonce = _verify_existing_identity(policy)
    context = policy.check()
    store = Store(context.database, storage_policy=policy)
    return MockSandbox(store, TaskPackages(store, context.blobs), nonce=nonce)


def execute_demo(*, action: str, label: str, crash_after_intent: bool = False) -> dict:
    if action not in {"init", "run", "status", "doctor"}:
        raise ValueError("unknown demo action")
    if crash_after_intent and action != "run":
        raise ValueError("crash injection only supports demo run")
    try:
        if action == "init":
            workspace = create_private_windows_workspace(label)
            workspace.blobs.mkdir()  # Inherit the verified root ACL.
            policy = PrivateStoragePolicy.open(label)
            with _cooperative_lock(policy):
                nonce = uuid.uuid4().hex
                context = policy.check()
                with (context.root / _MARKER).open("x", encoding="utf-8") as stream:
                    json.dump({"schema": 1, "label": label, "nonce": nonce}, stream)
                policy.source(context.root / _MARKER)
                store = Store(context.database, storage_policy=policy)
                packages = TaskPackages(store, context.blobs)
                sandbox = MockSandbox(store, packages, nonce=nonce, create=True)
                sandbox.initialize()
                return {**sandbox.inspect(), "label": label, "initialized": True,
                        "workspace": str(context.root), "exit_code": 0}
        policy = PrivateStoragePolicy.open(label)
        # Do not create even the demo lock file in an unrelated private root.
        _verify_existing_identity(policy)
        with _cooperative_lock(policy):
            sandbox = _open_existing(policy)
            if action == "run":
                result = sandbox.run(crash_after_intent=crash_after_intent)
            else:
                # Hash checks do not seal or replace missing/changed packages.
                for task in sandbox.store.all("offline-demo"):
                    sandbox.packages.read(task["task_id"], verify_blobs=True)
                result = sandbox.inspect()
            healthy = result["status"] in {"ready", "demo_complete"}
            code = 0 if healthy and (action != "run" or result["status"] == "demo_complete") else 2
            return {**result, "label": label, "exit_code": code}
    except sqlite3.Error as exc:
        raise ValueError("demo database rejected; no automatic repair or retry") from exc
    except portalocker.LockException as exc:
        raise ValueError("another cooperating demo controller holds the workspace lock") from exc
