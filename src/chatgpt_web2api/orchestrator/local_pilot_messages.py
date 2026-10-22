"""Canonical small read-only first-turn request builders shared by pilot/preflight.

These functions are pure: no process, account access or dispatch. They must
always be kept byte-shape identical for schema validation and live sending.
"""
from __future__ import annotations


def thread_start_params(*, model: str, cwd: str) -> dict:
    return {
        "model": model, "cwd": cwd,
        "approvalPolicy": "never", "sandbox": "read-only",
        "serviceName": "w2a_local_one_turn",
    }


def turn_start_params(
    *, thread_id: str, prompt: str, model: str, effort: str, cwd: str,
) -> dict:
    return {
        "threadId": thread_id,
        "input": [{"type": "text", "text": prompt}],
        "model": model, "effort": effort, "cwd": cwd,
        "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly"},
    }
