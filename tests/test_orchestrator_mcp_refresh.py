"""Provenance refresh fails closed without exposing identities or config values."""
from __future__ import annotations

import json
import runpy
import subprocess
from pathlib import Path

import pytest

from chatgpt_web2api.orchestrator.mcp_process_guard import _source_map, verify_mcp_disabled
from chatgpt_web2api.orchestrator.mcp_source_inventory import prepare_local_mcp_source_map


@pytest.mark.parametrize("script,function", [
    ("audit_codex_mcp_config.py", "verify_mcp_disabled"),
    ("prepare_codex_mcp_source_map.py", "prepare_local_mcp_source_map"),
])
def test_cli_errors_never_print_source_or_transport_details(monkeypatch, capsys, script, function):
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / script))
    main = namespace["main"]
    monkeypatch.setitem(
        main.__globals__, function,
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("SECRET_TRANSPORT_DETAILS")),
    )
    arguments = [script, "--codex-exe", "unused.exe", "--cwd", "unused"]
    arguments += (["--mcp-source-map", "unused"] if script.startswith("audit")
                  else ["--output-map", "unused"])
    monkeypatch.setattr("sys.argv", arguments)
    assert main() == 2
    captured = capsys.readouterr()
    assert "SECRET" not in captured.out + captured.err
    assert json.loads(captured.out)["error_type"] == "RuntimeError"


def test_inventory_drift_reports_counts_without_names(tmp_path):
    path = tmp_path / "map.json"
    path.write_text(json.dumps({"schema_version": 1, "servers": [
        {"name": "PRIVATE_REMOVED", "source": "unknown"},
    ]}))
    with pytest.raises(ValueError) as error:
        _source_map(path, {"PRIVATE_ADDED": True})
    assert "added=1 removed=1 unresolved=1" in str(error.value)
    assert "PRIVATE" not in str(error.value)


def test_guard_rejects_an_extra_disabled_identity(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"fixture")
    path = tmp_path / "map.json"
    path.write_text('{"schema_version":1,"servers":[]}')
    responses = iter([{}, {"unexpected": False}])
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard._inspect",
        lambda *a: next(responses),
    )
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard._inspect_apps_disabled",
        lambda *a: pytest.fail("drift must stop before the next process"),
    )
    with pytest.raises(PermissionError, match="inventory changed"):
        verify_mcp_disabled(exe, tmp_path, path)


def test_config_edit_during_inventory_writes_no_map(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"fixture")
    config = tmp_path / "config.toml"
    config.write_text("# initial")
    output = tmp_path / "map.json"

    def inspect(*args):
        config.write_text("# concurrent edit")
        return {}

    monkeypatch.setattr("chatgpt_web2api.orchestrator.mcp_source_inventory._inspect", inspect)
    with pytest.raises(ValueError, match="configuration changed"):
        prepare_local_mcp_source_map(
            exe, tmp_path, output, user_config=config,
            project_config=tmp_path / "missing.toml",
        )
    assert not output.exists()


def test_plugin_manifest_provenance_and_snapshot_drift(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"fixture")
    cwd = tmp_path / "scratch"
    cwd.mkdir()
    config = tmp_path / "config.toml"
    config.write_text('[plugins."fixture@market"]\nenabled=true\n')
    cache = tmp_path / "cache"
    root = cache / "market" / "fixture" / "1.0"
    (root / ".codex-plugin").mkdir(parents=True)
    manifest = root / ".codex-plugin" / "plugin.json"
    manifest.write_text('{"name":"fixture","mcpServers":"./.mcp.json"}')
    mcp = root / ".mcp.json"
    mcp.write_text('{"mcpServers":{"fixture-server":{"command":"SECRET_EXEC"}}}')
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_source_inventory._inspect",
        lambda *a: {"fixture-server": True},
    )
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_process_guard.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "codex-cli fixture\n", ""),
    )
    output = tmp_path / "map.json"
    report = prepare_local_mcp_source_map(
        exe, cwd, output, user_config=config,
        project_config=tmp_path / "missing.toml", plugin_cache=cache,
        bind_snapshot=True,
    )
    assert report["from_plugin_manifest"] == 1
    assert report["snapshot_bound"] is True
    data = json.loads(output.read_text())
    assert data["schema_version"] == 2
    assert data["servers"] == [
        {"name": "fixture-server", "source": "plugin", "plugin_id": "fixture@market"},
    ]
    assert "SECRET_EXEC" not in output.read_text()
    from chatgpt_web2api.orchestrator.mcp_config_snapshot import verify_snapshot
    verify_snapshot(data["snapshot"], exe, cwd, {"fixture-server": True})
    mcp.write_text('{"mcpServers":{}}')
    with pytest.raises(ValueError, match="snapshot changed"):
        verify_snapshot(data["snapshot"], exe, cwd, {"fixture-server": True})


def test_ambiguous_plugin_versions_remain_unknown(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"fixture")
    config = tmp_path / "config.toml"
    config.write_text('[plugins."fixture@market"]\nenabled=true\n')
    cache = tmp_path / "cache"
    for version in ("1.0", "2.0"):
        root = cache / "market" / "fixture" / version
        (root / ".codex-plugin").mkdir(parents=True)
        (root / ".codex-plugin/plugin.json").write_text(
            '{"name":"fixture","mcpServers":"./.mcp.json"}',
        )
        (root / ".mcp.json").write_text('{"mcpServers":{"fixture-server":{}}}')
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_source_inventory._inspect",
        lambda *a: {"fixture-server": True},
    )
    report = prepare_local_mcp_source_map(
        exe, tmp_path, tmp_path / "map.json", user_config=config,
        project_config=tmp_path / "missing.toml", plugin_cache=cache,
    )
    assert report["unresolved_source_count"] == 1


def test_redirected_plugin_manifest_never_becomes_provenance(tmp_path, monkeypatch):
    from chatgpt_web2api.orchestrator.mcp_source_inventory import _plugin_candidates
    root = tmp_path / "market/fixture/1.0"
    root.mkdir(parents=True)
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_source_inventory.source_fingerprint",
        lambda *a: (_ for _ in ()).throw(ValueError("redirected candidate")),
    )
    candidates, evidence, rejected = _plugin_candidates(
        tmp_path, {"plugins": {"fixture@market": {"enabled": True}}},
    )
    assert candidates == {} and evidence == {} and rejected == 1


@pytest.mark.parametrize("mutation", ["binary", "cwd", "inventory", "config"])
def test_snapshot_rejects_each_bound_input(tmp_path, monkeypatch, mutation):
    from chatgpt_web2api.orchestrator.mcp_config_snapshot import capture_snapshot, verify_snapshot
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"fixture")
    config = tmp_path / "c.toml"
    config.write_text("# fixture")
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_config_snapshot.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "codex-cli fixture\n", ""),
    )
    snapshot = capture_snapshot(exe, tmp_path, {"one": True}, [config])
    cwd, inventory = tmp_path, {"one": True}
    if mutation == "binary":
        exe.write_bytes(b"changed")
    elif mutation == "cwd":
        cwd = tmp_path / "other"
        cwd.mkdir()
    elif mutation == "inventory":
        inventory = {"one": False}
    else:
        config.write_text("# changed")
    with pytest.raises(ValueError, match="snapshot changed"):
        verify_snapshot(snapshot, exe, cwd, inventory)
