from __future__ import annotations

import pytest

from chatgpt_web2api.orchestrator.callback_inbox import CallbackInbox
from chatgpt_web2api.orchestrator.evidence import EvidenceLedger
from chatgpt_web2api.orchestrator.planner import Planner
from chatgpt_web2api.orchestrator.review_policy import ReviewLedger
from chatgpt_web2api.orchestrator.store import Store, TaskSpec

SHA = "a" * 40

class FakeProbe:
    def __init__(self, head=SHA, conclusion="success", repository_id="123", status="completed"):
        self.head, self.conclusion, self.repo, self.status = head, conclusion, repository_id, status
    def inspect_pr(self, repository_id, pr_number):
        return {"repository_id": self.repo, "number": pr_number, "head_sha": self.head, "state": "open"}
    def inspect_run(self, repository_id, run_id):
        return {"repository_id": self.repo, "id": run_id, "head_sha": self.head,
                "status": self.status, "conclusion": self.conclusion}

class MockOutbox:
    def __init__(self, store):
        self.store = store
        with store._connect() as db:
            db.execute("""CREATE TABLE orchestrator_dispatch_attempts(
                 attempt_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,status TEXT NOT NULL,
                 conversation_id TEXT NOT NULL,delivery_id TEXT NOT NULL)""")
    def complete(self, attempt_id, conversation_id, delivery_id, result_ref):
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if not row or row["conversation_id"]!=conversation_id or row["delivery_id"]!=delivery_id:
                raise ValueError("invalid delivery")
            if row["status"] == "completed":return False
            db.execute("UPDATE orchestrator_dispatch_attempts SET status='completed' WHERE attempt_id=?", (attempt_id,))
            return True

@pytest.fixture
def db(tmp_path):
    store=Store(tmp_path/"scheduler.sqlite")
    store.create(TaskSpec("build", "p", "implement", "do work",
                          write_scopes=("github:repo/123",)))
    store.create(TaskSpec("review-1", "p", "review", "review work", review_of="build"))
    with store._connect() as d:
        d.executescript("""CREATE TABLE orchestrator_workers(
                worker_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                project_id TEXT NOT NULL, session_key TEXT NOT NULL,
                role TEXT NOT NULL, transport TEXT NOT NULL,
                enabled INTEGER NOT NULL);
           CREATE TABLE orchestrator_worker_assignments(task_id TEXT,worker_id TEXT,state TEXT);
        """)
        d.execute("INSERT INTO orchestrator_workers VALUES ('dev','personal','p','fake:dev','implement','mock',1)")
        d.execute("INSERT INTO orchestrator_workers VALUES ('qa','personal','p','fake:qa','review','mock',1)")
        d.execute("INSERT INTO orchestrator_worker_assignments VALUES ('build','dev','active')")
        d.execute("INSERT INTO orchestrator_worker_assignments VALUES ('review-1','qa','active')")
        d.execute("UPDATE tasks SET state='verified',evidence_ref='mock-ref' WHERE task_id IN ('build','review-1')")
    return store

@pytest.fixture
def evid(db):
    return EvidenceLedger(db)


def test_evidence_exact_head_and_ci_success(db,evid):
    obj=evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,expected_head_sha=SHA,run_id=999,probe=FakeProbe())
    assert obj["new"]
    assert not evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,expected_head_sha=SHA,run_id=999,probe=FakeProbe())["new"]
    assert evid.get("build")["head_sha"]==SHA
    assert not evid.is_production_proof("build")

@pytest.mark.parametrize("probe,expect", [(FakeProbe(head="b"*40),"PR head"),(FakeProbe(conclusion="failure"),"CI"),(FakeProbe(repository_id="9"),"PR head")])
def test_stale_pr_and_ci_denied(db,evid,probe,expect):
    with pytest.raises(ValueError,match=expect):
        evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,expected_head_sha=SHA,run_id=1,probe=probe)


def test_evidence_sealed_and_cannot_shift_sha(db,evid):
    evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,expected_head_sha=SHA,run_id=1,probe=FakeProbe())
    with pytest.raises(ValueError, match="sealed"):
        evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,expected_head_sha=SHA,run_id=2,probe=FakeProbe())


def test_mock_independent_review_and_bounded_proposal(db,evid):
    evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,expected_head_sha=SHA,run_id=1,probe=FakeProbe())
    reviews=ReviewLedger(db)
    approved=reviews.record_mock(target_task_id="build",reviewer_task_id="review-1",head_sha=SHA,decision="changes_requested")
    assert approved["new"]
    assert not reviews.record_mock(target_task_id="build",reviewer_task_id="review-1",head_sha=SHA,decision="changes_requested")["new"]
    assert not reviews.production_approval_granted("build")
    with pytest.raises(ValueError,match="sealed"):
        reviews.record_mock(target_task_id="build",reviewer_task_id="review-1",head_sha=SHA,decision="approved")
    planner=Planner(db)
    assert planner.propose_mock_fix(target_task_id="build",reviewer_task_id="review-1",head_sha=SHA,proposed_prompt="patch this")["created"]
    assert not planner.propose_mock_fix(target_task_id="build",reviewer_task_id="review-1",head_sha=SHA,proposed_prompt="patch this")["created"]
    assert planner.list("build")[0]["cycle"]==1


def test_self_review_or_shared_worker_denied(db,evid):
    evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,expected_head_sha=SHA,run_id=1,probe=FakeProbe())
    reviews=ReviewLedger(db)
    with db._connect() as d:
        d.execute("UPDATE orchestrator_worker_assignments SET worker_id='dev' WHERE task_id='review-1'")
    with pytest.raises(ValueError,match="different live worker"):
        reviews.record_mock(target_task_id="build",reviewer_task_id="review-1",head_sha=SHA,decision="approved")


def test_review_wrong_head_and_unverified_review_denied(db,evid):
    evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,expected_head_sha=SHA,run_id=1,probe=FakeProbe())
    ledger=ReviewLedger(db)
    with pytest.raises(ValueError,match="head"):
        ledger.record_mock(target_task_id="build",reviewer_task_id="review-1",head_sha="b"*40,decision="approved")
    with db._connect() as d:
        d.execute("UPDATE tasks SET state='result_received' WHERE task_id='review-1'")
    with pytest.raises(ValueError,match="verified"):
        ledger.record_mock(target_task_id="build",reviewer_task_id="review-1",head_sha=SHA,decision="approved")


def test_callbacks_deduplicate_replay_and_restore(db):
    outbox=MockOutbox(db)
    with db._connect() as d:
        d.execute("INSERT INTO orchestrator_dispatch_attempts VALUES('attempt-1','build','accepted','conv-1','msg-1')")
    box=CallbackInbox(db,outbox)
    kwargs=dict(attempt_id="attempt-1",worker_id="dev",conversation_id="conv-1",delivery_id="msg-1")
    assert box.progress(**kwargs, sequence=1,kind="progress",message="started")
    assert not box.progress(**kwargs, sequence=1,kind="progress",message="started")
    assert box.progress(**kwargs, sequence=4,kind="heartbeat",message="alive")
    with pytest.raises(ValueError,match="conflicting"):
        box.progress(**kwargs,sequence=1,kind="progress",message="changed")
    with pytest.raises(ValueError,match="out-of-order"):
        box.progress(**kwargs,sequence=2,kind="progress",message="different")
    with pytest.raises(ValueError,match="invalid advisory"):
        box.progress(**kwargs,sequence=0,kind="heartbeat",message="late")
    assert len(CallbackInbox(db,outbox).events())==2
    assert box.complete_mock(**kwargs,result_ref="offline-hash")
    assert not box.complete_mock(**kwargs,result_ref="offline-hash")
    with pytest.raises(ValueError, match="mock-only worker binding"):
        box.progress(**kwargs,sequence=5,kind="progress",message="late")
    assert len(box.events())==2


def test_callbacks_mismatched_worker_and_conversation_denied(db):
    outbox=MockOutbox(db)
    with db._connect() as d:
        d.execute("INSERT INTO orchestrator_dispatch_attempts VALUES('attempt-1','build','accepted','conv-1','msg-1')")
    box=CallbackInbox(db,outbox)
    for worker,conv in [("qa","conv-1"),("dev","conv-2")]:
        with pytest.raises(ValueError, match="mock-only worker binding"):
            box.progress(attempt_id="attempt-1",worker_id=worker,conversation_id=conv,
                     delivery_id="msg-1",sequence=1,kind="progress",message="test")


def test_planner_cannot_propose_without_rejected_review(db,evid):
    evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,expected_head_sha=SHA,run_id=1,probe=FakeProbe())
    ReviewLedger(db)
    with pytest.raises(ValueError,match="requires sealed"):
        Planner(db).propose_mock_fix(target_task_id="build",reviewer_task_id="review-1",head_sha=SHA,proposed_prompt="fix")


@pytest.mark.parametrize("disabled_worker", ("qa", "dev"))
def test_disabled_reviewer_or_implementer_fails_closed(db, evid, disabled_worker):
    evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,
                      expected_head_sha=SHA,run_id=1,probe=FakeProbe())
    ledger = ReviewLedger(db)
    with db._connect() as d:
        d.execute("UPDATE orchestrator_workers SET enabled=0 WHERE worker_id=?",
                  (disabled_worker,))
    with pytest.raises(ValueError, match="enabled mock review worker"):
        ledger.record_mock(target_task_id="build",reviewer_task_id="review-1",
                           head_sha=SHA,decision="approved")
    assert ledger.get("build", "review-1") is None

def test_reviewer_must_share_project_account_but_not_session(db,evid):
    evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,
                      expected_head_sha=SHA,run_id=1,probe=FakeProbe())
    ledger=ReviewLedger(db)
    for column,value in (("account_id","other"),("project_id","elsewhere"),
                         ("session_key","fake:dev")):
        with db._connect() as d:
            d.execute(f"UPDATE orchestrator_workers SET {column}=? WHERE worker_id='qa'",(value,))
        with pytest.raises(ValueError,match="identity, account, project or session"):
            ledger.record_mock(target_task_id="build",reviewer_task_id="review-1",
                               head_sha=SHA,decision="approved")
        with db._connect() as d:
            d.execute(f"UPDATE orchestrator_workers SET {column}=? WHERE worker_id='qa'",
                      ({"account_id":"personal","project_id":"p","session_key":"fake:qa"}[column],))


def test_reviewer_rejects_disabled_or_cross_project_implementer(db,evid):
    evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,
                      expected_head_sha=SHA,run_id=1,probe=FakeProbe())
    ledger=ReviewLedger(db)
    with db._connect() as d:
        d.execute("UPDATE orchestrator_workers SET enabled=0 WHERE worker_id='dev'")
    with pytest.raises(ValueError,match="identity, account, project or session"):
        ledger.record_mock(target_task_id="build",reviewer_task_id="review-1",
                           head_sha=SHA,decision="approved")
    with db._connect() as d:
        d.execute("UPDATE orchestrator_workers SET enabled=1 WHERE worker_id='dev'")
        d.execute("UPDATE tasks SET project_id='another' WHERE task_id='review-1'")
    with pytest.raises(ValueError,match="same project"):
        ledger.record_mock(target_task_id="build",reviewer_task_id="review-1",
                           head_sha=SHA,decision="approved")


def test_callback_inbox_survives_database_reopen(db):
    outbox=MockOutbox(db)
    with db._connect() as d:
        d.execute("INSERT INTO orchestrator_dispatch_attempts VALUES('attempt-1','build','accepted','conv-1','msg-1')")
    box=CallbackInbox(db,outbox)
    box.progress(attempt_id="attempt-1",worker_id="dev",conversation_id="conv-1",delivery_id="msg-1",sequence=1,kind="progress",message="working")
    store2=Store(db.path)
    assert CallbackInbox(store2,MockOutboxExisting(store2)).events()[0]["sequence"]==1

class MockOutboxExisting:
    def __init__(self, store): self.store=store
    def complete(self, *args): raise AssertionError("unused")

def test_other_repository_proof_cannot_substitute(db, evid):
    with db._connect() as d:
        d.execute("UPDATE tasks SET write_scopes=? WHERE task_id='build'",
                  ('["github:repo/777"]',))
    with pytest.raises(ValueError, match="not in declared task scope"):
        evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,
                          expected_head_sha=SHA,run_id=2,probe=FakeProbe())


def test_ci_run_must_be_completed_not_just_success_label(db, evid):
    with pytest.raises(ValueError, match="CI"):
        evid.inspect_mock(task_id="build",repository_id="123",pr_number=4,
                          expected_head_sha=SHA,run_id=2,probe=FakeProbe(status="in_progress"))


def test_callback_progress_never_persists_raw_message(db):
    outbox=MockOutbox(db)
    with db._connect() as d:
        d.execute("INSERT INTO orchestrator_dispatch_attempts VALUES ('a1','build','accepted','c1','m1')")
    callback=CallbackInbox(db,outbox)
    secret="never-store-sensitive-text-123"
    assert callback.progress(attempt_id="a1",worker_id="dev",conversation_id="c1",
                             delivery_id="m1",sequence=1,kind="progress",message=secret)
    assert callback.events()[0]["message"]=="[redacted]"
    with db._connect() as d:
        row=d.execute("SELECT message FROM orchestrator_callback_inbox WHERE attempt_id='a1'").fetchone()
        assert row["message"]=="[redacted]"
