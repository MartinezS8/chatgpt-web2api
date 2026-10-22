"""Offline preview of the exact first-turn request payloads, NO Codex process."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .local_pilot_messages import thread_start_params, turn_start_params
from .local_wire_schema import LocalWireSchemas
from .storage_hardening import reject_reparse_path


def preview_local_one_turn(
    schema_root: str | Path, cwd: str | Path, prompt_file: str | Path, *,
    model: str, effort: str, selections: dict[str, str],
    simulated_thread_id: str = "thr_local_schema_placeholder",
) -> dict:
    """Validate outgoing requests only, without fabricating server responses."""
    if (any(type(s) is not str or not s or len(s) > 256
            for s in (model, effort, simulated_thread_id))):
        raise ValueError("explicit model, effort, and dummy thread ID are required")
    working = Path(cwd).expanduser()
    if not working.is_absolute() or not working.is_dir():
        raise ValueError("existing absolute scratch cwd required")
    reject_reparse_path(working, error_message="scratch cwd traverses reparse point")
    prompt_path = Path(prompt_file).expanduser()
    reject_reparse_path(prompt_path, error_message="test prompt traverses reparse point")
    if not prompt_path.is_file() or prompt_path.stat().st_size > 4096:
        raise ValueError("test prompt must be an existing file no larger than 4 KiB")
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not 1 <= len(prompt) <= 2000:
        raise ValueError("test prompt length must be 1..2000")
    check = LocalWireSchemas(schema_root, selections=selections)
    thread = thread_start_params(model=model, cwd=str(working))
    turn = turn_start_params(
        thread_id=simulated_thread_id, prompt=prompt, model=model,
        effort=effort, cwd=str(working),
    )
    check.require("thread_params", thread)
    check.require("turn_params", turn)
    return {
        "codex_version": check.codex_version,
        "schema_mapping": check.selections,
        "thread_params_schema_pass": True,
        "turn_params_schema_pass": True,
        "thread_result_schema_checked": False,
        "turn_result_schema_checked": False,
        "result_schemas_loaded": True,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "account_read_performed": False,
        "app_server_process_started": False,
        "real_turn_started": False,
        "live_compatibility_proven": False,
    }
