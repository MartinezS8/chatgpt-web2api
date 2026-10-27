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
    assert outcome["classification"] == "TERMINAL_UNREVIEWED"
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


@pytest.mark.parametrize("field,value", [
    ("max_turn_starts", True),
    ("max_turn_starts", "1"),
    ("max_turn_starts", 0),
    ("status", "transport_completed_unreviewed"),
])
def test_wrong_intent_contract_never_validates_terminal(receipt_dir, field, value):
    _write(receipt_dir, "result.json", _result())
    target = receipt_dir / "intent.json"
    intent = json.loads(target.read_text(encoding="utf-8"))
    intent[field] = value
    _write(receipt_dir, "intent.json", intent)
    actual = inspect_local_pilot_receipt(receipt_dir)
    assert actual["classification"] == "INCONSISTENT_RECEIPT"
    assert actual["production_finalization_permitted"] is False


def test_explicit_integer_max_turns_is_required(receipt_dir):
    _write(receipt_dir, "result.json", _result())
    intent = json.loads((receipt_dir / "intent.json").read_text(encoding="utf-8"))
    intent.pop("max_turn_starts")
    _write(receipt_dir, "intent.json", intent)
    actual = inspect_local_pilot_receipt(receipt_dir)
    assert actual["classification"] == "INCONSISTENT_RECEIPT"
