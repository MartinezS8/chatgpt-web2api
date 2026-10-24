"""Explicit local startup diagnostics, with no thread, turn or account request.

An app-server handshake does not execute a sandboxed child. The optional MXC
probe runs only a fixed PowerShell CWD read through ``codex sandbox``. Legacy
sandbox setup is deliberately excluded because it may provision OS accounts.
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path

from .local_codex_discovery import _DiscoverySession
from .local_pilot_doctor import local_pilot_doctor
from .mcp_process_guard import verify_mcp_disabled
from .mcp_runtime_fence import check_installed_apps, require_external_tools_disabled


def _stop(process) -> int:
    try:
        if process.stdin is not None:
            process.stdin.close()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    finally:
        if process.stdout is not None:
            process.stdout.close()
    return process.returncode


def probe_local_start(
    executable: str | Path, schema_root: str | Path, cwd: str | Path,
    source_map: str | Path, *, sandbox_backend: str = "mxc",
    probe_mxc_command: bool = False,
) -> dict:
    if sandbox_backend not in {"mxc", "elevated"}:
        raise ValueError("explicit supported sandbox backend required")
    if probe_mxc_command and sandbox_backend != "mxc":
        raise PermissionError("legacy sandbox setup is outside this diagnostic")
    report = local_pilot_doctor(executable, schema_root, cwd)
    exe, work = Path(executable), Path(cwd)
    policy = verify_mcp_disabled(exe, work, source_map)
    flags = (*policy.args, "-c", f'windows.sandbox="{sandbox_backend}"',
             "-c", "features.prefer_mxc=false", "-c", 'sandbox_mode="read-only"')
    process = subprocess.Popen(
        [str(exe), *flags, "app-server"], cwd=work,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
    )
    try:
        session = _DiscoverySession(process, timeout=30)
        hello = session.request(1, "initialize", {
            "clientInfo": {"name": "w2a_start_probe", "version": "0.1.0"},
        })
        if not isinstance(hello.get("userAgent"), str):
            raise RuntimeError("app-server initialization not recognized")
        session.notification("initialized", {})
        apps = session.request(2, "app/installed", {"forceRefresh": False})
        check_installed_apps(apps)
        status = session.request(3, "mcpServerStatus/list", {
            "limit": 100, "detail": "toolsAndAuthOnly",
        })
        report.update(require_external_tools_disabled(status, apps))
    finally:
        exit_code = _stop(process)
    report.update(
        app_server_initialized=True, app_server_exit_code=exit_code,
        process_stopped=process.poll() is not None,
        sandbox_backend_requested=sandbox_backend,
        sandbox_backend_execution_verified=False, sandbox_command_tested=False,
        provider_inference_performed=False, thread_started=False, turn_started=False,
    )
    if exit_code != 0:
        raise RuntimeError("app-server did not stop cleanly")
    if probe_mxc_command:
        # Absolute system PowerShell, fixed local read, no caller-supplied code.
        shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        # 0.164's sandbox command requires a named permission profile. A fresh
        # process-only name avoids inheriting an unrelated existing profile.
        profile = "w2a_probe_" + uuid.uuid4().hex
        command_flags = (*flags, "-c", f'permissions.{profile}.extends=":read-only"',
                         "-c", f"permissions.{profile}.network.enabled=false")
        try:
            result = subprocess.run(
                [str(exe), *command_flags, "sandbox", "-P", profile, "-C", str(work), "--", str(shell),
                 "-NoProfile", "-NonInteractive", "-Command", "[Console]::Write((Get-Location).Path)"],
                cwd=work, capture_output=True, text=True, timeout=45, check=False,
            )
        except subprocess.TimeoutExpired:
            # subprocess.run terminates and waits for its direct child; no retry.
            report.update(sandbox_command_tested=True, sandbox_command_timeout=True)
            return report
        errors = re.findall(r"Windows error (\d+)", result.stderr or "")
        matches = result.returncode == 0 and result.stdout.strip().casefold() == str(work).casefold()
        report.update(
            sandbox_command_tested=True, sandbox_command_exit_code=result.returncode,
            sandbox_cwd_matches=matches, sandbox_backend_execution_verified=matches,
            windows_error_codes=[int(code) for code in errors[:4]],
            sandbox_profile_process_scoped=True,
            sandbox_profile_extends=":read-only", sandbox_profile_network_enabled=False,
            sandbox_cli_usage_rejected="required arguments" in (result.stderr or ""),
        )
    return report
