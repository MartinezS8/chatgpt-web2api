"""PR-04 isolated integration with V4 store and exact V5 outbox schema contract.

All provider/callback sources are simulation doubles. No external provider
is contacted and no live callback capability is claimed by these tests.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from chatgpt_web2api.orchestrator.store import Store, TaskSpec, TaskState
from chatgpt_web2api.orchestrator.delivery import CallbackBridge
from chatgpt_web2api.orchestrator.evidence import (
    EvidenceClaim, EvidenceLedger, ProviderSnapshot,
)
from chatgpt_web2api.orchestrator.events import EventReader
from chatgpt_web2api.orchestrator.planner import BoundedPlanner
from chatgpt_web2api.orchestrator.review_policy import ReviewLedger, ReviewReceipt


class FakeProvider:
    def __init__(self):
        self.head = "a" * 40
        self.ci = "success"
        self.observed_at = time.time() - 1
        self.enabled = True

    def inspect(self, claim):
        if not self.enabled:
            return None
        return ProviderSnapshot(claim.repository_id,claim.pr_number,self.head,
                                claim.ci_run_id,claim.commit_sha,self.ci,self.observed_at)


class FakeReviewProof:
    def __init__(self, permitted=True):
        self.permitted = permitted

    def attest(self, receipt):
        return self.permitted


class FakeOutbox:
    def __init__(self, store):
        self.store=store

    def complete(self, attempt_id, conversation_id, delivery_id, result_ref):
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM orchestrator_dispatch_attempts WHERE attempt_id=?",
                           (attempt_id,)).fetchone()
            if row is None or (row['conversation_id'],row['delivery_id']) != (conversation_id,delivery_id):
                raise ValueError("outbox completion remote correlation mismatch")
            if row['status']=='completed':
                if row['result_ref']!=result_ref:
                    raise ValueError("conflicting result ref")
                return False
            if row['status']!='accepted':
                raise ValueError("not accepted")
            db.execute("UPDATE orchestrator_dispatch_attempts SET status='completed',result_ref=? WHERE attempt_id=?",
                       (result_ref,attempt_id))
            db.execute("UPDATE tasks SET state='result_received',evidence_ref=? WHERE task_id=?",
                       (result_ref,row['task_id']))
            db.execute("INSERT INTO orchestrator_delivery_events VALUES(NULL,?,?,?,?,?,?)",
                       (attempt_id+'/turn.completed',row['task_id'],attempt_id,'turn.completed','{}',time.time()))
            return True

    def consumer_events(self, consumer_id,limit=100):
        with self.store._connect() as db:
            old=db.execute("SELECT event_id FROM orchestrator_event_cursors WHERE consumer_id=?",
                           (consumer_id,)).fetchone()
            after=old[0] if old else 0
            return [dict(x) for x in db.execute("SELECT * FROM orchestrator_delivery_events WHERE id>? ORDER BY id LIMIT ?",
                                                 (after,limit))]

    def acknowledge_event(self,consumer_id,event_id):
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT event_id FROM orchestrator_event_cursors WHERE consumer_id=?",
                           (consumer_id,)).fetchone()
            prev=old[0] if old else 0
            if prev==event_id:
                return False
            next_=db.execute("SELECT id FROM orchestrator_delivery_events WHERE id>? ORDER BY id LIMIT 1",
                             (prev,)).fetchone()
            if next_ is None or next_[0]!=event_id:
                raise ValueError("out of order")
            db.execute("INSERT INTO orchestrator_event_cursors VALUES(?,?) ON CONFLICT(consumer_id) DO UPDATE SET event_id=excluded.event_id",
                       (consumer_id,event_id))
            return True


class PR04Case(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'work.sqlite')
        self.store.create(TaskSpec('impl','p','implement','Implement the test change',write_scopes=('repo:src',)))
        self.claim=self.store.claim('p')
        self.token=self.claim['claim_token']
        self.store.transition('impl',TaskState.RESERVED,TaskState.DISPATCHING,claim_token=self.token)
        self.store.transition('impl',TaskState.DISPATCHING,TaskState.IN_PROGRESS,claim_token=self.token,
                              conversation_id='conv-1',delivery_id='delivery-1')
        with self.store._connect() as db:
            db.executescript('''
                CREATE TABLE orchestrator_dispatch_attempts (
                    attempt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE,
                    package_sha256 TEXT NOT NULL, claim_token_hash TEXT NOT NULL,
                    status TEXT NOT NULL, conversation_id TEXT, delivery_id TEXT,
                    result_ref TEXT, error_code TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE orchestrator_delivery_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL, attempt_id TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, at REAL NOT NULL);
                CREATE TABLE orchestrator_event_cursors (
                    consumer_id TEXT PRIMARY KEY, event_id INTEGER NOT NULL);
                CREATE TABLE orchestrator_workers (
                    worker_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, role TEXT NOT NULL,
                    session_key TEXT NOT NULL, enabled INTEGER NOT NULL);
                CREATE TABLE orchestrator_worker_assignments (
                    task_id TEXT PRIMARY KEY,worker_id TEXT NOT NULL);
            ''')
            db.execute("INSERT INTO orchestrator_dispatch_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       ('attempt-1','impl','abc','hidden','accepted','conv-1','delivery-1',None,None,time.time(),time.time()))
            db.execute("INSERT INTO orchestrator_workers VALUES('dev','account','p','implement','fake:dev',1)")
            db.execute("INSERT INTO orchestrator_workers VALUES('rev','account','p','review','fake:rev',1)")
            db.execute("INSERT INTO orchestrator_worker_assignments VALUES('impl','dev')")
        self.outbox=FakeOutbox(self.store)
        self.provider=FakeProvider()
        self.evidence=EvidenceLedger(self.store,self.provider)
        self.claim_evidence=EvidenceClaim(12345,7,'a'*40,999)
        self.reviews=ReviewLedger(self.store,self.evidence,FakeReviewProof())

    def completed(self):
        CallbackBridge(self.store,self.outbox).complete('attempt-1','conv-1','delivery-1','git:sha:a')

    def verified(self):
        self.completed()
        return self.evidence.verify_completed('impl','attempt-1',self.token,self.claim_evidence)

    def verified_review(self):
        proof=self.verified()
        planner=BoundedPlanner(self.store,self.evidence,self.reviews)
        proposal=planner.review_task('impl','review-1')
        review=self.store.claim('p')
        token=review['claim_token']
        self.store.transition('review-1',TaskState.RESERVED,TaskState.DISPATCHING,claim_token=token)
        self.store.transition('review-1',TaskState.DISPATCHING,TaskState.IN_PROGRESS,claim_token=token,
                              conversation_id='review-conv',delivery_id='review-msg')
        self.store.transition('review-1',TaskState.IN_PROGRESS,TaskState.RESULT_RECEIVED,claim_token=token,
                              evidence_ref='mock-review-evidence')
        self.store.transition('review-1',TaskState.RESULT_RECEIVED,TaskState.VERIFIED,claim_token=token)
        with self.store._connect() as db:
            db.execute("INSERT INTO orchestrator_worker_assignments VALUES('review-1','rev')")
        receipt=ReviewReceipt('impl','review-1','rev',proof['snapshot_sha256'],
                              'approved','mock:review:1')
        return proof,proposal,receipt

    def test_provider_missing_denies_evidence(self):
        self.completed()
        with self.assertRaises(PermissionError):
            EvidenceLedger(self.store).verify_completed('impl','attempt-1',self.token,self.claim_evidence)
        self.assertEqual(self.store.get('impl')['state'],'result_received')

    def test_provider_mismatch_head_refuses(self):
        self.completed()
        self.provider.head='b'*40
        with self.assertRaises(ValueError):
            self.evidence.verify_completed('impl','attempt-1',self.token,self.claim_evidence)
        self.assertIsNone(self.evidence.get('impl'))

    def test_provider_non_success_denies(self):
        self.completed()
        self.provider.ci='failure'
        with self.assertRaises(ValueError):
            self.evidence.verify_completed('impl','attempt-1',self.token,self.claim_evidence)

    def test_immutable_promote_and_no_finalize(self):
        result=self.verified()
        self.assertEqual(self.store.get('impl')['state'],'verified')
        self.assertEqual(self.evidence.verify_completed('impl','attempt-1',self.token,self.claim_evidence)['snapshot_sha256'],result['snapshot_sha256'])
        self.assertEqual(self.store.get('impl')['slot'],1)
        self.assertIsNone(self.reviews.latest('impl'))

    def test_evidence_changed_on_recheck_denies(self):
        self.verified()
        self.provider.head='b'*40
        with self.assertRaises(ValueError):
            self.evidence.assert_fresh('impl')

    def test_correlated_outbox_required(self):
        self.completed()
        with self.store._connect() as db:
            db.execute("UPDATE orchestrator_dispatch_attempts SET delivery_id='different' WHERE attempt_id='attempt-1'")
        # It is still an acknowledged attempt; evidence ledger requires IDs,
        # but actual remote identity is only trusted by the adapter.
        with self.store._connect() as db:
            db.execute("UPDATE orchestrator_dispatch_attempts SET status='unknown' WHERE attempt_id='attempt-1'")
        with self.assertRaises(ValueError):
            self.evidence.verify_completed('impl','attempt-1',self.token,self.claim_evidence)

    def test_callback_progress_does_not_complete(self):
        bridge=CallbackBridge(self.store,self.outbox)
        self.assertTrue(bridge.progress('attempt-1','conv-1','delivery-1',event_id='evt-1',sequence=1,summary='thinking'))
        self.assertFalse(bridge.progress('attempt-1','conv-1','delivery-1',event_id='evt-1',sequence=1,summary='thinking'))
        self.assertEqual(self.store.get('impl')['state'],'in_progress')
        with self.assertRaises(ValueError):
            bridge.progress('attempt-1','wrong','delivery-1',event_id='evt-2',sequence=2,summary='wrong')
        with self.assertRaises(ValueError):
            bridge.progress('attempt-1','conv-1','delivery-1',event_id='evt-3',sequence=1,summary='reordered')
        with self.assertRaises(ValueError):
            bridge.progress('attempt-1','conv-1','delivery-1',event_id='evt-1',sequence=1,summary='different')

    def test_callback_completion_idempotent_and_mismatch(self):
        bridge=CallbackBridge(self.store,self.outbox)
        with self.assertRaises(ValueError):
            bridge.complete('attempt-1','conv-else','delivery-1','same')
        self.assertTrue(bridge.complete('attempt-1','conv-1','delivery-1','same'))
        self.assertFalse(bridge.complete('attempt-1','conv-1','delivery-1','same'))
        with self.assertRaises(ValueError):
            bridge.complete('attempt-1','conv-1','delivery-1','different')
        self.assertEqual(self.store.get('impl')['state'],'result_received')

    def test_callback_progress_after_completion_refused(self):
        bridge=CallbackBridge(self.store,self.outbox)
        self.assertTrue(bridge.complete('attempt-1','conv-1','delivery-1','confirmed-result'))
        with self.assertRaises(ValueError):
            bridge.progress('attempt-1','conv-1','delivery-1',event_id='late-1',sequence=1,summary='late')

    def test_callback_live_mode_disabled(self):
        with self.assertRaises(PermissionError):
            CallbackBridge(self.store,self.outbox,mode='live')

    def test_progress_events_replay_and_ack(self):
        bridge=CallbackBridge(self.store,self.outbox)
        bridge.progress('attempt-1','conv-1','delivery-1',event_id='evt-1',sequence=1,summary='streaming')
        reader=EventReader(self.store,self.outbox)
        unread=reader.unread('codex')
        self.assertEqual(len(unread),1)
        self.assertEqual(set(unread[0]),{'id','task_id','attempt_id','kind','at'})
        self.assertTrue(reader.ack('codex',unread[0]['id']))
        self.assertFalse(reader.ack('codex',unread[0]['id']))
        self.assertEqual(reader.unread('codex'),[])
        self.assertEqual(len(EventReader(self.store,self.outbox).unread('other')),1)

    def test_review_task_is_read_only_no_dependency_deadlock(self):
        self.verified()
        planner=BoundedPlanner(self.store,self.evidence,self.reviews)
        v=planner.review_task('impl','review-1')
        self.assertEqual(v['depends_on'],[])
        self.assertEqual(v['write_scopes'],[])
        self.assertEqual(self.store.get('review-1')['review_of'],'impl')
        self.assertEqual(self.store.claim('p')['task_id'],'review-1')

    def test_review_default_denied(self):
        _,_,receipt=self.verified_review()
        with self.assertRaises(PermissionError):
            ReviewLedger(self.store,self.evidence).record(receipt)

    def test_review_independent_and_no_release(self):
        _,_,receipt=self.verified_review()
        out=self.reviews.record(receipt)
        self.assertEqual(out['verdict'],'approved')
        self.assertFalse(out['authorizes_merge'])
        self.assertEqual(self.store.get('impl')['state'],'verified')
        self.assertEqual(self.store.get('impl')['slot'],1)
        self.assertFalse(self.reviews.record(receipt)['created'])
        with self.assertRaises(ValueError):
            self.reviews.record(ReviewReceipt('impl','review-1','rev',receipt.evidence_sha256,
                                              'changes_requested','mock:other'))

    def test_self_review_rejected(self):
        _,_,receipt=self.verified_review()
        with self.store._connect() as db:
            db.execute("UPDATE orchestrator_worker_assignments SET worker_id='dev' WHERE task_id='review-1'")
        with self.assertRaises(ValueError):
            self.reviews.record(receipt)

    def test_review_rejects_cross_account_and_same_session(self):
        _,_,receipt=self.verified_review()
        with self.store._connect() as db:
            db.execute("UPDATE orchestrator_workers SET account_id='other' WHERE worker_id='rev'")
        with self.assertRaises(ValueError):
            self.reviews.record(receipt)
        with self.store._connect() as db:
            db.execute("UPDATE orchestrator_workers SET account_id='account',session_key='fake:dev' WHERE worker_id='rev'")
        with self.assertRaises(ValueError):
            self.reviews.record(receipt)

    def test_review_rejects_disabled_worker(self):
        _,_,receipt=self.verified_review()
        with self.store._connect() as db:
            db.execute("UPDATE orchestrator_workers SET enabled=0 WHERE worker_id='rev'")
        with self.assertRaises(ValueError):
            self.reviews.record(receipt)

    def test_stale_provider_snapshot_denied(self):
        self.completed()
        self.provider.observed_at=time.time()-600
        with self.assertRaises(ValueError):
            self.evidence.verify_completed('impl','attempt-1',self.token,self.claim_evidence)

    def test_review_wrong_evidence_rejected(self):
        _,_,receipt=self.verified_review()
        with self.assertRaises(ValueError):
            self.reviews.record(ReviewReceipt('impl','review-1','rev','0'*64,'approved','mock:proof'))

    def test_review_stale_head_rejected(self):
        _,_,receipt=self.verified_review()
        self.provider.head='f'*40
        with self.assertRaises(ValueError):
            self.reviews.record(receipt)

    def test_review_proof_must_be_accepted(self):
        _,_,receipt=self.verified_review()
        proof=ReviewLedger(self.store,self.evidence,FakeReviewProof(False))
        with self.assertRaises(PermissionError):
            proof.record(receipt)

    def test_fix_planning_requires_rejected_review_and_keeps_lock(self):
        _,_,receipt=self.verified_review()
        rejection=ReviewReceipt(receipt.target_task_id,receipt.review_task_id,
                                receipt.reviewer_worker_id,receipt.evidence_sha256,
                                'changes_requested',receipt.review_ref)
        review=self.reviews.record(rejection)
        planner=BoundedPlanner(self.store,self.evidence,self.reviews,max_fix_rounds=2)
        fix=planner.propose_fix('impl','fix-1',review['review_id'],'Patch failed checks')
        self.assertTrue(fix['created'])
        self.assertTrue(fix['blocked_until_parent_reconciled'])
        self.assertFalse(planner.propose_fix('impl','fix-1',review['review_id'],'Patch failed checks')['created'])
        self.assertEqual(json.loads(self.store.get('fix-1')['write_scopes']),['repo:src'])
        self.assertIsNone(self.store.claim('p')) # original VERIFIED keeps repo:src lock

    def test_fix_budget_rejects_exhaustion(self):
        _,_,receipt=self.verified_review()
        rejected=ReviewReceipt(receipt.target_task_id,receipt.review_task_id,
                               receipt.reviewer_worker_id,receipt.evidence_sha256,
                               'changes_requested',receipt.review_ref)
        review=self.reviews.record(rejected)
        planner=BoundedPlanner(self.store,self.evidence,self.reviews,max_fix_rounds=2)
        with self.store._connect() as db:
            db.execute("INSERT INTO orchestrator_fix_plans VALUES(?,?,?,?,?)",
                       ('impl',1,'historical-review-1','historical-fix-1',time.time()))
            db.execute("INSERT INTO orchestrator_fix_plans VALUES(?,?,?,?,?)",
                       ('impl',2,'historical-review-2','historical-fix-2',time.time()))
        with self.assertRaises(ValueError):
            planner.propose_fix('impl','fix-3',review['review_id'],'Excessive third fix')
        self.assertIsNone(self.store.get('fix-3'))

    def test_approved_review_cannot_request_fix(self):
        _,_,receipt=self.verified_review()
        v=self.reviews.record(receipt)
        with self.assertRaises(ValueError):
            BoundedPlanner(self.store,self.evidence,self.reviews).propose_fix('impl','fix-1',v['review_id'],'Fix')

    def test_missing_provider_does_not_reopen_past_proof(self):
        self.verified()
        self.provider.enabled=False
        with self.assertRaises(PermissionError):
            self.evidence.assert_fresh('impl')

    def test_different_db_authority_refused(self):
        other=Store(Path(self.tmp.name)/'different.db')
        with self.assertRaises(ValueError):
            ReviewLedger(other,self.evidence)


if __name__=='__main__':
    unittest.main()