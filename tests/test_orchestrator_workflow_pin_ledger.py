"""Offline regression tests: source-pinned CI evidence survives task/review storage.

All tests use synthetic GitHub readers and mock dispatch. No external writes.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace

import pytest
from test_orchestrator_provider_evidence import SHA, STAMP, FakeReader, inspect
from test_orchestrator_provider_evidence import store as store
from test_orchestrator_task_review_evidence import Reviewer

from chatgpt_web2api.orchestrator.github_readonly_evidence import GitHubReadOnlyEvidence
from chatgpt_web2api.orchestrator.github_readonly_reviews import GitHubReadOnlyReviews
from chatgpt_web2api.orchestrator.provider_evidence import ProviderEvidenceLedger
from chatgpt_web2api.orchestrator.task_review_evidence import TaskReviewEvidenceLedger
from chatgpt_web2api.orchestrator.workflow_source_pin import WorkflowSourcePin

WORKFLOW_PATH = ".github/workflows/ci.yml"
SOURCE = b"name: verified-mock-CI\non: push\njobs: {}\n"
BLOB = hashlib.sha1(
    b"blob " + str(len(SOURCE)).encode() + b"\0" + SOURCE
).hexdigest()


class PinnedReader(FakeReader):
    def __call__(self, path):
        if path == "/repos/Acme/repo/actions/workflows/51":
            self.calls.append(path)
            return {"id": 51, "path": WORKFLOW_PATH, "state": "active"}
        if path == f"/repos/Acme/repo/contents/{WORKFLOW_PATH}?ref={SHA}":
            self.calls.append(path)
            return {"type": "file", "path": WORKFLOW_PATH, "name": "ci.yml",
                    "encoding": "base64", "size": len(SOURCE), "sha": BLOB,
                    "content": base64.b64encode(SOURCE).decode("ascii")}
        value = super().__call__(path)
        if path == "/repos/Acme/repo/actions/runs/99":
            return {**value, "path": WORKFLOW_PATH}
        return value


def pinned_gate(reader):
    pin = WorkflowSourcePin(
        owner="Acme", repo="repo", repository_id=137, workflow_id=51,
        workflow_path=WORKFLOW_PATH, trusted_blob_sha=BLOB, reader=reader,
    )
    return GitHubReadOnlyEvidence(
        owner="Acme", repo="repo", repository_id=137,
        trusted_workflow_ids=frozenset({51}),
        required_job_names=frozenset({"lint", "unit"}),
        reader=reader, now=lambda: STAMP, workflow_source_pin=pin,
    )


def reviewer_gate():
    return GitHubReadOnlyReviews(
        owner="Acme", repo="repo", repository_id=137,
        trusted_reviewer_ids=frozenset({44, 45}),
        reader=Reviewer(), now=lambda: STAMP,
    )


def test_pin_persisted_in_digest_and_read_only_receipt(store):
    ledger = ProviderEvidenceLedger(store, pinned_gate(PinnedReader()), now=lambda: STAMP)
    receipt = inspect(ledger)
    saved = ledger.get("impl")
    assert saved["workflow_blob_sha"] == BLOB == receipt["workflow_blob_sha"]
    assert receipt["digest"] == saved["digest"]
    assert not receipt["production_finalization_permitted"]
    assert not receipt["live_send_permitted"]
    assert store.get("impl")["state"] == "result_received"
    assert store.get("impl")["slot"] == 1
    with store._connect() as db:
        bound = ledger._binding(db, "impl", "attempt-1")
    data = {**bound, "repository_id": 137, "pr_number": 7,
            "head_sha": SHA, "run_id": 99, "workflow_id": 51, "run_attempt": 1,
            "assurance": "provider_read_only_unreviewed", "workflow_blob_sha": BLOB}
    expected = hashlib.sha256(json.dumps(
        data, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert saved["digest"] == expected


def test_pin_survives_reopen_and_is_idempotent(store):
    first = ProviderEvidenceLedger(store, pinned_gate(PinnedReader()), now=lambda: STAMP)
    initial = inspect(first)
    second = ProviderEvidenceLedger(store, pinned_gate(PinnedReader()), now=lambda: STAMP)
    later = inspect(second)
    assert not later["new"] and initial["digest"] == later["digest"]
    assert second.get("impl")["workflow_blob_sha"] == BLOB
    assert [e["kind"] for e in store.events("impl")].count("evidence.provider_observed") == 1


def test_missing_pin_or_spoofed_pin_cannot_be_sealed(store):
    for spoof in (None, "f" * 40):
        gate = pinned_gate(PinnedReader())
        actual = gate.inspect
        gate.inspect = lambda **kw: replace(actual(**kw), workflow_blob_sha=spoof)
        ledger = ProviderEvidenceLedger(store, gate, now=lambda: STAMP)
        with pytest.raises(ValueError, match="trusted workflow source pin"):
            inspect(ledger)
        assert ledger.get("impl") is None


def test_source_pin_cannot_be_claimed_by_unpinned_gate(store):
    reader = FakeReader()
    gate = GitHubReadOnlyEvidence(
        owner="Acme", repo="repo", repository_id=137,
        trusted_workflow_ids=frozenset({51}),
        required_job_names=frozenset({"lint", "unit"}),
        reader=reader, now=lambda: STAMP,
    )
    actual = gate.inspect
    gate.inspect = lambda **kw: replace(actual(**kw), workflow_blob_sha=BLOB)
    ledger = ProviderEvidenceLedger(store, gate, now=lambda: STAMP)
    with pytest.raises(ValueError, match="unpinned CI gate"):
        inspect(ledger)
    assert ledger.get("impl") is None


def test_stored_workflow_pin_tampering_blocks_review_before_network(store):
    ci = ProviderEvidenceLedger(store, pinned_gate(PinnedReader()), now=lambda: STAMP)
    inspect(ci)
    reviewer = reviewer_gate()
    review = TaskReviewEvidenceLedger(
        store, ci, reviewer, trusted_implementer_user_id=55, now=lambda: STAMP,
    )
    with store._connect() as db:
        db.execute(
            "UPDATE orchestrator_provider_observations SET workflow_blob_sha=? WHERE task_id='impl'",
            ("f" * 40,),
        )
    with pytest.raises(ValueError, match="workflow source pin"):
        review.inspect_and_record(task_id="impl", attempt_id="attempt-1")
    assert reviewer.reader.calls == []
    assert review.get("impl") is None


def test_review_digest_inherits_verified_source_pin(store):
    ci = ProviderEvidenceLedger(store, pinned_gate(PinnedReader()), now=lambda: STAMP)
    inspect(ci)
    review = TaskReviewEvidenceLedger(
        store, ci, reviewer_gate(), trusted_implementer_user_id=55,
        now=lambda: STAMP,
    )
    receipt = review.inspect_and_record(task_id="impl", attempt_id="attempt-1")
    assert receipt["ci_digest"] == ci.get("impl")["digest"]
    assert review.get("impl")["ci_digest"] == ci.get("impl")["digest"]
    assert not receipt["production_finalization_permitted"]
    assert store.get("impl")["state"] == "result_received"


def test_legacy_unpinned_receipt_not_upgraded_by_new_pin_policy(store):
    reader = FakeReader()
    old_gate = GitHubReadOnlyEvidence(
        owner="Acme", repo="repo", repository_id=137,
        trusted_workflow_ids=frozenset({51}),
        required_job_names=frozenset({"lint", "unit"}),
        reader=reader, now=lambda: STAMP,
    )
    old_ci = ProviderEvidenceLedger(store, old_gate, now=lambda: STAMP)
    legacy = inspect(old_ci)
    assert legacy["workflow_blob_sha"] is None
    assert old_ci.get("impl")["workflow_blob_sha"] is None
    pinned_ci = ProviderEvidenceLedger(
        store, pinned_gate(PinnedReader()), now=lambda: STAMP,
    )
    review = TaskReviewEvidenceLedger(
        store, pinned_ci, reviewer_gate(),
        trusted_implementer_user_id=55, now=lambda: STAMP,
    )
    with pytest.raises(ValueError, match="missing trusted workflow source pin"):
        review.inspect_and_record(task_id="impl", attempt_id="attempt-1")
    assert review.get("impl") is None


def test_migrates_real_legacy_sqlite_schema_without_changing_existing_proof(store):
    # Restore a historical, pre-V24 table shape before the next constructor.
    with store._connect() as db:
        db.execute("DROP TABLE IF EXISTS orchestrator_provider_observations")
        db.execute("""CREATE TABLE orchestrator_provider_observations (
            task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
            attempt_id TEXT NOT NULL UNIQUE,
            repository_id INTEGER NOT NULL, pr_number INTEGER NOT NULL,
            head_sha TEXT NOT NULL, run_id INTEGER NOT NULL,
            workflow_id INTEGER NOT NULL, run_attempt INTEGER NOT NULL,
            package_sha256 TEXT NOT NULL, result_sha256 TEXT NOT NULL,
            claim_version INTEGER NOT NULL, digest TEXT NOT NULL,
            assurance TEXT NOT NULL CHECK(assurance='provider_read_only_unreviewed'),
            observed_at REAL NOT NULL)""")
    reader = FakeReader()
    old_gate = GitHubReadOnlyEvidence(
        owner="Acme", repo="repo", repository_id=137,
        trusted_workflow_ids=frozenset({51}),
        required_job_names=frozenset({"lint", "unit"}),
        reader=reader, now=lambda: STAMP,
    )
    ledger = ProviderEvidenceLedger(store, old_gate, now=lambda: STAMP)
    assert inspect(ledger)["new"]
    initial = ledger.get("impl")
    again = ProviderEvidenceLedger(store, old_gate, now=lambda: STAMP)
    assert again.get("impl")["digest"] == initial["digest"]
    assert again.get("impl")["workflow_blob_sha"] is None
    with store._connect() as db:
        columns = {r["name"] for r in db.execute(
            "PRAGMA table_info(orchestrator_provider_observations)")}
    assert "workflow_blob_sha" in columns


def test_identical_ci_receipt_cannot_hide_mutated_source_column(store):
    ci = ProviderEvidenceLedger(store, pinned_gate(PinnedReader()), now=lambda: STAMP)
    inspect(ci)
    with store._connect() as db:
        db.execute(
            "UPDATE orchestrator_provider_observations SET workflow_blob_sha=NULL WHERE task_id='impl'"
        )
    with pytest.raises(ValueError, match="already sealed"):
        inspect(ci)
