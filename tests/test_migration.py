"""Mopu migration must neither strand old data nor create a second console."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from mopu.paths import default_state
from mopu.launcher import ensure_console
from mopu.tasks import Queue

class MigrationTests(unittest.TestCase):
    def test_fresh_and_legacy_directory_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old = home/'.local/share/phone-harness'
            new = home/'.local/share/mopu'
            self.assertEqual(default_state(home), new)
            new.mkdir(parents=True)
            old.mkdir()
            data = b'{"serial":"existing-device","custom":"keep"}'
            (old/'config.json').write_bytes(data)
            self.assertEqual(default_state(home), old)
            self.assertEqual((old/'config.json').read_bytes(), data)
            self.assertFalse((new/'config.json').exists())

    def test_old_module_launch_and_explicit_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); state=home/'chosen'
            # doctor on an unconfigured explicit path should fail identically,
            # without creating either default state directory.
            results=[]
            for module in ('mopu.cli','phone_harness.cli'):
                code = 'import runpy; from pathlib import Path; from unittest.mock import patch; '+f'ctx=patch("pathlib.Path.home",return_value=Path({tmp!r})); ctx.start(); runpy.run_module({module!r},run_name="__main__")'
                p=subprocess.run([sys.executable,'-c',code,'--state',str(state),'doctor'],capture_output=True,text=True)
                self.assertEqual(p.returncode,1,p.stderr)
                self.assertTrue(p.stdout, p.stderr)
                results.append(json.loads(p.stdout))
            self.assertEqual(results[0],results[1])
            self.assertFalse((home/'.local/share').exists())

    def test_old_imports_and_receipt_protocol(self):
        import phone_harness
        import mopu
        from phone_harness.mcp import TOOLS as legacy
        from mopu.mcp import TOOLS
        self.assertEqual(phone_harness.__version__,mopu.__version__)
        self.assertEqual(legacy,TOOLS)
        self.assertTrue(any(t['name']=='phone_finish' for t in TOOLS))

    def test_reuses_existing_console_without_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            (state/'endpoint.json').write_text(json.dumps({'url':'http://127.0.0.1:1234','token':'test'}))
            with patch('mopu.launcher.urllib.request.urlopen') as opened, patch('mopu.launcher.subprocess.Popen') as spawn:
                opened.return_value.__enter__.return_value.status=200
                self.assertEqual(ensure_console(state),'http://127.0.0.1:1234')
                spawn.assert_not_called()
