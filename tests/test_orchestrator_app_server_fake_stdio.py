"""Offline fake app-server JSONL integration tests; never invoke a Codex CLI."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

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
        FakeAppServerScenario.OUTPUT_FLOOD,
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


def test_oversized_outbound_prompt_is_rejected_before_turn_bytes(tmp_path):
    worker = session(tmp_path, max_frame_bytes=4096)

    with pytest.raises(ProtocolRejected, match="outbound JSONL frame exceeds limit"):
        worker.run(prompt="x" * 8192, cwd=str(tmp_path))

    assert worker.request_count("turn/start") == 0
    assert worker.delivery_status == "not_sent"
