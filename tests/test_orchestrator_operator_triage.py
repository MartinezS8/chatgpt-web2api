"""Offline triage cannot authorize a retry or complete a task."""
from __future__ import annotations

import pytest

from chatgpt_web2api.orchestrator.operator_triage import assess_delivery_case


def snapshot(status="unknown_delivery", **changes):
    result = {
        "attempt_id": "synthetic", "status": status,
        "pending_or_uncertain_messages": 1,
        "terminal_seen_unverified": False,
        "automatic_retry_permitted": False,
        "finalization_permitted": False,
    }
    result.update(changes)
    return result


@pytest.mark.parametrize("status", [
    "prepared", "running_offline_fake", "unknown_delivery", "needs_human",
    "not_sent_recovered", "offline_not_sent", "transport_completed_unverified",
])
def test_all_statuses_have_no_authority(status):
    response = assess_delivery_case(snapshot(status))
    for key in ("automatic_retry_permitted", "new_attempt_permitted",
                "live_send_permitted", "finalization_permitted"):
        assert response[key] is False
    assert response["requires_authenticated_operator"] is True


@pytest.mark.parametrize("override", [
    {"automatic_retry_permitted": True},
    {"finalization_permitted": True},
    {"status": "delivery_confirmed"},
    {"status": None},
    {"attempt_id": ""},
    {"attempt_id": "a" * 129},
    {"pending_or_uncertain_messages": -1},
    {"pending_or_uncertain_messages": True},
    {"pending_or_uncertain_messages": "1"},
    {"terminal_seen_unverified": 1},
    {"automatic_retry_permitted": None},
    {"finalization_permitted": None},
])
def test_forged_flags_and_partial_snapshot_rejected(override):
    with pytest.raises(ValueError):
        assess_delivery_case(snapshot(**override))


def test_operator_assertions_not_retained():
    out = assess_delivery_case(snapshot(operator_ref="forged", token="sentinel"))
    assert "forged" not in str(out)
    assert "sentinel" not in str(out)


def test_invalid_partial_snapshot_rejected():
    with pytest.raises(ValueError):
        assess_delivery_case({"status": "non_delivery_confirmed"})
