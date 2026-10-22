"""Canonical small read-only first-turn request builders shared by pilot/preflight.

These functions are pure: no process, account access or dispatch. They must
always be kept byte-shape identical for schema validation and live sending.
"""
from __future__ import annotations

from pathlib import Path

from .storage_hardening import reject_reparse_path


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


def read_pilot_prompt(prompt_file: str | Path) -> str:
    """Exactly the same bounded file rules for offline preview and live pilot."""
    path = Path(prompt_file).expanduser()
    if not path.is_absolute():
        raise ValueError("pilot prompt must be an absolute local file")
    reject_reparse_path(path, error_message="pilot prompt traverses reparse path")
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("pilot prompt must be a regular file no larger than 4 KiB")
    prompt = path.read_text(encoding="utf-8").strip()
    if not 1 <= len(prompt) <= 2000:
        raise ValueError("pilot prompt length must be 1..2000 characters")
    return prompt
