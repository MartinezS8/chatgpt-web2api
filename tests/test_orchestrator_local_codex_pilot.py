"""The manual pilot emits one synthetic turn at most and never auto-retries."""
from __future__ import annotations

import hashlib
import io
import json

import pytest

import chatgpt_web2api.orchestrator.local_codex_pilot as pilot


class _RetainStdin(io.BytesIO):
    def close(self):
        pass


class _FakeProcess:
    _test_cwd = None

    def __init__(self, data):
        for frame in data:
            if (isinstance(frame, dict) and frame.get("id") == 2
                    and isinstance(frame.get("result"), dict)
                    and frame["result"].get("cwd") == "__TEST_CWD__"):
                frame["result"]["cwd"] = str(self._test_cwd)
        self.stdin = _RetainStdin()
        self.stdout = io.BytesIO(b"".join(
            (json.dumps(frame) + "\n").encode("utf-8")
            if isinstance(frame, dict) else frame
            for frame in data
        ))
    def wait(self, *, timeout):
        return 0
    def terminate(self):
        pass
    def kill(self):
        pass


@pytest.fixture
def context(tmp_path, monkeypatch):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Output exactly ORCH_TEST_OK; do not use tools.", encoding="utf-8")
    exe = tmp_path / "codex.exe"
    exe.write_text("mock exe never run", encoding="utf-8")
    root = tmp_path / "schema"
    root.mkdir()
    schemas = {
        "ThreadStartParams.json": {
            "type": "object", "required": ["model", "sandbox"],
            "properties": {"sandbox": {"const": "read-only"}},
        },
        "ThreadStartResponse.json": {
            "type": "object", "required": ["thread"],
            "properties": {"thread": {
                "type": "object", "required": ["id", "source"],
                "properties": {"source": {"const": "synthetic"}}}},
        },
        "TurnStartParams.json": {
            "type": "object", "required": ["threadId", "input"],
            "properties": {"threadId": {"type": "string"}, "input": {"type": "array"}},
        },
        "TurnStartResponse.json": {
            "type": "object", "required": ["turn"],
            "properties": {"turn": {"type": "object"}},
        },
    }
    manifest = []
    for name, value in schemas.items():
        path = root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        manifest.append({
            "path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (root / "offline-readiness.json").write_text(json.dumps({
        "codex_version": "codex-cli fixture",
        "codex_binary_sha256": "a" * 64,
        "installed_schema_inspected": True,
        "generated_json_schema": manifest,
    }), encoding="utf-8")
    cwd = tmp_path / "scratch"
    cwd.mkdir()
    _FakeProcess._test_cwd = cwd
    receipt = tmp_path / "first-attempt"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(pilot, "local_pilot_doctor", lambda *a, **kw: {
        "codex_version": "codex-cli fixture",
        "binary_sha256": "a" * 64,
    })
    monkeypatch.setattr(pilot, "discover_local_codex", lambda *a, **kw: {
        "account_present": True,
        "account_mode": "chatgpt",
        "models": [{"id": "available", "supported_efforts": ["medium"],
                    "model_slug": "available", "supports_text": True,
                    "hidden": False}],
    })
    return exe, root, cwd, prompt, receipt


def _run(ctx, **kwargs):
    exe, root, cwd, prompt, receipt = ctx
    return pilot.run_one_local_pilot(
        exe, root, cwd, prompt, receipt, model="available",
        effort="medium", schema_selectors={
            "thread_params": "ThreadStartParams.json",
            "thread_result": "ThreadStartResponse.json",
            "turn_params": "TurnStartParams.json",
            "turn_result": "TurnStartResponse.json",
        }, **kwargs,
    )


def _success_frames():
    return [
        {"id": 1, "result": {"userAgent": "codex fixture"}},
        {"method": "thread/started", "params": {"thread": {"id": "thread-x"}}},
        {"id": 2, "result": {"thread": {
            "id": "thread-x", "sessionId": "thread-x", "source": "synthetic"},
            "model": "available", "approvalPolicy": "never",
            "sandbox": {"type": "readOnly"}, "cwd": "__TEST_CWD__"}},
        {"method": "turn/started", "params": {
            "threadId": "thread-x", "turnId": "turn-x",
            "turn": {"id": "turn-x", "status": "inProgress"}}},
        {"id": 3, "result": {"turn": {"id": "turn-x", "status": "inProgress"}}},
        {"method": "turn/completed", "params": {
            "threadId": "thread-x",
            "turn": {"id": "turn-x", "status": "completed"}}},
    ]


def test_no_consent_prevents_all_process_activity(context, monkeypatch):
    _, _, _, _, receipt = context
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: pytest.fail("spawned"))
    with pytest.raises(PermissionError, match="allow-one-turn"):
        _run(context)
    assert not receipt.exists()


def test_single_completed_turn_durable_receipts(context, monkeypatch):
    process = _FakeProcess(_success_frames())
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: process)
    result = _run(context, allow_one_turn=True)
    messages = [json.loads(s) for s in process.stdin.getvalue().splitlines()]
    assert [m["method"] for m in messages] == [
        "initialize", "initialized", "thread/start", "turn/start",
    ]
    assert messages[-1]["params"]["sandboxPolicy"] == {"type": "readOnly"}
    assert messages[-1]["params"]["approvalPolicy"] == "never"
    assert result["status"] == "transport_completed_unreviewed"
    assert result["retry_permitted"] is False
    receipt = context[-1]
    assert (receipt / "intent.json").is_file()
    assert (receipt / "result.json").is_file()
    intent_digest = hashlib.sha256((receipt / "intent.json").read_bytes()).hexdigest()
    assert json.loads((receipt / "result.json").read_text(encoding="utf-8"))[
        "intent_sha256"
    ] == intent_digest
    assert not (receipt / "quarantine.json").exists()
    assert "Output exactly" not in (receipt / "intent.json").read_text("utf-8")
    with pytest.raises(ValueError, match="new"):
        _run(context, allow_one_turn=True)


def test_foreign_terminal_does_not_get_marked_as_completed(context, monkeypatch):
    messages = _success_frames()
    messages[-1]["params"]["threadId"] = "foreign-thread"
    process = _FakeProcess(messages)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(RuntimeError, match="unmatched"):
        _run(context, allow_one_turn=True)
    receipt = context[-1]
    assert (receipt / "intent.json").exists()
    q = json.loads((receipt / "quarantine.json").read_text("utf-8"))
    assert q["retry_permitted"] is False
    assert not (receipt / "result.json").exists()


def test_lost_ack_after_one_turn_is_quarantined_no_replay(context, monkeypatch):
    frames = _success_frames()[:-2]
    process = _FakeProcess(frames)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(RuntimeError, match="closed"):
        _run(context, allow_one_turn=True)
    outgoing = [json.loads(v) for v in process.stdin.getvalue().splitlines()]
    assert sum(msg["method"] == "turn/start" for msg in outgoing) == 1
    assert (context[-1] / "quarantine.json").exists()
    assert not (context[-1] / "result.json").exists()


def test_wire_rejects_second_turn_even_after_ack():
    process = _FakeProcess([])
    wire = pilot._OneTurnWire(process, timeout=10)
    wire._send("turn/start", {"threadId": "x"}, request_id=3)
    with pytest.raises(PermissionError, match="second"):
        wire._send("turn/start", {"threadId": "x"}, request_id=4)
    assert len(process.stdin.getvalue().splitlines()) == 1


def test_schema_mismatch_in_thread_result_prevents_turn_start(context, monkeypatch):
    frames = _success_frames()
    frames[2]["result"]["thread"]["source"] = "old-0.157"
    proc = _FakeProcess(frames)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: proc)
    with pytest.raises(ValueError, match="thread_result"):
        _run(context, allow_one_turn=True)
    outgoing = [json.loads(line) for line in proc.stdin.getvalue().splitlines()]
    assert [item["method"] for item in outgoing] == [
        "initialize", "initialized", "thread/start",
    ]
    assert (context[-1] / "quarantine.json").exists()


def test_schema_mismatch_in_turn_params_prevents_turn_start(context, monkeypatch):
    root = context[1]
    schema = root / "TurnStartParams.json"
    schema.write_text(json.dumps({
        "type": "object", "required": ["threadId", "input", "mustNotBeOmitted"],
    }), encoding="utf-8")
    receipt = root / "offline-readiness.json"
    manifest = json.loads(receipt.read_text(encoding="utf-8"))
    for entry in manifest["generated_json_schema"]:
        if entry["path"] == schema.name:
            entry["sha256"] = hashlib.sha256(schema.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _FakeProcess(_success_frames())
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: proc)
    with pytest.raises(ValueError, match="turn_params"):
        _run(context, allow_one_turn=True)
    outgoing = [json.loads(line) for line in proc.stdin.getvalue().splitlines()]
    assert [item["method"] for item in outgoing] == [
        "initialize", "initialized", "thread/start",
    ]
    assert (context[-1] / "quarantine.json").exists()


def test_missing_wire_schema_selector_rejects_before_process_and_account(context, monkeypatch):
    exe, root, cwd, prompt, folder = context
    monkeypatch.setattr(pilot, "discover_local_codex", lambda *a, **kw: pytest.fail(
        "account read must not occur before schema selection"))
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: pytest.fail(
        "must not spawn app-server before schema validation"))
    with pytest.raises(ValueError, match="selectors"):
        pilot.run_one_local_pilot(
            exe, root, cwd, prompt, folder, model="available", effort="medium",
            allow_one_turn=True,
        )
    assert not folder.exists()


def test_schema_tampering_rejects_before_account_access(context, monkeypatch):
    schema = context[1] / "ThreadStartResponse.json"
    schema.write_text('{"type":"null"}', encoding="utf-8")
    monkeypatch.setattr(pilot, "discover_local_codex", lambda *a, **kw: pytest.fail(
        "account discovery after corrupted schema"))
    with pytest.raises(ValueError, match="checksum"):
        _run(context, allow_one_turn=True)
    assert not context[-1].exists()


def test_mismatched_thread_result_receipt_identifies_no_turn_attempt(context, monkeypatch):
    frames = _success_frames()
    frames[2]["result"]["thread"].pop("source")
    proc = _FakeProcess(frames)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: proc)
    with pytest.raises(ValueError, match="thread_result"):
        _run(context, allow_one_turn=True)
    receipt = json.loads((context[-1] / "quarantine.json").read_text("utf-8"))
    assert receipt["turn_start_may_have_been_sent"] is False
    assert receipt["status"] == "pre_turn_failure_no_turn_start_attempted"
    methods = [json.loads(line)["method"] for line in proc.stdin.getvalue().splitlines()]
    assert "turn/start" not in methods


def test_lost_post_send_ack_marks_uncertain_not_resendable(context, monkeypatch):
    frames = _success_frames()
    # Drop the turn/start ACK; process closes after one outbound turn/start.
    proc = _FakeProcess(frames[:4])
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: proc)
    with pytest.raises(RuntimeError, match="closed"):
        _run(context, allow_one_turn=True)
    receipt = json.loads((context[-1] / "quarantine.json").read_text("utf-8"))
    assert receipt["turn_start_may_have_been_sent"] is True
    assert receipt["status"] == "needs_human_unknown_or_unverified_delivery"
    assert receipt["retry_permitted"] is False
    methods = [json.loads(line)["method"] for line in proc.stdin.getvalue().splitlines()]
    assert methods.count("turn/start") == 1


def test_turn_started_before_thread_ack_is_protocol_error(context, monkeypatch):
    frames = _success_frames()
    frames.insert(2, {
        "method": "turn/started",
        "params": {"threadId": "thread-x", "turn": {
            "id": "turn-x", "status": "inProgress",
        }},
    })
    proc = _FakeProcess(frames)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: proc)
    with pytest.raises(RuntimeError, match="before turn/start"):
        _run(context, allow_one_turn=True)
    methods = [json.loads(line)["method"] for line in proc.stdin.getvalue().splitlines()]
    assert "turn/start" not in methods


def test_nested_foreign_turn_progress_is_rejected(context, monkeypatch):
    frames = _success_frames()
    frames[3]["params"].pop("turnId")
    frames[3]["params"]["turn"]["id"] = "foreign-turn"
    proc = _FakeProcess(frames)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: proc)
    with pytest.raises(RuntimeError, match="nested notification belongs"):
        _run(context, allow_one_turn=True)
    receipt = json.loads((context[-1] / "quarantine.json").read_text("utf-8"))
    assert receipt["turn_start_may_have_been_sent"] is True
    assert receipt["retry_permitted"] is False


def test_final_agent_output_is_verified_separately_from_transport(context, monkeypatch):
    frames = _success_frames()
    frames.insert(-1, {
        "method": "item/completed", "params": {
            "threadId": "thread-x", "turnId": "turn-x",
            "item": {"id": "item-x", "type": "agentMessage",
                     "phase": "final_answer", "text": "ORCH_TEST_OK"},
        },
    })
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: _FakeProcess(frames))
    result = _run(context, allow_one_turn=True)
    assert result["assistant_message_observed"] is True
    assert result["assistant_output_matches_expected"] is True
    assert result["content_verified_by_operator"] is False


def test_completed_turn_with_wrong_text_is_not_output_verified(context, monkeypatch):
    frames = _success_frames()
    frames.insert(-1, {
        "method": "item/completed", "params": {
            "threadId": "thread-x", "turnId": "turn-x",
            "item": {"type": "agentMessage", "phase": "final_answer",
                     "text": "NOT_THE_EXPECTED_TEXT"},
        },
    })
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: _FakeProcess(frames))
    result = _run(context, allow_one_turn=True)
    assert result["status"] == "transport_completed_unreviewed"
    assert result["assistant_output_matches_expected"] is False


@pytest.mark.parametrize("property,value", [
    ("model", "another-model"), ("sandbox", {"type": "dangerFullAccess"}),
    ("approvalPolicy", "on-request"), ("cwd", "C:/different"),
])
def test_effective_thread_settings_mismatch_blocks_turn(context, monkeypatch, property, value):
    frames = _success_frames()
    frames[2]["result"][property] = value
    process = _FakeProcess(frames)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(RuntimeError, match="effective thread"):
        _run(context, allow_one_turn=True)
    assert "turn/start" not in [
        json.loads(s)["method"] for s in process.stdin.getvalue().splitlines()
    ]


def test_explicit_read_only_network_false_allows_single_turn(context, monkeypatch):
    frames = _success_frames()
    frames[2]["result"]["sandbox"] = {
        "type": "readOnly", "networkAccess": False,
    }
    process = _FakeProcess(frames)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: process)

    result = _run(context, allow_one_turn=True)

    assert result["retry_permitted"] is False
    assert [json.loads(s)["method"] for s in process.stdin.getvalue().splitlines()].count(
        "turn/start"
    ) == 1


@pytest.mark.parametrize("sandbox", [
    {"type": "readOnly", "networkAccess": True},
    {"type": "readOnly", "networkAccess": 0},
    {"type": "readOnly", "networkAccess": False, "unknownPolicy": "value"},
])
def test_effective_read_only_policy_rejects_network_or_unknown_fields(
    context, monkeypatch, sandbox,
):
    frames = _success_frames()
    frames[2]["result"]["sandbox"] = sandbox
    process = _FakeProcess(frames)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: process)

    with pytest.raises(RuntimeError, match="effective thread"):
        _run(context, allow_one_turn=True)

    assert "turn/start" not in [
        json.loads(s)["method"] for s in process.stdin.getvalue().splitlines()
    ]


def test_model_reroute_is_not_accepted_as_success(context, monkeypatch):
    frames = _success_frames()
    frames.insert(-1, {"method": "model/rerouted", "params": {
        "fromModel": "available", "toModel": "different",
        "reason": "capacity",
    }})
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: _FakeProcess(frames))
    with pytest.raises(RuntimeError, match="rerouting"):
        _run(context, allow_one_turn=True)
    assert (context[-1] / "quarantine.json").exists()


def test_completed_turn_without_agent_message_cannot_claim_output_match(context, monkeypatch):
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: _FakeProcess(
        _success_frames(),
    ))
    result = _run(context, allow_one_turn=True)
    assert result["assistant_message_observed"] is False
    assert result["assistant_output_matches_expected"] is False


def test_keyboard_interrupt_after_send_records_uncertainty(context, monkeypatch):
    class _InterruptedWire(pilot._OneTurnWire):
        def wait_terminal(self, **kwargs):
            raise KeyboardInterrupt("user canceled")

    proc = _FakeProcess(_success_frames())
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: proc)
    monkeypatch.setattr(pilot, "_OneTurnWire", _InterruptedWire)
    with pytest.raises(KeyboardInterrupt, match="canceled"):
        _run(context, allow_one_turn=True)
    record = json.loads((context[-1] / "quarantine.json").read_text("utf-8"))
    assert record["turn_start_may_have_been_sent"] is True
    assert record["retry_permitted"] is False


def test_keyboard_interrupt_before_send_records_pre_turn(context, monkeypatch):
    class _InterruptedWire(pilot._OneTurnWire):
        def initialized(self):
            raise KeyboardInterrupt("user canceled before thread")

    proc = _FakeProcess(_success_frames())
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: proc)
    monkeypatch.setattr(pilot, "_OneTurnWire", _InterruptedWire)
    with pytest.raises(KeyboardInterrupt):
        _run(context, allow_one_turn=True)
    record = json.loads((context[-1] / "quarantine.json").read_text("utf-8"))
    assert record["turn_start_may_have_been_sent"] is False


def test_api_key_account_not_silently_billed(context, monkeypatch):
    monkeypatch.setattr(pilot, "discover_local_codex", lambda *a, **kw: {
        "account_present": True, "account_mode": "api_key",
        "models": [{"id": "available", "supported_efforts": ["medium"]}],
    })
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: pytest.fail(
        "provider process must not spawn under API key auth"))
    with pytest.raises(PermissionError, match="API-key billing"):
        _run(context, allow_one_turn=True)
    assert not context[-1].exists()


def test_model_slug_is_sent_not_picker_id(context, monkeypatch):
    monkeypatch.setattr(pilot, "discover_local_codex", lambda *a, **kw: {
        "account_present": True, "account_mode": "chatgpt",
        "models": [{"id": "available", "model_slug": "actual-slug",
                    "supported_efforts": ["medium"], "supports_text": True}],
    })
    frames = _success_frames()
    frames[2]["result"]["model"] = "actual-slug"
    proc = _FakeProcess(frames)
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: proc)
    result = _run(context, allow_one_turn=True)
    outgoing = [json.loads(line) for line in proc.stdin.getvalue().splitlines()]
    thread = next(x for x in outgoing if x["method"] == "thread/start")
    turn = next(x for x in outgoing if x["method"] == "turn/start")
    assert thread["params"]["model"] == "actual-slug"
    assert turn["params"]["model"] == "actual-slug"
    assert result["effective_model_slug"] == "actual-slug"


def test_text_incompatible_model_is_rejected(context, monkeypatch):
    monkeypatch.setattr(pilot, "discover_local_codex", lambda *a, **kw: {
        "account_present": True, "account_mode": "chatgpt",
        "models": [{"id": "available", "supported_efforts": ["medium"],
                    "supports_text": False}],
    })
    with pytest.raises(ValueError, match="does not support text"):
        _run(context, allow_one_turn=True)


def test_new_receipt_dir_cannot_replay_same_one_turn_under_same_user(context, monkeypatch):
    first = _FakeProcess(_success_frames())
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: first)
    result = _run(context, allow_one_turn=True)
    assert result["local_replay_reservation_recorded"] is True
    exe, schemas, cwd, prompt, original_receipt = context
    new_ctx = (exe, schemas, cwd, prompt, original_receipt.with_name("other-receipt"))
    monkeypatch.setattr(pilot.subprocess, "Popen", lambda *a, **kw: pytest.fail(
        "repeat launch must not reach provider"))
    with pytest.raises(PermissionError, match="already recorded"):
        _run(new_ctx, allow_one_turn=True)
    q = json.loads((new_ctx[-1] / "quarantine.json").read_text(encoding="utf-8"))
    assert q["turn_start_may_have_been_sent"] is False
    assert q["retry_permitted"] is False
