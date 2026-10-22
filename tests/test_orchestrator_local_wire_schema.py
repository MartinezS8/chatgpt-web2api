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


def test_cannot_validate_wrong_phase_or_non_object(local_bundle):
    v = LocalWireSchemas(local_bundle, selections=PHASES)
    with pytest.raises(ValueError, match="invalid"):
        v.require("unbound", {})
    with pytest.raises(ValueError, match="invalid"):
        v.require("turn_result", [])
