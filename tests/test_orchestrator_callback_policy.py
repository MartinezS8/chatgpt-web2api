from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from chatgpt_web2api.orchestrator.callback_policy import Callback, CallbackPolicy
from chatgpt_web2api.orchestrator.store import Store, TaskSpec


class FakeCorrelatedOutbox:
    def __init__(self, store):
        self.store = store
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE orchestrator_dispatch_attempts (
                    attempt_id TEXT PRIMARY KEY,task_id TEXT,status TEXT,
                    conversation_id TEXT,delivery_id TEXT,result_ref TEXT);
                CREATE TABLE orchestrator_delivery_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT UNIQUE,task_id TEXT,attempt_id TEXT,
                    kind TEXT,payload TEXT,at REAL);
            """)
            db.execute("INSERT INTO orchestrator_dispatch_attempts VALUES ('attempt','task','accepted','conv','user-msg',NULL)")

    def get(self, attempt_id):
        with self.store._connect() as db:
            r = db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            return dict(r) if r else None

    def complete(self, attempt_id, conversation_id, delivery_id, result_ref):
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            r = db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if (r["conversation_id"], r["delivery_id"]) != (conversation_id, delivery_id):
                raise ValueError("identity mismatch")
            if r["status"] == "completed":
                if r["result_ref"] != result_ref:
                    raise ValueError("conflicting result ref")
                return False
            db.execute("UPDATE orchestrator_dispatch_attempts SET status='completed',result_ref=? WHERE attempt_id=?", (result_ref, attempt_id))
            db.execute("INSERT INTO orchestrator_delivery_events(event_key,task_id,attempt_id,kind,payload,at) VALUES(?,?,?,?,?,0)",
                       (attempt_id + '/completed','task',attempt_id,'turn.completed','{}'))
            return True


def test_mock_progress_identity_idempotence_and_authoritative_completion():
    with tempfile.TemporaryDirectory() as root:
        store = Store(Path(root) / 'controller.db')
        store.create(TaskSpec('task', 'project', 'implement', 'task'))
        outbox = FakeCorrelatedOutbox(store)
        cb = CallbackPolicy(store, outbox)
        one = Callback('event-1', 'attempt', 'conv', 'user-msg', 1, 'progress')
        assert cb.ingest(one, source='mock')
        assert not cb.ingest(one, source='mock')
        with pytest.raises(ValueError):
            cb.ingest(Callback('event-1', 'attempt', 'conv', 'user-msg', 2, 'progress'), source='mock')
        with pytest.raises(ValueError):
            cb.ingest(Callback('event-2', 'attempt', 'wrong', 'user-msg', 2, 'progress'), source='mock')
        with pytest.raises(PermissionError):
            cb.ingest(one, source='chatgpt_ui')
        with pytest.raises(ValueError):
            cb.ingest(Callback('old', 'attempt', 'conv', 'user-msg', 0, 'progress'), source='mock')
        with pytest.raises(ValueError):
            cb.ingest(Callback('invalid', 'attempt', 'conv', 'user-msg', 2, 'progress', 'pretend-result'), source='mock')
        with store._connect() as db:
            kinds = [x[0] for x in db.execute('SELECT kind FROM orchestrator_delivery_events ORDER BY id')]
            assert kinds == ['turn.progress']
        terminal = Callback('event-3', 'attempt', 'conv', 'user-msg', 2, 'completed', 'git-ref')
        assert cb.ingest(terminal, source='mock')
        assert not cb.ingest(terminal, source='mock')
        with pytest.raises(ValueError):
            cb.ingest(Callback('event-4', 'attempt', 'conv', 'user-msg', 3, 'completed', 'other-ref'), source='mock')
        with pytest.raises(ValueError):
            cb.ingest(Callback('event-5', 'attempt', 'conv', 'user-msg', 4, 'progress'), source='mock')
        with store._connect() as db:
            kinds = [x[0] for x in db.execute('SELECT kind FROM orchestrator_delivery_events ORDER BY id')]
            assert kinds == ['turn.progress', 'turn.completed']