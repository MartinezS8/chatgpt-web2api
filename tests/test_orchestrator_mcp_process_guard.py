"""MCP config guard regression tests: zero app-server or provider actions."""
from __future__ import annotations

import json
import subprocess

import pytest

from chatgpt_web2api.orchestrator.mcp_process_guard import (
    parse_mcp_list,
    verify_mcp_disabled,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"fake native executable never run")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    source = tmp_path / "sources.json"
    calls = []
    first = [
        {"name": "from-file", "enabled": True, "transport": "stdio"},
        {"name": "from_cli", "enabled": True, "transport": "streamable_http"},
        {"name": "plugin_server", "enabled": True, "transport": "stdio"},
        {"name": "already-disabled", "enabled": False, "transport": "stdio"},
    ]
    provenance = [
        {"name": "from-file", "source": "user_config"},
        {"name": "from_cli", "source": "cli"},
        {"name": "plugin_server", "source": "plugin", "plugin_id": "sample@marketplace"},
        {"name": "already-disabled", "source": "user_config"},
    ]
    source.write_text(json.dumps({"schema_version": 1, "servers": provenance}), encoding="utf-8")

    def cli(argv, **kwargs):
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 20
        assert "app-server" not in argv and "turn/start" not in argv
        calls.append(argv)
        if argv[-3:] == ["mcp", "list", "--json"]:
            selected = first if len([x for x in calls if x[-3:] == ["mcp", "list", "--json"]]) == 1 else [
                {**x, "enabled": False} for x in first
            ]
            stdout = json.dumps(selected)
        elif argv[-2:] == ["features", "list"]:
            stdout = "Feature Stage State\napps stable false\n"
        else:
            pytest.fail("unexpected Codex read-only preflight command")
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard.subprocess.run", cli,
    )
    return exe, scratch, source, calls, provenance


def test_mixed_sources_only_leaf_overrides_preserve_transport(env):
    exe, scratch, source, calls, _ = env
    result = verify_mcp_disabled(exe, scratch, source)
    assert result.server_count == 4 and result.previously_enabled_count == 3
    assert result.remaining_enabled_count == 0
    assert len(calls) == 3
    args = calls[1]
    assert all("mcp_servers={" not in flag for flag in args)
    assert "mcp_servers.from-file.enabled=false" in args
    assert "mcp_servers.from_cli.enabled=false" in args
    assert "plugins.sample@marketplace.mcp_servers.plugin_server.enabled=false" in args
    assert "features.apps=false" in args
    assert calls[2][-2:] == ["features", "list"]
    assert result.sanitized()["apps_feature_disabled_verified"] is True
    assert result.sanitized()["built_in_tools_absent_verified"] is False
    assert result.sanitized()["live_turn_authorized"] is False


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("unsafe.name", {"source": "user_config"}),
        ("safe_name", {"source": "plugin", "plugin_id": "bad.id@marketplace"}),
    ],
)
def test_unrepresentable_config_identity_fails_before_second_probe(
    env, monkeypatch, name, source,
):
    exe, scratch, source_path, _, _ = env
    data = {"schema_version": 1, "servers": [{"name": name, **source}]}
    source_path.write_text(json.dumps(data), encoding="utf-8")
    inspections = []

    def inspect(*args, **kwargs):
        inspections.append(args)
        return {name: True}

    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard._inspect", inspect,
    )
    with pytest.raises(ValueError, match="safe Codex override"):
        verify_mcp_disabled(exe, scratch, source_path)
    assert len(inspections) == 1


def test_unknown_source_fails_without_second_config_probe(env):
    exe, scratch, source, calls, data = env
    data[2] = {"name": "plugin_server", "source": "unverified"}
    source.write_text(json.dumps({"schema_version": 1, "servers": data}), encoding="utf-8")
    with pytest.raises(ValueError, match="unclassified"):
        verify_mcp_disabled(exe, scratch, source)
    assert len(calls) == 1


def test_missing_plugin_identity_fails_before_second_probe(env):
    exe, scratch, source, calls, data = env
    data[2] = {"name": "plugin_server", "source": "plugin"}
    source.write_text(json.dumps({"schema_version": 1, "servers": data}), encoding="utf-8")
    with pytest.raises(ValueError, match="plugin identity"):
        verify_mcp_disabled(exe, scratch, source)
    assert len(calls) == 1


def test_malformed_transport_and_duplicate_names_fail():
    with pytest.raises(ValueError, match="transport"):
        parse_mcp_list(json.dumps([{"name": "x", "enabled": True}]))
    with pytest.raises(ValueError, match="duplicate"):
        parse_mcp_list(json.dumps([
            {"name": "x", "enabled": True, "transport": "stdio"},
            {"name": "x", "enabled": False, "transport": "stdio"},
        ]))


def test_override_not_effective_must_block(env, monkeypatch):
    exe, scratch, source, calls, _ = env
    original = json.dumps([{"name": "x", "enabled": True, "transport": "stdio"}])
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard._inspect",
        lambda *a, **kw: {"x": True},
    )
    source.write_text(json.dumps({
        "schema_version": 1, "servers": [{"name": "x", "source": "cli"}],
    }), encoding="utf-8")
    with pytest.raises(PermissionError, match="remain enabled"):
        verify_mcp_disabled(exe, scratch, source)
    assert original


def test_bad_cli_error_is_redacted(env, monkeypatch):
    exe, scratch, source, calls, _ = env
    def bad(*a, **kw):
        return subprocess.CompletedProcess(a[0], 1, stdout="", stderr="SECRET_TOKEN_X")
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard.subprocess.run", bad,
    )
    with pytest.raises(RuntimeError) as e:
        verify_mcp_disabled(exe, scratch, source)
    assert "SECRET_TOKEN_X" not in str(e.value)


def test_config_enumeration_never_starts_server_process(env, monkeypatch):
    exe, scratch, source, calls, _ = env
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard.subprocess.Popen",
        lambda *a, **kw: pytest.fail("MCP process launched"),
    )
    verify_mcp_disabled(exe, scratch, source)
    assert len(calls) == 3


def test_apps_override_not_effective_blocks_before_app_server(env, monkeypatch):
    exe, scratch, source, calls, _ = env
    source.write_text('{"schema_version":1,"servers":[]}', encoding="utf-8")

    def cli(argv, **kwargs):
        calls.append(argv)
        assert kwargs["capture_output"] is True and kwargs["timeout"] == 20
        if argv[-3:] == ["mcp", "list", "--json"]:
            return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")
        if argv[-2:] == ["features", "list"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout="Feature Stage State\napps stable true\n", stderr="",
            )
        pytest.fail("unexpected Codex preflight command")

    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard.subprocess.run", cli,
    )
    with pytest.raises(PermissionError, match="Apps feature remains enabled"):
        verify_mcp_disabled(exe, scratch, source)
    assert any(call[-2:] == ["features", "list"] for call in calls)


@pytest.mark.parametrize("feature_output", [
    "", "apps stable unknown", "apps stable false\napps beta false",
    "apps stable false\n" + "x" * (64 * 1024 + 1),
], ids=["empty", "unknown", "duplicate", "too-long"])
def test_apps_feature_probe_requires_one_bounded_boolean_row(env, monkeypatch, feature_output):
    exe, scratch, source, calls, _ = env
    source.write_text('{"schema_version":1,"servers":[]}', encoding="utf-8")

    def cli(argv, **kwargs):
        calls.append(argv)
        if argv[-3:] == ["mcp", "list", "--json"]:
            return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")
        if argv[-2:] == ["features", "list"]:
            return subprocess.CompletedProcess(argv, 0, stdout=feature_output, stderr="")
        pytest.fail("unexpected Codex preflight command")

    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard.subprocess.run", cli,
    )
    with pytest.raises((PermissionError, ValueError)):
        verify_mcp_disabled(exe, scratch, source)
