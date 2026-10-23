"""Synthetic process fixtures prove the discovery command has no turns."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

import chatgpt_web2api.orchestrator.local_codex_discovery as discovery
import chatgpt_web2api.orchestrator.mcp_process_guard as mcp_process_guard


class _CaptureStdin(io.BytesIO):
    def close(self):
        # Preserve only the synthetic bytes for request allowlist assertions.
        pass


class _FakeProcess:
    def __init__(self, lines):
        self.stdin = _CaptureStdin()
        self.stdout = io.BytesIO(b"".join(
            (json.dumps(line, separators=(",", ":")) + "\n").encode("utf-8")
            if not isinstance(line, bytes) else line
            for line in lines
        ))
        self.closed = False

    def wait(self, *, timeout):
        return 0

    def terminate(self):
        self.closed = True

    def kill(self):
        self.closed = True


@pytest.fixture
def discovery_files(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("native Windows executable pin is required")
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"synthetic never executed exe")
    root = tmp_path / "schemas"
    root.mkdir()
    target = root / "synthetic.json"
    target.write_text('{"type":"object"}', encoding="utf-8")
    receipt = {
        "codex_version": "codex-cli 0.test",
        "codex_binary_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "installed_schema_inspected": True,
        "generated_json_schema": [{
            "path": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }],
    }
    (root / "offline-readiness.json").write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(
        discovery.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="codex-cli 0.test\n"),
    )
    (tmp_path / "mcp-sources.json").write_text(
        '{"schema_version":1,"servers":[]}', encoding="utf-8",
    )
    monkeypatch.setattr(
        mcp_process_guard, "verify_mcp_disabled",
        lambda *a, **kw: SimpleNamespace(
            args=("-c", 'mcp_servers."fixture".enabled=false',
                  "-c", "features.apps=false"),
        ),
    )
    return exe, root, tmp_path


def _lines(**overrides):
    base = [
        {"id": 1, "result": {"userAgent": "Codex test", "platformOs": "windows"}},
        {"method": "account/updated", "params": {"email": "never-log@example.com"}},
        {"id": 2, "result": {"apps": []}},
        {"id": 3, "result": {"data": [], "nextCursor": None}},
        {"id": 4, "result": {
            "account": {"type": "chatgpt", "email": "secret@example.com",
                        "accessToken": "never-return-me"},
            "requiresOpenaiAuth": True,
        }},
        {"id": 5, "result": {
            "data": [{
                "id": "actual-model-from-server", "displayName": "Local Model",
                "defaultReasoningEffort": "medium",
                "supportedReasoningEfforts": [{"reasoningEffort": "medium"}],
                "isDefault": True,
            }], "nextCursor": None,
        }},
    ]
    for index, item in overrides.items():
        base[int(index)] = item
    return base


def _discover(exe, root, cwd, **kwargs):
    return discovery.discover_local_codex(
        exe, root, cwd, mcp_source_map=cwd / "mcp-sources.json", **kwargs,
    )


def test_session_accepts_bounded_large_server_frames():
    payload = "x" * 70_000
    process = _FakeProcess([{"id": 1, "result": {"payload": payload}}])
    session = discovery._DiscoverySession(process, timeout=1)

    assert session.request(1, "initialize", {})["payload"] == payload


def test_session_rejects_server_frames_above_response_bound():
    oversized = (
        b'{"id":1,"result":{"payload":"'
        + b"x" * (4 * 1024 * 1024)
        + b'"}}\n'
    )
    process = _FakeProcess([oversized])
    session = discovery._DiscoverySession(process, timeout=1)

    with pytest.raises(RuntimeError, match="app-server frame exceeded limit"):
        session.request(1, "initialize", {})


def test_session_keeps_outbound_request_limit():
    process = _FakeProcess([])
    session = discovery._DiscoverySession(process, timeout=1)

    with pytest.raises(ValueError, match="discovery request too large"):
        session.request(1, "initialize", {"padding": "x" * 65_536})


def test_explicit_opt_in_required_before_launch(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: pytest.fail("spawned"))
    with pytest.raises(PermissionError, match="explicit"):
        discovery.discover_local_codex(exe, root, cwd)


def test_account_discovery_requires_mcp_source_map_before_launch(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: pytest.fail("spawned"))
    with pytest.raises(PermissionError, match="MCP source map"):
        discovery.discover_local_codex(
            exe, root, cwd, allow_account_discovery=True,
        )


def test_read_only_handshake_and_no_leak_or_turn(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    p = _FakeProcess(_lines())
    launch = {}

    def fake_popen(args, **kwargs):
        launch["args"] = args
        return p
    monkeypatch.setattr(discovery.subprocess, "Popen", fake_popen)
    report = _discover(exe, root, cwd, allow_account_discovery=True)
    messages = [json.loads(line) for line in p.stdin.getvalue().splitlines()]
    assert [msg["method"] for msg in messages] == [
        "initialize", "initialized", "app/installed", "mcpServerStatus/list",
        "account/read", "model/list",
    ]
    assert launch["args"] == [
        str(exe), "-c", 'mcp_servers."fixture".enabled=false',
        "-c", "features.apps=false", "app-server",
    ]
    assert messages[4]["params"] == {"refreshToken": False}
    assert report["mcp_status_checked"] is True
    assert report["mcp_callables_found"] is False
    assert report["installed_apps_checked"] is True
    assert report["model_count"] == 1
    assert report["models"][0]["id"] == "actual-model-from-server"
    assert report["turn_started"] is False
    assert "secret@example.com" not in str(report)
    assert "never-return-me" not in str(report)


def test_active_mcp_state_blocks_account_read(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    frames = _lines(**{
        "2": {"id": 2, "result": {"apps": []}},
        "3": {"id": 3, "result": {
            "data": [{
                "name": "synthetic", "authStatus": "unsupported",
                "resourceTemplates": [], "resources": [],
                "tools": {"synthetic": {"name": "synthetic"}},
            }], "nextCursor": None,
        }},
    })
    process = _FakeProcess(frames)
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(PermissionError, match="MCP status"):
        _discover(exe, root, cwd, allow_account_discovery=True)
    sent = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert [message["method"] for message in sent] == [
        "initialize", "initialized", "app/installed", "mcpServerStatus/list",
    ]


def test_callable_app_state_blocks_account_read(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    frames = _lines(**{"2": {"id": 2, "result": {
        "apps": [{"id": "synthetic", "enabled": False, "callable": True}],
    }}})
    process = _FakeProcess(frames)
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(PermissionError, match="app is enabled or callable"):
        _discover(exe, root, cwd, allow_account_discovery=True)
    sent = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert [message["method"] for message in sent] == [
        "initialize", "initialized", "app/installed",
    ]


def test_rejected_mcp_policy_prevents_app_server_spawn(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    def reject_policy(*args, **kwargs):
        raise PermissionError("synthetic unclassified MCP source")
    monkeypatch.setattr(mcp_process_guard, "verify_mcp_disabled", reject_policy)
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: pytest.fail("spawned"))
    with pytest.raises(PermissionError, match="unclassified MCP source"):
        _discover(exe, root, cwd, allow_account_discovery=True)


def test_unpinned_codex_binary_fails_without_launch(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    exe.write_bytes(b"modified")
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="binary changed"):
        _discover(exe, root, cwd, allow_account_discovery=True)


def test_server_requests_never_receive_auto_approval(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    p = _FakeProcess(_lines(**{"1": {"id": 400, "method": "command/exec",
                                     "params": {"command": "unsafe"}}}))
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: p)
    with pytest.raises(RuntimeError, match="correlation"):
        _discover(exe, root, cwd, allow_account_discovery=True)
    sent = [json.loads(line) for line in p.stdin.getvalue().splitlines()]
    assert [m["method"] for m in sent] == [
        "initialize", "initialized", "app/installed",
    ]


def test_bad_model_list_cursor_not_silently_accepted(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    records = _lines(**{"5": {"id": 5, "result": {"data": [], "nextCursor": ""}}})
    p = _FakeProcess(records)
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: p)
    with pytest.raises(RuntimeError, match="cursor"):
        _discover(exe, root, cwd, allow_account_discovery=True)


def test_unexpected_or_malformed_frame_is_not_ignored(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    p = _FakeProcess([b'{"id":1,"id":1,"result":{}}\n'])
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: p)
    with pytest.raises(RuntimeError, match="malformed"):
        _discover(exe, root, cwd, allow_account_discovery=True)


def test_model_catalog_retains_slug_and_text_modality():
    from chatgpt_web2api.orchestrator.local_codex_discovery import _model_summary

    item = {"id": "picker-id", "model": "actual-model-slug",
            "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
            "defaultReasoningEffort": "high", "hidden": False,
            "inputModalities": ["text", "image"]}
    summary = _model_summary(item)
    assert summary["model_slug"] == "actual-model-slug"
    assert summary["supports_text"] is True
    assert summary["model_slug_declared"] is True


def test_model_catalog_rejects_invalid_modalities():
    from chatgpt_web2api.orchestrator.local_codex_discovery import _model_summary

    with pytest.raises(ValueError, match="input modalities"):
        _model_summary({"id": "other",
                        "supportedReasoningEfforts": [{"reasoningEffort": "medium"}],
                        "inputModalities": ["telepathy"]})
