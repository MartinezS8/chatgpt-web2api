import concurrent.futures
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path

from chatgpt_web2api.orchestrator.outbox import DispatchOutbox
from chatgpt_web2api.orchestrator.store import Store, TaskSpec, TaskState
from chatgpt_web2api.orchestrator.task_packages import TaskPackages


def _begin_worker(parameters: tuple[str, str, str, str]) -> bool:
    database, blob_root, task_id, token = parameters
    store = Store(database)
    packages = TaskPackages(store, blob_root)
    return DispatchOutbox(store, packages).begin(task_id, token)["new_send_permit"]


class PackageAndOutboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/'db.sqlite')
        self.pack=TaskPackages(self.store,self.root/'blobs')
        self.outbox=DispatchOutbox(self.store,self.pack)
        self.store.create(TaskSpec('t1','p','implement','hello',write_scopes=('repo:src',)))
    def tearDown(self): self.tmp.cleanup()
    def claim(self):
        claim=self.store.claim('p')
        self.assertIsNotNone(claim)
        return claim

    def test_prompt_and_attachment_snapshots_survive_original_edit(self):
        source=self.root/'source.py'
        source.write_text('original')
        p=self.pack.seal('t1','hello',[source],allowed_root=self.root)
        source.write_text('modified')
        read=self.pack.read('t1')
        self.assertEqual(read['attachments'][0]['sha256'],p['attachments'][0]['sha256'])
        self.assertEqual(read['prompt'],'hello')
        with self.assertRaises(ValueError):
            self.pack.seal('t1','hello',[source],allowed_root=self.root)

    def test_prompt_not_saved_if_mismatch(self):
        with self.assertRaises(ValueError):
            self.pack.seal('t1','bad')
        with self.assertRaises(ValueError):
            self.pack.read('t1')

    def test_missing_or_mutated_blob_rejected(self):
        source=self.root/'source.py'
        source.write_text('original')
        p=self.pack.seal('t1','hello',[source],allowed_root=self.root)
        (self.root/'blobs'/p['attachments'][0]['sha256']).write_text('changed!')
        with self.assertRaises(ValueError):
            self.pack.read('t1')

    def test_disallow_file_escapes(self):
        source=self.root/'safe.py'
        source.write_text('ok')
        with self.assertRaises(ValueError):
            self.pack.seal('t1','hello',[source])
        with self.assertRaises(ValueError):
            self.pack.seal('t1','hello',[self.root/'missing.py'],allowed_root=self.root)
        symlink=self.root/'link.py'
        try:
            symlink.symlink_to(source)
        except (OSError,NotImplementedError):
            return
        with self.assertRaises(ValueError):
            self.pack.seal('t1','hello',[symlink],allowed_root=self.root)

    def test_outbox_intent_atomic_no_repeat_permit(self):
        self.pack.seal('t1','hello')
        claim=self.claim()
        created=self.outbox.begin('t1',claim['claim_token'])
        self.assertTrue(created['new_send_permit'])
        self.assertEqual(self.store.get('t1')['state'],TaskState.DISPATCHING.value)
        another=self.outbox.begin('t1',claim['claim_token'])
        self.assertEqual(created['attempt_id'],another['attempt_id'])
        self.assertFalse(another['new_send_permit'])
        self.assertEqual(len(self.outbox.events()),1)

    def test_crashed_intent_reconciles_unknown_never_resend(self):
        self.pack.seal('t1','hello')
        claim=self.claim()
        attempt=self.outbox.begin('t1',claim['claim_token'])['attempt_id']
        self.assertEqual(self.outbox.reconcile_stale(seconds=1,now=time.time()+2),1)
        self.assertEqual(self.outbox.get(attempt)['status'],'unknown')
        self.assertEqual(self.store.get('t1')['state'],TaskState.UNKNOWN_DELIVERY.value)
        self.assertIsNone(self.store.claim('p'))
        self.assertFalse(self.outbox.begin('t1',claim['claim_token'])['new_send_permit'])

    def test_accept_completion_correlates_remote_turn_and_is_idempotent(self):
        self.pack.seal('t1','hello')
        claim=self.claim()
        attempt=self.outbox.begin('t1',claim['claim_token'])['attempt_id']
        self.assertTrue(self.outbox.accept(attempt,claim['claim_token'],'conv1','user1'))
        self.assertFalse(self.outbox.accept(attempt,claim['claim_token'],'conv1','user1'))
        with self.assertRaises(ValueError):
            self.outbox.complete(attempt,'conv-wrong','user1','sha')
        self.assertTrue(self.outbox.complete(attempt,'conv1','user1','commitsha1'))
        self.assertFalse(self.outbox.complete(attempt,'conv1','user1','commitsha1'))
        with self.assertRaises(ValueError):
            self.outbox.complete(attempt,'conv1','user1','fake')
        self.assertEqual(self.store.get('t1')['state'],TaskState.RESULT_RECEIVED.value)
        self.assertEqual([x['kind'] for x in self.outbox.events()],['dispatch.intent','delivery.accepted','turn.completed'])

    def test_event_cursors_survive_restart_and_no_skip(self):
        self.pack.seal('t1','hello')
        claim=self.claim()
        attempt=self.outbox.begin('t1',claim['claim_token'])['attempt_id']
        self.outbox.accept(attempt,claim['claim_token'],'conv1','turn1')
        evs=self.outbox.consumer_events('codex')
        with self.assertRaises(ValueError):
            self.outbox.acknowledge_event('codex',evs[1]['id'])
        self.assertTrue(self.outbox.acknowledge_event('codex',evs[0]['id']))
        next_outbox=DispatchOutbox(self.store,self.pack)
        self.assertEqual(next_outbox.consumer_events('codex')[0]['id'],evs[1]['id'])
        self.assertFalse(next_outbox.acknowledge_event('codex',evs[0]['id']))

    def test_concurrent_begin_yields_exactly_one_send_permit(self):
        self.pack.seal("t1", "hello")
        claim = self.claim()
        args = (str(self.root / "db.sqlite"), str(self.root / "blobs"), "t1", claim["claim_token"])
        ctx = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(max_workers=3, mp_context=ctx) as pool:
            permits = list(pool.map(_begin_worker, [args] * 9))
        self.assertEqual(permits.count(True), 1)
        self.assertEqual(permits.count(False), 8)
        self.assertEqual(len(self.outbox.events()), 1)

    def test_wrong_claim_cannot_inspect_existing_attempt(self):
        self.pack.seal("t1", "hello")
        claim = self.claim()
        self.outbox.begin("t1", claim["claim_token"])
        with self.assertRaises(ValueError):
            self.outbox.begin("t1", "wrong-claim")

    def test_no_ack_without_fenced_claim(self):
        self.pack.seal('t1','hello')
        claim=self.claim()
        attempt=self.outbox.begin('t1',claim['claim_token'])['attempt_id']
        with self.assertRaises(ValueError):
            self.outbox.accept(attempt,'bad','conv','turn')
        self.assertEqual(self.outbox.get(attempt)['status'],'intent')

if __name__=='__main__':
    unittest.main()