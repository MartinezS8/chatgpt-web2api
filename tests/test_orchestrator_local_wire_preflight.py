"""Offline preview must use the same pure request builders as real wire."""
from __future__ import annotations

import hashlib
import json

import pytest

import chatgpt_web2api.orchestrator.local_wire_preflight as preflight
from chatgpt_web2api.orchestrator.local_pilot_messages import (
    thread_start_params,
    turn_start_params,
)


@pytest.fixture
def ready(tmp_path):
    folder = tmp_path / "schemas"
    folder.mkdir()
    names = {
        "thread_params": "thread.json",
        "thread_result": "thread_result.json",
        "turn_params": "turn.json",
        "turn_result": "turn_result.json",
    }
    specifications = {
        "thread.json": {"type": "object", "required": ["model", "approvalPolicy", "sandbox"],
                        "properties": {"approvalPolicy": {"const": "never"},
                                       "sandbox": {"const": "read-only"}}},
        "thread_result.json": {"type": "object"},
        "turn.json": {"type": "object", "required": ["threadId", "input", "sandboxPolicy"],
                      "properties": {"sandboxPolicy": {"type": "object", "properties": {
                          "type": {"const": "readOnly"}}}}},
        "turn_result.json": {"type": "object"},
    }
    manifest = []
    for name, spec in specifications.items():
        file = folder / name
        file.write_text(json.dumps(spec), encoding="utf-8")
        manifest.append({"path": name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    (folder / "offline-readiness.json").write_text(json.dumps({
        "codex_version": "codex-cli local-fixture",
        "codex_binary_sha256": "a" * 64,
        "installed_schema_inspected": True,
        "generated_json_schema": manifest,
    }), encoding="utf-8")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Only output ORCH_TEST_OK", encoding="utf-8")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return folder, scratch, prompt, names


def test_pure_builders_agree_on_read_only_policy():
    thread = thread_start_params(model="test", cwd="C:/scratch")
    turn = turn_start_params(thread_id="thr", prompt="safe", model="test",
                             effort="medium", cwd="C:/scratch")
    assert thread["sandbox"] == "read-only"
    assert turn["sandboxPolicy"] == {"type": "readOnly"}
    assert turn["approvalPolicy"] == thread["approvalPolicy"] == "never"


def test_real_shapes_previewed_with_no_provider_contact(ready, monkeypatch):
    folder, scratch, prompt, names = ready
    monkeypatch.setattr(preflight, "subprocess", None, raising=False)
    report = preflight.preview_local_one_turn(
        folder, scratch, prompt, model="selected", effort="medium", selections=names,
    )
    assert report["thread_params_schema_pass"]
    assert report["turn_params_schema_pass"]
    assert report["real_turn_started"] is False
    assert report["thread_result_schema_checked"] is False
    assert report["account_read_performed"] is False
    assert "Only output" not in str(report)


def test_new_schema_breaks_preview_without_live_action(ready):
    folder, scratch, prompt, names = ready
    changed = folder / names["turn_params"]
    changed.write_text(json.dumps({
        "type": "object", "required": ["field_not_supplied_by_live_adapter"],
    }), encoding="utf-8")
    receipt = folder / "offline-readiness.json"
    content = json.loads(receipt.read_text(encoding="utf-8"))
    for entry in content["generated_json_schema"]:
        if entry["path"] == changed.name:
            entry["sha256"] = hashlib.sha256(changed.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="turn_params"):
        preflight.preview_local_one_turn(
            folder, scratch, prompt, model="selected", effort="medium", selections=names,
        )


def test_wrong_bundle_or_missing_prompt_is_rejected(ready):
    folder, scratch, prompt, names = ready
    prompt.unlink()
    with pytest.raises(ValueError, match="prompt"):
        preflight.preview_local_one_turn(
            folder, scratch, prompt, model="selected", effort="medium", selections=names,
        )
    prompt.write_text("test", encoding="utf-8")
    (folder / names["thread_params"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        preflight.preview_local_one_turn(
            folder, scratch, prompt, model="selected", effort="medium", selections=names,
        )
