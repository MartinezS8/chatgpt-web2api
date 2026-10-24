"""Startup probes never gain account, thread or turn authority."""
from __future__ import annotations

import io
import subprocess
from types import SimpleNamespace

import pytest

from chatgpt_web2api.orchestrator import codex_start_probe as probe


@pytest.fixture
def harness(tmp_path, monkeypatch):
    calls = []
    process = SimpleNamespace(
        stdin=io.BytesIO(), stdout=io.BytesIO(), returncode=0,
        wait=lambda **kw: 0, poll=lambda: 0,
    )
    monkeypatch.setattr(probe, "local_pilot_doctor", lambda *a: {"account_discovery_performed": False})
    monkeypatch.setattr(probe, "verify_mcp_disabled", lambda *a: SimpleNamespace(args=()))
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **kw: process)

    class Session:
        def __init__(self, *a, **kw):
            pass

        def request(self, identity, method, params):
            calls.append(method)
            return {
                "initialize": {"userAgent": "fixture"},
                "app/installed": {"apps": []},
                "mcpServerStatus/list": {"data": [], "nextCursor": None},
            }[method]

        def notification(self, method, params):
            calls.append(method)

    monkeypatch.setattr(probe, "_DiscoverySession", Session)
    return tmp_path, calls, process


def test_handshake_only_does_not_claim_sandbox_execution(harness):
    path, calls, process = harness
    result = probe.probe_local_start(path / "codex.exe", path, path, path / "map")
    assert calls == ["initialize", "initialized", "app/installed", "mcpServerStatus/list"]
    assert result["process_stopped"] is True and process.stdin.closed
    assert result["sandbox_backend_execution_verified"] is False
    assert result["sandbox_command_tested"] is False
    assert result["thread_started"] is False and result["turn_started"] is False


def test_fixed_mxc_probe_checks_actual_cwd_and_redacts_stderr(harness, monkeypatch):
    path, calls, process = harness

    def run(argv, **kw):
        assert argv[-1] == "[Console]::Write((Get-Location).Path)"
        assert 'windows.sandbox="mxc"' in argv
        assert 'sandbox_mode="read-only"' in argv
        assert "-P" in argv
        profile = argv[argv.index("-P") + 1]
        assert f'permissions.{profile}.extends=":read-only"' in argv
        assert f"permissions.{profile}.network.enabled=false" in argv
        assert kw["timeout"] == 45 and kw["cwd"] == path
        return subprocess.CompletedProcess(argv, 1, "", "PRIVATE_DETAILS Windows error 267")

    monkeypatch.setattr(probe.subprocess, "run", run)
    result = probe.probe_local_start(
        path / "codex.exe", path, path, path / "map", probe_mxc_command=True,
    )
    assert result["windows_error_codes"] == [267]
    assert result["sandbox_cwd_matches"] is False
    assert "PRIVATE_DETAILS" not in str(result)


def test_different_cwd_with_success_exit_still_fails(harness, monkeypatch):
    path, calls, process = harness
    monkeypatch.setattr(probe.subprocess, "run", lambda argv, **kw:
                        subprocess.CompletedProcess(argv, 0, str(path.parent), ""))
    result = probe.probe_local_start(
        path / "codex.exe", path, path, path / "map", probe_mxc_command=True,
    )
    assert result["sandbox_command_exit_code"] == 0
    assert result["sandbox_cwd_matches"] is False
    assert result["sandbox_backend_execution_verified"] is False


def test_legacy_command_probe_is_rejected_before_any_process(monkeypatch):
    monkeypatch.setattr(probe, "local_pilot_doctor", lambda *a: pytest.fail("process started"))
    with pytest.raises(PermissionError, match="legacy sandbox"):
        probe.probe_local_start("", "", "", "", sandbox_backend="elevated", probe_mxc_command=True)


def test_active_apps_stop_before_mcp_status_and_close_process(harness, monkeypatch):
    path, calls, process = harness
    monkeypatch.setattr(
        probe, "check_installed_apps",
        lambda *a: (_ for _ in ()).throw(PermissionError("active app")),
    )
    with pytest.raises(PermissionError, match="active app"):
        probe.probe_local_start(path / "codex.exe", path, path, path / "map")
    assert "mcpServerStatus/list" not in calls and process.stdin.closed
