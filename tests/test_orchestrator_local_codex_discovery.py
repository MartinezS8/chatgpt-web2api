"""Synthetic process fixtures prove the discovery command has no turns."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess

import pytest

import chatgpt_web2api.orchestrator.local_codex_discovery as discovery


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
    return exe, root, tmp_path


def _lines(**overrides):
    base = [
        {"id": 1, "result": {"userAgent": "Codex test", "platformOs": "windows"}},
        {"method": "account/updated", "params": {"email": "never-log@example.com"}},
        {"id": 2, "result": {
            "account": {"type": "chatgpt", "email": "secret@example.com",
                        "accessToken": "never-return-me"},
            "requiresOpenaiAuth": True,
        }},
        {"id": 3, "result": {
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


def test_explicit_opt_in_required_before_launch(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: pytest.fail("spawned"))
    with pytest.raises(PermissionError, match="explicit"):
        discovery.discover_local_codex(exe, root, cwd)


def test_read_only_handshake_and_no_leak_or_turn(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    p = _FakeProcess(_lines())
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: p)
    report = discovery.discover_local_codex(exe, root, cwd, allow_account_discovery=True)
    messages = [json.loads(line) for line in p.stdin.getvalue().splitlines()]
    assert [msg["method"] for msg in messages] == [
        "initialize", "initialized", "account/read", "model/list",
    ]
    assert messages[2]["params"] == {"refreshToken": False}
    assert report["model_count"] == 1
    assert report["models"][0]["id"] == "actual-model-from-server"
    assert report["turn_started"] is False
    assert "secret@example.com" not in str(report)
    assert "never-return-me" not in str(report)


def test_unpinned_codex_binary_fails_without_launch(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    exe.write_bytes(b"modified")
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="binary changed"):
        discovery.discover_local_codex(exe, root, cwd, allow_account_discovery=True)


def test_server_requests_never_receive_auto_approval(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    p = _FakeProcess(_lines(**{"1": {"id": 400, "method": "command/exec",
                                     "params": {"command": "unsafe"}}}))
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: p)
    with pytest.raises(RuntimeError, match="correlation"):
        discovery.discover_local_codex(exe, root, cwd, allow_account_discovery=True)
    sent = [json.loads(line) for line in p.stdin.getvalue().splitlines()]
    assert [m["method"] for m in sent] == ["initialize", "initialized", "account/read"]


def test_bad_model_list_cursor_not_silently_accepted(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    records = _lines(**{"3": {"id": 3, "result": {"data": [], "nextCursor": ""}}})
    p = _FakeProcess(records)
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: p)
    with pytest.raises(RuntimeError, match="cursor"):
        discovery.discover_local_codex(exe, root, cwd, allow_account_discovery=True)


def test_unexpected_or_malformed_frame_is_not_ignored(discovery_files, monkeypatch):
    exe, root, cwd = discovery_files
    p = _FakeProcess([b'{"id":1,"id":1,"result":{}}\n'])
    monkeypatch.setattr(discovery.subprocess, "Popen", lambda *a, **kw: p)
    with pytest.raises(RuntimeError, match="malformed"):
        discovery.discover_local_codex(exe, root, cwd, allow_account_discovery=True)


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
