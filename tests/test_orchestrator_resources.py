"""PR-02B resource authority tests; no external provider calls."""
import tempfile
import unittest
from pathlib import Path
from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.resource_registry import ResourceRegistry, ResourceIdentity

class ResourceAuthorityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'tasks.sqlite')
        self.registry = ResourceRegistry(self.store)
    def tearDown(self): self.tmp.cleanup()

    def test_github_aliases_collapse_to_same_global_lock(self):
        gh = ResourceIdentity('github','123456')
        self.assertEqual(self.registry.register('gh:owner/repo',gh,operator='owner'),'github:repo/123456')
        self.registry.register('repo:frontend',gh,operator='owner')
        a = self.registry.task_with_resolved_scopes(TaskSpec('a','project1','implement','p'),(('gh:owner/repo','src'),))
        b = self.registry.task_with_resolved_scopes(TaskSpec('b','project2','implement','p'),(('repo:frontend','src/views'),))
        self.store.create(a);self.store.create(b)
        self.assertIsNotNone(self.store.claim('project1'))
        self.assertIsNone(self.store.claim('project2'))

    def test_supabase_scopes_and_environment_boundaries(self):
        self.registry.register('sb:staging',ResourceIdentity('supabase','abcdefghijklm','staging'),operator='admin')
        self.registry.register('sb:prod',ResourceIdentity('supabase','abcdefghijklm','production'),operator='admin')
        a=self.registry.resolve('sb:staging')
        b=self.registry.resolve('sb:prod')
        self.assertNotEqual(a,b)
        self.assertEqual(a,'supabase:project/abcdefghijklm/env/staging')

    def test_no_unverified_alias_or_id_rebinding(self):
        with self.assertRaises(ValueError): self.registry.resolve('repo:missing')
        self.registry.register('repo:a',ResourceIdentity('github','123'),operator='admin')
        with self.assertRaises(ValueError): self.registry.register('repo:a',ResourceIdentity('github','124'),operator='admin')
        self.assertFalse(self.registry.provider_write_authorized())

    def test_never_accept_self_claimed_provider_verification(self):
        with self.assertRaises(ValueError):
            self.registry.register('repo:a',ResourceIdentity('github','123'),operator='admin',provenance='provider_verified')

    def test_reject_path_escape_or_ambiguous_id(self):
        self.registry.register('repo:a',ResourceIdentity('github','123'),operator='admin')
        for bad in ('/etc','..','.','a//b','a\\b','a/../b','a/*','a/:'):
            with self.subTest(bad=bad),self.assertRaises(ValueError): self.registry.resolve('repo:a',bad)
        for bad in ('owner/name','0','0001','-12'):
            with self.subTest(id=bad),self.assertRaises(ValueError): ResourceIdentity('github',bad).key()

    def test_legacy_scope_mix_denied(self):
        self.registry.register('repo:a',ResourceIdentity('github','123'),operator='admin')
        with self.assertRaises(ValueError):
            self.registry.task_with_resolved_scopes(TaskSpec('x','p','implement','p',write_scopes=('repo:old',)),(('repo:a',None),))

if __name__=='__main__': unittest.main()