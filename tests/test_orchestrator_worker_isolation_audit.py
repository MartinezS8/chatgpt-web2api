"""A disposable probe is diagnostic, never trusted worker authorization."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from chatgpt_web2api.orchestrator.worker_isolation_audit import (
    _assessment,
    _check,
    _probe_root,
    probe_disposable_root,
)


def test_only_explicit_disposable_probe_roots_are_accepted(tmp_path):
    candidate = tmp_path / "chatgpt-web2api" / "w2a-isolation-probe-abcdef"
    assert _probe_root(candidate) == candidate
    for invalid in (
        tmp_path / "chatgpt-web2api" / "controller",
        tmp_path / "other" / "w2a-isolation-probe-abcdef",
        tmp_path / "chatgpt-web2api" / "w2a-isolation-probe-abcdef" / "..",
        Path("w2a-isolation-probe-abcdef"),
    ):
        with pytest.raises(ValueError, match="disposable"):
            _probe_root(invalid)


@pytest.mark.parametrize(("result", "expected"), [
    ({"read": "DENIED", "append": "DENIED", "create": "DENIED",
      "rename": "DENIED", "delete": "DENIED"},
     "OBSERVED_DENIAL_REQUIRES_INDEPENDENT_ATTESTATION"),
    ({"read": "DENIED", "append": "ALLOWED"}, "FAIL_ACCESS_ALLOWED"),
    ({"read": "DENIED", "append": "INCONCLUSIVE_MISSING"}, "INCONCLUSIVE"),
    ({}, "INCONCLUSIVE"),
])
def test_isolation_assessment_never_calls_simple_denial_production_ready(result, expected):
    assert _assessment(result) == expected


def test_access_probe_classifies_errors_without_hiding_success():
    def deny():
        raise PermissionError("synthetic")

    def missing():
        raise FileNotFoundError("synthetic")

    def error():
        raise OSError("synthetic")

    assert _check(deny) == "DENIED"
    assert _check(missing) == "INCONCLUSIVE_MISSING"
    assert _check(error) == "INCONCLUSIVE_ERROR"
    assert _check(lambda: None) == "ALLOWED"


@pytest.mark.skipif(os.name != "nt", reason="native Windows process identity")
def test_same_sid_rejected_before_touching_synthetic_marker(tmp_path):
    from chatgpt_web2api.orchestrator.worker_isolation_audit import current_windows_sid

    root = tmp_path / "chatgpt-web2api" / "w2a-isolation-probe-abcdef"
    root.mkdir(parents=True)
    marker = root / "probe-sentinel.bin"
    marker.write_bytes(b"synthetic sentinel unchanged")
    sid = current_windows_sid()
    result = probe_disposable_root(root, expected_controller_sid=sid)
    assert result["status"] == "FAIL_SAME_WINDOWS_IDENTITY"
    assert result["checks"] == {}
    assert result["live_send_permitted"] is False
    assert marker.read_bytes() == b"synthetic sentinel unchanged"

@pytest.mark.skipif(os.name != "nt", reason="native Windows marker isolation behavior")
def test_allowed_probe_access_never_changes_primary_attestation_marker(tmp_path, monkeypatch):
    import chatgpt_web2api.orchestrator.worker_isolation_audit as audit

    root = tmp_path / "chatgpt-web2api" / "w2a-isolation-probe-abcdef"
    root.mkdir(parents=True)
    original = root / audit._MARKER
    original.write_bytes(b"read-only synthetic original")
    append = root / audit._APPEND_MARKER
    append.write_bytes(b"append synthetic")
    rename = root / audit._RENAME_MARKER
    rename.write_bytes(b"rename synthetic")
    delete = root / audit._DELETE_MARKER
    delete.write_bytes(b"delete synthetic")
    monkeypatch.setattr(audit, "current_windows_sid", lambda: "S-1-5-21-777-1002")

    report = audit.probe_disposable_root(
        root, expected_controller_sid="S-1-5-21-777-1001",
    )
    assert report["status"] == "FAIL_ACCESS_ALLOWED"
    assert report["checks"] == {
        "read": "ALLOWED", "append": "ALLOWED", "create": "ALLOWED",
        "rename": "ALLOWED", "delete": "ALLOWED",
    }
    assert report["production_authorized"] is False
    assert original.read_bytes() == b"read-only synthetic original"
    assert append.read_bytes() == b"append syntheticx"
    assert rename.read_bytes() == b"rename synthetic"
    assert not delete.exists()


@pytest.mark.skipif(os.name != "nt", reason="native Windows marker isolation behavior")
def test_missing_operation_markers_are_inconclusive_not_false_denial(tmp_path, monkeypatch):
    import chatgpt_web2api.orchestrator.worker_isolation_audit as audit

    root = tmp_path / "chatgpt-web2api" / "w2a-isolation-probe-abcdef"
    root.mkdir(parents=True)
    original = root / audit._MARKER
    original.write_bytes(b"synthetic original")
    monkeypatch.setattr(audit, "current_windows_sid", lambda: "S-1-5-21-777-1002")

    report = audit.probe_disposable_root(
        root, expected_controller_sid="S-1-5-21-777-1001",
    )
    assert report["status"] == "FAIL_ACCESS_ALLOWED"
    assert report["checks"]["read"] == "ALLOWED"
    for operation in ("append", "rename", "delete"):
        assert report["checks"][operation] == "INCONCLUSIVE_MISSING"
    assert not (root / audit._APPEND_MARKER).exists()
    assert original.read_bytes() == b"synthetic original"
