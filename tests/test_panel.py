import asyncio
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from mopu.device import Device, physical_panel
from mopu.app import Console

CONFIG = {'serial':'test-device','adb':'/test/adb','scrcpy_server':'/test/server','backend_command':['/test/node']}

def display(mode, ident=1, kind='Internal'):
    return f'Display {ident}\n    connectionType={kind}\n    powerMode={mode}\n'

class PhysicalPanelTests(unittest.TestCase):
    def test_virtual_on_and_logical_awake_do_not_mean_physical_on(self):
        sf = display('Off') + 'Virtual Display 22\n    powerMode=On\n' + 'mWakefulness=Awake\n'
        self.assertEqual(physical_panel(sf), ('off',['off']))

    def test_any_lit_internal_panel_including_doze_is_visible(self):
        for mode in ('On','Doze','DozeSuspend','1','2','3','4'):
            with self.subTest(mode=mode):
                self.assertEqual(physical_panel(display('Off')+display(mode,2))[0], 'on')

    def test_unknown_is_never_reported_dark(self):
        for sf in ('',display('Undefined'),display('99'),display('On',kind='External'),display('Off')+display('Undefined',2)):
            self.assertEqual(physical_panel(sf)[0], 'unknown')

    def test_legacy_display_blocks_are_isolated(self):
        sf='DisplayDevice{isVirtual=false, powerMode=0}\nDisplayDevice{isVirtual=true, powerMode=2}'
        self.assertEqual(physical_panel(sf), ('off',['0']))

class PanelControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.d=Device(CONFIG,'/unused'); self.d.send=AsyncMock()

    async def test_set_power_sends_explicit_boolean_and_reads_back(self):
        self.d.sample_panel=AsyncMock(side_effect=['off','on'])
        with patch('mopu.device.asyncio.sleep',new=AsyncMock()): await self.d.set_panel(True)
        self.d.send.assert_awaited_once_with(bytes([10,1]))
        self.assertEqual(self.d.sample_panel.await_count,2)
        self.d.send.reset_mock(); self.d.sample_panel=AsyncMock(return_value='off')
        await self.d.set_panel(False)
        self.d.send.assert_awaited_once_with(bytes([10,0]))

    async def test_unconfirmed_action_is_not_replayed_or_claimed_success(self):
        self.d.sample_panel=AsyncMock(return_value='unknown')
        with patch('mopu.device.asyncio.sleep',new=AsyncMock()):
            with self.assertRaises(RuntimeError): await self.d.set_panel(False)
        self.d.send.assert_awaited_once()
        with self.assertRaises(ValueError): await self.d.set_panel('false')
        self.d.send.assert_awaited_once()

    async def test_failed_read_invalidates_old_off(self):
        self.d.telemetry={'panel':'off'}; self.d.panel_sampled=time.monotonic()
        self.d.shell=AsyncMock(side_effect=RuntimeError('gone'))
        with self.assertRaises(RuntimeError): await self.d.sample_panel()
        self.assertIsNone(self.d.panel_sampled)
        self.assertEqual(self.d.telemetry['panel'],'unknown')

    async def test_stale_or_disconnected_sample_is_unknown_without_mutating_history(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Console(CONFIG,folder); c.device.connected=True
            c.device.telemetry={'panel':'off'}; c.device.panel_sampled=time.monotonic()-6
            self.assertEqual(c.snapshot()['device']['telemetry']['panel'],'unknown')
            c.device.panel_sampled=time.monotonic()
            self.assertEqual(c.snapshot()['device']['telemetry']['panel'],'off')
            c.device.connected=False
            self.assertEqual(c.snapshot()['device']['telemetry']['panel'],'unknown')
            self.assertEqual(c.device.telemetry['panel'],'off')

    async def test_panel_monitor_does_not_wait_for_agent_action(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Console(CONFIG,folder); c.device.connected=True
            sampled=asyncio.Event()
            async def sample(): sampled.set(); return 'on'
            c.device.sample_panel=sample
            async with c.op:
                monitor=asyncio.create_task(c.panel_loop())
                try: await asyncio.wait_for(sampled.wait(),.5)
                finally:
                    monitor.cancel()
                    await asyncio.gather(monitor,return_exceptions=True)

    async def test_rotate_requires_human_and_preserves_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Console(CONFIG,folder); c.device.connected=True; c.device.rotate=AsyncMock(return_value=False)
            c.queue.owner='agent'
            with self.assertRaises(ValueError): await c.control({'action':'rotate'})
            c.device.rotate.assert_not_awaited()
            c.queue.owner='human'
            result=await c.control({'action':'rotate'})
            self.assertIn('仍保持原方向',result['notice'])
            self.assertEqual(c.queue.owner,'human')

if __name__=='__main__': unittest.main()
