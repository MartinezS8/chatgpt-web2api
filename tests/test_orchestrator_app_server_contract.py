"""Contract-level protocol tests: never launch Codex or open an account."""
from __future__ import annotations

import pytest

from chatgpt_web2api.orchestrator.app_server_contract import (
    OfflineAppServerContract,
    ProtocolRejected,
)


def contract():
    return OfflineAppServerContract("gpt-6.1-sol", "high")


def ack(machine, request, result):
    return machine.receive_response({"id": request["id"], "result": result})


def ready():
    machine = contract()
    req = machine.initialize()
    ack(machine, req, {"userAgent": "fake", "platformFamily": "windows"})
    assert machine.initialized() == {"method": "initialized", "params": {}}
    req = machine.model_list()
    ack(machine, req, {"data": [
        {"model": "gpt-6.1-sol", "hidden": False, "supportedReasoningEfforts": [
            {"reasoningEffort": "medium"}, {"reasoningEffort": "high"}]}
    ]})
    req = machine.thread_start(cwd=r"C:\isolated\worktree")
    assert req["params"]["sandbox"] == "readOnly"
    ack(machine, req, {"thread": {"id": "thread-1", "sessionId": "session-1"}})
    return machine


def active():
    machine = ready()
    req = machine.turn_start("Offline test prompt")
    assert req["params"]["approvalPolicy"] == "never"
    assert req["params"]["sandboxPolicy"]["type"] == "readOnly"
    ack(machine, req, {"turn": {"id": "turn-1", "status": "inProgress"}})
    return machine


def complete(machine, *, thread_id="thread-1", turn_id="turn-1", status="completed"):
    return machine.receive_event({
        "method": "turn/completed",
        "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": status}},
    })


def test_ordered_offline_transcript_is_never_dispatch_authority():
    m = active()
    assert m.receive_event({"method": "item/agentMessage/delta",
                            "params": {"delta": "secret output"}}) == "ignored_unverified"
    assert complete(m) == "transport_completed_unverified"
    assert m.thread_id == "thread-1"
    assert m.session_id == "session-1"
    assert m.turn_id == "turn-1"
    assert m.live_send_permitted is False
    assert m.production_finalization_permitted is False
    assert "secret" not in vars(m).__repr__()


@pytest.mark.parametrize(("model", "effort"), [
    ("", "high"), ("gpt-6.1-sol", ""), ("   ", "medium"),
])
def test_invalid_request_selection_rejected(model, effort):
    with pytest.raises(ProtocolRejected):
        OfflineAppServerContract(model, effort)


def test_no_turn_before_capability_and_thread_handshake():
    m = contract()
    with pytest.raises(ProtocolRejected, match="turn requires"):
        m.turn_start("should not send")
    assert m.state == "needs_human"
    assert m.live_send_permitted is False


def test_no_double_initialize():
    m = contract()
    m.initialize()
    with pytest.raises(ProtocolRejected, match="once"):
        m.initialize()


def test_initialized_requires_successful_response():
    m = contract()
    m.initialize()
    with pytest.raises(ProtocolRejected, match="successful handshake"):
        m.initialized()


def test_wrong_response_id_blocks_flow():
    m = contract()
    m.initialize()
    with pytest.raises(ProtocolRejected, match="id mismatch"):
        m.receive_response({"id": 99, "result": {}})
    assert m.state == "needs_human"


@pytest.mark.parametrize("response", [
    {"id": 1, "error": {"code": 1, "message": "failed"}},
    {"id": 1, "result": None},
    {"id": True, "result": {}},
])
def test_invalid_initialize_response_fails_closed(response):
    m = contract()
    m.initialize()
    with pytest.raises(ProtocolRejected):
        m.receive_response(response)
    assert m.state == "needs_human"


@pytest.mark.parametrize("catalog", [
    {"data": []},
    {"data": [{"model": "gpt-6.1-sol", "hidden": True,
               "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}]},
    {"data": [{"model": "gpt-6.1-sol", "supportedReasoningEfforts": []}]},
    {"data": [{"model": "gpt-6.1-sol"}]},
    {"data": [{"model": "different", "supportedReasoningEfforts": [
        {"reasoningEffort": "high"}]}]},
    {"data": [{"model": "gpt-6.1-sol", "supportedReasoningEfforts": [
        {"reasoningEffort": "high"}]}] * 2},
])
def test_model_or_effort_mismatch_fails_closed(catalog):
    m = contract()
    req = m.initialize()
    ack(m, req, {})
    m.initialized()
    req = m.model_list()
    with pytest.raises(ProtocolRejected):
        ack(m, req, catalog)
    assert m.state == "needs_human"


def test_thread_requires_explicit_cwd():
    m = contract()
    req = m.initialize()
    ack(m, req, {})
    m.initialized()
    req = m.model_list()
    ack(m, req, {"data": [{"model": "gpt-6.1-sol",
                            "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}]})
    with pytest.raises(ProtocolRejected, match="explicit cwd"):
        m.thread_start(cwd="")
    assert m.state == "needs_human"


def test_invalid_thread_response_does_not_start_turn():
    m = contract()
    req = m.initialize()
    ack(m, req, {})
    m.initialized()
    req = m.model_list()
    ack(m, req, {"data": [{"model": "gpt-6.1-sol",
                            "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}]})
    req = m.thread_start(cwd=r"C:\synthetic")
    with pytest.raises(ProtocolRejected, match="thread id"):
        ack(m, req, {"thread": {"id": ""}})


@pytest.mark.parametrize(("thread_id", "turn_id"), [
    ("wrong-thread", "turn-1"), ("thread-1", "wrong-turn"),
])
def test_cross_session_terminal_event_never_completes(thread_id, turn_id):
    m = active()
    with pytest.raises(ProtocolRejected, match="different thread or turn"):
        complete(m, thread_id=thread_id, turn_id=turn_id)
    assert m.state == "needs_human"


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_failed_or_interrupted_turn_requires_human(status):
    m = active()
    assert complete(m, status=status) == "needs_human"
    assert m.terminal_status == status


def test_server_initiated_approval_request_is_never_auto_granted():
    m = active()
    with pytest.raises(ProtocolRejected, match="explicit approval"):
        m.receive_event({"id": 7, "method": "item/commandExecution/requestApproval",
                         "params": {"threadId": "thread-1", "reason": "execute"}})
    assert m.state == "needs_human"


def test_duplicate_terminal_event_is_rejected():
    m = active()
    complete(m)
    with pytest.raises(ProtocolRejected, match="without acknowledged active turn"):
        complete(m)


def test_unattested_success_cannot_create_another_turn():
    m = active()
    assert complete(m) == "transport_completed_unverified"
    with pytest.raises(ProtocolRejected, match="turn requires"):
        m.turn_start("duplicate send")


def test_turn_started_before_ack_is_correlated_without_completing():
    m = ready()
    req = m.turn_start("synthetic")
    assert m.receive_event({"method": "turn/started",
                            "params": {"threadId": "thread-1",
                                       "turn": {"id": "turn-early"}}}) == "pending_turn_ack"
    assert m.turn_id is None
    ack(m, req, {"turn": {"id": "turn-early", "status": "inProgress"}})
    assert m.turn_id == "turn-early"
    assert complete(m, turn_id="turn-early") == "transport_completed_unverified"


def test_pre_ack_notification_mismatch_blocks_turn():
    m = ready()
    req = m.turn_start("synthetic")
    m.receive_event({"method": "turn/started",
                     "params": {"threadId": "thread-1", "turn": {"id": "t1"}}})
    with pytest.raises(ProtocolRejected, match="pre-ack turn notification id mismatch"):
        ack(m, req, {"turn": {"id": "t2", "status": "inProgress"}})
    assert m.state == "needs_human"


def test_foreign_thread_progress_rejected_without_exposing_content():
    m = active()
    with pytest.raises(ProtocolRejected, match="different thread"):
        m.receive_event({"method": "item/agentMessage/delta",
                         "params": {"threadId": "foreign", "delta": "private"}})
    assert m.state == "needs_human"
    assert "private" not in repr(vars(m))
