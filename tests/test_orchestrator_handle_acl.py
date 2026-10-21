"""Handle-bound descriptor tests, not effective second-user access proofs."""
import os
import shutil
import uuid

import pytest

from chatgpt_web2api.orchestrator.storage_hardening import create_private_windows_workspace
from chatgpt_web2api.orchestrator.storage_policy import PrivateStoragePolicy
from chatgpt_web2api.orchestrator.store import Store
from chatgpt_web2api.orchestrator.windows_acl import read_windows_descriptor
from chatgpt_web2api.orchestrator.windows_database_pin import pin_database

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows handle ACLs")


def test_pin_validates_opened_root_and_child_descriptors():
    workspace = create_private_windows_workspace("handle-acl-" + uuid.uuid4().hex[:10])
    try:
        root = workspace.root.resolve(strict=True)
        sid = read_windows_descriptor(root)["owner_sid"]
        with pin_database(root / "controller.sqlite3", create=True, expected_sid=sid):
            assert (root / "controller.sqlite3").is_file()
    finally:
        shutil.rmtree(workspace.root)


def test_pin_rejects_extra_child_trustee_and_releases_handles(monkeypatch):
    import chatgpt_web2api.orchestrator.windows_database_pin as native

    workspace = create_private_windows_workspace("handle-child-" + uuid.uuid4().hex[:10])
    try:
        root = workspace.root.resolve(strict=True)
        database = root / "controller.sqlite3"
        database.write_bytes(b"synthetic unchanged")
        sid = read_windows_descriptor(root)["owner_sid"]
        original = native.read_windows_handle_descriptor
        calls = []

        def altered_child(handle):
            descriptor = original(handle)
            calls.append(handle)
            if len(calls) == 2:
                descriptor["aces"].append({"sid": "S-1-1-0", "type": 0, "mask": 0x1F01FF, "flags": 0})
            return descriptor

        monkeypatch.setattr(native, "read_windows_handle_descriptor", altered_child)
        with pytest.raises(PermissionError, match="unexpected access"):
            with pin_database(database, expected_sid=sid):
                pytest.fail("unrelated child trustee must not enter operation")
        assert len(calls) == 2
        assert database.read_bytes() == b"synthetic unchanged"
        database.unlink()
    finally:
        shutil.rmtree(workspace.root)


def test_pin_rejects_wrong_expected_owner_before_operation(tmp_path):
    database = tmp_path.resolve(strict=True) / "synthetic.sqlite3"
    with pytest.raises(PermissionError, match="owner"):
        with pin_database(database, create=True, expected_sid="S-1-5-21-1-2-3-99999"):
            pytest.fail("wrong principal must not enter operation")
    # The root is rejected before even creating a main file.
    assert not database.exists()


def test_handle_readback_failure_has_no_path_fallback(tmp_path, monkeypatch):
    import chatgpt_web2api.orchestrator.windows_database_pin as native

    database = tmp_path.resolve(strict=True) / "synthetic.sqlite3"
    calls = []

    def deny(handle):
        calls.append(handle)
        raise PermissionError("synthetic native handle inspection failure")

    monkeypatch.setattr(native, "read_windows_handle_descriptor", deny)
    with pytest.raises(PermissionError, match="native handle inspection failure"):
        with pin_database(database, create=True, expected_sid="S-1-5-21-1-2-3-99999"):
            pytest.fail("handle inspection must not fall back")
    assert len(calls) == 1
    assert not database.exists()
    moved = database.parent.with_name(database.parent.name + "-released")
    database.parent.rename(moved)
    moved.rename(database.parent)


def test_protected_store_rejects_handle_acl_before_sqlite_and_creation(monkeypatch):
    workspace = create_private_windows_workspace("handle-policy-" + uuid.uuid4().hex[:10])
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        calls = []

        def deny(handle):
            raise PermissionError("synthetic handle ACL revocation")

        def forbidden(*args, **kwargs):
            calls.append(args)
            raise AssertionError("SQLite must not open after handle ACL denial")

        monkeypatch.setattr("chatgpt_web2api.orchestrator.windows_database_pin.read_windows_handle_descriptor", deny)
        monkeypatch.setattr("sqlite3.connect", forbidden)
        with pytest.raises(PermissionError, match="handle ACL revocation"):
            Store(policy.context.database, storage_policy=policy)
        assert not calls
        assert not policy.context.database.exists()
    finally:
        shutil.rmtree(workspace.root)
