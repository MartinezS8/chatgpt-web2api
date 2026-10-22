"""Schema readiness is offline, explicit and fail-closed, without model/list."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import chatgpt_web2api.orchestrator.codex_readiness as readiness


@pytest.fixture
def setup_codex(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("native Windows only")
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"synthetic fixture, never actually executed")
    target = tmp_path / "brand-new-schema"
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        assert kwargs["check"] is True
        assert kwargs["capture_output"] is True
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(argv, 0, stdout="codex-cli 0.test.1\n")
        if argv[1:4] == ["app-server", "generate-json-schema", "--out"]:
            (target / "codex_app_server_protocol.schemas.json").write_text(
                json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema",
                            "type": "object"}), encoding="utf-8",
            )
            return subprocess.CompletedProcess(argv, 0, stdout="")
        raise AssertionError("unexpected command would cause live activity")

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)
    return exe, target, calls


def test_only_two_offline_commands_and_schema_fingerprint(setup_codex):
    exe, target, calls = setup_codex
    response = readiness.inspect_codex_schema(
        exe, target, expected_version="codex-cli 0.test.1",
    )
    assert len(calls) == 2
    assert calls[0] == [str(exe), "--version"]
    assert calls[1] == [str(exe), "app-server", "generate-json-schema", "--out", str(target)]
    assert response["codex_binary_sha256"]
    assert len(response["generated_json_schema"]) == 1
    assert response["account_available_models_checked"] is False
    assert response["available_thinking_efforts_checked"] is False
    assert response["live_provider_authorized"] is False
    assert (target / "offline-readiness.json").is_file()


def test_version_mismatch_refuses_schema_generation(setup_codex):
    exe, target, calls = setup_codex
    with pytest.raises(ValueError, match="differs"):
        readiness.inspect_codex_schema(exe, target, expected_version="codex-cli elsewhere")
    assert len(calls) == 1
    assert not target.exists()


def test_no_path_lookup_no_overwrite_and_no_cmd_shim(setup_codex):
    exe, target, calls = setup_codex
    with pytest.raises(ValueError, match="absolute"):
        readiness.inspect_codex_schema("codex", target)
    with pytest.raises(ValueError, match="native Codex"):
        readiness.inspect_codex_schema(exe.with_suffix(".cmd"), target)
    target.mkdir()
    with pytest.raises(ValueError, match="NEW"):
        readiness.inspect_codex_schema(exe, target)
    assert not calls


def test_malformed_version_fails_before_creating_directory(setup_codex, monkeypatch):
    exe, target, calls = setup_codex

    def malformed(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="not-codex\n")

    monkeypatch.setattr(readiness.subprocess, "run", malformed)
    with pytest.raises(ValueError, match="unrecognized"):
        readiness.inspect_codex_schema(exe, target)
    assert not target.exists()


def test_no_generated_schema_is_not_a_pass(setup_codex, monkeypatch):
    exe, target, _ = setup_codex

    def empty_schema(argv, **kwargs):
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(argv, 0, stdout="codex-cli 0.test.1\n")
        return subprocess.CompletedProcess(argv, 0, stdout="")

    monkeypatch.setattr(readiness.subprocess, "run", empty_schema)
    with pytest.raises(ValueError, match="missing"):
        readiness.inspect_codex_schema(exe, target)


def test_subprocess_failure_is_not_silently_ignored(setup_codex, monkeypatch):
    exe, target, _ = setup_codex

    def refused(argv, **kwargs):
        raise subprocess.CalledProcessError(8, argv)

    monkeypatch.setattr(readiness.subprocess, "run", refused)
    with pytest.raises(subprocess.CalledProcessError):
        readiness.inspect_codex_schema(exe, target)
    assert not target.exists()
