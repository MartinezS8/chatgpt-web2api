"""Offline fake app-server JSONL integration tests; never invoke a Codex CLI."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Event

import pytest

import chatgpt_web2api.orchestrator.app_server_fake as app_server_fake
from chatgpt_web2api.orchestrator.app_server_fake import (
    AttemptBinding,
    FakeAppServerScenario,
    OfflineFakeAppServer,
    ProtocolRejected,
    UnknownDelivery,
)

SYNTHETIC_PROMPT = "synthetic-only-marker-48b"


def binding():
    return AttemptBinding(
        controller_id="controller-offline",
        worker_id="worker-offline-1",
        account_id="account-offline",
        project_id="project-offline",
        task_id="task-offline-1",
        attempt_id="attempt-offline-1",
    )


def session(tmp_path, scenario=FakeAppServerScenario.SUCCESS, **kwargs):
    kwargs.setdefault("timeout_seconds", 0.5)
    return OfflineFakeAppServer(
        binding(), scenario=scenario, **kwargs
    )


def test_fake_stdio_roundtrip_uses_bounded_jsonl_and_eof_shutdown(tmp_path, caplog):
    worker = session(tmp_path)
    result = worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))

    assert result["state"] == "transport_completed_unverified"
    assert result["thread_id"] == "fake-thread-48b"
    assert result["turn_id"] == "fake-turn-48b"
    assert result["model"] == "offline-fake-model-0.157"
    assert result["effort"] == "medium"
    assert worker.live_send_permitted is False
    assert worker.delivery_status == "transport_completed_unverified"
    assert worker.shutdown_mode == "stdin_eof"
    assert worker.process_exit_code == 0
    assert worker.request_count("initialize") == 1
    assert worker.notification_count("initialized") == 1
    assert worker.request_count("model/list") == 1
    assert worker.request_count("thread/start") == 1
    assert worker.request_count("turn/start") == 1
    assert worker.request_count("item/commandExecution/requestApproval") == 0
    assert SYNTHETIC_PROMPT not in repr(result)
    assert SYNTHETIC_PROMPT not in caplog.text


def test_attempt_binding_is_immutable_for_one_fake_process_attempt(tmp_path):
    original = binding()
    worker = OfflineFakeAppServer(original)
    with pytest.raises(FrozenInstanceError):
        original.worker_id = "different-worker"

    result = worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))
    assert worker.binding is original
    assert result["worker_id"] == "worker-offline-1"


def test_exact_synthetic_model_and_effort_have_no_fallback(tmp_path):
    worker = session(tmp_path, model="unavailable-model")

    with pytest.raises(ProtocolRejected, match="unavailable or ambiguous"):
        worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))

    assert worker.delivery_status == "needs_human"
    assert worker.request_count("thread/start") == 0
    assert worker.request_count("turn/start") == 0

    unsupported_effort = session(tmp_path, effort="high")
    with pytest.raises(ProtocolRejected, match="reasoning effort was not attested"):
        unsupported_effort.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))
    assert unsupported_effort.request_count("thread/start") == 0
    assert unsupported_effort.request_count("turn/start") == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 61},
        {"max_frame_bytes": 65_537},
        {"max_queued_messages": 65},
    ],
)
def test_transport_limits_are_finite_and_bounded(kwargs):
    with pytest.raises(ValueError, match="bounded fake transport"):
        OfflineFakeAppServer(binding(), **kwargs)


@pytest.mark.parametrize(
    "scenario",
    [
        FakeAppServerScenario.MALFORMED_JSON,
        FakeAppServerScenario.TRUNCATED_JSONL,
        FakeAppServerScenario.DUPLICATE_JSON_KEYS,
        FakeAppServerScenario.OVERSIZED_OUTPUT,
        FakeAppServerScenario.WRONG_REQUEST_ID,
        FakeAppServerScenario.APPROVAL_REQUEST,
        FakeAppServerScenario.FOREIGN_THREAD,
        FakeAppServerScenario.FOREIGN_TURN,
        FakeAppServerScenario.DUPLICATE_TERMINAL,
    ],
)
def test_adversarial_transcripts_fail_closed_without_payload_errors(tmp_path, scenario):
    worker = session(tmp_path, scenario)

    with pytest.raises((ProtocolRejected, UnknownDelivery)):
        worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))

    assert worker.delivery_status in {"needs_human", "unknown_delivery"}
    assert worker.live_send_permitted is False
    assert worker.request_count("item/commandExecution/requestApproval") == 0


@pytest.mark.parametrize(
    "scenario",
    [
        FakeAppServerScenario.BROKEN_PIPE_BEFORE_TURN,
        FakeAppServerScenario.DIE_AFTER_TURN_REQUEST,
        FakeAppServerScenario.TIMEOUT_AFTER_TURN_REQUEST,
    ],
)
def test_uncertain_turn_delivery_is_never_emitted_again(tmp_path, scenario):
    # Windows process startup itself can exceed 150ms on a cold interpreter;
    # retain enough time for startup while the timeout scenario still blocks.
    worker = session(tmp_path, scenario, timeout_seconds=0.75)

    with pytest.raises(UnknownDelivery):
        worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))

    attempts_after_failure = worker.request_count("turn/start")
    assert attempts_after_failure == 1
    assert worker.delivery_status == "unknown_delivery"
    with pytest.raises(UnknownDelivery, match="already quarantined"):
        worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))
    assert worker.request_count("turn/start") == attempts_after_failure


def test_interrupted_turn_requires_human_and_does_not_repeat(tmp_path):
    worker = session(tmp_path, FakeAppServerScenario.INTERRUPTED)

    result = worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))

    assert result["state"] == "needs_human"
    assert worker.delivery_status == "needs_human"
    assert worker.request_count("turn/start") == 1


def test_prompt_echo_is_not_retained_in_result_logs_or_session_repr(tmp_path, caplog):
    worker = session(tmp_path, FakeAppServerScenario.ECHO_PROMPT)

    result = worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))

    assert result["state"] == "transport_completed_unverified"
    assert SYNTHETIC_PROMPT not in caplog.text
    assert SYNTHETIC_PROMPT not in repr(result)
    assert SYNTHETIC_PROMPT not in repr(worker)


@pytest.mark.parametrize("prompt", ["x" * 8192, "x\n" * 1500, "é" * 2048])
def test_oversized_outbound_prompt_is_rejected_before_turn_bytes(
    tmp_path, monkeypatch, prompt
):
    worker = session(tmp_path, max_frame_bytes=4096)
    serialized_prompt_sizes = []
    original_dumps = app_server_fake.json.dumps

    def track_prompt_serialization(value, *args, **kwargs):
        if isinstance(value, dict) and value.get("method") == "turn/start":
            prompt = value["params"]["input"][0]["text"]
            serialized_prompt_sizes.append(len(prompt))
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(app_server_fake.json, "dumps", track_prompt_serialization)

    with pytest.raises(ProtocolRejected, match="outbound JSONL frame exceeds limit"):
        worker.run(prompt=prompt, cwd=str(tmp_path))

    assert worker.request_count("turn/start") == 0
    assert worker.delivery_status == "not_sent"
    assert serialized_prompt_sizes == []


def test_oversized_cwd_is_rejected_before_thread_request_serialization(tmp_path, monkeypatch):
    worker = session(tmp_path, max_frame_bytes=4096)
    serialized_cwd_sizes = []
    original_dumps = app_server_fake.json.dumps

    def track_cwd_serialization(value, *args, **kwargs):
        if isinstance(value, dict) and value.get("method") == "thread/start":
            serialized_cwd_sizes.append(len(value["params"]["cwd"]))
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(app_server_fake.json, "dumps", track_cwd_serialization)
    with pytest.raises(ProtocolRejected, match="outbound JSONL frame exceeds limit"):
        worker.run(prompt=SYNTHETIC_PROMPT, cwd="C:\\" + "x" * 8192)

    assert worker.request_count("thread/start") == 0
    assert worker.request_count("turn/start") == 0
    assert worker.delivery_status == "not_sent"
    assert serialized_cwd_sizes == []


def test_concurrent_run_is_rejected_without_replacing_first_transport(tmp_path, monkeypatch):
    worker = session(tmp_path, timeout_seconds=5)
    first_request_entered = Event()
    release_first_request = Event()
    original_request = app_server_fake._FakeJsonlProcess.request

    def pause_first_request(transport, request, **kwargs):
        if request.get("method") == "initialize":
            first_request_entered.set()
            if not release_first_request.wait(timeout=5):
                raise AssertionError("test did not release first fake request")
        return original_request(transport, request, **kwargs)

    monkeypatch.setattr(app_server_fake._FakeJsonlProcess, "request", pause_first_request)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(worker.run, prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))
        assert first_request_entered.wait(timeout=5)
        second = executor.submit(worker.run, prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))
        try:
            with pytest.raises(ProtocolRejected, match="already running"):
                second.result(timeout=3)
        finally:
            release_first_request.set()
        result = first.result(timeout=10)

    assert result["state"] == "transport_completed_unverified"
    assert worker.request_count("turn/start") == 1
    assert worker.process_exit_code == 0
    assert worker.shutdown_mode == "stdin_eof"


def test_attempt_result_uses_binding_captured_at_start(tmp_path, monkeypatch):
    original_binding = binding()
    worker = OfflineFakeAppServer(original_binding)
    finish = app_server_fake._FakeJsonlProcess.finish

    def finish_then_rebind(transport, **kwargs):
        result = finish(transport, **kwargs)
        worker._binding = AttemptBinding(
            controller_id="controller-rebound",
            worker_id="worker-rebound",
            account_id="account-rebound",
            project_id="project-rebound",
            task_id="task-rebound",
            attempt_id="attempt-rebound",
        )
        return result

    monkeypatch.setattr(app_server_fake._FakeJsonlProcess, "finish", finish_then_rebind)
    result = worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))

    assert result["worker_id"] == original_binding.worker_id
    assert result["attempt_id"] == original_binding.attempt_id


def test_output_flood_is_rejected_by_queue_limit_not_timeout(tmp_path, monkeypatch):
    worker = session(
        tmp_path,
        FakeAppServerScenario.OUTPUT_FLOOD,
        timeout_seconds=5,
        max_queued_messages=1,
    )
    next_raw = app_server_fake._FakeJsonlProcess._next_raw

    def hold_consumer_until_output_queue_fails(transport, deadline):
        if (transport._scenario is FakeAppServerScenario.OUTPUT_FLOOD
                and transport.request_count("model/list") == 1):
            assert transport._fatal.wait(timeout=5)
        return next_raw(transport, deadline)

    monkeypatch.setattr(
        app_server_fake._FakeJsonlProcess,
        "_next_raw",
        hold_consumer_until_output_queue_fails,
    )
    with pytest.raises(UnknownDelivery, match="output queue exceeded its message limit"):
        worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))

    assert worker.delivery_status == "unknown_delivery"
    assert worker.request_count("turn/start") == 0


def test_deeply_nested_bounded_json_is_quarantined(tmp_path):
    depth = 5000
    frame = b'{"nested":' + b"[" * depth + b"0" + b"]" * depth + b"}\n"
    assert len(frame) < 65_536

    with pytest.raises(UnknownDelivery, match="malformed JSONL"):
        app_server_fake._FakeJsonlProcess._decode(frame)


@pytest.mark.parametrize(
    "value",
    ['quote"', "slash\\", "\x00\x1f\b\f\n\r\t", "é", "🧪", "plain"],
)
def test_bounded_json_string_size_matches_encoder(value):
    expected = len(app_server_fake.json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8"))

    assert app_server_fake._json_string_encoded_size(value, limit=1024) == expected


def test_bounded_json_string_size_rejects_lone_surrogate():
    with pytest.raises(ProtocolRejected, match="invalid Unicode"):
        app_server_fake._json_string_encoded_size("\ud800", limit=1024)


def test_foreign_turn_started_after_ack_is_rejected(tmp_path):
    worker = session(tmp_path, FakeAppServerScenario.FOREIGN_TURN_AFTER_ACK)

    with pytest.raises(ProtocolRejected, match="different turn"):
        worker.run(prompt=SYNTHETIC_PROMPT, cwd=str(tmp_path))

    assert worker.delivery_status == "needs_human"
    assert worker.request_count("turn/start") == 1
