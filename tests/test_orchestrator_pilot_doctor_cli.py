"""CLI argument handling for local Codex account/model discovery."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_cli():
    script = Path(__file__).resolve().parents[1] / "scripts" / "orchestrator_pilot_doctor.py"
    spec = importlib.util.spec_from_file_location("orchestrator_pilot_doctor_cli", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _required_args(*extra: str) -> list[str]:
    return [
        "orchestrator_pilot_doctor.py",
        "--codex-exe", r"C:\Codex\codex.exe",
        "--schema-root", r"C:\scratch\schemas",
        "--cwd", r"C:\scratch\work",
        *extra,
    ]


def test_account_discovery_requires_source_map_before_calling_doctor(monkeypatch, capsys):
    cli = _load_cli()
    monkeypatch.setattr(sys, "argv", _required_args("--allow-account-discovery"))
    monkeypatch.setattr(cli, "local_pilot_doctor", lambda *args, **kwargs: pytest.fail(
        "doctor must not run when the MCP provenance map is missing"
    ))

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == 2
    assert "--mcp-source-map is required" in capsys.readouterr().err


def test_account_discovery_passes_source_map_to_doctor(monkeypatch, capsys, tmp_path):
    cli = _load_cli()
    source_map = tmp_path / "mcp-source-map.json"
    calls = []
    monkeypatch.setattr(sys, "argv", _required_args(
        "--allow-account-discovery", "--mcp-source-map", str(source_map),
        "--model", "synthetic-model", "--effort", "medium",
    ))
    monkeypatch.setattr(cli, "local_pilot_doctor", lambda *args, **kwargs: (
        calls.append((args, kwargs)) or {"account_discovery_performed": False}
    ))

    assert cli.main() == 0

    assert len(calls) == 1
    assert calls[0][1]["mcp_source_map"] == str(source_map)
    assert calls[0][1]["allow_account_discovery"] is True
    assert calls[0][1]["model"] == "synthetic-model"
    assert calls[0][1]["effort"] == "medium"
    assert '"account_discovery_performed": false' in capsys.readouterr().out


def test_offline_doctor_mode_passes_no_source_map(monkeypatch, capsys):
    cli = _load_cli()
    calls = []
    monkeypatch.setattr(sys, "argv", _required_args())
    monkeypatch.setattr(cli, "local_pilot_doctor", lambda *args, **kwargs: (
        calls.append((args, kwargs)) or {"account_discovery_performed": False}
    ))

    assert cli.main() == 0

    assert len(calls) == 1
    assert calls[0][1]["allow_account_discovery"] is False
    assert calls[0][1]["mcp_source_map"] is None
    assert '"account_discovery_performed": false' in capsys.readouterr().out
