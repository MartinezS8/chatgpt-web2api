"""Offline integration regressions for task-scoped, read-only GitHub proof."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from chatgpt_web2api.orchestrator.github_readonly_evidence import GitHubReadOnlyEvidence
from chatgpt_web2api.orchestrator.provider_evidence import ProviderEvidenceLedger
from chatgpt_web2api.orchestrator.store import Store, TaskSpec

SHA = "a" * 40
STAMP = 1_781_000_000.0
PACKAGE = "c" * 64
REMOTE_RESULT = "remote:verified-turn-with-sensitive-link-not-for-logs"


class FakeReader:
    def __init__(self, store: Store | None = None, *, fail_run=False,
                 move_head=False, mutation=None):
        self.store, self.fail_run, self.move_head, self.mutation = (
            store, fail_run, move_head, mutation)
        self.pr_views = 0
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        if path == "/repos/Acme/repo":
            return {"id": 137, "full_name": "Acme/repo"}
        if path == "/repos/Acme/repo/pulls/7":
            self.pr_views += 1
            head = "b" * 40 if self.move_head and self.pr_views == 2 else SHA
            return {"number": 7, "state": "open", "merged": False,
                    "base": {"repo": {"id": 137}},
                    "head": {"sha": head, "ref": "codex/fix", "repo": {"id": 137}}}
        if path.endswith("/jobs?filter=latest&per_page=100"):
            job_run_id = int(path.split("/actions/runs/")[1].split("/")[0])
            return {"total_count": 2, "jobs": [
                {"name": name, "run_id": job_run_id, "head_sha": SHA,
                 "status": "completed", "conclusion": "success"}
                for name in ("lint", "unit")]}
        if path.startswith("/repos/Acme/repo/actions/runs/"):
            if self.mutation is not None:
                self.mutation(self.store)
            return {"id": int(path.rsplit("/", 1)[1]), "repository": {"id": 137},
                    "workflow_id": 51, "head_sha": SHA, "status": "completed",
                    "conclusion": "failure" if self.fail_run else "success",
                    "run_attempt": 1, "event": "push", "head_branch": "codex/fix",
                    "head_repository": {"id": 137}}
        raise AssertionError("unexpected provider path")


@pytest.fixture
def store(tmp_path: Path) -> Store:
    item = Store(tmp_path / "controller.sqlite")
    item.create(TaskSpec("impl", "p", "implement", "Please implement safely",
                         write_scopes=("github:repo/137/src",)))
    claim = item.claim("p")
    assert claim is not None and claim["claim_token"] and claim["slot"] == 1
    result_hash = hashlib.sha256(claim["claim_token"].encode()).hexdigest()
    with item._connect() as db:
        db.execute("""CREATE TABLE orchestrator_task_packages
            (task_id TEXT PRIMARY KEY,package_sha256 TEXT,prompt TEXT,
             attachments_json TEXT,sealed_at REAL)""")
        db.execute("INSERT INTO orchestrator_task_packages VALUES (?,?,?,?,?)",
                   ("impl", PACKAGE, "Please implement safely", "[]", STAMP))
        db.execute("""CREATE TABLE orchestrator_dispatch_attempts
            (attempt_id TEXT PRIMARY KEY,task_id TEXT UNIQUE,package_sha256 TEXT,
             claim_token_hash TEXT,status TEXT,conversation_id TEXT,
             delivery_id TEXT,result_ref TEXT,error_code TEXT,
             created_at REAL,updated_at REAL)""")
        db.execute("INSERT INTO orchestrator_dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   ("attempt-1", "impl", PACKAGE, result_hash, "completed",
                    "fake:chat", "fake:message", REMOTE_RESULT, None, STAMP, STAMP))
        db.execute("UPDATE tasks SET state='result_received', evidence_ref=?, claim_version=claim_version+1 WHERE task_id='impl'",
                   (REMOTE_RESULT,))
    return item


def gate(reader):
    return GitHubReadOnlyEvidence(owner="Acme", repo="repo", repository_id=137,
                                  trusted_workflow_ids=frozenset({51}),
                                  required_job_names=frozenset({"lint", "unit"}),
                                  reader=reader, now=lambda: STAMP)


def inspect(ledger, *, task="impl", attempt="attempt-1", run_id=99):
    return ledger.inspect_and_record(task_id=task, attempt_id=attempt,
                                     pr_number=7, expected_head_sha=SHA, run_id=run_id)


def test_records_exact_fenced_task_pr_ci_without_finishing_or_releasing_lock(store):
    reader = FakeReader()
    ledger = ProviderEvidenceLedger(store, gate(reader), now=lambda: STAMP)
    proof = inspect(ledger)
    assert proof["new"] and not proof["production_finalization_permitted"]
    assert proof["assurance"] == "provider_read_only_unreviewed"
    assert proof["run_id"] == 99 and proof["repository_id"] == 137
    assert store.get("impl")["state"] == "result_received"
    assert store.get("impl")["slot"] == 1
    assert ledger.get("impl")["package_sha256"] == PACKAGE
    assert ledger.get("impl")["result_sha256"] == hashlib.sha256(REMOTE_RESULT.encode()).hexdigest()
    assert REMOTE_RESULT not in json.dumps(ledger.get("impl"))
    assert not ledger.production_finalization_permitted("impl")
    assert any(e["kind"] == "evidence.provider_observed" for e in store.events("impl"))
    assert reader.calls == ["/repos/Acme/repo", "/repos/Acme/repo/pulls/7",
                             "/repos/Acme/repo/actions/runs/99",
                            "/repos/Acme/repo/actions/runs/99/jobs?filter=latest&per_page=100",
                            "/repos/Acme/repo/pulls/7"]


def test_same_evidence_is_immutable_and_idempotent(store):
    ledger = ProviderEvidenceLedger(store, gate(FakeReader()), now=lambda: STAMP)
    first = inspect(ledger)
    second = inspect(ledger)
    assert first["digest"] == second["digest"]
    assert second["new"] is False
    assert [e["kind"] for e in store.events("impl")].count("evidence.provider_observed") == 1
    reopened = ProviderEvidenceLedger(store, gate(FakeReader()), now=lambda: STAMP)
    assert reopened.get("impl")["digest"] == first["digest"]


def test_different_run_cannot_overwrite_sealed_observation(store):
    ledger = ProviderEvidenceLedger(store, gate(FakeReader()), now=lambda: STAMP)
    inspect(ledger)
    with pytest.raises(ValueError, match="already sealed"):
        inspect(ledger, run_id=100)
    assert ledger.get("impl")["run_id"] == 99


@pytest.mark.parametrize("mutation", [
    "scope", "state", "slot", "claim", "result", "attempt_state",
    "attempt_token", "package",
])
def test_local_provenance_must_match_before_remote_query(store, mutation):
    with store._connect() as db:
        statements = {
            "scope": "UPDATE tasks SET write_scopes='[\"github:repo/138\"]'",
            "state": "UPDATE tasks SET state='needs_human'",
            "slot": "UPDATE tasks SET slot=NULL",
            "claim": "UPDATE tasks SET claim_token='hijacked'",
            "result": "UPDATE tasks SET evidence_ref='unrelated'",
            "attempt_state": "UPDATE orchestrator_dispatch_attempts SET status='intent'",
            "attempt_token": "UPDATE orchestrator_dispatch_attempts SET claim_token_hash='deadbeef'",
            "package": "UPDATE orchestrator_task_packages SET package_sha256='d'",
        }
        db.execute(statements[mutation])
    reader = FakeReader()
    ledger = ProviderEvidenceLedger(store, gate(reader), now=lambda: STAMP)
    with pytest.raises(ValueError):
        inspect(ledger)
    assert reader.calls == []  # fail before contacting provider
    assert ledger.get("impl") is None


def test_unrelated_dispatch_attempt_is_not_evidence(store):
    ledger = ProviderEvidenceLedger(store, gate(FakeReader()), now=lambda: STAMP)
    with pytest.raises(ValueError, match="result does not belong"):
        inspect(ledger, attempt="other-attempt")


def test_provider_failure_does_not_record_observation(store):
    reader = FakeReader(fail_run=True)
    ledger = ProviderEvidenceLedger(store, gate(reader), now=lambda: STAMP)
    with pytest.raises(ValueError, match="workflow evidence"):
        inspect(ledger)
    assert ledger.get("impl") is None


def test_moving_remote_pr_head_does_not_record_observation(store):
    ledger = ProviderEvidenceLedger(store, gate(FakeReader(move_head=True)), now=lambda: STAMP)
    with pytest.raises(ValueError, match="PR head"):
        inspect(ledger)
    assert ledger.get("impl") is None


def test_task_mutated_while_provider_is_queried_rejects_stale_result(store):
    def mutate(s):
        with s._connect() as db:
            db.execute("UPDATE tasks SET claim_version=claim_version+1 WHERE task_id='impl'")
    ledger = ProviderEvidenceLedger(store, gate(FakeReader(store, mutation=mutate)),
                                    now=lambda: STAMP)
    with pytest.raises(ValueError, match="changed during provider"):
        inspect(ledger)
    assert ledger.get("impl") is None


def test_package_changed_while_provider_is_queried_rejects_stale_result(store):
    def mutate(s):
        with s._connect() as db:
            db.execute("UPDATE orchestrator_task_packages SET package_sha256=? WHERE task_id='impl'",
                       ("d" * 64,))
    ledger = ProviderEvidenceLedger(store, gate(FakeReader(store, mutation=mutate)),
                                    now=lambda: STAMP)
    with pytest.raises(ValueError, match="dispatch package identity mismatch"):
        inspect(ledger)
    assert ledger.get("impl") is None


@pytest.mark.parametrize("delay", [121, 1000000])
def test_stale_provider_snapshot_rejected(store, delay):
    ledger = ProviderEvidenceLedger(store, gate(FakeReader()),
                                    now=lambda: STAMP + delay, max_age_seconds=120)
    with pytest.raises(ValueError, match="stale"):
        inspect(ledger)
    assert ledger.get("impl") is None


def test_future_clock_skew_rejected(store):
    ledger = ProviderEvidenceLedger(store, gate(FakeReader()), now=lambda: STAMP-6)
    with pytest.raises(ValueError, match="invalid time"):
        inspect(ledger)


def test_readonly_review_evidence_does_not_unlock_resources(store):
    store.create(TaskSpec("conflict", "another", "implement", "Another task",
                          write_scopes=("github:repo/137/src",)))
    ledger = ProviderEvidenceLedger(store, gate(FakeReader()), now=lambda: STAMP)
    inspect(ledger)
    assert store.claim("another") is None


def test_request_and_freshness_configuration_fail_closed(store):
    with pytest.raises(ValueError):
        ProviderEvidenceLedger(store, gate(FakeReader()), max_age_seconds=0)
    ledger = ProviderEvidenceLedger(store, gate(FakeReader()), now=lambda: STAMP)
    with pytest.raises(ValueError, match="invalid task"):
        ledger.inspect_and_record(task_id="", attempt_id="attempt-1", pr_number=7,
                                  expected_head_sha=SHA, run_id=99)
    with pytest.raises(ValueError, match="invalid dispatch attempt"):
        inspect(ledger, attempt="")
