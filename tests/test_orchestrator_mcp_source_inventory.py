"""Source inventory never guesses unknown plugin/CLI origins or emits secrets."""
from __future__ import annotations

import json

import pytest

from chatgpt_web2api.orchestrator.mcp_source_inventory import prepare_local_mcp_source_map


def test_generated_map_contains_only_names_and_classifications(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"fake, never executed")
    cwd = tmp_path / "scratch"
    cwd.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[mcp_servers.local]\ncommand="secret_command"\n'
        'env={SECRET_TOKEN="KEEP_PRIVATE"}\n',
        encoding="utf-8",
    )
    inventory = tmp_path / "inventory.json"
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_source_inventory._inspect",
        lambda *a, **kw: {"local": True, "from-plugin": True},
    )
    result = prepare_local_mcp_source_map(
        exe, cwd, inventory, user_config=cfg,
        project_config=tmp_path / "not-created.toml",
    )
    assert result["from_user_config"] == 1
    assert result["unresolved_source_count"] == 1
    assert result["ready_for_live_guard"] is False
    assert "KEEP_PRIVATE" not in inventory.read_text(encoding="utf-8")
    assert "secret_command" not in inventory.read_text(encoding="utf-8")
    report = json.loads(inventory.read_text(encoding="utf-8"))
    assert report["servers"] == [
        {"name": "from-plugin", "source": "unknown"},
        {"name": "local", "source": "user_config"},
    ]


def test_duplicate_user_and_project_config_does_not_guess_provenance(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"fixture")
    cwd = tmp_path / "scratch"
    cwd.mkdir()
    u, p = tmp_path / "u.toml", tmp_path / "p.toml"
    for x in (u, p):
        x.write_text("[mcp_servers.same]\ncommand='echo'\n", encoding="utf-8")
    monkeypatch.setattr(
        "chatgpt_web2api.orchestrator.mcp_source_inventory._inspect",
        lambda *a, **kw: {"same": True},
    )
    output = tmp_path / "source-map.json"
    report = prepare_local_mcp_source_map(
        exe, cwd, output, user_config=u, project_config=p,
    )
    assert report["unresolved_source_count"] == 1
    with pytest.raises(ValueError, match="new absolute file"):
        prepare_local_mcp_source_map(
            exe, cwd, output, user_config=u, project_config=p,
        )
