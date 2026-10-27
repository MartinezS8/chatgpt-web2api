"""Receipt inspection is strictly offline, read-only, and conservative."""
from __future__ import annotations

import json

import pytest

from chatgpt_web2api.orchestrator.local_pilot_receipt import inspect_local_pilot_receipt


@pytest.fixture
def receipt_dir(tmp_path):
    folder = tmp_path / "receipt"
    folder.mkdir()
    (folder / "intent.json").write_text(json.dumps({
        "status": "possible_send_not_yet_verified",
        "prompt_sha256": "a" * 64,
        "turn_start_request_id": 3,
        "max_turn_starts": 1,
        "retry_permitted": False,
    }), encoding="utf-8")
    return folder


def _write(folder, name, payload):
    (folder / name).write_text(json.dumps(payload), encoding="utf-8")


def _result(terminal="completed"):
    return {
        "status": ("transport_completed_unreviewed" if terminal == "completed"
                   else "turn_ended_needs_review"),
        "turn_terminal_status": terminal,
        "thread_id": "thread-x", "turn_id": "turn-y",
        "live_turn_started": True, "retry_permitted": False,
        "production_finalization_permitted": False,
    }


def _quarantine(attempted):
    return {
        "status": ("needs_human_unknown_or_unverified_delivery" if attempted
                   else "pre_turn_failure_no_turn_start_attempted"),
        "turn_start_may_have_been_sent": attempted,
        "retry_permitted": False,
    }


def test_terminal_receipt_is_not_auto_finalized_or_retried(receipt_dir):
    _write(receipt_dir, "result.json", _result())
    before = (receipt_dir / "result.json").read_bytes()
    outcome = inspect_local_pilot_receipt(receipt_dir)
    assert outcome["classification"] == "LEGACY_TERMINAL_OUTPUT_UNCHECKED"
    assert outcome["provider_output_independently_verified"] is False
    assert outcome["automatic_retry_permitted"] is False
    assert outcome["production_finalization_permitted"] is False
    assert (receipt_dir / "result.json").read_bytes() == before


@pytest.mark.parametrize("terminal", ["failed", "interrupted"])
def test_failed_terminal_is_not_mistaken_for_success(receipt_dir, terminal):
    _write(receipt_dir, "result.json", _result(terminal))
    assert inspect_local_pilot_receipt(receipt_dir)["classification"] == (
        "TERMINAL_FAILED_OR_INTERRUPTED"
    )


@pytest.mark.parametrize("attempted,expected", [
    (True, "UNKNOWN_DELIVERY"), (False, "PRE_TURN_FAILURE"),
])
def test_quarantine_classifies_turn_attempt_without_replay(receipt_dir, attempted, expected):
    _write(receipt_dir, "quarantine.json", _quarantine(attempted))
    outcome = inspect_local_pilot_receipt(receipt_dir)
    assert outcome["classification"] == expected
    assert outcome["turn_start_may_have_been_sent"] is attempted
    assert outcome["same_receipt_directory_reusable"] is False


def test_legacy_quarantine_has_unknown_send_status(receipt_dir):
    _write(receipt_dir, "quarantine.json", {
        "status": "needs_human_unknown_or_unverified_delivery",
        "retry_permitted": False,
    })
    result = inspect_local_pilot_receipt(receipt_dir)
    assert result["classification"] == "LEGACY_OR_UNCLASSIFIED_QUARANTINE"
    assert result["turn_start_may_have_been_sent"] is None


def test_intent_without_result_is_not_misclassified_as_pre_send(receipt_dir):
    result = inspect_local_pilot_receipt(receipt_dir)
    assert result["classification"] == "INCOMPLETE_OR_INTERRUPTED"
    assert result["turn_start_may_have_been_sent"] is None


def test_conflicting_result_and_quarantine_are_inconsistent(receipt_dir):
    _write(receipt_dir, "result.json", _result())
    _write(receipt_dir, "quarantine.json", _quarantine(True))
    assert inspect_local_pilot_receipt(receipt_dir)["classification"] == (
        "INCONSISTENT_RECEIPT"
    )


def test_invalid_intent_and_conflicting_terminal_are_inconsistent(receipt_dir):
    _write(receipt_dir, "result.json", _result())
    intent = receipt_dir / "intent.json"
    content = json.loads(intent.read_text(encoding="utf-8"))
    content["retry_permitted"] = True
    intent.write_text(json.dumps(content), encoding="utf-8")
    assert inspect_local_pilot_receipt(receipt_dir)["classification"] == (
        "INCONSISTENT_RECEIPT"
    )
    content["retry_permitted"] = False
    intent.write_text(json.dumps(content), encoding="utf-8")
    broken = _result()
    broken["turn_terminal_status"] = "failed"
    _write(receipt_dir, "result.json", broken)
    assert inspect_local_pilot_receipt(receipt_dir)["classification"] == (
        "INCONSISTENT_RECEIPT"
    )


def test_malformed_json_duplicate_keys_and_symlink_are_rejected(receipt_dir):
    (receipt_dir / "result.json").write_text(
        '{"status":"x","status":"y"}', encoding="utf-8",
    )
    with pytest.raises(ValueError, match="malformed"):
        inspect_local_pilot_receipt(receipt_dir)
    (receipt_dir / "result.json").unlink()
    (receipt_dir / "result.json").write_text("x" * 17000, encoding="utf-8")
    with pytest.raises(ValueError, match="bounded"):
        inspect_local_pilot_receipt(receipt_dir)


def test_missing_intent_is_not_a_verified_result(tmp_path):
    root = tmp_path / "receipt"
    root.mkdir()
    _write(root, "result.json", _result())
    output = inspect_local_pilot_receipt(root)
    assert output["classification"] == "INCONSISTENT_RECEIPT"


def test_bound_receipt_rejects_changed_intent_without_authenticating_provider(receipt_dir):
    import hashlib

    intent = receipt_dir / "intent.json"
    result = _result()
    result["intent_sha256"] = hashlib.sha256(intent.read_bytes()).hexdigest()
    _write(receipt_dir, "result.json", result)
    report = inspect_local_pilot_receipt(receipt_dir)
    assert report["classification"] == "LEGACY_TERMINAL_OUTPUT_UNCHECKED"
    assert report["receipt_intent_binding_verified"] is True
    changed = json.loads(intent.read_text(encoding="utf-8"))
    changed["prompt_sha256"] = "b" * 64
    intent.write_text(json.dumps(changed), encoding="utf-8")
    report = inspect_local_pilot_receipt(receipt_dir)
    assert report["classification"] == "INCONSISTENT_RECEIPT"
    assert report["receipt_intent_binding_verified"] is False
    assert report["provider_output_independently_verified"] is False


def test_legacy_result_does_not_claim_binding(receipt_dir):
    _write(receipt_dir, "result.json", _result())
    report = inspect_local_pilot_receipt(receipt_dir)
    assert report["receipt_intent_binding_verified"] is False
    assert report["classification"] == "LEGACY_TERMINAL_OUTPUT_UNCHECKED"


@pytest.mark.parametrize("matches,observed,expected", [
    (True, True, "TERMINAL_TOOL_AUDIT_UNVERIFIED"),
    (False, True, "TERMINAL_OUTPUT_MISMATCH_OR_MISSING"),
    (False, False, "TERMINAL_OUTPUT_MISMATCH_OR_MISSING"),
])
def test_terminal_transport_is_not_confused_with_correct_answer(
    receipt_dir, matches, observed, expected,
):
    result = _result()
    result["assistant_output_matches_expected"] = matches
    result["assistant_message_observed"] = observed
    _write(receipt_dir, "result.json", result)
    report = inspect_local_pilot_receipt(receipt_dir)
    assert report["classification"] == expected
    assert report["production_finalization_permitted"] is False


@pytest.mark.parametrize("unexpected,clean,expected", [
    (False, True, "TERMINAL_OUTPUT_MATCHED_UNREVIEWED"),
    (True, False, "TERMINAL_UNEXPECTED_TOOL_ACTIVITY"),
    (True, True, "INCONSISTENT_RECEIPT"),
    (False, False, "INCONSISTENT_RECEIPT"),
])
def test_matching_answer_needs_consistent_tool_event_audit(
    receipt_dir, unexpected, clean, expected,
):
    import hashlib

    result = _result()
    result.update(
        assistant_output_matches_expected=True,
        assistant_message_observed=True,
        assistant_output_preview="ORCH_TEST_OK",
        assistant_output_sha256=hashlib.sha256(b"ORCH_TEST_OK").hexdigest(),
        expected_output="ORCH_TEST_OK",
        turn_start_request_id=3,
        intent_sha256=hashlib.sha256((receipt_dir / "intent.json").read_bytes()).hexdigest(),
        tool_event_audit_version=1,
        tool_event_audit_complete=True,
        tool_event_audit_scope="observed_app_server_events_only",
        observed_item_type_counts=({"agentMessage": 1, "commandExecution": 1} if unexpected
                                   else {"agentMessage": 1}),
        unexpected_notification_counts={},
        unexpected_tool_activity_observed=unexpected,
        clean_tool_free_pilot=clean,
    )
    _write(receipt_dir, "result.json", result)

    report = inspect_local_pilot_receipt(receipt_dir)

    assert report["classification"] == expected
    assert report["production_finalization_permitted"] is False


def test_audit_counts_cannot_disagree_with_no_tool_claim(receipt_dir):
    import hashlib

    result = _result()
    result.update(
        assistant_output_matches_expected=True,
        assistant_message_observed=True,
        assistant_output_preview="ORCH_TEST_OK",
        assistant_output_sha256=hashlib.sha256(b"ORCH_TEST_OK").hexdigest(),
        expected_output="ORCH_TEST_OK",
        turn_start_request_id=3,
        tool_event_audit_version=1,
        tool_event_audit_complete=True,
        tool_event_audit_scope="observed_app_server_events_only",
        observed_item_type_counts={"agentMessage": 1, "commandExecution": 1},
        unexpected_notification_counts={},
        unexpected_tool_activity_observed=False,
        clean_tool_free_pilot=True,
    )
    _write(receipt_dir, "result.json", result)

    assert inspect_local_pilot_receipt(receipt_dir)["classification"] == "INCONSISTENT_RECEIPT"


@pytest.mark.parametrize("field,value", [
    ("assistant_output_sha256", "0" * 64),
    ("assistant_output_preview", "other"),
    ("expected_output", "other"),
    ("turn_start_request_id", 99),
    ("observed_item_type_counts", {}),
])
def test_audited_receipt_rejects_conflicting_output_or_request_id(receipt_dir, field, value):
    import hashlib

    result = _result()
    result.update(
        assistant_output_matches_expected=True,
        assistant_message_observed=True,
        assistant_output_preview="ORCH_TEST_OK",
        assistant_output_sha256=hashlib.sha256(b"ORCH_TEST_OK").hexdigest(),
        expected_output="ORCH_TEST_OK",
        turn_start_request_id=3,
        tool_event_audit_version=1,
        tool_event_audit_complete=True,
        tool_event_audit_scope="observed_app_server_events_only",
        observed_item_type_counts={"agentMessage": 1},
        unexpected_notification_counts={},
        unexpected_tool_activity_observed=False,
        clean_tool_free_pilot=True,
        intent_sha256=hashlib.sha256((receipt_dir / "intent.json").read_bytes()).hexdigest(),
    )
    result[field] = value
    _write(receipt_dir, "result.json", result)

    assert inspect_local_pilot_receipt(receipt_dir)["classification"] == "INCONSISTENT_RECEIPT"


def test_request_id_must_match_bound_intent(receipt_dir):
    import hashlib

    intent_path = receipt_dir / "intent.json"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["turn_start_request_id"] = 99
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    result = _result()
    result.update(
        assistant_output_matches_expected=True,
        assistant_message_observed=True,
        assistant_output_preview="ORCH_TEST_OK",
        assistant_output_sha256=hashlib.sha256(b"ORCH_TEST_OK").hexdigest(),
        expected_output="ORCH_TEST_OK",
        turn_start_request_id=3,
        tool_event_audit_version=1,
        tool_event_audit_complete=True,
        tool_event_audit_scope="observed_app_server_events_only",
        observed_item_type_counts={"agentMessage": 1},
        unexpected_notification_counts={},
        unexpected_tool_activity_observed=False,
        clean_tool_free_pilot=True,
        intent_sha256=hashlib.sha256(intent_path.read_bytes()).hexdigest(),
    )
    _write(receipt_dir, "result.json", result)

    assert inspect_local_pilot_receipt(receipt_dir)["classification"] == "INCONSISTENT_RECEIPT"


def test_unexpected_output_digest_is_not_accepted_in_audited_receipt(receipt_dir):
    result = _result()
    result.update(
        assistant_output_matches_expected=False,
        assistant_message_observed=True,
        assistant_output_preview=None,
        assistant_output_sha256="0" * 64,
        expected_output="ORCH_TEST_OK",
        turn_start_request_id=3,
        tool_event_audit_version=1,
        tool_event_audit_complete=True,
        tool_event_audit_scope="observed_app_server_events_only",
        observed_item_type_counts={"agentMessage": 1},
        unexpected_notification_counts={},
        unexpected_tool_activity_observed=False,
        clean_tool_free_pilot=False,
    )
    _write(receipt_dir, "result.json", result)

    assert inspect_local_pilot_receipt(receipt_dir)["classification"] == "INCONSISTENT_RECEIPT"
