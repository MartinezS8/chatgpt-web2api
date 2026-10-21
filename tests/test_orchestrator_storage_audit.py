import os

import pytest

from chatgpt_web2api.orchestrator import storage_audit
from chatgpt_web2api.orchestrator.storage_audit import SURFACES, classify, security_gate


def test_gate_rejects_incomplete_duplicate_and_unknown_coverage():
    rows = [dict(surface=s, status="BLOCKED") for s in SURFACES]
    assert security_gate(rows)
    assert not security_gate(rows[:-1])
    assert not security_gate(rows + [rows[0]])
    assert not security_gate(rows[:-1] + [dict(surface="unknown", status="BLOCKED")])


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
