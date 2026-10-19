import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from chatgpt_web2api.orchestrator.cli import main

class ResourceCLI(unittest.TestCase):
    def test_register_resolve_and_reserve_by_alias(self):
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/'tasks.db')
            prompt=Path(td)/'prompt.txt'
            prompt.write_text('implement this',encoding='utf-8')
            def run(*args):
                out=StringIO()
                with redirect_stdout(out):
                    code=main(['--db',db,'--json',*args])
                self.assertEqual(code,0,out.getvalue())
                return json.loads(out.getvalue())['data']
            r=run('register-resource','--alias','gh:me/example','--provider','github','--provider-id','1001','--operator','me')
            self.assertEqual(r['canonical_id'],'github:repo/1001')
            self.assertFalse(r['provider_write_authorized'])
            r=run('resolve-resource','--alias','gh:me/example','--path','src')
            self.assertEqual(r['canonical_scope'],'github:repo/1001/src')
            run('create-task','--id','t1','--project','x','--role','implement','--prompt-file',str(prompt),'--resource-alias','gh:me/example')
            self.assertEqual(run('claim','--project','x')['reserved']['write_scopes'],'["github:repo/1001"]')

    def test_mixed_scopes_fail(self):
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/'tasks.db')
            prompt=Path(td)/'p'
            prompt.write_text('X')
            out=StringIO()
            with redirect_stdout(out):
                rc=main(['--db',db,'--json','create-task','--id','t','--project','p','--role','implement','--prompt-file',str(prompt),'--resource-alias','no','--write-scope','repo:legacy'])
            self.assertEqual(rc,2)

if __name__=='__main__':
    unittest.main()