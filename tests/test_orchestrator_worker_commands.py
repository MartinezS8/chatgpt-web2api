from __future__ import annotations
import argparse
import tempfile
import unittest
from pathlib import Path
from chatgpt_web2api.orchestrator.store import Store
from chatgpt_web2api.orchestrator.worker_commands import configure_worker_commands, execute_worker_command

class TestWorkerCommands(unittest.TestCase):
    def test_capability_and_registration_pause_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'controller.db')
            parser=argparse.ArgumentParser()
            commands=parser.add_subparsers(dest='command',required=True)
            configure_worker_commands(commands)
            cap=execute_worker_command(parser.parse_args(['worker-capabilities']),store)
            self.assertEqual(cap['remote_generations_available'],0)
            parsed=parser.parse_args(['register-worker','--id','wk-1','--account','acct','--project','p',
                                      '--session-key','fake:wk-1','--role','implement'])
            self.assertTrue(execute_worker_command(parsed,store)['created'])
            listed=execute_worker_command(parser.parse_args(['list-workers','--account','acct']),store)
            self.assertEqual(len(listed['workers']),1)
            self.assertTrue(execute_worker_command(parser.parse_args(['pause-workers','--account','acct']),store)['paused'])
            self.assertFalse(execute_worker_command(parser.parse_args(['resume-workers','--account','acct']),store)['paused'])
            self.assertTrue(execute_worker_command(parser.parse_args(['worker-heartbeat','--id','wk-1']),store)['found'])
            self.assertEqual(execute_worker_command(parser.parse_args(['worker-assignments','--account','acct']),store)['assignments'],[])
    def test_real_transport_not_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'controller.db')
            parser=argparse.ArgumentParser()
            commands=parser.add_subparsers(dest='command',required=True)
            configure_worker_commands(commands)
            args=parser.parse_args(['register-worker','--id','w','--account','acct','--project','p',
                                      '--session-key','session-1','--role','implement','--transport','chatgpt_ui'])
            with self.assertRaises(ValueError):
                execute_worker_command(args,store)
            args=parser.parse_args(['register-worker','--id','w','--account','acct','--project','p',
                                      '--session-key','session-1','--role','implement','--transport','chatgpt_ui','--disabled'])
            self.assertTrue(execute_worker_command(args,store)['created'])