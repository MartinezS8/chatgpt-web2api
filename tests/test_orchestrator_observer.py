from __future__ import annotations

import sqlite3

import pytest

from chatgpt_web2api.orchestrator.mcp_control import dispatch_observer
from chatgpt_web2api.orchestrator.observer import Observer
from chatgpt_web2api.orchestrator.store import Store, TaskSpec


@pytest.fixture
def db(tmp_path):
    path=tmp_path/"store.sqlite"
    s=Store(path)
    s.create(TaskSpec("task-1", "p", "implement", "secret prompt text"))
    with s._connect() as x:
        x.executescript("""CREATE TABLE orchestrator_delivery_events (id INTEGER PRIMARY KEY,task_id TEXT,attempt_id TEXT,kind TEXT,at REAL);
           CREATE TABLE orchestrator_callback_inbox(id INTEGER PRIMARY KEY,attempt_id TEXT,worker_id TEXT,sequence INTEGER,kind TEXT,created_at REAL);
           CREATE TABLE orchestrator_workers(worker_id TEXT,account_id TEXT,project_id TEXT,role TEXT,transport TEXT,enabled INTEGER,last_heartbeat REAL,session_key TEXT);
           CREATE TABLE orchestrator_evidence(task_id TEXT,repository_id TEXT,pr_number INTEGER,head_sha TEXT,run_id INTEGER,digest TEXT,assurance TEXT,recorded_at REAL);
           CREATE TABLE orchestrator_review_decisions(target_task_id TEXT,reviewer_task_id TEXT,head_sha TEXT,decision TEXT,assurance TEXT,created_at REAL);
           CREATE TABLE orchestrator_fix_proposals(id INTEGER, target_task_id TEXT,reviewer_task_id TEXT,cycle INTEGER,head_sha TEXT,status TEXT,created_at REAL);
        """)
        x.execute("INSERT INTO orchestrator_delivery_events VALUES(1,'task-1','a','delivery.accepted',123)")
        x.execute("INSERT INTO orchestrator_callback_inbox VALUES(1,'a','w1',1,'progress',124)")
        x.execute("INSERT INTO orchestrator_workers VALUES('w1','acc','p','implement','mock',1,123,'fake:secret')")
        x.execute("INSERT INTO orchestrator_evidence VALUES('task-1','123',1,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',2,'digest','offline_mock_only',125)")
        x.execute("INSERT INTO orchestrator_review_decisions VALUES('task-1','r1','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','approved','offline_mock_only',125)")
        x.execute("INSERT INTO orchestrator_fix_proposals VALUES(1,'task-1','r1',1,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','proposed',125)")
    return path


def test_status_and_worker_view_no_secrets(db):
    o=Observer(db)
    assert o.status('p')['states']=={'queued':1}
    workers=o.workers('acc')['workers']
    assert len(workers)==1
    assert 'session_key' not in workers[0]
    assert 'secret prompt text' not in str(o.status('p'))


def test_event_cursors_and_reopen(db):
    o=Observer(db)
    assert o.events()['events'][0]['kind']=='delivery.accepted'
    assert o.events(after=1)['events']==[]
    assert Observer(db).callbacks()['callbacks'][0]['sequence']==1


def test_evidence_and_review_telemetry_never_grant_approval(db):
    o=Observer(db)
    assert o.evidence('task-1')['evidence']['assurance']=='offline_mock_only'
    assert o.reviews('task-1')['reviews'][0]['decision']=='approved'
    assert o.proposals('task-1')['proposals'][0]['status']=='proposed'
    assert o.capabilities()['user_approval_actions'] is False


def test_mcp_whitelist_has_no_mutating_tool(db):
    o=Observer(db)
    assert dispatch_observer(o,'orchestrator_status',{'project_id':'p'})['tasks']==1
    for name in ('orchestrator_approve','orchestrator_submit','chat_completion'):
        with pytest.raises(ValueError,match='forbidden'):
            dispatch_observer(o,name,{})
    with pytest.raises(ValueError,match='unsupported tool arguments'):
        dispatch_observer(o,'orchestrator_status',{'project_id':'p','claim_token':'leak'})


def test_missing_database_cannot_be_created_by_read_only_observer(tmp_path):
    p=tmp_path/'missing.sqlite'
    with pytest.raises(FileNotFoundError):Observer(p)
    assert not p.exists()



def test_read_only_connections_are_closed_after_each_query(db, monkeypatch):
    closed = []
    original_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            closed.append(True)
            return super().close()

    def tracked_connect(*args, **kwargs):
        return original_connect(*args, factory=TrackedConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    observer = Observer(db)
    assert observer.status("p")["tasks"] == 1
    assert observer.events()["events"]
    assert len(closed) == 2


def test_invalid_pagination(db):
    o=Observer(db)
    with pytest.raises(ValueError):o.events(after=-1)
    with pytest.raises(ValueError):o.callbacks(limit=9999)
    with pytest.raises(ValueError):o.workers('acc',limit=100)

