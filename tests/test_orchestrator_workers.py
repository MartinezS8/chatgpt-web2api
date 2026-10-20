"""Offline behavior of worker identity/scheduling; no remote transport."""
from __future__ import annotations

import concurrent.futures
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from chatgpt_web2api.orchestrator.scheduler import Scheduler
from chatgpt_web2api.orchestrator.store import Store, TaskSpec, TaskState
from chatgpt_web2api.orchestrator.supervisor import Supervisor
from chatgpt_web2api.orchestrator.worker_registry import WorkerRegistry, WorkerSpec


class FakePackages:
    """Minimal persistent sealed-package seam: not a ChatGPT upload stub."""
    def __init__(self, store):
        self.store=store
        with store._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS fake_packages (task_id TEXT PRIMARY KEY)')

    def seal(self, task_id):
        with self.store._connect() as db:
            db.execute('INSERT INTO fake_packages VALUES (?)', (task_id,))

    def read(self, task_id, *, verify_blobs=True):
        with self.store._connect() as db:
            row=db.execute('SELECT task_id FROM fake_packages WHERE task_id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('unsealed')
        return {"task_id":task_id}


def _process_schedule(args):
    path, account, project = args
    s=Store(path)
    result=Scheduler(s,WorkerRegistry(s),FakePackages(s)).claim_next(account,project)
    return result['task']['task_id'] if result else None


class WorkerSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'controller.db')
        self.store=Store(self.path)
        self.reg=WorkerRegistry(self.store)
        self.pack=FakePackages(self.store)
        self.scheduler=Scheduler(self.store,self.reg,self.pack)
        self.supervisor=Supervisor(self.store,self.reg)

    def worker(self, idx=1,role='implement',project='p',account='a'):
        return self.reg.register(WorkerSpec(f'{account}-{idx}',account,project,role,'mock',f'fake:{account}-{idx}'))

    def task(self, n=1,role='implement',project='p',scopes=(),depends=(),seal=True):
        name=f'{project}-t{n}'
        self.store.create(TaskSpec(name,project,role,f'prompt-{name}',
                                   write_scopes=tuple(scopes),dependencies=tuple(depends)))
        if seal:
            self.pack.seal(name)
        return name

    def test_identity_idempotence_duplicate_binding_and_enabled_live_denied(self):
        self.assertTrue(self.worker())
        self.assertFalse(self.worker())
        with self.assertRaises(ValueError):
            self.reg.register(WorkerSpec('another','a','p','implement','mock','fake:a-1'))
        with self.assertRaises(ValueError):
            self.reg.register(WorkerSpec('w-web','a','p','implement','chatgpt_ui','tab:1',True))
        with self.assertRaises(ValueError):
            self.reg.register(WorkerSpec('w-codex','a','p','implement','codex_app_server','stdio-singleton',False))
        self.assertEqual(len(self.reg.list('a')),1)

    def test_five_worker_cap_and_no_fake_web_availability(self):
        for i in range(1,6):
            self.worker(i)
        with self.assertRaises(ValueError):
            self.worker(6)
        self.assertEqual(sum(x['transport']=='mock' for x in self.reg.list('a')),5)

    def test_schedule_no_package_no_slot_consumed(self):
        self.worker()
        self.task(seal=False)
        self.assertIsNone(self.scheduler.claim_next('a','p'))
        self.assertEqual(self.store.get('p-t1')['state'],'queued')

    def test_exact_role_worker_affinity_and_claim_fencing(self):
        self.worker(1,'review')
        self.worker(2,'implement')
        self.task()
        assignment=self.scheduler.claim_next('a','p')
        self.assertEqual(assignment['worker_id'],'a-2')
        self.assertTrue(assignment['session_key'].startswith('fake:'))
        self.assertFalse(assignment['remote_send_permitted'])
        self.assertEqual(assignment['task']['state'],'reserved')
        self.assertTrue(assignment['task']['claim_token'])
        self.assertIsNone(self.scheduler.claim_next('a','p'))

    def test_five_slots_bounded_and_restart(self):
        for i in range(1,6):
            self.worker(i)
        for i in range(1,8):
            self.task(i)
        allocated=[self.scheduler.claim_next('a','p') for _ in range(7)]
        self.assertEqual(sum(x is not None for x in allocated),5)
        self.assertEqual(len({x['worker_id'] for x in allocated if x}),5)
        self.assertIsNone(Scheduler(Store(self.path),WorkerRegistry(Store(self.path)),FakePackages(Store(self.path))).claim_next('a','p'))
        self.assertEqual(len(self.reg.assignments('a')),5)

    def test_global_scopes_are_not_released_by_unknown(self):
        self.worker(1,project='p')
        self.worker(2,project='p2')
        first=self.task(project='p',scopes=('db:production',))
        self.task(project='p2',scopes=('db:production',))
        a=self.scheduler.claim_next('a','p')
        self.assertIsNotNone(a)
        self.assertTrue(self.store.transition(first,TaskState.RESERVED,TaskState.DISPATCHING,claim_token=a['task']['claim_token']))
        self.assertTrue(self.store.transition(first,TaskState.DISPATCHING,TaskState.UNKNOWN_DELIVERY,claim_token=a['task']['claim_token']))
        self.assertIsNone(self.scheduler.claim_next('a','p2'))

    def test_dependent_task_blocked_until_finished(self):
        self.worker(1)
        self.worker(2)
        parent=self.task(1)
        child=self.task(2,depends=(parent,))
        a=self.scheduler.claim_next('a','p')
        self.assertEqual(a['task']['task_id'],parent)
        self.assertIsNone(self.scheduler.claim_next('a','p'))
        self.assertEqual(self.store.get(child)['state'],'queued')

    def test_pause_resume_and_account_throttle(self):
        self.worker()
        self.task()
        self.supervisor.pause('a')
        self.assertIsNone(self.scheduler.claim_next('a','p'))
        self.supervisor.resume('a')
        self.supervisor.throttle('a',30)
        self.assertIsNone(self.scheduler.claim_next('a','p'))
        self.reg.control('a', throttle_until=0)
        self.assertIsNotNone(self.scheduler.claim_next('a','p'))

    def test_individual_worker_disable_prevents_claims_and_preserves_active_assignment(self):
        self.worker()
        self.task(1)
        self.task(2)

        self.assertTrue(self.reg.set_enabled('a-1', False))
        self.assertFalse(self.reg.get('a-1')['enabled'])
        self.assertIsNone(self.scheduler.claim_next('a', 'p'))
        self.assertEqual(self.store.get('p-t1')['state'], TaskState.QUEUED.value)
        self.assertEqual(self.store.get('p-t2')['state'], TaskState.QUEUED.value)

        self.assertTrue(self.reg.set_enabled('a-1', True))
        claim = self.scheduler.claim_next('a', 'p')
        self.assertIsNotNone(claim)
        assigned_task = claim['task']['task_id']
        self.assertTrue(self.reg.set_enabled('a-1', False))
        self.assertEqual(self.reg.assignments('a')[0]['task_id'], assigned_task)
        self.assertIsNone(self.scheduler.claim_next('a', 'p'))
        self.assertEqual(self.store.get(assigned_task)['state'], TaskState.RESERVED.value)
        self.assertFalse(self.reg.set_enabled('a-1', False))
        self.assertFalse(self.reg.set_enabled('missing-worker', True))

    def test_stale_worker_alert_does_not_release_or_auto_retry(self):
        self.worker()
        self.task()
        a=self.scheduler.claim_next('a','p',heartbeat_age_seconds=300)
        self.assertIsNotNone(a)
        record=self.reg.get('a-1')
        stale=self.supervisor.scan('a',stale_after=300,now=record['last_heartbeat']+350)
        self.assertEqual(len(stale),1)
        self.assertEqual(len(self.supervisor.alerts('a')),1)
        self.assertEqual(len(self.supervisor.scan('a',stale_after=300,now=record['last_heartbeat']+400)),1)
        self.assertEqual(len(self.supervisor.alerts('a')),1)
        self.assertEqual(self.store.get('p-t1')['state'],'reserved')
        self.assertIsNone(self.scheduler.claim_next('a','p'))

    def test_stale_heartbeat_worker_prevented_from_assignment(self):
        self.worker()
        self.task()
        created=self.reg.get('a-1')['last_heartbeat']
        self.assertIsNone(self.scheduler.claim_next('a','p',now=created+1000))
        self.assertIsNotNone(self.scheduler.claim_next('a','p',now=created+100))

    def test_multiprocess_claim_and_worker_uniqueness(self):
        for i in range(1,6):
            self.worker(i)
        for i in range(1,16):
            self.task(i)
        ctx=multiprocessing.get_context('spawn')
        with concurrent.futures.ProcessPoolExecutor(max_workers=4,mp_context=ctx) as ex:
            assigned=list(ex.map(_process_schedule,[(self.path,'a','p')]*13))
        self.assertEqual(len([x for x in assigned if x]),5)
        self.assertEqual(len(set(x for x in assigned if x)),5)
        self.assertEqual(len(self.reg.assignments('a')),5)

    def test_reclaimed_pre_send_task_reuses_released_assignment(self):
        self.worker()
        task_id = self.task()
        first = self.scheduler.claim_next('a', 'p')
        self.assertIsNotNone(first)
        self.store.recover('p', now=first['task']['lease_until'] + 1)
        self.assertEqual(self.store.get(task_id)['state'], 'queued')
        second = self.scheduler.claim_next('a', 'p')
        self.assertIsNotNone(second)
        self.assertEqual(second['task']['task_id'], task_id)
        self.assertNotEqual(second['task']['claim_token'], first['task']['claim_token'])
        self.assertEqual(len(self.reg.assignments('a')), 1)
        self.assertEqual(self.reg.assignments('a')[0]['claim_version'],
                         second['task']['claim_version'])

    def test_mock_only_capacity_gate_no_external_transport_available(self):
        self.reg.register(WorkerSpec('real-1','a','p','implement','codex_app_server','thread:one',False))
        self.task()
        self.assertIsNone(self.scheduler.claim_next('a','p'))


if __name__ == '__main__':
    unittest.main()
