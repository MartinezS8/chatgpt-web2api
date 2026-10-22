"""Positive/negative schema fencing against disposable synthetic bundles."""
from __future__ import annotations

import hashlib
import json

import pytest

from chatgpt_web2api.orchestrator.local_wire_schema import LocalWireSchemas

PHASES = {
    "thread_params": "ThreadStartParams.json",
    "thread_result": "ThreadStartResponse.json",
    "turn_params": "TurnStartParams.json",
    "turn_result": "TurnStartResponse.json",
}


@pytest.fixture
def local_bundle(tmp_path):
    folder = tmp_path / "generated"
    folder.mkdir()
    schemas = {
        "ThreadStartParams.json": {"type": "object", "required": ["model", "sandbox"],
                                   "properties": {"sandbox": {"const": "read-only"}}},
        "ThreadStartResponse.json": {"type": "object", "required": ["thread"],
                                     "properties": {"thread": {
                                         "type": "object", "required": ["id", "source"],
                                         "properties": {"source": {"type": "string"}}}}},
        "TurnStartParams.json": {"type": "object", "required": ["threadId", "input"],
                                 "properties": {"input": {"type": "array", "minItems": 1}}},
        "TurnStartResponse.json": {"type": "object", "required": ["turn"],
                                   "properties": {"turn": {"type": "object",
                                                         "required": ["id"]}}},
    }
    manifest = []
    for name, document in schemas.items():
        path = folder / name
        path.write_text(json.dumps(document), encoding="utf-8")
        manifest.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (folder / "offline-readiness.json").write_text(json.dumps({
        "codex_version": "codex-cli synthetic",
        "codex_binary_sha256": "a" * 64,
        "installed_schema_inspected": True,
        "generated_json_schema": manifest,
    }), encoding="utf-8")
    return folder


def test_compatible_synthetic_phases_pass(local_bundle):
    verifier = LocalWireSchemas(local_bundle, selections=PHASES)
    verifier.require("thread_params", {"model": "synthetic", "sandbox": "read-only"})
    verifier.require("thread_result", {"thread": {"id": "x", "source": "test"}})
    verifier.require("turn_params", {"threadId": "x", "input": [{"type": "text"}]})
    verifier.require("turn_result", {"turn": {"id": "t"}})
    assert verifier.codex_version == "codex-cli synthetic"


def test_old_thread_result_shape_is_rejected(local_bundle):
    verifier = LocalWireSchemas(local_bundle, selections=PHASES)
    with pytest.raises(ValueError, match="thread_result"):
        verifier.require("thread_result", {"thread": {"id": "old-no-source"}})


def test_outgoing_turn_params_missing_input_are_rejected(local_bundle):
    verifier = LocalWireSchemas(local_bundle, selections=PHASES)
    with pytest.raises(ValueError, match="turn_params"):
        verifier.require("turn_params", {"threadId": "x"})


def test_wrong_selector_duplicate_or_tampering_is_blocked(local_bundle):
    wrong = dict(PHASES)
    wrong["thread_params"] = "uncaptured.json"
    with pytest.raises(ValueError, match="absent"):
        LocalWireSchemas(local_bundle, selections=wrong)
    wrong["thread_params"] = wrong["turn_params"]
    with pytest.raises(ValueError, match="distinct"):
        LocalWireSchemas(local_bundle, selections=wrong)
    (local_bundle / PHASES["thread_result"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        LocalWireSchemas(local_bundle, selections=PHASES)


@pytest.mark.parametrize("phase", list(PHASES))
def test_schema_that_accepts_malformed_rpc_is_not_accepted(local_bundle, phase):
    schema_file = local_bundle / PHASES[phase]
    schema_file.write_text(json.dumps({"type": "object"}), encoding="utf-8")
    manifest_file = local_bundle / "offline-readiness.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    for entry in manifest["generated_json_schema"]:
        if entry["path"] == schema_file.name:
            entry["sha256"] = hashlib.sha256(schema_file.read_bytes()).hexdigest()
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match=phase + " schema accepts malformed"):
        LocalWireSchemas(local_bundle, selections=PHASES)


def test_cannot_validate_wrong_phase_or_non_object(local_bundle):
    v = LocalWireSchemas(local_bundle, selections=PHASES)
    with pytest.raises(ValueError, match="invalid"):
        v.require("unbound", {})
    with pytest.raises(ValueError, match="invalid"):
        v.require("turn_result", [])


def test_semantically_wrong_schema_title_is_rejected(local_bundle):
    target = local_bundle / PHASES["thread_params"]
    document = json.loads(target.read_text(encoding="utf-8"))
    document["title"] = "TurnStartParams"
    target.write_text(json.dumps(document), encoding="utf-8")
    manifest_file = local_bundle / "offline-readiness.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    for entry in manifest["generated_json_schema"]:
        if entry["path"] == target.name:
            entry["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="title belongs"):
        LocalWireSchemas(local_bundle, selections=PHASES)
