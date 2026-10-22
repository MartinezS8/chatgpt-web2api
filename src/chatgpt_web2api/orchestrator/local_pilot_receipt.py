"""Read-only first-turn receipt diagnostics for a local hobby pilot.

Only uses existing local JSON receipts; no Codex process, authentication,
network, SQLite writes or GitHub mutations. Treats files as diagnostic
claims, never independent evidence of actual provider execution.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .local_codex_discovery import _pairs_no_duplicates
from .storage_hardening import reject_reparse_path


def _read_receipt(path: Path) -> dict | None:
    if not path.exists():
        return None
    reject_reparse_path(path, error_message="receipt traverses reparse point")
    if (path.is_symlink() or not path.is_file()
            or not 2 <= path.stat().st_size <= 16 * 1024):
        raise ValueError("pilot receipt is not a bounded regular file")
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream, object_pairs_hook=_pairs_no_duplicates)
    except (ValueError, UnicodeError):
        raise ValueError("malformed pilot receipt JSON") from None
    if type(data) is not dict:
        raise ValueError("pilot receipt must be a JSON object")
    return data


def inspect_local_pilot_receipt(folder_value: str | Path) -> dict:
    """Classify local receipt without granting replay or completion authority."""
    folder = Path(folder_value).expanduser()
    if not folder.is_absolute() or not folder.is_dir() or folder.is_symlink():
        raise ValueError("explicit existing absolute receipt directory required")
    reject_reparse_path(folder, error_message="pilot receipt directory traverses reparse path")
    intent = _read_receipt(folder / "intent.json")
    result = _read_receipt(folder / "result.json")
    quarantine = _read_receipt(folder / "quarantine.json")

    status = "INCONSISTENT_RECEIPT"
    turn_attempted = None
    # This is a locally consistent hash link, not a signature/third-party
    # delivery proof; legacy receipts may lack the field.
    observed = result if result is not None else quarantine
    observed_hash = observed.get("intent_sha256") if observed is not None else None
    binding_verified = False
    if observed_hash is not None and intent is not None:
        actual_hash = hashlib.sha256((folder / "intent.json").read_bytes()).hexdigest()
        binding_verified = (
            type(observed_hash) is str and observed_hash == actual_hash
        )
    if intent is None:
        detail = "intent file is missing or write was interrupted"
    elif (intent.get("max_turn_starts") != 1
          or intent.get("retry_permitted") is not False
          or type(intent.get("prompt_sha256")) is not str
          or len(intent["prompt_sha256"]) != 64
          or any(c not in "0123456789abcdef" for c in intent["prompt_sha256"])):
        detail = "intent binding is malformed"
    elif result is not None and quarantine is not None:
        detail = "both result and quarantine exist"
    elif observed_hash is not None and not binding_verified:
        detail = "result/quarantine intent hash binding does not match"
    elif result is not None:
        terminal = result.get("turn_terminal_status")
        good = (
            result.get("status") == "transport_completed_unreviewed"
            and terminal == "completed"
        ) or (
            result.get("status") == "turn_ended_needs_review"
            and terminal in ("failed", "interrupted")
        )
        if (good and result.get("live_turn_started") is True
                and result.get("retry_permitted") is False
                and result.get("production_finalization_permitted") is False
                and isinstance(result.get("thread_id"), str)
                and bool(result["thread_id"])
                and isinstance(result.get("turn_id"), str)
                and bool(result["turn_id"])):
            status = ("TERMINAL_UNREVIEWED" if terminal == "completed"
                      else "TERMINAL_FAILED_OR_INTERRUPTED")
            turn_attempted = True
            detail = "terminal transport receipt; model output not independently verified"
        else:
            detail = "terminal result has conflicting or incomplete fields"
    elif quarantine is not None:
        marker = quarantine.get("turn_start_may_have_been_sent")
        declared = quarantine.get("status")
        if quarantine.get("retry_permitted") is not False:
            detail = "quarantine unexpectedly permits retry"
        elif marker is True and declared == "needs_human_unknown_or_unverified_delivery":
            status = "UNKNOWN_DELIVERY"
            turn_attempted = True
            detail = "turn/start may have reached provider; do not replay"
        elif marker is False and declared == "pre_turn_failure_no_turn_start_attempted":
            status = "PRE_TURN_FAILURE"
            turn_attempted = False
            detail = "local diagnostic reported failure before attempted turn/start"
        else:
            # Older PR #63 receipts lack a send-attempt field. No optimistic
            # inference about non-delivery is possible from their absence.
            status = "LEGACY_OR_UNCLASSIFIED_QUARANTINE"
            detail = "quarantine does not attest whether a turn was attempted"
    else:
        status = "INCOMPLETE_OR_INTERRUPTED"
        detail = "intent exists without a terminal/quarantine receipt"

    return {
        "classification": status,
        "diagnostic_detail": detail,
        "has_intent": intent is not None,
        "has_result": result is not None,
        "has_quarantine": quarantine is not None,
        "turn_start_may_have_been_sent": turn_attempted,
        "automatic_retry_permitted": False,
        "same_receipt_directory_reusable": False,
        "production_finalization_permitted": False,
        "provider_output_independently_verified": False,
        "receipt_intent_binding_verified": binding_verified,
        "read_only_inspection": True,
    }
