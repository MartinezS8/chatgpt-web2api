"""Preflight-bound offline intents never authorize an external send."""
from __future__ import annotations

import pytest
from test_orchestrator_mock_dispatch_binding import assigned as assigned
from test_orchestrator_upload_preflight import Caps, Uploader

from chatgpt_web2api.orchestrator.store import TaskState
from chatgpt_web2api.orchestrator.upload_preflight import UploadPreflight


def _create_preflight(assigned):
    store, _, outbox, _ = assigned
    preflight = UploadPreflight(store, outbox.packages)
    result = preflight.check_mock(
        task_id="task-1",
        worker_id="worker-1",
        model="GPT-6",
        effort="High",
        required_apps=("GitHub",),
        capability=Caps(),
        uploader=Uploader(),
    )
    assert result["mock_ready"] is True
    assert result["live_send_permitted"] is False
    return preflight


def _begin(assigned, *, worker_id="worker-1", claim_token=None):
    _, _, outbox, token = assigned
    return outbox.begin_preflighted_mock(
        task_id="task-1",
        worker_id=worker_id,
        claim_token=token if claim_token is None else claim_token,
    )


def _assert_no_dispatch_intent(store):
    with store._connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM orchestrator_dispatch_attempts"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM orchestrator_delivery_events WHERE kind='dispatch.intent'"
        ).fetchone()[0] == 0


def test_missing_upload_preflight_creates_no_dispatch_intent(assigned):
    store, _, _, _ = assigned

    with pytest.raises(ValueError, match="preflight.*ready"):
        _begin(assigned)

    _assert_no_dispatch_intent(store)
    assert store.get("task-1")["state"] == TaskState.RESERVED.value


def test_matching_preflight_package_worker_and_claim_create_offline_intent(assigned):
    store, _, outbox, token = assigned
    preflight = _create_preflight(assigned)
    sealed = outbox.packages.read("task-1")
    ready = preflight.get("task-1")
    assert ready["worker_id"] == "worker-1"
    assert ready["package_sha256"] == sealed["package_sha256"]
    assert ready["assurance"] == "offline_mock_only"

    receipt = _begin(assigned)

    assert receipt["new_send_permit"] is True
    assert receipt["remote_send_permitted"] is False
    assert receipt["assurance"] == "offline_mock_only"
    record = outbox.get(receipt["attempt_id"])
    assert record["package_sha256"] == sealed["package_sha256"]
    assert record["status"] == "intent"
    assert store.get("task-1")["state"] == TaskState.DISPATCHING.value
    assert token


@pytest.mark.parametrize(
    ("field", "value"),
    (("worker_id", "worker-2"), ("package_sha256", "f" * 64)),
)
def test_mismatched_sealed_preflight_binding_creates_no_intent(assigned, field, value):
    store, _, _, _ = assigned
    _create_preflight(assigned)
    with store._connect() as db:
        db.execute(
            f"UPDATE orchestrator_mock_upload_preflight SET {field}=? WHERE task_id=?",
            (value, "task-1"),
        )

    with pytest.raises(ValueError, match="preflight"):
        _begin(assigned)

    _assert_no_dispatch_intent(store)
    assert store.get("task-1")["state"] == TaskState.RESERVED.value


def test_preflight_from_rotated_claim_cannot_create_intent(assigned):
    store, _, _, _ = assigned
    _create_preflight(assigned)
    with store._connect() as db:
        db.execute(
            "UPDATE tasks SET claim_token='rotated-claim', claim_version=claim_version+1 "
            "WHERE task_id='task-1'"
        )
        db.execute(
            "UPDATE orchestrator_worker_assignments "
            "SET claim_version=(SELECT claim_version FROM tasks WHERE task_id='task-1') "
            "WHERE task_id='task-1' AND state='active'"
        )

    with pytest.raises(ValueError, match="preflight.*ready"):
        _begin(assigned, claim_token="rotated-claim")

    _assert_no_dispatch_intent(store)
    assert store.get("task-1")["state"] == TaskState.RESERVED.value


def test_wrong_worker_cannot_create_preflighted_intent(assigned):
    store, _, _, _ = assigned
    _create_preflight(assigned)

    with pytest.raises(ValueError, match="mock worker assignment"):
        _begin(assigned, worker_id="worker-2")

    _assert_no_dispatch_intent(store)
    assert store.get("task-1")["state"] == TaskState.RESERVED.value


def test_expired_claim_cannot_create_preflighted_intent(assigned):
    store, _, _, _ = assigned
    _create_preflight(assigned)
    with store._connect() as db:
        db.execute("UPDATE tasks SET lease_until=0 WHERE task_id='task-1'")

    with pytest.raises(ValueError, match="fenced and unexpired"):
        _begin(assigned)

    _assert_no_dispatch_intent(store)
    assert store.get("task-1")["state"] == TaskState.RESERVED.value


def test_disabled_worker_cannot_create_preflighted_intent(assigned):
    store, workers, _, _ = assigned
    _create_preflight(assigned)
    assert workers.set_enabled("worker-1", False)

    with pytest.raises(ValueError, match="mock worker assignment"):
        _begin(assigned)

    _assert_no_dispatch_intent(store)
    assert store.get("task-1")["state"] == TaskState.RESERVED.value


def test_dispatch_replay_never_reissues_permit_including_unknown(assigned):
    store, _, outbox, _ = assigned
    _create_preflight(assigned)

    first = _begin(assigned)
    replay = _begin(assigned)
    assert first["new_send_permit"] is True
    assert replay["attempt_id"] == first["attempt_id"]
    assert replay["new_send_permit"] is False
    assert replay["remote_send_permitted"] is False

    assert outbox.mark_unknown(first["attempt_id"], "synthetic_timeout") is True
    unknown_replay = _begin(assigned)
    assert unknown_replay["attempt_id"] == first["attempt_id"]
    assert unknown_replay["status"] == "unknown"
    assert unknown_replay["new_send_permit"] is False
    assert unknown_replay["remote_send_permitted"] is False
    assert outbox.get(first["attempt_id"])["status"] == "unknown"

    with store._connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM orchestrator_dispatch_attempts WHERE task_id='task-1'"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM orchestrator_delivery_events "
            "WHERE task_id='task-1' AND kind='dispatch.intent'"
        ).fetchone()[0] == 1
