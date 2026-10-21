import os
from pathlib import Path

import pytest

from chatgpt_web2api.orchestrator import storage_audit
from chatgpt_web2api.orchestrator.storage_audit import SURFACES, classify, security_gate


def test_gate_rejects_incomplete_duplicate_and_unknown_coverage():
    rows = [dict(surface=s, status="BLOCKED") for s in SURFACES]
    assert security_gate(rows)
    assert not security_gate(rows[:-1])
    assert not security_gate(rows + [rows[0]])
    assert not security_gate(rows[:-1] + [dict(surface="unknown", status="BLOCKED")])
    rows[0]["cleanup_error"] = "PermissionError"
    assert not security_gate(rows)


@pytest.mark.parametrize("status", ["NOT_TESTED", "REPRODUCED_UNSAFE", "PASS"])
def test_gate_never_accepts_untested_or_unsafe_surface(status):
    rows = [dict(surface=s, status="BLOCKED") for s in SURFACES]
    rows[0]["status"] = status
    assert not security_gate(rows)


def test_postflight_exception_cannot_hide_a_write():
    assert classify(reached=True, winerror=32, marker_changed=True,
                    protected_changed=False, error="ValueError") == "REPRODUCED_UNSAFE"
    assert classify(reached=True, winerror=None, marker_changed=False,
                    protected_changed=True, error="DatabaseError") == "REPRODUCED_UNSAFE"
    assert classify(reached=True, winerror=None, marker_changed=False,
                    protected_changed=False, path_changed=True,
                    error="ValueError") == "REPRODUCED_UNSAFE"
    assert classify(reached=True, winerror=None, marker_changed=False,
                    protected_changed=False, write_succeeded=True) == "REPRODUCED_UNSAFE"


def test_other_errors_and_unreached_hooks_are_not_protection():
    for reached, code in ((False, 32), (True, 5), (True, None)):
        assert classify(reached=reached, winerror=code, marker_changed=False,
                        protected_changed=False) == "NOT_TESTED"
    assert classify(reached=True, winerror=32, marker_changed=False,
                    protected_changed=False) == "BLOCKED"


def test_diagnostic_exit_does_not_grant_security_acceptance(monkeypatch, capsys):
    monkeypatch.setattr(storage_audit, "audit", lambda: {"model2_accepted": False})
    assert storage_audit.main([]) == 1
    assert storage_audit.main(["--diagnostic"]) == 0
    assert '"model2_accepted": false' in capsys.readouterr().out


@pytest.mark.skipif(os.name != "nt", reason="native Windows disposable probe")
def test_native_probe_reports_content_mutation_despite_sqlite_error():
    row = storage_audit._probe("content_write")
    assert row["status"] == "REPRODUCED_UNSAFE"
    assert row["operation_error"] == "DatabaseError"
    assert row["protected_before"] != row["protected_after"]
    assert row["outside_before"] == row["outside_after"]


@pytest.mark.skipif(os.name != "nt", reason="native Windows disposable probe")
def test_cleanup_failure_preserves_unsafe_evidence(monkeypatch):
    original = storage_audit.shutil.rmtree
    retained = []

    def fail_workspace_cleanup(path, *args, **kwargs):
        if Path(path).name.startswith("audit-"):
            retained.append(path)
            raise PermissionError("synthetic cleanup failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(storage_audit.shutil, "rmtree", fail_workspace_cleanup)
    try:
        row = storage_audit._probe("content_write")
        assert row["status"] == "REPRODUCED_UNSAFE"
        assert row["cleanup_error"] == "PermissionError"
        assert row["protected_before"] != row["protected_after"]
        assert retained
    finally:
        for path in retained:
            original(path)


@pytest.mark.skipif(os.name != "nt", reason="native Windows disposable probe")
def test_marker_postflight_failure_preserves_attacker_observation(monkeypatch):
    original = storage_audit._digest
    marker_reads = []

    def failing_digest(path):
        if path.name == "synthetic-marker.bin":
            marker_reads.append(path)
            if len(marker_reads) == 2:
                raise PermissionError("synthetic marker postflight failure")
        return original(path)

    monkeypatch.setattr(storage_audit, "_digest", failing_digest)
    row = storage_audit._probe("content_write")
    assert row["status"] == "REPRODUCED_UNSAFE"
    assert row["wrote"] is True
    assert row["post_observation_error"] == "PermissionError"
    assert row["operation_error"] == "DatabaseError"
    assert row["outside_before"]


@pytest.mark.skipif(os.name != "nt", reason="native Windows disposable probe")
@pytest.mark.parametrize("surface", ["main", "wal", "shm", "migration_journal"])
def test_native_preopen_replacement_is_blocked(surface):
    row = storage_audit._probe(surface)
    assert row["status"] == "BLOCKED"
    assert row["unlinked"] is False
    assert row["winerror"] == 32
    assert row["outside_before"] == row["outside_after"]


@pytest.mark.skipif(os.name != "nt", reason="native Windows disposable probe")
def test_hot_recovery_path_change_is_reported_despite_late_failure():
    row = storage_audit._probe("hot_recovery_journal")
    assert row["status"] == "REPRODUCED_UNSAFE"
    assert row["unlinked"] is True
    assert row["hook"] == "before_sqlite_journal_recovery"
    assert row["outside_before"] == row["outside_after"]
