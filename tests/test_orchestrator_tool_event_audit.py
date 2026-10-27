"""Synthetic regression coverage for local-pilot tool-event auditing."""
from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest

from tests.test_orchestrator_local_codex_pilot import _FakeProcess, _run, _success_frames
from tests.test_orchestrator_local_codex_pilot import context as context

_TOOL_ITEM_TYPES = (
    "commandExecution",
    "fileChange",
    "mcpToolCall",
    "dynamicToolCall",
    "futureToolActivity",
)


def _agent_message(text: str = "ORCH_TEST_OK") -> dict:
    return {
        "method": "item/completed",
        "params": {
            "completedAtMs": 1730910000000,
            "threadId": "thread-x",
            "turnId": "turn-x",
            "item": {
                "id": "agent-message-x",
                "type": "agentMessage",
                "phase": "final_answer",
                "text": text,
            },
        },
    }


def _started_agent(item_id: str = "agent-message-x") -> dict:
    return {"method": "item/started", "params": {
        "threadId": "thread-x", "turnId": "turn-x",
        "item": {"id": item_id, "type": "agentMessage", "phase": "final_answer"},
    }}


def _add_agent(frames: list, text: str = "ORCH_TEST_OK") -> None:
    frames[-1:-1] = [_started_agent(), _agent_message(text)]
    frames[-1]["params"]["turn"]["items"].append({
        "id": "agent-message-x", "type": "agentMessage", "phase": "final_answer",
        "text": text,
    })


def _tool_item_event(method: str, item_type: str, marker: str) -> dict:
    return {
        "method": method,
        "params": {
            "threadId": "thread-x",
            "turnId": "turn-x",
            "item": {
                "id": f"tool-item-{item_type}",
                "type": item_type,
                "command": [marker],
                "rawPayload": {"marker": marker},
            },
        },
    }


@pytest.mark.parametrize("method", ("item/started", "item/completed"))
@pytest.mark.parametrize("item_type", _TOOL_ITEM_TYPES)
def test_tool_item_events_are_audited_without_persisting_payloads(
    context, monkeypatch, method, item_type,
):
    marker = f"SYNTHETIC_RAW_TOOL_PAYLOAD_{method}_{item_type}"
    frames = _success_frames()
    frames[-1:-1] = [_tool_item_event(method, item_type, marker)]
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["assistant_output_matches_expected"] is True
    assert result["unexpected_tool_activity_observed"] is True
    assert result["clean_tool_free_pilot"] is False
    result_json = (context[-1] / "result.json").read_text(encoding="utf-8")
    assert marker not in result_json
    if item_type == "futureToolActivity":
        assert item_type not in result_json
        assert result["observed_item_type_counts"]["unknown"] == 1


def test_clean_completed_agent_message_is_marked_tool_free(context, monkeypatch):
    frames = _success_frames()
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["assistant_output_matches_expected"] is True
    assert result["unexpected_tool_activity_observed"] is False
    assert result["clean_tool_free_pilot"] is True
    assert result["item_lifecycle_consistent"] is True


@pytest.mark.parametrize("terminal", ("failed", "interrupted"))
def test_non_completed_terminal_never_counts_as_clean(context, monkeypatch, terminal):
    frames = _success_frames()
    frames[-1]["params"]["turn"]["status"] = terminal
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["assistant_output_matches_expected"] is False
    assert result["clean_tool_free_pilot"] is False


def test_wrong_agent_answer_never_counts_as_clean(context, monkeypatch):
    frames = _success_frames()
    _add_agent(frames, "NOT_ORCH_TEST_OK")
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["assistant_output_matches_expected"] is False
    assert result["clean_tool_free_pilot"] is False


@pytest.mark.parametrize("method", [
    "item/commandExecution/outputDelta",
    "item/fileChange/outputDelta",
    "item/futureTool/SECRET_EVENT_PAYLOAD",
    "hook/started",
    "serverRequest/resolved",
])
def test_unexpected_notifications_are_redacted_and_not_clean(context, monkeypatch, method):
    frames = _success_frames()
    frames[-1:-1] = [
        {"method": method, "params": {
            "threadId": "thread-x", "turnId": "turn-x", "payload": "PRIVATE_EVENT_PAYLOAD",
        }},
    ]
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["unexpected_tool_activity_observed"] is True
    assert result["clean_tool_free_pilot"] is False
    receipt = (context[-1] / "result.json").read_text(encoding="utf-8")
    assert "PRIVATE_EVENT_PAYLOAD" not in receipt
    assert "SECRET_EVENT_PAYLOAD" not in receipt


def test_early_tool_event_before_turn_ack_is_not_lost(context, monkeypatch):
    frames = _success_frames()
    ack = next(i for i, frame in enumerate(frames) if frame.get("id") == 3)
    frames.insert(ack, _tool_item_event("item/started", "commandExecution", "SECRET"))
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["unexpected_tool_activity_observed"] is True
    assert result["clean_tool_free_pilot"] is False


def test_tool_event_after_terminal_is_drained_before_success(context, monkeypatch):
    frames = _success_frames()
    _add_agent(frames)
    frames.append(_tool_item_event("item/completed", "commandExecution", "SECRET"))
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["unexpected_tool_activity_observed"] is True
    assert result["clean_tool_free_pilot"] is False


def test_tool_item_in_turn_response_is_audited(context, monkeypatch):
    frames = _success_frames()
    ack = next(frame for frame in frames if frame.get("id") == 3)
    ack["result"]["turn"]["items"] = [{"id": "x", "type": "fileChange", "secret": "PRIVATE"}]
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["unexpected_tool_activity_observed"] is True
    assert result["clean_tool_free_pilot"] is False
    assert "PRIVATE" not in (context[-1] / "result.json").read_text(encoding="utf-8")


def test_tool_item_in_terminal_response_is_audited(context, monkeypatch):
    frames = _success_frames()
    frames[-1]["params"]["turn"]["items"] = [{"id": "x", "type": "webSearch"}]
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["observed_item_type_counts"]["webSearch"] == 1
    assert result["clean_tool_free_pilot"] is False


def test_agent_output_that_is_not_expected_is_not_copied_into_receipts(context, monkeypatch):
    marker = "PRIVATE_MODEL_OUTPUT"
    frames = _success_frames()
    _add_agent(frames, marker)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    result = _run(context, allow_one_turn=True)

    assert result["assistant_output_preview"] is None
    assert result["assistant_output_sha256"] is None
    assert marker not in (context[-1] / "result.json").read_text(encoding="utf-8")


def test_duplicate_terminal_is_quarantined_without_retry(context, monkeypatch):
    frames = _success_frames()
    _add_agent(frames)
    frames.append(frames[-1].copy())
    process = _FakeProcess(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: process,
    )

    with pytest.raises(RuntimeError, match="duplicate turn completion"):
        _run(context, allow_one_turn=True)

    outgoing = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert sum(message["method"] == "turn/start" for message in outgoing) == 1
    assert (context[-1] / "quarantine.json").is_file()


def test_duplicate_terminal_tool_item_is_recorded_without_payload(context, monkeypatch):
    frames = _success_frames()
    _add_agent(frames)
    duplicate = {"method": "turn/completed", "params": {
        "threadId": "thread-x", "turn": {
            "id": "turn-x", "status": "completed",
            "items": [{"id": "x", "type": "commandExecution", "command": "PRIVATE"}],
        },
    }}
    frames.append(duplicate)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    with pytest.raises(RuntimeError, match="duplicate turn completion"):
        _run(context, allow_one_turn=True)

    receipt = (context[-1] / "quarantine.json").read_text(encoding="utf-8")
    audit = json.loads(receipt)
    assert audit["unexpected_tool_activity_observed"] is True
    assert audit["observed_item_type_counts"]["commandExecution"] == 1
    assert audit["retry_permitted"] is False
    assert "PRIVATE" not in receipt


@pytest.mark.parametrize("clean,unexpected,overrides,expected_exit", [
    (True, False, {}, 0),
    (False, True, {}, 2),
    (True, True, {}, 2),
    (True, False, {"retry_permitted": True}, 2),
    (True, False, {"production_finalization_permitted": True}, 2),
    (True, False, {"status": "turn_ended_needs_review"}, 2),
    (True, False, {"live_turn_started": False}, 2),
])
def test_pilot_cli_exit_requires_clean_tool_audit(
    monkeypatch, clean, unexpected, overrides, expected_exit,
):
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "scripts/pilot_one_codex_turn.py"))
    main = namespace["main"]
    result = {
        "status": "transport_completed_unreviewed",
        "live_turn_started": True,
        "retry_permitted": False,
        "production_finalization_permitted": False,
        "assistant_output_matches_expected": True,
        "assistant_message_observed": True,
        "assistant_output_preview": "ORCH_TEST_OK",
        "assistant_output_sha256": hashlib.sha256(b"ORCH_TEST_OK").hexdigest(),
        "expected_output": "ORCH_TEST_OK",
        "turn_start_request_id": 3,
        "turn_terminal_status": "completed",
        "tool_event_audit_version": 2,
        "tool_event_audit_complete": True,
        "tool_event_audit_scope": "observed_app_server_events_only",
        "observed_item_type_counts": ({"agentMessage": 1, "commandExecution": 1}
                                      if unexpected else {"agentMessage": 1}),
        "unexpected_notification_counts": {},
        "unexpected_tool_activity_observed": unexpected,
        "clean_tool_free_pilot": clean,
        "item_lifecycle_consistent": True,
    }
    result.update(overrides)
    monkeypatch.setitem(main.__globals__, "run_one_local_pilot", lambda *a, **kw: result)
    arguments = ["pilot_one_codex_turn.py"]
    for option in (
        "codex-exe", "schema-root", "cwd", "prompt-file", "receipt-dir", "model", "effort",
        "thread-params-schema", "thread-result-schema", "turn-params-schema", "turn-result-schema",
        "mcp-source-map",
    ):
        arguments.extend([f"--{option}", "synthetic"])
    monkeypatch.setattr("sys.argv", arguments)

    assert main() == expected_exit


def test_nonzero_process_exit_after_terminal_quarantines_result(context, monkeypatch):
    frames = _success_frames()
    _add_agent(frames)
    process = _FakeProcess(frames)
    process.wait = lambda *, timeout: 1
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: process,
    )

    with pytest.raises(RuntimeError, match="failed after terminal"):
        _run(context, allow_one_turn=True)

    assert (context[-1] / "quarantine.json").is_file()
    assert not (context[-1] / "result.json").exists()


def test_foreign_model_notification_cannot_be_called_clean(context, monkeypatch):
    frames = _success_frames()
    frames[-1:-1] = [
        {"method": "model/safetyBuffering/updated", "params": {
            "threadId": "foreign-thread", "turnId": "turn-x",
        }},
    ]
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    with pytest.raises(RuntimeError, match="foreign"):
        _run(context, allow_one_turn=True)

    assert (context[-1] / "quarantine.json").is_file()


def test_conflicting_ack_and_terminal_status_is_quarantined(context, monkeypatch):
    frames = _success_frames()
    ack = next(frame for frame in frames if frame.get("id") == 3)
    ack["result"]["turn"]["status"] = "failed"
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    with pytest.raises(RuntimeError, match="status"):
        _run(context, allow_one_turn=True)

    assert (context[-1] / "quarantine.json").is_file()
    assert not (context[-1] / "result.json").exists()


@pytest.mark.parametrize("mismatch", ["started_status", "completion_error"])
def test_inconsistent_turn_status_never_counts_as_clean(context, monkeypatch, mismatch):
    frames = _success_frames()
    if mismatch == "started_status":
        frames[3]["params"]["turn"]["status"] = "failed"
    else:
        frames[-1]["params"]["turn"]["error"] = {"message": "PRIVATE_ERROR"}
    _add_agent(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )

    with pytest.raises(RuntimeError, match="status"):
        _run(context, allow_one_turn=True)

    quarantine = (context[-1] / "quarantine.json").read_text(encoding="utf-8")
    assert "PRIVATE_ERROR" not in quarantine
    assert not (context[-1] / "result.json").exists()


def test_server_initiated_tool_approval_is_quarantined_without_payload(
    context, monkeypatch,
):
    marker = "SYNTHETIC_APPROVAL_COMMAND_PAYLOAD"
    frames = _success_frames()
    frames.insert(-1, {
        "id": 900,
        "method": "item/commandExecution/requestApproval",
        "params": {
            "threadId": "thread-x",
            "turnId": "turn-x",
            "itemId": "command-item-x",
            "command": [marker],
            "reason": marker,
            "rawPayload": {"marker": marker},
        },
    })
    process = _FakeProcess(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: process,
    )

    with pytest.raises(RuntimeError, match="server-initiated request needs human review"):
        _run(context, allow_one_turn=True)

    outgoing = [
        json.loads(line)
        for line in process.stdin.getvalue().splitlines()
    ]
    assert sum(message["method"] == "turn/start" for message in outgoing) == 1
    quarantine_json = (context[-1] / "quarantine.json").read_text(encoding="utf-8")
    quarantine = json.loads(quarantine_json)
    assert quarantine["turn_start_may_have_been_sent"] is True
    assert quarantine["retry_permitted"] is False
    assert quarantine["unexpected_tool_activity_observed"] is True
    assert marker not in quarantine_json


@pytest.mark.parametrize("variant", [
    "completed_without_started", "double_started", "double_completed",
    "type_changed", "unfinished_item", "terminal_omits_item",
    "terminal_adds_unobserved_item", "duplicate_terminal_item",
])
def test_item_lifecycle_anomalies_cannot_claim_clean(context, monkeypatch, variant):
    frames = _success_frames()
    _add_agent(frames)
    if variant == "completed_without_started":
        frames.pop(-3)  # remove matching item/started
    elif variant == "double_started":
        frames.insert(-3, _started_agent())
    elif variant == "double_completed":
        frames.insert(-1, _agent_message())
    elif variant == "type_changed":
        frames[-2]["params"]["item"]["type"] = "plan"
    elif variant == "unfinished_item":
        frames.insert(-1, _tool_item_event("item/started", "plan", "PRIVATE"))
    elif variant == "terminal_omits_item":
        frames[-1]["params"]["turn"]["items"] = []
    elif variant == "terminal_adds_unobserved_item":
        frames[-1]["params"]["turn"]["items"].append({
            "id": "extra-agent", "type": "agentMessage", "text": "PRIVATE",
        })
    else:
        frames[-1]["params"]["turn"]["items"].append(
            dict(frames[-1]["params"]["turn"]["items"][0]))
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )
    result = _run(context, allow_one_turn=True)
    assert result["clean_tool_free_pilot"] is False
    assert result["item_lifecycle_consistent"] is False
    assert result["unexpected_tool_activity_observed"] is True
    assert result["retry_permitted"] is False
    assert not (context[-1] / "quarantine.json").exists()


@pytest.mark.parametrize("method,params", [
    ("item/agentMessage/delta", {"threadId": "thread-x", "turnId": "turn-x",
                                 "itemId": "agent-message-x", "delta": "SECRET"}),
    ("thread/status/changed", {"threadId": "thread-x"}),
    ("turn/plan/updated", {"threadId": "thread-x", "turnId": "turn-x", "plan": []}),
])
def test_late_safe_notifications_do_not_qualify_as_clean(
    context, monkeypatch, method, params,
):
    frames = _success_frames()
    _add_agent(frames)
    frames.append({"method": method, "params": params})
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )
    result = _run(context, allow_one_turn=True)
    assert result["clean_tool_free_pilot"] is False
    assert result["unexpected_notification_counts"]["late_notification"] == 1


@pytest.mark.parametrize("method,params", [
    ("thread/status/changed", {}),
    ("item/agentMessage/delta", {"threadId": "thread-x", "turnId": "turn-x"}),
    ("model/safetyBuffering/updated", {}),
    ("turn/plan/updated", {"threadId": "thread-x", "plan": []}),
])
def test_uncorrelated_safe_notification_cannot_claim_clean(
    context, monkeypatch, method, params,
):
    frames = _success_frames()
    _add_agent(frames)
    frames.insert(-1, {"method": method, "params": params})
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )
    result = _run(context, allow_one_turn=True)
    assert result["clean_tool_free_pilot"] is False
    assert result["unexpected_notification_counts"]["uncorrelated_notification"] >= 1


def test_correlated_safe_plan_is_not_falsely_rejected(context, monkeypatch):
    frames = _success_frames()
    _add_agent(frames)
    frames.insert(-1, {"method": "turn/plan/updated", "params": {
        "threadId": "thread-x", "turnId": "turn-x", "plan": [],
    }})
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: _FakeProcess(frames),
    )
    result = _run(context, allow_one_turn=True)
    assert result["clean_tool_free_pilot"] is True
    assert result["item_lifecycle_consistent"] is True


def test_malformed_trailing_frame_quarantined_without_result(context, monkeypatch):
    frames = _success_frames()
    _add_agent(frames)
    frames.append(b'{"method":"item/started"')
    process = _FakeProcess(frames)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.local_codex_pilot.subprocess.Popen",
        lambda *a, **kw: process,
    )
    with pytest.raises(RuntimeError, match="truncated"):
        _run(context, allow_one_turn=True)
    assert (context[-1] / "quarantine.json").is_file()
    assert not (context[-1] / "result.json").exists()
    outgoing = [json.loads(x) for x in process.stdin.getvalue().splitlines()]
    assert sum(x["method"] == "turn/start" for x in outgoing) == 1


def test_missing_v2_lifecycle_evidence_cannot_pass_cli(monkeypatch):
    namespace = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts/pilot_one_codex_turn.py"))
    main = namespace["main"]
    result = {
        "status": "transport_completed_unreviewed",
        "live_turn_started": True, "retry_permitted": False,
        "production_finalization_permitted": False,
        "assistant_output_matches_expected": True,
        "assistant_message_observed": True,
        "assistant_output_preview": "ORCH_TEST_OK",
        "assistant_output_sha256": hashlib.sha256(b"ORCH_TEST_OK").hexdigest(),
        "expected_output": "ORCH_TEST_OK",
        "turn_start_request_id": 3, "turn_terminal_status": "completed",
        "tool_event_audit_version": 2,
        "tool_event_audit_complete": True,
        "tool_event_audit_scope": "observed_app_server_events_only",
        "observed_item_type_counts": {"agentMessage": 3},
        "unexpected_notification_counts": {},
        "unexpected_tool_activity_observed": False,
        "clean_tool_free_pilot": True,
    }
    monkeypatch.setitem(main.__globals__, "run_one_local_pilot", lambda *a, **kw: result)
    arguments = ["pilot_one_codex_turn.py"]
    for option in (
        "codex-exe", "schema-root", "cwd", "prompt-file", "receipt-dir", "model", "effort",
        "thread-params-schema", "thread-result-schema", "turn-params-schema",
        "turn-result-schema", "mcp-source-map",
    ):
        arguments.extend([f"--{option}", "synthetic"])
    monkeypatch.setattr("sys.argv", arguments)
    assert main() == 2
