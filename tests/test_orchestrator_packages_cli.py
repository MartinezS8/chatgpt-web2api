import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from chatgpt_web2api.orchestrator.cli import main


class PackageCLITests(unittest.TestCase):
    def test_seal_and_inspect_without_disclosing_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            db=root/'controller.sqlite'
            pf=root/'prompt.txt'
            af=root/'notes.md'
            prompt='a private-ish prompt only in the package'
            pf.write_text(prompt,encoding='utf-8')
            af.write_text('# note',encoding='utf-8')
            def call(*args):
                out=StringIO()
                with redirect_stdout(out):
                    rc=main(['--db',str(db),'--json',*args])
                self.assertEqual(rc,0,out.getvalue())
                return json.loads(out.getvalue())['data']
            call('create-task','--id','task1','--project','p','--role','implement','--prompt-file',str(pf))
            sealed=call('seal-task','--id','task1','--prompt-file',str(pf),'--attachment',str(af),'--allowed-root',td)
            self.assertEqual(len(sealed['attachments']),1)
            inspected=call('task-package','--id','task1')
            self.assertNotIn('prompt',inspected)
            self.assertEqual(inspected['package_sha256'],sealed['package_sha256'])
            self.assertEqual(call('delivery-events')['events'],[])

if __name__=='__main__':
    unittest.main()