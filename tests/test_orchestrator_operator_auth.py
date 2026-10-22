"""Native Windows-token offline quarantine audit; strictly no send/release."""
from __future__ import annotations

import os
import sqlite3

import pytest

import chatgpt_web2api.orchestrator.operator_auth as auth
from chatgpt_web2api.orchestrator.app_server_delivery import AppServerDeliveryLedger
from chatgpt_web2api.orchestrator.app_server_fake import (
    AttemptBinding,
    FakeAppServerScenario,
    OfflineFakeAppServer,
    UnknownDelivery,
)
from chatgpt_web2api.orchestrator.outbox import DispatchOutbox
from chatgpt_web2api.orchestrator.scheduler import Scheduler
from chatgpt_web2api.orchestrator.store import Store, TaskSpec, TaskState
from chatgpt_web2api.orchestrator.task_packages import TaskPackages
from chatgpt_web2api.orchestrator.worker_registry import WorkerRegistry, WorkerSpec

_OPERATOR = "S-1-5-21-555-666-777-1001"
_OTHER = "S-1-5-21-555-666-777-1002"


@pytest.fixture
def quarantined(tmp_path, monkeypatch):
    store = Store(tmp_path / "audit.sqlite3")
    workers = WorkerRegistry(store)
    packages = TaskPackages(store, tmp_path / "blobs")
    store.create(TaskSpec("task-auth", "project-auth", "implement", "synthetic auth"))
    workers.register(WorkerSpec(
        "worker-auth", "account-auth", "project-auth", "implement",
        "mock", "fake:worker-auth",
    ))
    packages.seal("task-auth", "synthetic auth")
    claimed = Scheduler(store, workers, packages).claim_next("account-auth", "project-auth")
    outbox = DispatchOutbox(store, packages)
    attempt = outbox.begin_mock_for_assignment(
        task_id="task-auth", worker_id="worker-auth",
        claim_token=claimed["task"]["claim_token"],
    )
    binding = AttemptBinding(
        controller_id="controller-auth", worker_id="worker-auth",
        account_id="account-auth", project_id="project-auth",
        task_id="task-auth", attempt_id=attempt["attempt_id"],
    )
    ledger = AppServerDeliveryLedger(outbox)
    fake = OfflineFakeAppServer(
        binding, scenario=FakeAppServerScenario.TIMEOUT_AFTER_TURN_REQUEST,
    )
    with pytest.raises(UnknownDelivery):
        ledger.run_fake(
            fake, claim_token=claimed["task"]["claim_token"],
            prompt="synthetic auth", cwd="C:/synthetic/worktree",
        )
    assert ledger.get(binding.attempt_id)["status"] == "unknown_delivery"
    monkeypatch.setattr(auth, "current_process_token_sid", lambda: _OPERATOR)
    gate = auth.WindowsOperatorQuarantineGate(
        ledger, trusted_operator_sids=frozenset({_OPERATOR}),
    )
    return store, ledger, outbox, binding.attempt_id, gate


def test_windows_native_token_user_sid():
    if os.name != "nt":
        with pytest.raises(OSError, match="Windows-only"):
            auth.current_process_token_sid()
    else:
        assert auth._SID.fullmatch(auth.current_process_token_sid())


def test_authenticated_decision_is_one_time_and_never_releases(quarantined):
    store, ledger, outbox, attempt, gate = quarantined
    before = ledger.reconcile(attempt)
    challenge = gate.issue_challenge(attempt, disposition="delivery_unresolved")
    assert challenge["operator_authenticated"] is True
    assert challenge["live_send_permitted"] is False
    result = gate.record_unresolved(
        attempt, nonce=challenge["nonce"], version=challenge["version"],
    )
    assert result["operator_authenticated"] is True
    for field in ("resolution_permitted", "new_attempt_permitted",
                  "automatic_retry_permitted", "live_send_permitted",
                  "finalization_permitted"):
        assert result[field] is False
    assert result["independent_delivery_evidence_verified"] is False
    assert ledger.reconcile(attempt) == before
    assert store.get("task-auth")["state"] == TaskState.UNKNOWN_DELIVERY.value
    assert outbox.get(attempt)["status"] == "unknown"
    with pytest.raises(ValueError, match="already committed"):
        gate.record_unresolved(attempt, nonce=challenge["nonce"], version=1)
    with pytest.raises(ValueError, match="already committed"):
        gate.issue_challenge(attempt, disposition="delivery_unresolved")
    with store._connect() as db:
        entries = db.execute(
            "SELECT attempt_id,disposition,windows_sid FROM orchestrator_operator_decisions"
        ).fetchall()
        assert len(entries) == 1
        assert entries[0]["windows_sid"] == _OPERATOR
        assert challenge["nonce"] not in repr(tuple(entries[0]))
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute("UPDATE orchestrator_operator_decisions SET version=2")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute("DELETE FROM orchestrator_operator_decisions")


@pytest.mark.parametrize("disposition", ["delivery_confirmed", "non_delivery_confirmed", "yes"])
def test_external_evidence_required_and_never_promoted(quarantined, disposition):
    _, _, _, attempt, gate = quarantined
    with pytest.raises(PermissionError, match="independent evidence"):
        gate.issue_challenge(attempt, disposition=disposition)


def test_replaced_challenge_cannot_be_replayed(quarantined):
    _, _, _, attempt, gate = quarantined
    old = gate.issue_challenge(attempt, disposition="delivery_unresolved")
    new = gate.issue_challenge(attempt, disposition="delivery_unresolved")
    assert new["version"] == old["version"] + 1
    with pytest.raises(PermissionError):
        gate.record_unresolved(attempt, nonce=old["nonce"], version=old["version"])
    assert gate.record_unresolved(
        attempt, nonce=new["nonce"], version=new["version"],
    )["audit_recorded"] is True


def test_sid_cannot_be_asserted_by_caller(quarantined, monkeypatch):
    _, _, _, attempt, gate = quarantined
    monkeypatch.setattr(auth, "current_process_token_sid", lambda: _OTHER)
    with pytest.raises(PermissionError, match="not an approved"):
        gate.issue_challenge(attempt, disposition="delivery_unresolved")
    monkeypatch.setattr(auth, "current_process_token_sid", lambda: _OPERATOR)
    issued = gate.issue_challenge(attempt, disposition="delivery_unresolved")
    monkeypatch.setattr(auth, "current_process_token_sid", lambda: _OTHER)
    with pytest.raises(PermissionError, match="not an approved"):
        gate.record_unresolved(attempt, nonce=issued["nonce"], version=issued["version"])


@pytest.mark.parametrize("value", [None, "", True, 0, -1, "10", 1.5, 301])
def test_invalid_ttl_fails_closed(quarantined, value):
    _, _, _, attempt, gate = quarantined
    with pytest.raises(ValueError, match="lifetime"):
        gate.issue_challenge(attempt, disposition="delivery_unresolved", ttl=value)


def test_invalid_nonce_and_version_fails_closed(quarantined):
    _, _, _, attempt, gate = quarantined
    item = gate.issue_challenge(attempt, disposition="delivery_unresolved")
    with pytest.raises(ValueError, match="decision version"):
        gate.record_unresolved(attempt, nonce=item["nonce"], version=True)
    with pytest.raises(PermissionError):
        gate.record_unresolved(attempt, nonce="x" * 32, version=item["version"])
    with pytest.raises(ValueError, match="nonce"):
        gate.record_unresolved(attempt, nonce=True, version=item["version"])
    assert gate.record_unresolved(
        attempt, nonce=item["nonce"], version=item["version"],
    )["audit_recorded"]


def test_expired_challenge_refused(quarantined, monkeypatch):
    _, _, _, attempt, gate = quarantined
    item = gate.issue_challenge(attempt, disposition="delivery_unresolved", ttl=1)
    monkeypatch.setattr(auth.time, "time", lambda: item["expires_at"] + 1)
    with pytest.raises(PermissionError, match="expired"):
        gate.record_unresolved(attempt, nonce=item["nonce"], version=item["version"])


def test_attempt_changed_after_challenge_fails_cas(quarantined):
    store, _, _, attempt, gate = quarantined
    item = gate.issue_challenge(attempt, disposition="delivery_unresolved")
    with store._connect() as db:
        db.execute(
            "UPDATE orchestrator_app_server_attempts SET updated_at=updated_at+1 "
            "WHERE attempt_id=?", (attempt,),
        )
    with pytest.raises(PermissionError, match="stale"):
        gate.record_unresolved(attempt, nonce=item["nonce"], version=item["version"])


def test_invalid_allowlist_and_fake_ledger_refused(quarantined):
    _, ledger, _, _, _ = quarantined
    for bad in (frozenset(), frozenset({"user-string"}), {"S-1-5-18"}, None):
        with pytest.raises(ValueError):
            auth.WindowsOperatorQuarantineGate(ledger, trusted_operator_sids=bad)
    with pytest.raises(TypeError):
        auth.WindowsOperatorQuarantineGate(
            object(), trusted_operator_sids=frozenset({_OPERATOR}),
        )


def test_future_schema_version_fails_closed(quarantined):
    store, ledger, _, _, _ = quarantined
    with store._connect() as db:
        db.execute(
            "UPDATE orchestrator_schema_versions SET version=99 WHERE component=?",
            (auth._COMPONENT,),
        )
    with pytest.raises(ValueError, match="schema version"):
        auth.WindowsOperatorQuarantineGate(
            ledger, trusted_operator_sids=frozenset({_OPERATOR}),
        )


def test_task_outbox_state_mismatch_never_creates_challenge(quarantined):
    store, _, _, attempt, gate = quarantined
    with store._connect() as db:
        db.execute(
            "UPDATE tasks SET state='verified' WHERE task_id='task-auth'"
        )
    with pytest.raises(ValueError, match="conservative review"):
        gate.issue_challenge(attempt, disposition="delivery_unresolved")
    with store._connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM orchestrator_operator_challenges"
        ).fetchone()[0] == 0
