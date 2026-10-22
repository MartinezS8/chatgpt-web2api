"""The pilot doctor cannot authorize a live send through model discovery."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

import pytest

import chatgpt_web2api.orchestrator.local_pilot_doctor as doctor


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("native Windows executable pin")
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"fake binary, not executed")
    folder = tmp_path / "schema"
    folder.mkdir()
    file = folder / "test.json"
    file.write_text('{"type":"object"}', encoding="utf-8")
    report = {
        "installed_schema_inspected": True,
        "codex_version": "codex-cli 0.test",
        "codex_binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "generated_json_schema": [{
            "path": "test.json", "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        }],
    }
    (folder / "offline-readiness.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(doctor.subprocess, "run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0, stdout="codex-cli 0.test\n"))
    return executable, folder, tmp_path


def test_offline_readiness_does_not_discover_or_send(pinned, monkeypatch):
    exe, folder, cwd = pinned
    monkeypatch.setattr(doctor, "discover_local_codex", lambda *a, **kw: pytest.fail(
        "unexpected account discovery"))
    result = doctor.local_pilot_doctor(exe, folder, cwd)
    assert result["schema_pinned"] is True
    assert result["schema_file_count"] == 1
    assert result["model_verified"] is False
    assert result["account_discovery_performed"] is False
    assert result["first_live_turn_authorized"] is False


def test_opt_in_account_catalog_is_checked_not_guessed(pinned, monkeypatch):
    exe, folder, cwd = pinned
    calls = []
    def fake_discovery(*args, **kwargs):
        calls.append(kwargs)
        return {
            "account_present": True,
            "models": [
                {"id": "offered-model", "supported_efforts": ["low", "medium"]},
            ],
        }
    monkeypatch.setattr(doctor, "discover_local_codex", fake_discovery)
    result = doctor.local_pilot_doctor(
        exe, folder, cwd, allow_account_discovery=True,
        model="offered-model", effort="medium",
    )
    assert calls == [{"allow_account_discovery": True}]
    assert result["model_verified"] is True
    assert result["first_live_turn_authorized"] is False
    assert result["first_live_turn_started"] is False
    assert result["selected_model"] == "offered-model"


def test_unavailable_model_and_effort_fail_closed(pinned, monkeypatch):
    exe, folder, cwd = pinned
    monkeypatch.setattr(doctor, "discover_local_codex", lambda *args, **kw: {
        "account_present": True,
        "models": [{"id": "real", "supported_efforts": ["medium"]}],
    })
    for model, effort in [("invented", "medium"), ("real", "very-high")]:
        with pytest.raises(ValueError, match="not present"):
            doctor.local_pilot_doctor(
                exe, folder, cwd, allow_account_discovery=True,
                model=model, effort=effort,
            )


def test_model_and_effort_must_be_selected_as_pair(pinned):
    exe, folder, cwd = pinned
    with pytest.raises(ValueError, match="together"):
        doctor.local_pilot_doctor(exe, folder, cwd, model="single")
    with pytest.raises(ValueError, match="together"):
        doctor.local_pilot_doctor(exe, folder, cwd, effort="medium")


def test_catalog_without_selection_does_not_use_server_default(pinned, monkeypatch):
    exe, folder, cwd = pinned
    monkeypatch.setattr(doctor, "discover_local_codex", lambda *args, **kw: {
        "account_present": True,
        "models": [{"id": "real", "supported_efforts": ["medium"],
                    "default_effort": "medium"}],
    })
    r = doctor.local_pilot_doctor(exe, folder, cwd, allow_account_discovery=True)
    assert r["model_verified"] is False
    assert "Select" in r["next_action"]
    assert r["first_live_turn_authorized"] is False


def test_mutated_bin_rejects_discovery_and_pilot(pinned, monkeypatch):
    exe, folder, cwd = pinned
    exe.write_bytes(b"changed binary")
    monkeypatch.setattr(doctor, "discover_local_codex", lambda *args, **kw: pytest.fail(
        "called after mismatch"))
    with pytest.raises(ValueError, match="binary differs"):
        doctor.local_pilot_doctor(exe, folder, cwd, allow_account_discovery=True)
