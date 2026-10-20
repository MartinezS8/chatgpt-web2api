"""Provider metadata and offline mock worker correlation must not authorize writes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from test_orchestrator_provider_evidence import SHA, STAMP
from test_orchestrator_provider_evidence import store as store
from test_orchestrator_task_review_evidence import record, seed

from chatgpt_web2api.orchestrator.implementer_provenance import (
    GitHubSignedCommitReader,
    ImplementerProvenanceLedger,
)


class Commits:
    def __init__(self, mutation=None, **overrides):
        self.calls = []
        self.mutation = mutation
        self.data = {"sha": SHA, "author": {"id": 55}, "committer": {"id": 55},
                     "commit": {"verification": {"verified": True, "reason": "valid"}}}
        self.pr = {"number": 7, "state": "open", "merged": False,
                   "head": {"sha": SHA, "repo": {"id": 137}},
                   "base": {"repo": {"id": 137}}}
        self.repo = {"id": 137, "full_name": "Acme/repo"}
        for k, v in overrides.items():
            setattr(self, k, v)

    def __call__(self, path):
        self.calls.append(path)
        if path == "/repos/Acme/repo":
            return self.repo
        if path == "/repos/Acme/repo/pulls/7":
            return self.pr
        if path == f"/repos/Acme/repo/commits/{SHA}":
            if self.mutation:
                m, self.mutation = self.mutation, None
                m()
            return self.data
        raise AssertionError("wrong GitHub route " + path)


def source(db, commits=None, *, id=55, worker="dev", policy=None, now=STAMP):
    commits = commits or Commits()
    adapter = GitHubSignedCommitReader(owner="Acme", repo="repo", repository_id=137,
                                       reader=commits, now=lambda: now)
    from test_orchestrator_provider_evidence import FakeReader, gate
    from test_orchestrator_task_review_evidence import Reviewer

    from chatgpt_web2api.orchestrator.github_readonly_reviews import GitHubReadOnlyReviews
    from chatgpt_web2api.orchestrator.provider_evidence import ProviderEvidenceLedger
    from chatgpt_web2api.orchestrator.task_review_evidence import TaskReviewEvidenceLedger
    ci = ProviderEvidenceLedger(db,gate(FakeReader()),now=lambda:STAMP)
    review = TaskReviewEvidenceLedger(db, ci, GitHubReadOnlyReviews(
        owner="Acme",repo="repo", repository_id=137, reader=Reviewer(),
        trusted_reviewer_ids=frozenset({44}), now=lambda: STAMP),
        trusted_implementer_user_id=55, now=lambda: STAMP)
    return ImplementerProvenanceLedger(db, review, adapter,
                                      trusted_worker_user_ids=policy or {worker:id},
                                      now=lambda: now), commits


@pytest.fixture
def prepared(store):
    review, ci, _ = seed(store)
    record(review)
    task = store.get("impl")
    with store._connect() as d:
        d.executescript("""CREATE TABLE orchestrator_workers (
            worker_id TEXT PRIMARY KEY,account_id TEXT,project_id TEXT,
            role TEXT,transport TEXT,session_key TEXT,enabled INTEGER);
        CREATE TABLE orchestrator_worker_assignments (
            task_id TEXT PRIMARY KEY,worker_id TEXT,claim_version INTEGER,state TEXT);
        """)
        d.execute("INSERT INTO orchestrator_workers VALUES (?,?,?,?,?,?,?)",
                  ("dev", "account", "p", "implement", "mock", "fake:dev", 1))
        d.execute("INSERT INTO orchestrator_worker_assignments VALUES (?,?,?,?)",
                  ("impl", "dev", task["claim_version"], "active"))
    return store


def check(ledger):
    return ledger.inspect_and_record(task_id="impl",attempt_id="attempt-1")


def test_exact_signed_commit_and_active_mock_assignment_is_only_a_non_authorizing_observation(prepared):
    led, reader = source(prepared)
    r = check(led)
    assert r["new"] and r["worker_id"] == "dev" and r["github_user_id"] == 55
    assert not r["production_finalization_permitted"] and not r["live_send_permitted"]
    assert not led.production_finalization_permitted("impl")
    assert prepared.get("impl")["state"] == "result_received"
    assert prepared.get("impl")["slot"] == 1
    assert [e["kind"] for e in prepared.events("impl")].count("implementer.provider_observed") == 1
    assert reader.calls == ["/repos/Acme/repo","/repos/Acme/repo/pulls/7",
                            f"/repos/Acme/repo/commits/{SHA}","/repos/Acme/repo/pulls/7"]
    assert not check(led)["new"]


@pytest.mark.parametrize("changed",[
    {"author":{"id":44}}, {"committer":{"id":44}},
    {"commit":{"verification":{"verified":False,"reason":"unsigned"}}},
    {"commit":{"verification":{"verified":True,"reason":"unsigned"}}},
    {"sha":"f"*40}, {"author":None},{"committer":None},
])
def test_modified_commit_metadata_denied(prepared,changed):
    reader = Commits()
    reader.data.update(changed)
    led,_=source(prepared,reader)
    with pytest.raises(ValueError,match="unverified|mismatch"):
        check(led)
    assert led.get("impl") is None


@pytest.mark.parametrize("change", ["fork","head","closed","base","repo"])
def test_moved_or_forked_head_or_repository_denied(prepared,change):
    reader = Commits()
    if change == "fork":
        reader.pr["head"]["repo"]["id"]=138
    elif change == "head":
        reader.pr["head"]["sha"]="b"*40
    elif change == "closed":
        reader.pr["state"]="closed"
    elif change == "base":
        reader.pr["base"]["repo"]["id"]=138
    else:
        reader.repo["id"]=138
    led,_=source(prepared,reader)
    with pytest.raises(ValueError):
        check(led)
    assert led.get("impl") is None


@pytest.mark.parametrize("mutate",[
    "UPDATE orchestrator_worker_assignments SET state='released'",
    "UPDATE orchestrator_worker_assignments SET worker_id='wrong'",
    "UPDATE orchestrator_worker_assignments SET claim_version=claim_version+1",
    "UPDATE orchestrator_workers SET enabled=0",
    "UPDATE orchestrator_workers SET role='review'",
    "UPDATE orchestrator_workers SET project_id='other'",
    "UPDATE orchestrator_workers SET transport='chatgpt_ui'",
    "UPDATE orchestrator_workers SET session_key='stdio-singleton'",
    "UPDATE orchestrator_provider_review_observations SET digest='corrupt'",
    "UPDATE tasks SET claim_version=claim_version+1 WHERE task_id='impl'",
])
def test_worker_or_task_or_review_mutation_denied_before_github(prepared,mutate):
    led, reader = source(prepared)
    with prepared._connect() as db:
        db.execute(mutate)
    with pytest.raises(ValueError):
        check(led)
    assert not reader.calls and led.get("impl") is None


def test_different_controller_worker_policy_denied(prepared):
    led,reader=source(prepared,policy={"dev": 56})
    with pytest.raises(ValueError,match="trusted worker policy"):
        check(led)
    assert not reader.calls


def test_external_read_race_with_worker_reassignment_fails(prepared):
    def change():
        with prepared._connect() as d:
            d.execute("UPDATE orchestrator_worker_assignments SET claim_version=claim_version+1")
    led,_=source(prepared,Commits(mutation=change))
    with pytest.raises(ValueError):
        check(led)
    assert led.get("impl") is None


def test_external_read_race_with_review_digest_fails(prepared):
    def change():
        with prepared._connect() as d:
            d.execute("UPDATE orchestrator_provider_review_observations SET digest='changed'")
    led,_=source(prepared,Commits(mutation=change))
    with pytest.raises(ValueError):
        check(led)
    assert led.get("impl") is None


def test_concurrent_identical_observations_idempotent(prepared):
    led,_=source(prepared)
    with ThreadPoolExecutor(max_workers=8) as pool:
        res=list(pool.map(lambda _:check(led),range(16)))
    assert sum(r["new"] for r in res)==1
    assert len({r["digest"] for r in res})==1
    assert [e["kind"] for e in prepared.events("impl")].count("implementer.provider_observed")==1


def test_incomplete_or_mismatched_config_denied(prepared):
    with pytest.raises(ValueError,match="trusted worker"):
        source(prepared,policy={"dev":0})
    bad=GitHubSignedCommitReader(owner="Acme",repo="repo",repository_id=138,reader=Commits())
    from test_orchestrator_task_review_evidence import create
    review=create(prepared)[0]
    with pytest.raises(ValueError,match="matching"):
        ImplementerProvenanceLedger(prepared,review,bad,trusted_worker_user_ids={"dev":55})


def test_reserved_assignment_version_can_precede_delivery_transitions(prepared):
    # Real Scheduler captures claim_version at reservation, whereas later
    # outbox transitions increase the task version without replacing assignment.
    with prepared._connect() as db:
        row=db.execute("SELECT claim_version FROM tasks WHERE task_id='impl'").fetchone()
        assert row[0] > 1
        db.execute("UPDATE orchestrator_worker_assignments SET claim_version=1")
    led,_=source(prepared)
    assert check(led)["new"]


@pytest.mark.parametrize("bad_version",[0,99999])
def test_assignment_version_cannot_be_zero_or_in_the_future(prepared,bad_version):
    with prepared._connect() as db:
        db.execute("UPDATE orchestrator_worker_assignments SET claim_version=?",(bad_version,))
    led,reader=source(prepared)
    with pytest.raises(ValueError):
        check(led)
    assert reader.calls==[]
