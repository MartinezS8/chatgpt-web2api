"""One-command, non-inferencing Codex preflight for an eventual hobby pilot.

Validates the installed CLI binary, generated-schema manifest and (optionally)
the account's actual model/effort catalog. Never sends a thread/turn or task.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .local_codex_discovery import discover_local_codex
from .schema_fixture_audit import _digest, verified_bundle
from .storage_hardening import reject_reparse_path


def local_pilot_doctor(
    executable: str | Path, schema_root: str | Path, cwd: str | Path, *,
    allow_account_discovery: bool = False,
    mcp_source_map: str | Path | None = None,
    model: str | None = None, effort: str | None = None,
) -> dict:
    """Return a minimal machine-readable receipt; never a send permission."""
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise OSError("local pilot doctor requires Windows 11 and Python 3.12")
    if (model is None) != (effort is None):
        raise ValueError("model and effort must be selected together")
    if any(type(value) is not str or not value.strip() or len(value) > 256
           for value in (model, effort) if value is not None):
        raise ValueError("invalid model or reasoning effort")
    exe, work = Path(executable).expanduser(), Path(cwd).expanduser()
    if (not exe.is_absolute() or exe.suffix.lower() != ".exe"
            or not exe.is_file() or not work.is_absolute() or not work.is_dir()):
        raise ValueError("absolute native exe and existing absolute cwd required")
    reject_reparse_path(exe, error_message="Codex executable traverses reparse point")
    reject_reparse_path(work, error_message="Codex workspace traverses reparse point")
    receipt, schemas = verified_bundle(schema_root)
    binary_sha = _digest(exe)
    if binary_sha != receipt["codex_binary_sha256"]:
        raise ValueError("Codex binary differs from captured schemas")
    version = subprocess.run(
        [str(exe), "--version"], capture_output=True, text=True, check=True, timeout=20,
    ).stdout.strip()
    if version != receipt["codex_version"]:
        raise ValueError("Codex version differs from captured schemas")
    report = {
        "codex_version": version,
        "binary_sha256": binary_sha,
        "schema_file_count": len(schemas),
        "schema_pinned": True,
        "account_discovery_performed": False,
        "account_present": None,
        "account_mode": None,
        "model_verified": False,
        "selected_model": model,
        "selected_effort": effort,
        "first_live_turn_authorized": False,
        "first_live_turn_started": False,
        "review_required_before_live_turn": True,
    }
    if not allow_account_discovery:
        report["next_action"] = "Run again with --allow-account-discovery after user consent"
        return report
    if mcp_source_map is None:
        raise PermissionError("explicit local MCP source map required before account discovery")
    discovery = discover_local_codex(
        exe, schema_root, work, allow_account_discovery=True,
        mcp_source_map=mcp_source_map,
    )
    report["account_discovery_performed"] = True
    account_present = discovery.get("account_present")
    if type(account_present) is not bool:
        raise RuntimeError("Codex discovery returned invalid account presence")
    report["account_present"] = account_present
    account_mode = discovery.get("account_mode")
    if (type(account_mode) is not str
            or account_mode not in {"chatgpt", "api_key", "other", "none"}):
        raise RuntimeError("Codex discovery returned an invalid account mode")
    if ((account_present and account_mode == "none")
            or (not account_present and account_mode != "none")):
        raise RuntimeError("Codex discovery account presence and mode disagree")
    report["account_mode"] = account_mode
    report["available_models"] = discovery["models"]
    if model is None:
        report["next_action"] = "Select --model and --effort from available_models"
        return report
    choices = [
        value for value in discovery["models"]
        if value["id"] == model and effort in value["supported_efforts"]
    ]
    if len(choices) != 1:
        raise ValueError("selected model/effort not present in account catalog")
    report["model_verified"] = True
    report["next_action"] = (
        "Manual sign-off and a separate, bounded one-turn implementation are required"
    )
    return report
