import asyncio,tempfile,unittest,time
from unittest.mock import AsyncMock
from mopu.app import Console
from test_control import CONFIG
class Modes(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=Console(CONFIG,self.tmp.name)
 async def asyncTearDown(self):self.tmp.cleanup()
 async def test_background_connect_never_quiets_or_wakes_main(self):
  d=self.c.device;d.acquire=AsyncMock();d.quiet=AsyncMock();d.ensure_awake=AsyncMock();d.adb=AsyncMock()
  await d.prepare_mode('background')
  self.assertTrue(d.connected);self.assertTrue(d.background_mode)
  d.acquire.assert_awaited_once();d.quiet.assert_not_awaited();d.ensure_awake.assert_not_awaited();d.adb.assert_not_awaited()
 async def test_existing_background_blocks_main_ui_backend(self):
  d=self.c.device;d.connected=True;d.background_mode=True
  with self.assertRaises(PermissionError):await d.backend('mobile_press_button',{'button':'HOME'})
 async def test_mode_switch_requires_no_lease(self):
  self.c.queue.lease={'task':'some-other-task'}
  with self.assertRaises(PermissionError):await self.c.control({'action':'mode_main'})
 async def test_closing_view_does_not_pause_background(self):
  c=self.c;c.device.connected=True;c.device.background_mode=True;c.closed_view_at=time.monotonic()-20
  c.device.watchers=set();c.queue.data['settings']['close_pauses']=True;c.transition_to=AsyncMock()
  worker=asyncio.create_task(c.monitor_loop());await asyncio.sleep(2.1);worker.cancel();await asyncio.gather(worker,return_exceptions=True)
  c.transition_to.assert_not_awaited()
 async def test_normal_mode_still_closes_view(self):
  c=self.c;c.device.connected=True;c.device.background_mode=False;c.closed_view_at=time.monotonic()-20
  c.device.watchers=set();c.queue.data['settings']['close_pauses']=True;c.transition_to=AsyncMock();c.device.close=AsyncMock()
  worker=asyncio.create_task(c.monitor_loop());await asyncio.sleep(2.1);worker.cancel();await asyncio.gather(worker,return_exceptions=True)
  c.transition_to.assert_awaited_once();c.device.close.assert_awaited_once()
