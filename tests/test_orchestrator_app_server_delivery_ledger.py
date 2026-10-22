"""Durable, mock-only app-server correlation never grants a live send."""
from __future__ import annotations

import hashlib

import pytest

from chatgpt_web2api.orchestrator.app_server_delivery import AppServerDeliveryLedger
from chatgpt_web2api.orchestrator.app_server_fake import (
    AttemptBinding,
    FakeAppServerScenario,
    OfflineFakeAppServer,
    UnknownDelivery,
)
from chatgpt_web2api.orchestrator.mcp_control import dispatch_observer
from chatgpt_web2api.orchestrator.observer import Observer
from chatgpt_web2api.orchestrator.outbox import DispatchOutbox
from chatgpt_web2api.orchestrator.scheduler import Scheduler
from chatgpt_web2api.orchestrator.store import Store, TaskSpec, TaskState
from chatgpt_web2api.orchestrator.task_packages import TaskPackages
from chatgpt_web2api.orchestrator.worker_registry import WorkerRegistry, WorkerSpec

PROMPT = "safe mock prompt"


@pytest.fixture
def assigned(tmp_path):
    store = Store(tmp_path / "orchestrator.sqlite")
    workers = WorkerRegistry(store)
    packages = TaskPackages(store, tmp_path / "blobs")
    assert store.create(TaskSpec("task-1", "project-1", "implement", PROMPT))
    assert workers.register(
        WorkerSpec("worker-1", "account-1", "project-1", "implement", "mock", "fake:worker-1")
    )
    packages.seal("task-1", PROMPT)
    claimed = Scheduler(store, workers, packages).claim_next("account-1", "project-1")
    assert claimed is not None
    return store, workers, DispatchOutbox(store, packages), claimed["task"]["claim_token"]


def _prepared(assigned, *, worker_id="worker-1", prompt=PROMPT):
    store, _, outbox, claim_token = assigned
    receipt = outbox.begin_mock_for_assignment(
        task_id="task-1", worker_id=worker_id, claim_token=claim_token
    )
    binding = AttemptBinding(
        controller_id="controller-test",
        worker_id=worker_id,
        account_id="account-1",
        project_id="project-1",
        task_id="task-1",
        attempt_id=receipt["attempt_id"],
    )
    ledger = AppServerDeliveryLedger(outbox)
    return store, outbox, claim_token, binding, ledger, prompt


def _message_rows(store, attempt_id):
    with store._connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM orchestrator_app_server_messages WHERE attempt_id=? "
            "ORDER BY message_seq", (attempt_id,)
        )]


def test_fake_roundtrip_persists_correlations_without_finishing_task(assigned):
    store, outbox, claim, binding, ledger, prompt = _prepared(assigned)
    fake = OfflineFakeAppServer(binding)

    result = ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    assert result["state"] == "transport_completed_unverified"
    assert result["live_send_permitted"] is False
    delivery = ledger.get(binding.attempt_id)
    assert delivery["status"] == "transport_completed_unverified"
    assert delivery["worker_id"] == binding.worker_id
    assert delivery["package_sha256"] == outbox.get(binding.attempt_id)["package_sha256"]
    assert delivery["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    assert delivery["thread_id"] == result["thread_id"]
    assert delivery["turn_id"] == result["turn_id"]
    assert [row["method"] for row in _message_rows(store, binding.attempt_id)] == [
        "initialize", "initialized", "model/list", "thread/start", "turn/start"
    ]
    assert [row["status"] for row in _message_rows(store, binding.attempt_id)] == [
        "acknowledged", "written", "acknowledged", "acknowledged", "acknowledged"
    ]
    assert outbox.get(binding.attempt_id)["status"] == "offline_simulated_unverified"
    assert store.get("task-1")["state"] == TaskState.NEEDS_HUMAN.value
    assert store.get("task-1")["evidence_ref"] is None
    assert store.get("task-1")["approved_by"] is None


def test_binding_change_after_terminal_event_prevents_fake_completion_receipt(assigned, monkeypatch):
    store, outbox, claim, binding, ledger, prompt = _prepared(assigned)
    original = OfflineFakeAppServer._run_with_journal

    def complete_then_disable_worker(fake, **kwargs):
        result = original(fake, **kwargs)
        with store._connect() as db:
            db.execute("UPDATE orchestrator_workers SET enabled=0 WHERE worker_id=?",
                       (binding.worker_id,))
        return result

    monkeypatch.setattr(OfflineFakeAppServer, "_run_with_journal", complete_then_disable_worker)
    fake = OfflineFakeAppServer(binding)
    with pytest.raises(UnknownDelivery, match="durable binding check"):
        ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    assert ledger.get(binding.attempt_id)["status"] == "needs_human"
    assert outbox.get(binding.attempt_id)["status"] == "needs_human"
    assert store.get(binding.task_id)["state"] == TaskState.NEEDS_HUMAN.value


def test_ledger_persists_hashes_only_and_never_session_or_prompt_material(assigned):
    store, _, claim, binding, ledger, prompt = _prepared(assigned)
    fake = OfflineFakeAppServer(binding)
    ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    with store._connect() as db:
        serialized = "\n".join(str(tuple(row)) for row in db.execute(
            "SELECT * FROM orchestrator_app_server_attempts"
        ))
        serialized += "\n" + "\n".join(str(tuple(row)) for row in db.execute(
            "SELECT * FROM orchestrator_app_server_messages"
        ))
        serialized += "\n" + "\n".join(str(tuple(row)) for row in db.execute(
            "SELECT * FROM orchestrator_app_server_events"
        ))
    assert prompt not in serialized
    assert claim not in serialized
    assert "fake:worker-1" not in serialized
    assert hashlib.sha256(claim.encode()).hexdigest() in serialized
    assert hashlib.sha256(prompt.encode()).hexdigest() in serialized


def test_same_attempt_cannot_run_fake_transport_twice_after_restart(assigned):
    store, outbox, claim, binding, ledger, prompt = _prepared(assigned)
    first_fake = OfflineFakeAppServer(binding)
    ledger.run_fake(first_fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")
    count = first_fake.request_count("turn/start")

    restarted_store = type(store)(store.path)
    packages = TaskPackages(restarted_store, outbox.packages.blob_root)
    restarted_outbox = type(outbox)(restarted_store, packages)
    restarted_ledger = AppServerDeliveryLedger(restarted_outbox)
    replay = OfflineFakeAppServer(binding)
    with pytest.raises(UnknownDelivery, match="already started"):
        restarted_ledger.run_fake(
            replay, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree"
        )

    assert replay.request_count("turn/start") == 0
    assert count == 1
    assert restarted_ledger.get(binding.attempt_id)["status"] == "transport_completed_unverified"


def test_prompt_must_match_immutable_task_hash_before_fake_process_starts(assigned):
    _, _, claim, binding, ledger, _ = _prepared(assigned)
    fake = OfflineFakeAppServer(binding)

    with pytest.raises(ValueError, match="prompt hash"):
        ledger.run_fake(fake, claim_token=claim, prompt="different synthetic prompt",
                        cwd="C:/synthetic/worktree")

    assert fake.request_count("initialize") == 0
    assert ledger.get(binding.attempt_id) is None


@pytest.mark.parametrize(("field", "value"), [
    ("model", "m" * 257),
    ("effort", "e" * 33),
])
def test_model_and_effort_are_bounded_before_transport_or_journal(assigned, field, value):
    _, _, _, binding, _, _ = _prepared(assigned)

    with pytest.raises(ValueError, match="exact synthetic model and effort"):
        OfflineFakeAppServer(binding, **{field: value})


def test_wrong_worker_binding_cannot_attach_to_dispatch_attempt(assigned):
    _, _, claim, binding, ledger, prompt = _prepared(assigned)
    wrong_binding = AttemptBinding(
        controller_id=binding.controller_id,
        worker_id="worker-2",
        account_id=binding.account_id,
        project_id=binding.project_id,
        task_id=binding.task_id,
        attempt_id=binding.attempt_id,
    )
    fake = OfflineFakeAppServer(wrong_binding)

    with pytest.raises(ValueError, match="worker binding"):
        ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    assert fake.request_count("initialize") == 0
    assert ledger.get(binding.attempt_id) is None


def test_unknown_fake_delivery_recovery_is_explicit_and_never_replays(assigned):
    store, _, claim, binding, ledger, prompt = _prepared(assigned)
    fake = OfflineFakeAppServer(binding, scenario=FakeAppServerScenario.TIMEOUT_AFTER_TURN_REQUEST)

    with pytest.raises(UnknownDelivery):
        ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    assert ledger.get(binding.attempt_id)["status"] == "unknown_delivery"
    assert store.get("task-1")["state"] == TaskState.UNKNOWN_DELIVERY.value
    assert ledger.recover_pending() == 0
    replay = OfflineFakeAppServer(binding)
    with pytest.raises(UnknownDelivery):
        ledger.run_fake(replay, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")
    assert replay.request_count("turn/start") == 0


def test_partial_client_frame_write_is_quarantined_without_second_turn(assigned):
    store, outbox, claim, binding, ledger, prompt = _prepared(assigned)
    fake = OfflineFakeAppServer(
        binding, scenario=FakeAppServerScenario.PARTIAL_CLIENT_SEND_BEFORE_TURN
    )

    with pytest.raises(UnknownDelivery, match="partial frame"):
        ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    turn_messages = [row for row in _message_rows(store, binding.attempt_id)
                     if row["method"] == "turn/start"]
    assert len(turn_messages) == 1
    assert turn_messages[0]["status"] == "unknown"
    assert fake.request_count("turn/start") == 1
    assert ledger.get(binding.attempt_id)["status"] == "unknown_delivery"
    assert outbox.get(binding.attempt_id)["status"] == "unknown"
    assert store.get(binding.task_id)["state"] == TaskState.UNKNOWN_DELIVERY.value

    replay = OfflineFakeAppServer(binding)
    with pytest.raises(UnknownDelivery):
        ledger.run_fake(replay, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")
    assert replay.request_count("turn/start") == 0


def test_duplicate_acknowledgement_is_idempotent_and_conflicting_replay_is_rejected(assigned):
    _, _, claim, binding, ledger, prompt = _prepared(assigned)
    ledger._prepare(OfflineFakeAppServer(binding), claim_token=claim, prompt=prompt)
    ledger._start(binding.attempt_id)
    message_seq = ledger._message_intent(
        binding.attempt_id, message_kind="request", request_id=1,
        method="initialize", message_sha256="a" * 64,
    )
    assert ledger._message_written(binding.attempt_id, message_seq) is True
    response_sha = "b" * 64

    assert ledger._message_acknowledged(
        binding.attempt_id, message_seq, response_sha256=response_sha,
        thread_id=None, turn_id=None,
    ) is True
    event_count = len(ledger.events(binding.attempt_id))
    assert ledger._message_acknowledged(
        binding.attempt_id, message_seq, response_sha256=response_sha,
        thread_id=None, turn_id=None,
    ) is False
    assert len(ledger.events(binding.attempt_id)) == event_count
    with pytest.raises(ValueError, match="conflicting duplicate"):
        ledger._message_acknowledged(
            binding.attempt_id, message_seq, response_sha256="c" * 64,
            thread_id=None, turn_id=None,
        )
    with pytest.raises(ValueError, match="sequence gap"):
        ledger._message_intent(
            binding.attempt_id, message_kind="request", request_id=1,
            method="initialize", message_sha256="d" * 64,
        )


def test_stale_claim_cannot_start_or_replay_app_server_fake(assigned):
    store, _, claim, binding, ledger, prompt = _prepared(assigned)
    with store._connect() as db:
        db.execute("UPDATE tasks SET claim_token='rotated-claim' WHERE task_id='task-1'")
    fake = OfflineFakeAppServer(binding)

    with pytest.raises(ValueError, match="claim"):
        ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    assert fake.request_count("initialize") == 0
    assert ledger.get(binding.attempt_id) is None


def test_prepared_attempt_rechecks_dispatch_fence_atomically_before_fake_start(
    assigned, monkeypatch
):
    store, outbox, claim, binding, ledger, prompt = _prepared(assigned)
    fake = OfflineFakeAppServer(binding)
    prepare = ledger._prepare

    def prepare_then_fence(*args, **kwargs):
        row = prepare(*args, **kwargs)
        with store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE orchestrator_dispatch_attempts SET status='unknown' WHERE attempt_id=?",
                (binding.attempt_id,),
            )
            db.execute(
                "UPDATE tasks SET state=? WHERE task_id=?",
                (TaskState.UNKNOWN_DELIVERY.value, binding.task_id),
            )
        return row

    monkeypatch.setattr(ledger, "_prepare", prepare_then_fence)
    with pytest.raises(UnknownDelivery, match="stale; no fake process started"):
        ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    assert fake.request_count("initialize") == 0
    assert fake._transport is None
    assert outbox.get(binding.attempt_id)["status"] == "unknown"
    assert ledger.get(binding.attempt_id)["status"] == "needs_human"
    assert store.get(binding.task_id)["state"] == TaskState.UNKNOWN_DELIVERY.value


def test_observer_mcp_exposes_only_read_only_redacted_delivery_state(assigned):
    store, _, claim, binding, ledger, prompt = _prepared(assigned)
    fake = OfflineFakeAppServer(binding)
    ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    observer = Observer(store.path)
    response = dispatch_observer(
        observer,
        "orchestrator_app_server_delivery",
        {"attempt_id": binding.attempt_id},
    )
    serialized = str(response)
    assert response["delivery"]["status"] == "transport_completed_unverified"
    assert response["automatic_retry_permitted"] is False
    assert response["finalization_permitted"] is False
    assert "app_server_delivery" in observer.capabilities()["methods"]
    assert "safe mock prompt" not in serialized
    assert hashlib.sha256(prompt.encode()).hexdigest() not in serialized
    assert claim not in serialized
    assert "fake:worker-1" not in serialized
    assert "transport_identity_sha256" not in serialized
    assert "claim_token_sha256" not in serialized
    with pytest.raises(ValueError, match="forbidden"):
        dispatch_observer(observer, "orchestrator_operator_disposition", {})


def test_mcp_delivery_query_is_read_only_and_rejects_mutation_arguments(assigned):
    store, _, claim, binding, ledger, prompt = _prepared(assigned)
    fake = OfflineFakeAppServer(binding)
    ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")
    observer = Observer(store.path)
    before = (store.get("task-1"), ledger.get(binding.attempt_id), ledger.events(binding.attempt_id))

    with pytest.raises(ValueError, match="unsupported tool arguments"):
        dispatch_observer(observer, "orchestrator_app_server_delivery", {
            "attempt_id": binding.attempt_id, "disposition": "non_delivery_confirmed",
        })

    after = (store.get("task-1"), ledger.get(binding.attempt_id), ledger.events(binding.attempt_id))
    assert after == before


def test_operator_disposition_is_audited_but_never_unquarantines_or_authorizes(assigned):
    store, _, claim, binding, ledger, prompt = _prepared(assigned)
    fake = OfflineFakeAppServer(binding, scenario=FakeAppServerScenario.TIMEOUT_AFTER_TURN_REQUEST)
    with pytest.raises(UnknownDelivery):
        ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    assert ledger.record_operator_disposition(
        binding.attempt_id, operator_ref="local-operator", disposition="delivery_unresolved",
        reason_code="no_external_evidence",
    ) is True
    assert ledger.record_operator_disposition(
        binding.attempt_id, operator_ref="local-operator", disposition="delivery_unresolved",
        reason_code="no_external_evidence",
    ) is False
    assert ledger.reconcile(binding.attempt_id)["automatic_retry_permitted"] is False
    assert ledger.get(binding.attempt_id)["status"] == "unknown_delivery"
    assert store.get("task-1")["state"] == TaskState.UNKNOWN_DELIVERY.value
    with store._connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM orchestrator_app_server_operator_dispositions WHERE attempt_id=?",
            (binding.attempt_id,),
        ).fetchone()[0] == 1
        disposition = db.execute(
            "SELECT * FROM orchestrator_app_server_operator_dispositions WHERE attempt_id=?",
            (binding.attempt_id,),
        ).fetchone()
        assert "local-operator" not in str(tuple(disposition))


@pytest.mark.parametrize(
    ("boundary", "expected_request_status", "expected_recovered_status"),
    [
        ("before_write", "intent", "unknown_delivery"),
        ("after_write", "written", "unknown_delivery"),
        ("before_ack_persist", "written", "unknown_delivery"),
        ("after_ack_persist", "acknowledged", "unknown_delivery"),
        ("after_terminal", "acknowledged", "needs_human"),
    ],
)
def test_crash_boundaries_recover_to_quarantine_without_second_send(
    assigned, monkeypatch, boundary, expected_request_status, expected_recovered_status
):
    store, outbox, claim, binding, ledger, prompt = _prepared(assigned)
    crash_type = type("SyntheticProcessCrash", (BaseException,), {})
    crash = crash_type("synthetic process interruption")

    method_name = {
        "before_write": "_message_intent",
        "after_write": "_message_written",
        "before_ack_persist": "_message_acknowledged",
        "after_ack_persist": "_message_acknowledged",
        "after_terminal": "_capture_notification",
    }[boundary]
    original = getattr(ledger, method_name)

    def interrupted(*args, **kwargs):
        if boundary == "before_ack_persist":
            raise crash
        result = original(*args, **kwargs)
        if boundary == "after_terminal" and kwargs.get("method") != "turn/completed":
            return result
        if boundary in {"before_write", "after_write", "after_ack_persist", "after_terminal"}:
            raise crash
        return result

    monkeypatch.setattr(ledger, method_name, interrupted)
    fake = OfflineFakeAppServer(binding)
    with pytest.raises(crash_type):
        ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")

    request_rows = _message_rows(store, binding.attempt_id)
    assert request_rows[0]["status"] == expected_request_status
    assert ledger.get(binding.attempt_id)["status"] == "running_offline_fake"

    recovered_store = type(store)(store.path)
    recovered_outbox = type(outbox)(recovered_store, outbox.packages)
    recovered = AppServerDeliveryLedger(recovered_outbox)
    assert recovered.recover_pending() == 1
    assert recovered.get(binding.attempt_id)["status"] == expected_recovered_status
    assert recovered.reconcile(binding.attempt_id)["automatic_retry_permitted"] is False

    replay = OfflineFakeAppServer(binding)
    with pytest.raises(UnknownDelivery):
        recovered.run_fake(replay, claim_token=claim, prompt=prompt,
                           cwd="C:/synthetic/worktree")
    assert replay.request_count("turn/start") == 0


def test_future_ledger_schema_version_fails_closed_without_replacing_schema(assigned):
    store, outbox, _, _, _, _ = _prepared(assigned)
    with store._connect() as db:
        db.execute(
            "UPDATE orchestrator_schema_versions SET version=99 "
            "WHERE component='app-server-delivery-ledger'"
        )

    with pytest.raises(ValueError, match="unsupported app-server ledger schema"):
        AppServerDeliveryLedger(outbox)

    with store._connect() as db:
        assert db.execute(
            "SELECT version FROM orchestrator_schema_versions "
            "WHERE component='app-server-delivery-ledger'"
        ).fetchone()[0] == 99


def test_operator_triage_of_unknown_send_is_read_only_and_non_authorizing(assigned):
    store, outbox, claim, binding, ledger, prompt = _prepared(assigned)
    fake = OfflineFakeAppServer(binding, scenario=FakeAppServerScenario.TIMEOUT_AFTER_TURN_REQUEST)
    with pytest.raises(UnknownDelivery):
        ledger.run_fake(fake, claim_token=claim, prompt=prompt, cwd="C:/synthetic/worktree")
    before = ledger.reconcile(binding.attempt_id)
    plan = ledger.triage(binding.attempt_id)
    assert plan["classification"] == "delivery_ambiguous_quarantined"
    assert plan["live_send_permitted"] is False
    assert plan["automatic_retry_permitted"] is False
    assert plan["new_attempt_permitted"] is False
    assert plan["finalization_permitted"] is False
    assert ledger.reconcile(binding.attempt_id) == before
    assert store.get(binding.task_id)["state"] == TaskState.UNKNOWN_DELIVERY.value
    assert outbox.get(binding.attempt_id)["status"] == "unknown"
