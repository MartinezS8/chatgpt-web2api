"""The manual pilot emits one synthetic turn at most and never auto-retries."""
from __future__ import annotations

import io
import json

import pytest

import chatgpt_web2api.orchestrator.local_codex_pilot as pilot


class _RetainStdin(io.BytesIO):
    def close(self):
        pass


class _FakeProcess:
    def __init__(self, data):
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
    cwd = tmp_path / "scratch"
    cwd.mkdir()
    receipt = tmp_path / "first-attempt"
    monkeypatch.setattr(pilot, "local_pilot_doctor", lambda *a, **kw: {
        "codex_version": "codex-cli fixture",
    })
    monkeypatch.setattr(pilot, "discover_local_codex", lambda *a, **kw: {
        "account_present": True,
        "models": [{"id": "available", "supported_efforts": ["medium"]}],
    })
    return exe, root, cwd, prompt, receipt


def _run(ctx, **kwargs):
    exe, root, cwd, prompt, receipt = ctx
    return pilot.run_one_local_pilot(
        exe, root, cwd, prompt, receipt, model="available",
        effort="medium", **kwargs,
    )


def _success_frames():
    return [
        {"id": 1, "result": {"userAgent": "codex fixture"}},
        {"method": "thread/started", "params": {"thread": {"id": "thread-x"}}},
        {"id": 2, "result": {"thread": {"id": "thread-x", "sessionId": "thread-x"}}},
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
