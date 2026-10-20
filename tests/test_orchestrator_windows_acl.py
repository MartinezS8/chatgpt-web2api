"""DACL evidence is deliberately distinct from second-user effective access."""
import copy
import os
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from chatgpt_web2api.orchestrator.stage_maintenance import cleanup_managed_stages
from chatgpt_web2api.orchestrator.storage_hardening import (
    create_private_windows_workspace,
    parse_current_user_sid,
)
from chatgpt_web2api.orchestrator.windows_acl import (
    read_windows_descriptor,
    validate_private_descriptor,
)

SID = "S-1-5-21-1-2-3-1001"


def descriptor():
    return {"owner_sid": SID, "protected": True, "aces": [
        {"type": 0, "flags": 3, "mask": 0x1F01FF, "sid": SID},
        {"type": 0, "flags": 3, "mask": 0x1F01FF, "sid": "S-1-5-18"},
    ]}


def test_exact_private_descriptor_is_accepted():
    validate_private_descriptor(descriptor(), SID)


@pytest.mark.parametrize("mutation", ["owner", "inheritance", "everyone", "inherited",
                                     "deny", "rights", "missing", "duplicate"])
def test_descriptor_violations_fail_closed(mutation):
    value = copy.deepcopy(descriptor())
    if mutation == "owner":
        value["owner_sid"] = "S-1-1-0"
    elif mutation == "inheritance":
        value["protected"] = False
    elif mutation == "everyone":
        value["aces"].append({"type": 0, "flags": 3, "mask": 1, "sid": "S-1-1-0"})
    elif mutation == "inherited":
        value["aces"][0]["flags"] |= 16
    elif mutation == "deny":
        value["aces"][0]["type"] = 1
    elif mutation == "rights":
        value["aces"][0]["mask"] = 1
    elif mutation == "missing":
        value["aces"] = []
    else:
        value["aces"][1] = value["aces"][0]
    with pytest.raises(PermissionError):
        validate_private_descriptor(value, SID)


@pytest.mark.skipif(os.name != "nt", reason="native Windows DACL readback")
def test_native_workspace_owner_dacl_and_extra_trustee_rejection():
    sid = parse_current_user_sid(subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"], check=True,
        capture_output=True, text=True, timeout=15).stdout)
    label = "gate-acl-" + uuid.uuid4().hex[:16]
    workspace = create_private_windows_workspace(label)
    try:
        validate_private_descriptor(read_windows_descriptor(workspace.root), sid)
        child = workspace.root / "synthetic.txt"
        child.write_text("synthetic", encoding="utf-8")
        assert child.read_text(encoding="utf-8") == "synthetic"
        child.unlink()
        with pytest.raises(FileExistsError):
            create_private_windows_workspace(label)
        subprocess.run(["icacls.exe", str(workspace.root), "/grant",
                        "*S-1-1-0:(OI)(CI)R"], check=True, capture_output=True, timeout=15)
        with pytest.raises(PermissionError):
            validate_private_descriptor(read_windows_descriptor(workspace.root), sid)
    finally:
        workspace.root.rmdir()


@pytest.mark.skipif(os.name == "nt", reason="non-Windows refusal")
def test_native_inspection_is_not_emulated_on_other_systems(tmp_path):
    with pytest.raises(OSError, match="requires Windows"):
        read_windows_descriptor(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows ancestor reparse attributes")
def test_staging_cleanup_rejects_ancestor_junction_before_lock_creation(tmp_path, monkeypatch):
    parent = tmp_path / "junction"
    root = parent / "stages"
    root.mkdir(parents=True)
    real_lstat = Path.lstat

    def changed(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path == parent:
            return SimpleNamespace(st_file_attributes=0x410, st_mode=info.st_mode)
        return info

    monkeypatch.setattr(Path, "lstat", changed)
    with pytest.raises(ValueError, match="reparse"):
        cleanup_managed_stages(root, dry_run=False)
    assert list(root.iterdir()) == []
