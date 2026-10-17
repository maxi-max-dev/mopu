import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from phone_harness.setup import configure,select_device,executable

class SetupTests(unittest.TestCase):
    def test_explicit_missing_binary_does_not_silently_select_another(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError): executable('adb',str(Path(d)/'missing'))

    def test_ambiguous_unauthorized_and_network_devices_not_auto_bound(self):
        self.assertEqual(select_device([['a','device'],['b','unauthorized']]),'a')
        for rows in ([['a','device'],['b','device']],[['a','unauthorized']],[['127.0.0.1:5555','device']],[['emulator-5554','device']]):
            with self.assertRaises(RuntimeError):select_device(rows)
        with self.assertRaises(RuntimeError):select_device([['a','device']],'b')

    def test_config_is_private_bound_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);server=root/'server';server.write_text('test')
            backend=root/'backend';backend.write_text('test')
            args=argparse.Namespace(adb='adb',node='node',serial=None,scrcpy_server=str(server),mobile_mcp=str(backend),operation_lock=None,install_dependencies=False)
            with patch('phone_harness.setup.executable',side_effect=lambda name,value:name),patch('phone_harness.setup.devices',return_value=[['phone','device']]),patch('phone_harness.setup.verify_dependencies'):
                configure(root,args)
                path=root/'config.json';original=path.read_bytes()
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
                with self.assertRaises(RuntimeError):configure(root,args)
                self.assertEqual(original,path.read_bytes())

if __name__=='__main__':unittest.main()
