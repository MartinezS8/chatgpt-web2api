"""Schema bundle checks stay offline and reject the old thread fixture."""
from __future__ import annotations

import hashlib
import json

import pytest

from chatgpt_web2api.orchestrator.schema_fixture_audit import (
    audit_fixture,
    verified_bundle,
)


@pytest.fixture
def captured(tmp_path):
    root = tmp_path / "captured"
    root.mkdir()
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["approvalsReviewer", "sandbox", "thread"],
        "properties": {
            "approvalsReviewer": {"type": ["object", "null"]},
            "sandbox": {"enum": ["read-only"]},
            "thread": {
                "type": "object", "required": ["source"],
                "properties": {"source": {"type": "string"}},
            },
        },
    }
    file = root / "ThreadStartResponse.json"
    file.write_text(json.dumps(schema), encoding="utf-8")
    report = {
        "codex_version": "codex-cli 0.synthetic",
        "codex_binary_sha256": "a" * 64,
        "installed_schema_inspected": True,
        "generated_json_schema": [{
            "path": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        }],
    }
    (root / "offline-readiness.json").write_text(json.dumps(report), encoding="utf-8")
    fixture = tmp_path / "response.json"
    return root, fixture


def test_correct_fixture_is_valid_and_no_provider_call(captured):
    root, fixture = captured
    fixture.write_text(json.dumps({
        "approvalsReviewer": None, "sandbox": "read-only",
        "thread": {"source": "test"},
    }), encoding="utf-8")
    result = audit_fixture(root, "ThreadStartResponse.json", fixture)
    assert result["valid"] is True
    assert result["provider_contacted"] is False
    assert result["live_send_permitted"] is False


def test_previous_response_shape_is_rejected_with_paths(captured):
    root, fixture = captured
    fixture.write_text(json.dumps({
        "approvalsReviewer": "on-request", "sandbox": "danger-full-access",
        "thread": {"id": "thread-1"},
    }), encoding="utf-8")
    result = audit_fixture(root, "ThreadStartResponse.json", fixture)
    assert result["valid"] is False
    assert result["error_count"] == 3
    assert {"/approvalsReviewer", "/sandbox", "/thread"}.issubset(result["error_paths"])


def test_tampered_schema_and_extra_files_are_rejected(captured):
    root, _ = captured
    target = root / "ThreadStartResponse.json"
    target.write_text('{"type":"null"}', encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        verified_bundle(root)
    target.write_text('{"type":"object"}', encoding="utf-8")
    (root / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected|checksum"):
        verified_bundle(root)


@pytest.mark.parametrize("path", ["../secret.json", "/elsewhere.json", "a/../../x.json",
                                  "C:\\\\Windows\\\\test.json", "offline-readiness.json"])
def test_schema_path_cannot_escape_bundle(captured, path):
    root, fixture = captured
    fixture.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        audit_fixture(root, path, fixture)


def test_missing_and_duplicate_manifest_entries_are_refused(captured):
    root, _ = captured
    receipt = root / "offline-readiness.json"
    report = json.loads(receipt.read_text(encoding="utf-8"))
    report["generated_json_schema"].append(report["generated_json_schema"][0])
    receipt.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        verified_bundle(root)


def test_no_uncaptured_schema_file_is_accepted(captured):
    root, _ = captured
    (root / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected"):
        verified_bundle(root)
