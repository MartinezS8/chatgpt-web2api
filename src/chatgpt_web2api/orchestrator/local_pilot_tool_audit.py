"""Versioned, conservative labels for observed local App Server events.

The audit sees protocol events only. It cannot prevent a tool invocation or
prove that an untrusted process emitted every event.
"""
from __future__ import annotations

import hashlib

AUDIT_VERSION = 2
AUDIT_SCOPE = "observed_app_server_events_only"
TURN_START_REQUEST_ID = 3
EXPECTED_OUTPUT = "ORCH_TEST_OK"
EXPECTED_OUTPUT_SHA256 = hashlib.sha256(EXPECTED_OUTPUT.encode("utf-8")).hexdigest()
SAFE_ITEM_TYPES = frozenset({"userMessage", "agentMessage", "reasoning", "plan"})
ACTION_ITEM_TYPES = frozenset({
    "hookPrompt", "functionCallOutput", "commandExecution", "fileChange",
    "mcpToolCall", "dynamicToolCall", "collabAgentToolCall", "subAgentActivity",
    "webSearch", "imageView", "imageGeneration", "sleep", "enteredReviewMode",
    "exitedReviewMode", "contextCompaction",
})
SAFE_NOTIFICATIONS = frozenset({
    "thread/started", "thread/status/changed", "thread/tokenUsage/updated",
    "turn/started", "turn/plan/updated", "item/agentMessage/delta", "item/plan/delta",
    "item/reasoning/summaryTextDelta", "item/reasoning/summaryPartAdded",
    "item/reasoning/textDelta", "model/safetyBuffering/updated",
})
ACTION_NOTIFICATIONS = {
    "item/commandExecution/outputDelta": "commandExecution",
    "item/fileChange/outputDelta": "fileChange",
    "turn/diff/updated": "fileChange",
    "hook/started": "hook",
    "hook/completed": "hook",
    "serverRequest/resolved": "server_request",
}
NOTIFICATION_CATEGORIES = frozenset(ACTION_NOTIFICATIONS.values()) | frozenset({
    "unknown", "malformed_item", "late_item", "late_notification",
    "item_lifecycle", "item_snapshot", "uncorrelated_notification",
    "ambiguous_final_answer", "server_request",
})


def _valid_counts(value: object, allowed: frozenset[str]) -> bool:
    return (
        type(value) is dict
        and set(value).issubset(allowed)
        and all(type(count) is int and 0 < count <= 1_000_000 for count in value.values())
    )


def result_audit_is_consistent(result: dict) -> bool:
    """Reject malformed or contradictory labels, not receipt tampering itself."""
    items = result.get("observed_item_type_counts")
    notifications = result.get("unexpected_notification_counts")
    unexpected = result.get("unexpected_tool_activity_observed")
    terminal = result.get("turn_terminal_status")
    status_valid = (
        terminal == "completed" and result.get("status") == "transport_completed_unreviewed"
    ) or (
        terminal in ("failed", "interrupted") and result.get("status") == "turn_ended_needs_review"
    )
    if (not status_valid
            or result.get("live_turn_started") is not True
            or result.get("retry_permitted") is not False
            or result.get("production_finalization_permitted") is not False
            or type(result.get("tool_event_audit_version")) is not int
            or result["tool_event_audit_version"] != AUDIT_VERSION
            or result.get("tool_event_audit_complete") is not True
            or result.get("tool_event_audit_scope") != AUDIT_SCOPE
            or type(result.get("item_lifecycle_consistent")) is not bool
            or type(result.get("turn_start_request_id")) is not int
            or result["turn_start_request_id"] != TURN_START_REQUEST_ID
            or result.get("expected_output") != EXPECTED_OUTPUT
            or type(result.get("assistant_message_observed")) is not bool
            or type(result.get("assistant_output_matches_expected")) is not bool
            or type(unexpected) is not bool
            or type(result.get("clean_tool_free_pilot")) is not bool
            or not _valid_counts(items, SAFE_ITEM_TYPES | ACTION_ITEM_TYPES | {"unknown"})
            or not _valid_counts(notifications, NOTIFICATION_CATEGORIES)):
        return False
    if result["assistant_output_matches_expected"] and (
        result["assistant_message_observed"] is not True
        or result.get("assistant_output_preview") != EXPECTED_OUTPUT
        or result.get("assistant_output_sha256") != EXPECTED_OUTPUT_SHA256
    ):
        return False
    if not result["assistant_output_matches_expected"] and (
        result.get("assistant_output_preview") is not None
        or result.get("assistant_output_sha256") is not None
    ):
        return False
    if result["assistant_message_observed"] and not items.get("agentMessage"):
        return False
    lifecycle_bad = any(
        key in notifications
        for key in ("item_lifecycle", "item_snapshot", "uncorrelated_notification")
    )
    if result["item_lifecycle_consistent"] is lifecycle_bad:
        return False
    found = bool(notifications) or any(name not in SAFE_ITEM_TYPES for name in items)
    clean = (
        result.get("turn_terminal_status") == "completed"
        and result.get("assistant_message_observed") is True
        and result.get("assistant_output_matches_expected") is True
        and not unexpected
        and result["item_lifecycle_consistent"] is True
    )
    return unexpected is found and result["clean_tool_free_pilot"] is clean
