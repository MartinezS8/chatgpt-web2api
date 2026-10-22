"""Fail-closed read-only classification of durable app-server attempts.

Not operator authentication, delivery proof, release, retry, or finalization.
"""
from __future__ import annotations

from typing import Any

_KNOWN = frozenset({
    "prepared", "running_offline_fake", "unknown_delivery", "needs_human",
    "not_sent_recovered", "offline_not_sent", "transport_completed_unverified",
})
_GUIDANCE = {
    "prepared": ("in_flight_or_recovery_required", "Stop the process, then perform offline recovery."),
    "running_offline_fake": ("in_flight_or_recovery_required", "Stop the process, then perform offline recovery."),
    "unknown_delivery": ("delivery_ambiguous_quarantined", "Verify delivery independently; preserve quarantine."),
    "needs_human": ("manual_review_required", "Inspect external evidence; preserve quarantine."),
    "not_sent_recovered": ("local_no_send_recorded", "A new attempt requires separate policy and approval."),
    "offline_not_sent": ("local_no_send_recorded", "A new attempt requires separate policy and approval."),
    "transport_completed_unverified": ("transport_terminal_not_work_evidence", "Verify result and reviewer independently."),
}


def assess_delivery_case(record: dict[str, Any]) -> dict[str, Any]:
    """Produce review instructions from the canonical ledger's reconcile snapshot.

    The returned fields can NEVER authorize transport, retry, evidence or approval.
    This helper does not trust operator-supplied identity strings or provider claims.
    """
    if type(record) is not dict:
        raise ValueError("canonical delivery status required")
    attempt = record.get("attempt_id")
    status = record.get("status")
    count = record.get("pending_or_uncertain_messages")
    terminal = record.get("terminal_seen_unverified")
    if (not isinstance(attempt, str) or not attempt or len(attempt) > 128
            or status not in _KNOWN or type(count) is not int or count < 0
            or type(terminal) is not bool
            or record.get("automatic_retry_permitted") is not False
            or record.get("finalization_permitted") is not False):
        raise ValueError("invalid or non-fail-closed delivery snapshot")
    classification, instruction = _GUIDANCE[status]
    return {
        "attempt_id": attempt,
        "classification": classification,
        "instruction": instruction,
        "requires_authenticated_operator": True,
        "requires_independent_delivery_evidence": True,
        "automatic_retry_permitted": False,
        "new_attempt_permitted": False,
        "live_send_permitted": False,
        "finalization_permitted": False,
    }
