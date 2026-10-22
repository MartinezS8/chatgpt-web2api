"""Read-only operator triage for offline App Server attempts.

This module intentionally has NO authority to resolve quarantine, send turns,
infer authenticated operator identity, attach evidence or finalize a task.
"""
from __future__ import annotations

from .observer import Observer

_DECISIONS = frozenset({
    "delivery_unresolved",
    "delivery_confirmed",
    "non_delivery_confirmed",
})


class OperatorReviewBoard:
    """A read-only Windows CLI review surface; never an authorization primitive."""

    def __init__(self, observer: Observer):
        if type(observer) is not Observer:
            raise TypeError("operator review requires the canonical read-only observer")
        self._observer = observer

    def queue(self, *, limit: int = 20) -> dict:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("review queue limit must be between 1 and 50")
        tables = self._observer._read(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='orchestrator_app_server_attempts' LIMIT ?", limit=1
        )
        if not tables:
            return {"items": [], "operator_authenticated": False,
                    "resolution_permitted": False, "live_send_permitted": False}
        items = self._observer._read(
            """SELECT a.attempt_id, a.task_id, a.worker_id, a.status,
                      a.terminal_seen, a.updated_at, t.state AS task_state,
                      d.status AS outbox_status
               FROM orchestrator_app_server_attempts a
               JOIN tasks t ON t.task_id=a.task_id
               JOIN orchestrator_dispatch_attempts d ON d.attempt_id=a.attempt_id
               WHERE a.status IN ('unknown_delivery','needs_human',
                                  'not_sent_recovered','offline_not_sent',
                                  'transport_completed_unverified')
               ORDER BY a.updated_at DESC, a.attempt_id LIMIT ?""",
            limit=limit,
        )
        return {"items": items, "operator_authenticated": False,
                "resolution_permitted": False, "live_send_permitted": False}

    def preview(self, attempt_id: str, *, disposition: str) -> dict:
        if disposition not in _DECISIONS:
            raise ValueError("unsupported operator review disposition")
        current = self._observer.app_server_delivery(attempt_id)
        attempt = current["delivery"]
        if attempt is None:
            raise ValueError("app-server attempt not found")
        messages = current["messages"]
        unconfirmed = sum(
            1 for row in messages if row["status"] in {"intent", "written", "unknown"}
        )
        if disposition == "delivery_unresolved":
            status = "retain_quarantine"
        elif disposition == "delivery_confirmed":
            status = "requires_independent_delivery_evidence_and_authenticated_operator"
        else:
            status = "requires_independent_non_delivery_proof_and_new_attempt_policy"
        return {
            "attempt_id": attempt["attempt_id"],
            "task_id": attempt["task_id"],
            "current_status": attempt["status"],
            "requested_disposition": disposition,
            "pending_or_uncertain_messages": unconfirmed,
            "terminal_seen_unverified": bool(attempt["terminal_seen"]),
            "existing_annotation": current["operator_disposition"] is not None,
            "review_outcome": status,
            "operator_authenticated": False,
            "evidence_verified": False,
            "resolution_permitted": False,
            "new_attempt_permitted": False,
            "live_send_permitted": False,
            "finalization_permitted": False,
        }
